"""Enrollment: briefing document -> enrolled user in Atlas. Sam.

The user asks their own AI assistant to write a briefing document about them,
pastes it in, and we turn it into users + memory_events (+ an optional
voiceprint). Parsing is deliberately lenient -- people paste markdown fences,
chatter, or plain prose.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone

MAX_MEMORIES = 40
MIN_TEXT_LEN = 25
VALID_KINDS = {"conversation", "fact", "decision", "event"}

_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"(?:\d[\s\-]?){9,}", "looks like an account/card/ID number"),
    (r"\bpass(word|code|phrase)\b", "mentions a password"),
    (r"\bapi[\s_-]?key\b", "mentions an API key"),
    (r"\bsecret\b", "mentions a secret"),
    (r"\bseed\s+phrase\b", "mentions a seed phrase"),
    (r"\brouting\s+number\b", "mentions a routing number"),
    (r"\b(ssn|social security)\b", "mentions an SSN"),
    (r"[\w.+-]+@[\w-]+\.[\w.]{2,}", "contains an email address"),
    (r"\+?(?:\d[\s.\-()]{0,2}){10,}", "contains a phone number"),
    (
        r"\b\d{1,5}\s+[\w.'-]+(\s+[\w.'-]+){0,3}\s+"
        r"(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|"
        r"court|ct|way|place|pl|terrace|circle|cir)\b\.?",
        "contains a street address",
    ),
]
_SECRET_RES = [(re.compile(p, re.I), why) for p, why in _SECRET_PATTERNS]

_LLM_PROMPT = (
    "Convert the text about a person into JSON with exactly this shape: "
    '{"name": str, "profile": {"role": str, "city": str}, "memories": '
    '[{"ts": ISO8601 str, "kind": "conversation"|"fact"|"decision"|"event", '
    '"text": str, "salient_attrs": {}}]}. Each memory text is one concrete, '
    "specific episodic detail (>=25 chars). Aim for 12-25 memories. Today is "
    "2026-08-13; spread timestamps over the last few weeks. JSON only."
)


# ---------------------------------------------------------------- parsing


def _first_json_block(raw: str) -> dict | None:
    start = raw.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(raw)):
            c = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(raw[start : i + 1])
                    except Exception:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = raw.find("{", start + 1)
    return None


def _llm_parse(raw: str) -> dict | None:
    try:
        from openai import OpenAI

        from app.config import settings

        if not settings.openrouter_api_key:
            return None
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        r = client.chat.completions.create(
            model=settings.openrouter_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_PROMPT},
                {"role": "user", "content": raw[:12000]},
            ],
        )
        obj = json.loads(r.choices[0].message.content or "{}")
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_briefing(raw: str) -> dict:
    """Lenient parse of whatever the user pasted into the canonical dict."""
    if not raw or not raw.strip():
        raise ValueError("Nothing to enroll -- paste your briefing document first.")
    doc = None
    try:
        obj = json.loads(raw)
        doc = obj if isinstance(obj, dict) else None
    except Exception:
        doc = None
    if doc is None:
        doc = _first_json_block(raw)
    if doc is None or not doc.get("memories"):
        doc = _llm_parse(raw) or doc
    if not isinstance(doc, dict) or not doc.get("memories"):
        raise ValueError(
            "Couldn't read that briefing. Paste the JSON your assistant "
            "produced, or a few paragraphs about recent things you did."
        )
    return doc


# ------------------------------------------------------------- sanitising


def sanitize(doc: dict) -> tuple[dict, list[str]]:
    """Strip anything privacy-dangerous before it reaches the DB."""
    warnings: list[str] = []
    name = str(doc.get("name") or "").strip() or "Anonymous"
    profile = doc.get("profile") if isinstance(doc.get("profile"), dict) else {}
    profile = {str(k): v for k, v in list(profile.items())[:12]}

    raw_mems = doc.get("memories")
    raw_mems = raw_mems if isinstance(raw_mems, list) else []

    clean: list[dict] = []
    dropped_secret = 0
    dropped_short = 0
    for m in raw_mems:
        if isinstance(m, str):
            m = {"text": m}
        if not isinstance(m, dict):
            continue
        text = str(m.get("text") or "").strip()
        if len(text) < MIN_TEXT_LEN:
            dropped_short += 1
            continue
        hit = next((why for rx, why in _SECRET_RES if rx.search(text)), None)
        if hit:
            dropped_secret += 1
            warnings.append(f"Dropped a memory that {hit}.")
            continue
        kind = str(m.get("kind") or "conversation")
        attrs = m.get("salient_attrs")
        clean.append(
            {
                "ts": m.get("ts"),
                "kind": kind if kind in VALID_KINDS else "conversation",
                "text": text,
                "salient_attrs": {str(k): v for k, v in attrs.items()}
                if isinstance(attrs, dict)
                else {},
            }
        )

    if len(clean) > MAX_MEMORIES:
        warnings.append(f"Kept the first {MAX_MEMORIES} of {len(clean)} memories.")
        clean = clean[:MAX_MEMORIES]
    if dropped_short:
        warnings.append(f"Dropped {dropped_short} memories that were too short to ask about.")
    if dropped_secret > 3:
        warnings = [w for w in warnings if not w.startswith("Dropped a memory that")]
        warnings.insert(0, f"Dropped {dropped_secret} memories containing sensitive details.")
    if len(clean) < 5:
        warnings.append("Fewer than 5 usable memories -- questioning will be weak.")

    return {"name": name, "profile": profile, "memories": clean}, warnings


# ------------------------------------------------------------- enrollment


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return (s or "user")[:24]


def _ts(raw, i: int) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        try:
            d = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    # spread across the last 3 days so recency questions still work
    return datetime.now(timezone.utc) - timedelta(minutes=17 * (i + 1) % 4320)


def enroll_user(store, embedder, doc: dict, user_id: str | None = None,
                audio: bytes | None = None, voice=None) -> dict:
    """Upsert the user + their memory_events into Atlas."""
    clean, warnings = sanitize(doc)
    name = clean["name"]
    uid = user_id or f"u_{_slug(name)}_{random.randrange(16**4):04x}"
    db = store.db
    mems = clean["memories"]

    db.users.replace_one(
        {"_id": uid},
        {"_id": uid, "name": name, "profile": clean["profile"],
         "created_at": datetime.now(timezone.utc)},
        upsert=True,
    )

    db.memory_events.delete_many({"user_id": uid})
    if mems:
        vecs = embedder.embed_batch([m["text"] for m in mems])
        db.memory_events.insert_many([
            {
                "_id": f"m_{uid}_{i:02d}",
                "user_id": uid,
                "ts": _ts(m["ts"], i),
                "kind": m["kind"],
                "text": m["text"],
                "salient_attrs": m["salient_attrs"],
                "embedding": vecs[i],
            }
            for i, m in enumerate(mems)
        ])

    voiceprint = False
    if audio and voice is not None:
        try:
            db.voiceprints.replace_one(
                {"_id": f"vp_{uid}"},
                {"_id": f"vp_{uid}", "user_id": uid,
                 "embedding": list(voice.embed_voice(audio)),
                 "enrolled_at": datetime.now(timezone.utc)},
                upsert=True,
            )
            voiceprint = True
        except Exception as exc:  # a broken encoder must never block text enrollment
            warnings.append(f"Voice enrollment failed ({type(exc).__name__}) -- text only.")

    return {
        "user_id": uid,
        "name": name,
        "memories": len(mems),
        "voiceprint": voiceprint,
        "warnings": warnings,
    }
