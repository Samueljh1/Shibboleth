"""Clone-attack rig — demo Act 2. Jabir — Task A.

ElevenLabs instant voice clone from a short reference clip, then speak `text`
in that voice. The point of the beat is that the biometric *passes*: the cloned
utterance should embed close enough to the target that `narrow()` still ranks
them first, and it is the knowledge gate that rejects them.

Only clone a teammate or a judge who has agreed on the spot.

Fallback, per the build plan: set `CLONE_FALLBACK_AUDIO` to a pre-recorded
clone. If live cloning is slow or the account lacks IVC, that file is returned
instead and the demo runs identically.
"""

from __future__ import annotations

import io
import os
import uuid

import requests

from app.config import Settings

VOICES_URL = "https://api.elevenlabs.io/v1/voices"
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
TIMEOUT = 45.0


class CloneError(RuntimeError):
    """Live cloning failed and no pre-recorded fallback was configured."""


def clone_utterance(reference_audio: bytes, text: str, settings: Settings) -> bytes:
    """-> audio of `text` in the reference speaker's voice."""
    try:
        return _live_clone(reference_audio, text, settings)
    except Exception as exc:
        fallback = _fallback_audio()
        if fallback:
            return fallback
        raise CloneError(f"live clone failed and CLONE_FALLBACK_AUDIO is unset: {exc}") from exc


def _live_clone(reference_audio: bytes, text: str, settings: Settings) -> bytes:
    if not settings.elevenlabs_api_key:
        raise CloneError("ELEVENLABS_API_KEY is not set")
    if not reference_audio:
        raise CloneError("no reference audio")

    session = requests.Session()
    session.headers.update({"xi-api-key": settings.elevenlabs_api_key})
    voice_id = _add_voice(session, reference_audio)
    try:
        r = session.post(
            f"{TTS_URL}/{voice_id}",
            json={
                "text": text,
                "model_id": os.getenv("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5"),
                # Push similarity high: we WANT the biometric to be fooled.
                "voice_settings": {"stability": 0.35, "similarity_boost": 0.95},
            },
            headers={"Accept": "audio/mpeg"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.content
    finally:
        # Instant voice clones count against the account's voice slots, and we
        # may run this beat several times during rehearsal.
        try:
            session.delete(f"{VOICES_URL}/{voice_id}", timeout=10)
        except Exception:
            pass


def _add_voice(session: requests.Session, reference_audio: bytes) -> str:
    r = session.post(
        f"{VOICES_URL}/add",
        data={"name": f"shibboleth-clone-{uuid.uuid4().hex[:8]}"},
        files={"files": ("reference.webm", io.BytesIO(reference_audio), "audio/webm")},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    voice_id = r.json().get("voice_id")
    if not voice_id:
        raise CloneError(f"no voice_id in clone response: {r.text[:200]}")
    return voice_id


def _fallback_audio() -> bytes | None:
    path = os.getenv("CLONE_FALLBACK_AUDIO")
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()
