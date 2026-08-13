# `voice/` — Task A · **owner: Jabir**

| File | Class / fn | Implements |
| --- | --- | --- |
| `encoder.py` | `ResemblyzerEncoder` | `VoiceEncoder` — wav → 256-d |
| `stt.py` | `ElevenLabsStt` | `Stt` |
| `tts.py` | `ElevenLabsTts` | `Tts` |
| `clone.py` | `clone_utterance` | the Act 2 attack rig |

`app/main.py` imports exactly those names — keep them, or change `main.py` in the
same commit.

**Done when:** same speaker → high cosine, different → low; `speak()` returns
playable bytes; `transcribe()` round-trips a clip; a cloned utterance embeds
close enough to the target that `narrow()` still ranks them first (the biometric
*passing* is the point — the knowledge gate is what rejects them).

**Don't touch:** `store/`, `web/`, `app/`. Import from `contracts/` only.
