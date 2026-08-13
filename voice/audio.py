"""Audio decoding helpers. Jabir — Task A.

The browser records `audio/webm` (see web/app.js), and neither soundfile nor
librosa can open Opus-in-WebM. So every path that needs samples goes through
`decode_to_float32` here, which tries, in order:

  1. soundfile  — wav / flac / ogg, no subprocess;
  2. stdlib wave — plain PCM wav, works with nothing installed;
  3. ffmpeg     — webm/opus, mp3, m4a, anything else.

Returning `(samples, sample_rate)` rather than a file keeps the callers free of
temp-file cleanup, and every failure surfaces as `DecodeError` so the API layer
can answer with something better than a stack trace.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave

import numpy as np

TARGET_SR = 16_000
"""Resemblyzer's working rate; also what ElevenLabs is happy to receive."""


class DecodeError(RuntimeError):
    """Audio could not be decoded by any available backend."""


def decode_to_float32(audio: bytes, target_sr: int = TARGET_SR) -> tuple[np.ndarray, int]:
    """Any audio bytes -> (mono float32 in [-1, 1], sample_rate).

    Resampling to `target_sr` only happens on the ffmpeg path, where it is
    free; the other backends return their native rate and the caller passes it
    on to resemblyzer, which resamples properly.
    """
    if not audio:
        raise DecodeError("empty audio payload")

    for backend in (_via_soundfile, _via_wave, _via_ffmpeg):
        try:
            samples, sr = backend(audio, target_sr)
        except Exception:
            continue
        if samples is not None and samples.size:
            return _to_mono(samples), sr

    raise DecodeError(
        "could not decode audio — install soundfile, or ffmpeg for webm/opus "
        "(the browser records webm by default)"
    )


def duration_seconds(audio: bytes) -> float:
    samples, sr = decode_to_float32(audio)
    return float(len(samples)) / float(sr or TARGET_SR)


def to_wav_bytes(samples: np.ndarray, sr: int = TARGET_SR) -> bytes:
    """float32 mono -> 16-bit PCM wav bytes. Useful for handing decoded audio
    to an API that only accepts wav."""
    clipped = np.clip(_to_mono(np.asarray(samples, dtype=np.float32)), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)
    return buf.getvalue()


# -- backends ---------------------------------------------------------------


def _via_soundfile(audio: bytes, _target_sr: int):
    import soundfile as sf  # lazy: heavy, and optional

    samples, sr = sf.read(io.BytesIO(audio), dtype="float32", always_2d=False)
    return np.asarray(samples, dtype=np.float32), int(sr)


def _via_wave(audio: bytes, _target_sr: int):
    with wave.open(io.BytesIO(audio), "rb") as w:
        if w.getsampwidth() != 2:
            raise DecodeError("stdlib wave path handles 16-bit PCM only")
        frames = w.readframes(w.getnframes())
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            samples = samples.reshape(-1, w.getnchannels())
        return samples, int(w.getframerate())


def _via_ffmpeg(audio: bytes, target_sr: int):
    """The webm/opus path — what the browser actually sends."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise DecodeError("ffmpeg not on PATH")
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "f32le", "-ac", "1", "-ar", str(int(target_sr)), "pipe:1"],
        input=audio,
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise DecodeError(f"ffmpeg failed: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy(), int(target_sr)


def _to_mono(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    return arr.mean(axis=1).astype(np.float32) if arr.ndim > 1 else arr
