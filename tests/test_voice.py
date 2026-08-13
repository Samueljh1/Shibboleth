"""Acceptance spec for voice/. Jabir — Task A.

Runs with no API keys and without resemblyzer/torch installed: the embedding
path is skipped when resemblyzer is absent, everything else is exercised for
real. The decode tests are the ones that matter most — the browser sends
webm/opus and that is where this integration actually breaks.
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from app.config import Settings
from contracts.interfaces import Stt, VoiceEncoder
from voice import audio as va

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def sine_wav(seconds: float = 2.0, sr: int = 16_000, freq: float = 220.0) -> bytes:
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    return va.to_wav_bytes(0.4 * np.sin(2 * np.pi * freq * t), sr)


# -- decoding ---------------------------------------------------------------


def test_wav_round_trips_through_decode():
    samples, sr = va.decode_to_float32(sine_wav())
    assert sr == 16_000
    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert len(samples) == pytest.approx(32_000, rel=0.02)
    assert float(np.abs(samples).max()) == pytest.approx(0.4, abs=0.02)


def test_duration_seconds_is_right():
    assert va.duration_seconds(sine_wav(1.5)) == pytest.approx(1.5, abs=0.05)


def test_empty_audio_raises_decode_error():
    with pytest.raises(va.DecodeError):
        va.decode_to_float32(b"")


def test_garbage_audio_raises_decode_error():
    with pytest.raises(va.DecodeError):
        va.decode_to_float32(b"not audio at all, just some bytes" * 20)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_browser_webm_opus_decodes():
    """web/app.js records `audio/webm`. If this fails, /session/start is dead."""
    webm = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-c:a", "libopus", "-f", "webm", "pipe:1"],
        input=sine_wav(), capture_output=True, timeout=30,
    )
    if webm.returncode != 0:
        pytest.skip("this ffmpeg build has no libopus encoder")

    samples, sr = va.decode_to_float32(webm.stdout)
    assert sr == va.TARGET_SR
    assert samples.ndim == 1
    assert len(samples) == pytest.approx(32_000, rel=0.1)


def test_stereo_is_mixed_to_mono():
    sr = 16_000
    t = np.arange(sr, dtype=np.float32) / sr
    stereo = np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    mono = va._to_mono(stereo)
    assert mono.ndim == 1 and len(mono) == sr


# -- protocol conformance ---------------------------------------------------


def test_classes_match_the_contract_protocols():
    """Method names and arity must match or app/main.py cannot wire them."""
    from voice.encoder import ResemblyzerEncoder
    from voice.stt import ElevenLabsStt

    import inspect

    for cls, proto, method in (
        (ResemblyzerEncoder, VoiceEncoder, "embed_voice"),
        (ElevenLabsStt, Stt, "transcribe"),
    ):
        impl = getattr(cls, method, None)
        assert callable(impl), f"{cls.__name__}.{method} missing"
        assert list(inspect.signature(impl).parameters) == list(
            inspect.signature(getattr(proto, method)).parameters
        ), f"{cls.__name__}.{method} signature diverges from {proto.__name__}"


def test_importing_voice_does_not_require_the_heavy_deps():
    """`import voice` must not drag in torch — app/main.py builds STT and TTS
    independently of the encoder, and that only works if imports stay local."""
    import voice  # noqa: F401
    import voice.audio  # noqa: F401
    import voice.clone  # noqa: F401
    import voice.stt  # noqa: F401


# -- credentials ------------------------------------------------------------


def test_missing_keys_raise_at_construction_not_at_call_time():
    """app/main.py's `attempt()` records the reason and /health shows it —
    that only works if construction is what fails."""
    from voice.stt import ElevenLabsStt

    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        ElevenLabsStt(Settings(elevenlabs_api_key=""))


# -- clone rig --------------------------------------------------------------


def test_clone_falls_back_to_the_prerecorded_file(tmp_path, monkeypatch):
    """The build plan's armed fallback: live cloning is slow on the day."""
    from voice.clone import clone_utterance

    canned = tmp_path / "clone.mp3"
    canned.write_bytes(b"ID3-pretend-mp3")
    monkeypatch.setenv("CLONE_FALLBACK_AUDIO", str(canned))

    out = clone_utterance(b"", "anything", Settings(elevenlabs_api_key=""))
    assert out == b"ID3-pretend-mp3"


def test_clone_raises_clearly_when_there_is_no_fallback(monkeypatch):
    from voice.clone import CloneError, clone_utterance

    monkeypatch.delenv("CLONE_FALLBACK_AUDIO", raising=False)
    with pytest.raises(CloneError):
        clone_utterance(b"", "anything", Settings(elevenlabs_api_key=""))


# -- the real encoder, when it is installed ---------------------------------


def speechlike_wav(f0: float, seconds: float = 3.0, sr: int = 16_000, seed: int = 0) -> bytes:
    """A harmonic stack with a syllable-rate envelope and a little noise.

    Pure tones do NOT work: webrtcvad classifies them as non-speech and
    `preprocess_wav` returns an empty array. This survives the VAD and behaves
    like a speaker — f0 stands in for vocal tract identity.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    harmonics = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12))
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    return va.to_wav_bytes(0.3 * harmonics * envelope + 0.02 * rng.standard_normal(t.size), sr)


def test_resemblyzer_encoder_when_installed():
    pytest.importorskip("resemblyzer", reason="resemblyzer not installed")
    from voice.encoder import VOICE_DIM, ResemblyzerEncoder

    enc = ResemblyzerEncoder()
    same_a = enc.embed_voice(speechlike_wav(110, seed=1))
    same_b = enc.embed_voice(speechlike_wav(110, seed=9))  # different noise draw
    other = enc.embed_voice(speechlike_wav(200, seed=2))

    assert len(same_a) == VOICE_DIM
    assert np.linalg.norm(same_a) == pytest.approx(1.0, abs=1e-5)
    assert float(np.dot(same_a, same_b)) > 0.9, "same speaker must land close"
    assert float(np.dot(same_a, other)) < float(np.dot(same_a, same_b))


def test_encoder_is_deterministic():
    pytest.importorskip("resemblyzer", reason="resemblyzer not installed")
    from voice.encoder import ResemblyzerEncoder

    enc = ResemblyzerEncoder()
    clip = speechlike_wav(140, seed=4)
    assert float(np.dot(enc.embed_voice(clip), enc.embed_voice(clip))) > 0.999


@pytest.mark.parametrize("clip", ["silence", "tone"])
def test_encoder_refuses_audio_with_no_speech(clip):
    """A VAD-stripped clip embeds to a constant vector that sits equidistant
    from every enrolled voiceprint — `narrow()` would return a confident
    ranking built on nothing. It has to fail loudly instead."""
    pytest.importorskip("resemblyzer", reason="resemblyzer not installed")
    from voice.encoder import NoSpeechDetected, ResemblyzerEncoder

    audio = (
        va.to_wav_bytes(np.zeros(16_000 * 3, dtype=np.float32))
        if clip == "silence"
        else sine_wav(3.0)
    )
    with pytest.raises(NoSpeechDetected):
        ResemblyzerEncoder().embed_voice(audio)
