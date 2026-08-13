"""Speaker embeddings (resemblyzer, 256-d). Jabir — Task A.

    from resemblyzer import VoiceEncoder, preprocess_wav
    wav = preprocess_wav(io.BytesIO(audio))
    return VoiceEncoder().embed_utterance(wav).tolist()

Load the model once in __init__, not per call.
"""

from __future__ import annotations


class ResemblyzerEncoder:
    """Implements contracts.interfaces.VoiceEncoder."""

    def __init__(self) -> None:
        raise NotImplementedError("voice/encoder.py — Jabir")

    def embed_voice(self, audio: bytes) -> list[float]:
        """wav bytes -> 256-d L2-normalised vector."""
        raise NotImplementedError
