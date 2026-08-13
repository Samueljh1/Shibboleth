"""FastAPI app. Sam. Implements contracts/api.md.

Composition only — VoiceEncoder -> Store.narrow -> Engine. No identity logic here.

    uvicorn app.main:app --reload

Subsystems are built lazily and independently: if voice/ or engine/ isn't wired
yet, only the endpoints that need it return 503, so we're never blocked on each
other. GET /health shows what's live.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from contracts.models import AuthSession, QuestionSpec

app = FastAPI(title="Shibboleth")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _build() -> tuple[dict, dict[str, str]]:
    """Construct what we can; record why anything else failed."""
    parts: dict = {}
    errors: dict[str, str] = {}

    def attempt(name: str, fn) -> None:
        try:
            parts[name] = fn()
        except Exception as exc:
            parts[name] = None
            errors[name] = f"{type(exc).__name__}: {exc}"

    def embedder():
        from store.embeddings import OpenAIEmbedder

        return OpenAIEmbedder(settings)

    def store():
        from store.atlas_store import AtlasStore

        return AtlasStore(settings, parts["embedder"])

    def voice():
        from voice.encoder import ResemblyzerEncoder

        return ResemblyzerEncoder()

    def stt():
        from voice.stt import ElevenLabsStt

        return ElevenLabsStt(settings)

    def tts():
        from voice.tts import ElevenLabsTts

        return ElevenLabsTts(settings)

    def llm():
        from engine.llm import OpenRouterLlm

        return OpenRouterLlm(settings)

    def engine():
        from engine.engine import EntropyEngine

        return EntropyEngine(
            store=parts["store"],
            embedder=parts["embedder"],
            llm=parts["llm"],
            tau_id=settings.tau_id,
            tau_reject=settings.tau_reject,
            max_questions=settings.max_questions,
        )

    for name, fn in (
        ("embedder", embedder), ("store", store), ("voice", voice),
        ("stt", stt), ("tts", tts), ("llm", llm), ("engine", engine),
    ):
        attempt(name, fn)
    return parts, errors


P, ERR = _build()


def need(*names: str):
    """Fetch subsystems or 503 with the actual reason."""
    missing = [n for n in names if P.get(n) is None]
    if missing:
        raise HTTPException(503, {n: ERR.get(n, "not wired") for n in missing})
    return [P[n] for n in names]


class StartBody(BaseModel):
    audio_b64: str | None = None
    claimed_id: str | None = None


class AnswerBody(BaseModel):
    session_id: str
    answer_text: str | None = None
    audio_b64: str | None = None


class WipeBody(BaseModel):
    user_id: str


def _speak(q: QuestionSpec | None) -> str | None:
    tts = P.get("tts")
    if q is None or tts is None:
        return None
    try:
        return base64.b64encode(tts.speak(q.question_text)).decode()
    except Exception:
        return None  # a dead TTS call must never end the demo


def _advance(s: AuthSession) -> dict:
    """Ask the next question, or finalise. Shared by /start and /answer."""
    (store, engine) = need("store", "engine")
    q = None
    if s.status == "in_progress":
        s, q = engine.next_question(s)
        if q is None:
            s = engine.finalize(s, force=True)  # budget spent, or memory wiped
    s.pending = q
    store.save_session(s)

    result = None
    if s.status != "in_progress":
        leader, _ = s.leader
        identified = s.status == "identified" and leader
        result = {
            "status": s.status,
            "user_id": leader if identified else None,
            "name": store.get_user(leader).name if identified else None,
            "questions_used": len(s.asked),
        }
    return {
        "session": s.model_dump(by_alias=True, mode="json"),
        "next_question": q.model_dump(mode="json") if q else None,
        "question_audio_b64": _speak(q),
        "result": result,
    }


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "ready": {k: v is not None for k, v in P.items()},
        "errors": ERR,
    }


@app.get("/personas")
def personas() -> list[dict]:
    (store,) = need("store")
    return [
        {
            "id": u.id,
            "name": u.name,
            "role": u.profile.get("role"),
            "memory_count": len(store.memories(u.id)),
        }
        for u in store.list_users()
    ]


@app.post("/session/start")
def session_start(body: StartBody) -> dict:
    (store, voice, engine) = need("store", "voice", "engine")
    if not body.audio_b64:
        raise HTTPException(400, "audio_b64 required")

    voice_vec = voice.embed_voice(base64.b64decode(body.audio_b64))
    candidates = store.narrow(voice_vec, settings.voice_topk)
    if not candidates:
        raise HTTPException(404, "no enrolled voiceprints — run scripts/seed.py")

    s = engine.start(candidates)
    s.claimed_id = body.claimed_id
    s.voice_vec = voice_vec
    out = _advance(s)
    return {
        "session": out["session"],
        "first_question": out["next_question"],
        "question_audio_b64": out["question_audio_b64"],
    }


@app.post("/session/answer")
def session_answer(body: AnswerBody) -> dict:
    (store, engine) = need("store", "engine")
    s = store.get_session(body.session_id)
    if s is None:
        raise HTTPException(404, f"unknown session: {body.session_id}")
    if s.status != "in_progress":
        raise HTTPException(409, f"session already {s.status}")

    if body.answer_text is not None:
        answer = body.answer_text
    elif body.audio_b64:
        (stt,) = need("stt")
        answer = stt.transcribe(base64.b64decode(body.audio_b64))
    else:
        raise HTTPException(400, "answer_text or audio_b64 required")

    if s.pending is not None:
        s = engine.grade_and_update(s, s.pending, answer)
    return _advance(s)


@app.post("/session/wipe")
def session_wipe(body: WipeBody) -> dict:
    (store,) = need("store")
    deleted = len(store.memories(body.user_id))
    store.wipe_user_memory(body.user_id)
    return {"ok": True, "deleted": deleted}


_web = Path(__file__).resolve().parent.parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
