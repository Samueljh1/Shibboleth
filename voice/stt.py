"""STT via ElevenLabs Scribe. Jabir — Task A.

Returns "" on failure rather than raising — the UI has a typed-answer fallback
and the demo must survive a bad transcription in a loud room.

POST https://api.elevenlabs.io/v1/speech-to-text, multipart `file` + `model_id`,
auth via the `xi-api-key` header; the transcript comes back on `text`.
"""

from __future__ import annotations

import io
import os

import requests

from app.config import Settings

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
TIMEOUT = 25.0

MODELS = ("scribe_v1", "scribe_v2")
"""Tried in order. Which one an account has access to varies, and a 4xx on the
first is not worth losing an answer over — so we retry once with the other."""


class ElevenLabsStt:
    """Implements contracts.interfaces.Stt."""

    def __init__(self, settings: Settings) -> None:
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self.session = requests.Session()
        self.session.headers.update({"xi-api-key": settings.elevenlabs_api_key})
        preferred = os.getenv("ELEVENLABS_STT_MODEL")
        self.models = (preferred,) + MODELS if preferred else MODELS

    def transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""
        for model_id in self.models:
            try:
                r = self.session.post(
                    API_URL,
                    files={"file": ("utterance.webm", io.BytesIO(audio), "audio/webm")},
                    data={"model_id": model_id},
                    timeout=TIMEOUT,
                )
                if r.status_code >= 400:
                    continue  # wrong model name / no access — try the next
                return (r.json().get("text") or "").strip()
            except Exception:
                continue
        return ""
