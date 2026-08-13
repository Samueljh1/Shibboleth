"""STT via ElevenLabs Scribe. Jabir — Task A.

Return "" on failure rather than raising — the UI has a typed-answer fallback and
the demo must survive a bad transcription.
"""

from __future__ import annotations

from app.config import Settings


class ElevenLabsStt:
    """Implements contracts.interfaces.Stt."""

    def __init__(self, settings: Settings) -> None:
        raise NotImplementedError("voice/stt.py — Jabir")

    def transcribe(self, audio: bytes) -> str:
        raise NotImplementedError
