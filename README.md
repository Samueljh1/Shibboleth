# Shibboleth

Prove you're you, from any device — and defeat voice clones by asking the
questions only the real you can answer.

Voice narrows the field (Atlas Vector Search over speaker embeddings). Then the
engine asks **entropy-optimal questions** drawn from your private episodic
memory until one candidate crosses the threshold, or nobody does. Shannon
entropy in bits, dropping to zero, is the number on the projector.

## Who owns what

| | Area | Owner |
| --- | --- | --- |
| **A** | `voice/` — speaker embeddings, STT, TTS, clone rig | **Jabir** |
| **C** | `engine/` — entropy engine + LLM ⭐ centerpiece | **Jabir** |
| **B** | `store/`, `scripts/seed.py` — Atlas, personas | **Sam** |
| **D** | `web/` — the live visual | **Sam** |
| **E** | `app/` — API orchestration | **Sam** |

Each directory has a README with its acceptance criteria. **Stay in your own
directories.** Modules never import each other — only `contracts/` plus injected
interfaces. That's what lets us both work at once without merge pain.

`contracts/` is shared and is the source of truth. Need it changed? Change it,
prefix the commit `contract:`, and say so — don't diverge silently.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # fill in: Mongo URI, ElevenLabs, OpenRouter, OpenAI
```

Seed Atlas, then run:

```bash
python -m scripts.seed --index
uvicorn app.main:app --reload
```

UI at http://localhost:8000, API health at http://localhost:8000/health.

`/health` reports which subsystems constructed and why the others didn't.
Anything not wired yet returns 503 from its own endpoints only — so a half-built
`voice/` never blocks work on `store/` or `web/`, and vice versa.

## Flow

    audio -> VoiceEncoder -> Store.narrow (top-k candidates, prior from cosine sim)
          -> Engine.start -> next_question (argmax expected info gain)
          -> answer -> grade_and_update (Bayes) -> identified | rejected

HTTP surface: [contracts/api.md](contracts/api.md).
Shapes: [contracts/models.py](contracts/models.py).
Protocols: [contracts/interfaces.py](contracts/interfaces.py).

## Demo beats

1. **Narrowing** — speak one sentence, bars collapse, 2–3 questions, entropy → 0.
2. **Clone attack** — the biometric *passes* (that's the scary part), the
   knowledge gate rejects.
3. **Wipe** — drop a user's `memory_events` live; they can no longer authenticate.
   Proof that MongoDB was doing the work.

## Tests

```bash
python -m pytest -q
```

`tests/test_infogain.py` is the engine's acceptance spec — it skips while the
functions are stubs and goes live as they land.
