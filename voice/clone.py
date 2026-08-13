"""Clone-attack rig — demo Act 2. Jabir — Task A.

ElevenLabs instant voice clone from a short reference clip, then speak `text` in
that voice. Pre-record the clip as a fallback if live cloning is slow on the day.

Only clone a teammate or a judge who has agreed on the spot.
"""

from __future__ import annotations

from app.config import Settings


def clone_utterance(reference_audio: bytes, text: str, settings: Settings) -> bytes:
    """-> audio of `text` in the reference speaker's voice."""
    raise NotImplementedError("voice/clone.py — Jabir")
