"""TTS via ElevenLabs REST. Optional -- the demo is fully usable without it.

Restored after the A/C merge dropped it: the questions being *spoken* is part of
the demo, and ElevenLabs on both sides (the agent's voice and the clone attack)
is worth real points. Deliberately no SDK dependency -- one requests call.

If ELEVENLABS_API_KEY is unset this raises at construction, app/main.py records
it, and questions render as text exactly as they do today.
"""

from __future__ import annotations

import requests

from app.config import Settings

API = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel, on every free account
MODEL = "eleven_flash_v2_5"  # lowest latency; this sits in the live loop
TIMEOUT = 12


class ElevenLabsTts:
    """Implements contracts.interfaces.Tts."""

    def __init__(self, settings: Settings) -> None:
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self.voice_id = settings.elevenlabs_voice_id or DEFAULT_VOICE
        self.session = requests.Session()
        self.session.headers.update({
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        })

    def speak(self, text: str) -> bytes:
        """-> mp3 bytes. Raises on failure; the caller degrades to text."""
        r = self.session.post(
            f"{API}/{self.voice_id}",
            json={
                "text": text,
                "model_id": MODEL,
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            raise RuntimeError(f"elevenlabs {r.status_code}: {r.text[:200]}")
        return r.content
