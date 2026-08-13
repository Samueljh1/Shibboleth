"""Signup / enrollment routes. Sam.

Paste a briefing -> preview (parse + sanitize) -> review -> commit.

Everything heavy is imported *inside* the handlers: this module must import
cleanly with no API keys set, and `store/enroll.py` plus `app.main` are only
touched at request time (the latter would otherwise be a circular import).
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

router = APIRouter()

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "web" / "prompt.txt"


class PreviewBody(BaseModel):
    raw: str


class EnrollBody(BaseModel):
    doc: dict
    audio_b64: str | None = None
    user_id: str | None = None


def _enroll_mod():
    """Import store/enroll.py lazily; 503 with the reason if it can't load."""
    try:
        from store import enroll as enroll_mod
    except Exception as exc:  # noqa: BLE001 - missing keys / half-written module
        raise HTTPException(503, f"enrollment unavailable: {type(exc).__name__}: {exc}")
    return enroll_mod


def _parts() -> tuple[object, object, object | None]:
    """(store, embedder, voice) from app.main's built subsystems."""
    try:
        from app.main import P
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"app not initialised: {type(exc).__name__}: {exc}")
    store, embedder, voice = P.get("store"), P.get("embedder"), P.get("voice")
    missing = [n for n, v in (("store", store), ("embedder", embedder)) if v is None]
    if missing:
        errs = {}
        try:
            from app.main import ERR

            errs = {n: ERR.get(n, "not wired") for n in missing}
        except Exception:  # noqa: BLE001
            errs = {n: "not wired" for n in missing}
        raise HTTPException(503, f"enrollment needs {', '.join(missing)}: {errs}")
    return store, embedder, voice


@router.get("/prompt.txt", response_class=PlainTextResponse)
def prompt_txt() -> PlainTextResponse:
    """The briefing prompt users paste into their own assistant."""
    try:
        text = _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(503, f"prompt file not found at {_PROMPT_PATH} — web/prompt.txt is not written yet")
    except OSError as exc:
        raise HTTPException(503, f"could not read {_PROMPT_PATH}: {exc}")
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.post("/enroll/preview")
def enroll_preview(body: PreviewBody) -> dict:
    """Parse + clean a pasted briefing so the user can review before committing."""
    mod = _enroll_mod()
    if not (body.raw or "").strip():
        raise HTTPException(400, "raw briefing text is empty")
    try:
        doc = mod.parse_briefing(body.raw)
        doc, warnings = mod.sanitize(doc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"{type(exc).__name__}: {exc}")
    return {
        "doc": doc,
        "warnings": list(warnings or []),
        "memory_count": len((doc or {}).get("memories") or []),
    }


@router.post("/enroll")
def enroll(body: EnrollBody) -> dict:
    """Commit a reviewed doc. Sanitized again — never trust the client."""
    mod = _enroll_mod()
    store, embedder, voice = _parts()

    try:
        doc, warnings = mod.sanitize(body.doc or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    audio = None
    if body.audio_b64:
        try:
            audio = base64.b64decode(body.audio_b64)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"audio_b64 is not valid base64: {exc}")

    try:
        out = mod.enroll_user(
            store, embedder, doc,
            user_id=body.user_id,
            audio=audio,
            voice=voice if audio else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"enrollment failed: {type(exc).__name__}: {exc}")

    out = dict(out or {})
    out.setdefault("warnings", list(warnings or []))
    return out


@router.get("/enrolled")
def enrolled() -> list[dict]:
    """The growing roster, for the demo."""
    store, _embedder, _voice = _parts()
    out: list[dict] = []
    for u in store.list_users():
        try:
            n = len(store.memories(u.id))
        except Exception:  # noqa: BLE001
            n = 0
        out.append({"id": u.id, "name": u.name, "memory_count": n})
    return out
