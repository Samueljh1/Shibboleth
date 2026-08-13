# `web/` — Task D · **owner: Sam**

Static single page served by FastAPI at `/`. Talks only to
[contracts/api.md](../contracts/api.md) — never reads the DB.

The money visual: candidate probability bars reanimating each step, the entropy
meter in bits dropping toward 0, the Q/A log, and the IDENTIFIED / REJECTED
verdict. Plus the wipe control for Act 3.

Mic capture uses `MediaRecorder` (webm) — confirm `voice/stt.py` accepts that
container, or transcode server-side. The typed-answer box is always live; Pier 48
is loud and it's the armed fallback.
