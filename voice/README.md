# `voice/` — Task A · **owner: Jabir**

| File | Class / fn | Implements |
| --- | --- | --- |
| `encoder.py` | `ResemblyzerEncoder` | `VoiceEncoder` — wav → 256-d |
| `stt.py` | `ElevenLabsStt` | `Stt` |
| `clone.py` | `clone_utterance` | the Act 2 attack rig |

`app/main.py` imports exactly those names — keep them, or change `main.py` in the
same commit.

**Done when:** same speaker → high cosine, different → low; `transcribe()`
round-trips a clip; a cloned utterance embeds
close enough to the target that `narrow()` still ranks them first (the biometric
*passing* is the point — the knowledge gate is what rejects them).

**Don't touch:** `store/`, `web/`, `app/`. Import from `contracts/` only.

---

## Status — implemented (branch `jabir/a-c-voice-engine`)

All four names `app/main.py` imports exist and match the Protocol signatures
(asserted in `tests/test_voice.py`).

**The thing that would have broken the demo:** `web/app.js` records
`audio/webm`, and neither resemblyzer, librosa nor soundfile can open
Opus-in-WebM — `preprocess_wav(io.BytesIO(audio))` would have failed on every
real recording. So there is a new `voice/audio.py` that decodes through
soundfile → stdlib `wave` → **ffmpeg** (the webm path) and hands resemblyzer
samples plus a sample rate. `ffmpeg` must be on PATH on the demo machine;
`test_browser_webm_opus_decodes` covers it and skips if absent.

Also handled: clips shorter than resemblyzer's 1.6s window are padded, not
rejected — someone on stage will say two words.

**No TTS.** Questions are rendered as text on screen (Sam, `web/`), so
`voice/tts.py`, the `Tts` Protocol and the `question_audio_b64` response field
are gone — see the `contract:` note in the commit. That also takes a synthesis
call out of the live loop: the question appears the instant it is chosen.

**Failure policy**, matching how `app/main.py` reports readiness: missing keys
raise at *construction* so `attempt()` records the reason and `/health` shows
it. `transcribe()` returns `""` on any failure (the UI has a typed fallback);
STT tries `scribe_v1` then `scribe_v2` since account access varies.

**Clone rig:** `clone_utterance()` does live instant-voice-cloning (add voice →
TTS at `similarity_boost` 0.95 → delete the voice so rehearsals don't burn
slots), and falls back to a pre-recorded file at `CLONE_FALLBACK_AUDIO` when
live cloning is slow or unavailable — the armed fallback from the build plan.

Env beyond `.env.example`: `ELEVENLABS_STT_MODEL`, `ELEVENLABS_TTS_MODEL`
(the clone rig still synthesises), `CLONE_FALLBACK_AUDIO` — all optional.
`ELEVENLABS_VOICE_ID` is now unused; the clone rig creates its own voice.

**Not verified against real services** — no keys here. The ElevenLabs STT
endpoint/fields were checked against the current API docs; voice-add follows
the standard shape and needs one live call to confirm.

Full function-by-function reference: [docs/voice-and-engine.md](../docs/voice-and-engine.md)
