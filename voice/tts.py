"""TTS via ElevenLabs — the agent asks its questions out loud. Jabir — Task A."""

from __future__ import annotations

from app.config import Settings


class ElevenLabsTts:
    """Implements contracts.interfaces.Tts."""

    def __init__(self, settings: Settings) -> None:
        raise NotImplementedError("voice/tts.py — Jabir")

    def speak(self, text: str) -> bytes:
        """-> mp3/wav bytes. Keep latency low; this is in the live loop."""
        raise NotImplementedError
