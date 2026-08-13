"""Speaker embeddings (resemblyzer, 256-d). Jabir — Task A.

The browser sends webm/opus, which resemblyzer cannot open — so audio goes
through `voice.audio.decode_to_float32` first and reaches resemblyzer as
samples plus a sample rate. The model is loaded once in `__init__`; loading it
per call costs ~1s and would land squarely in the live loop.

Output is L2-normalised, which makes the store's cosine search and the
engine's prior directly comparable across utterances of different length.
"""

from __future__ import annotations

import numpy as np

from voice.audio import TARGET_SR, decode_to_float32

VOICE_DIM = 256
MIN_SECONDS = 1.6
"""Resemblyzer's partial-utterance window. Shorter clips get padded rather than
rejected — on stage someone will say two words and we still have to answer."""

MIN_VOICED_SAMPLES = 800  # 50ms at 16kHz
"""Below this after VAD there is no speech left to embed. See NoSpeechDetected."""


class NoSpeechDetected(ValueError):
    """The clip contained no speech once silence was trimmed.

    This matters more than it looks. `preprocess_wav` runs webrtcvad and
    returns an EMPTY array for silence, a pure tone, or a dead microphone —
    and `embed_utterance` on an empty (or zero-padded) array happily returns a
    constant vector. That vector is equidistant from every enrolled
    voiceprint, so `narrow()` returns a confident-looking ranking built on
    nothing and the demo authenticates against noise. Failing loudly here is
    the only honest option.

    `app/main.py` should catch this on /session/start and return 400 "no
    speech detected — try again" rather than letting it 500.
    """


class ResemblyzerEncoder:
    """Implements contracts.interfaces.VoiceEncoder."""

    def __init__(self) -> None:
        from resemblyzer import VoiceEncoder  # lazy: pulls in torch

        self._model = VoiceEncoder()

    def embed_voice(self, audio: bytes) -> list[float]:
        """wav bytes -> 256-d L2-normalised vector."""
        from resemblyzer import preprocess_wav

        samples, sr = decode_to_float32(audio, target_sr=TARGET_SR)
        wav = preprocess_wav(samples, source_sr=sr)

        if wav.size < MIN_VOICED_SAMPLES or not np.all(np.isfinite(wav)):
            raise NoSpeechDetected(
                f"no speech in {len(samples) / max(sr, 1):.1f}s of audio "
                "(silence, a dead mic, or a non-speech tone)"
            )

        need = int(MIN_SECONDS * TARGET_SR)
        if wav.size < need:
            # Pad rather than fail: a too-short clip is a weak embedding, and a
            # weak embedding just means the voice narrows less — which the
            # knowledge gate is there to absorb.
            wav = np.pad(wav, (0, need - wav.size))

        vec = np.asarray(self._model.embed_utterance(wav), dtype=np.float32)
        n = float(np.linalg.norm(vec))
        if n < 1e-8:
            raise NoSpeechDetected("encoder returned a degenerate embedding")
        return [float(x) for x in vec / n]
