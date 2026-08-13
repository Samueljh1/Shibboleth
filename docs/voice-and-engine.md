# `voice/` and `engine/` — reference

Tasks A and C (Jabir). Written so an agent picking up `store/`, `web/` or
`app/` can use these two modules without reading their source.

Both depend only on `contracts/` plus interfaces injected at construction.
Neither imports the other, nor `store/`, `web/` or `app/` — except
`engine/llm.py` and `voice/stt.py`, which read `app.config.Settings` for API
keys (the pattern `store/embeddings.py` already uses).

---

## Where they sit

```
audio bytes ──► voice.encoder.ResemblyzerEncoder.embed_voice() ──► 256-d vector
                                                                       │
                                             store.narrow(vec, k) ◄────┘
                                                      │
                                        [(user_id, cosine_sim), ...]
                                                      │
                              engine.start() ──► AuthSession (prior + entropy)
                                                      │
                    ┌─────────────── engine.next_question() ──► QuestionSpec
                    │                                 │
                    │                    (text shown on screen — no TTS)
                    │                                 │
                    │                   answer text (typed, or voice.stt)
                    │                                 │
                    └──── engine.grade_and_update() ──┘
                                     │
                         identified | rejected | in_progress
```

The engine re-reads memories from the Store on **every** call and caches
nothing across calls. That costs a query per step and buys the Act 3 wipe:
delete a user's `memory_events` and the next `next_question()` genuinely has
nothing to ask them.

---

## `engine/infogain.py` — pure maths, no I/O

Import it freely; it pulls in nothing but numpy.

### Distributions

| Function | Returns | Notes |
| --- | --- | --- |
| `shannon(posterior)` | `float` bits | `-Σ p·log2 p` over `p>0`. Uniform *n* → `log2 n`; point mass → `0`. This is the number on the projector. |
| `softmax(scores, temp=0.15)` | `dict` | Voice cosines → the prior. Max subtracted for stability. `temp` is the dial that keeps the biometric a *narrowing* step (see Tuning). |
| `bayes_update(posterior, likelihood)` | `dict` | `prior × likelihood`, renormalised. Never mutates inputs. An all-zero likelihood falls back to the prior instead of dividing by zero. |
| `leader(posterior)` | `(id\|None, prob)` | Pure-function twin of `AuthSession.leader`. |

### Vectors

| Function | Returns | Notes |
| --- | --- | --- |
| `as_matrix(vecs)` | `(n,d)` float32 | `(0,0)` for empty input. |
| `l2_normalize(M)` | `(n,d)` | Row-wise. Zero rows stay zero rather than producing NaN. |
| `cosine_matrix(A, B=None)` | `(n,m)` | Full pairwise cosine in one matmul. `B` defaults to `A`. |

### Question value

**The model.** For a question drawn from memory `m` owned by candidate `o`,
define `p_correct[u] = P(the answer grades correct | the speaker really is u)`.
For the owner that is `P_HIT`; for anyone else it scales with how much *their*
memories overlap `m` — if another candidate has a near-identical memory they
answer correctly too and the question is worthless. That overlap is exactly
`1 − discriminability`.

| Function | Returns | Notes |
| --- | --- | --- |
| `discriminability(memory_vec, other_vecs)` | `float` [0,1] | `1 − max cosine` against the nearest memory of any *other* candidate. `1.0` when nobody else has anything like it. Empty `other_vecs` → `1.0`. |
| `discriminability_batch(M, owners)` | `(n,)` | Same for every memory at once. `owners[i]` is memory *i*'s owner column index. One matmul instead of n² cosine calls. |
| `hit_probabilities(keys, owner_id, memory_vec, mems_by_candidate)` | `dict` | Scalar form of `p_correct`, keyed by user id. |
| `hit_probability_matrix(M, owners, n_candidates)` | `(n,c)` | Vectorised form. `[i,u]` = P(candidate *u* answers memory *i* correctly). |
| `expected_info_gain(posterior, owner_id, discrim)` | `float` bits | **The contract signature** (`tests/test_infogain.py`). Exact mutual information between the binary outcome and identity — peaks when the owner sits near p=0.5. |
| `expected_info_gain_pc(posterior, p_correct)` | `float` bits | Same, but each rival scored on its own overlap rather than a shared worst case. Sharper. |
| `info_gain_batch(post_vec, PC)` | `(n,)` bits | All candidate questions at once. **Identification** IG. |
| `info_gain_verify_batch(post_vec, PC, claimed_idx)` | `(n,)` bits | **Verification** IG — information about the single bit "is the speaker the claimed user?". See below. |

**Why two IG functions.** Identification IG chases whichever candidate
currently leads. That is right when nobody has claimed an identity. But when
`session.claimed_id` is set, a clone's first wrong answer knocks the claimed
user down, the engine wanders off interrogating bystanders, *they* fail
questions that were never about them, and the claimed user drifts back up. It
still rejects — but by running out of budget, with the impostor's bar climbing
on screen. Targeting the claim keeps every question pointed at the one bit
that matters, and produces the brief's stated clone path: the claimed
identity's mass collapses. `next_question()` picks which to use automatically.

### Grading

| Function | Returns | Notes |
| --- | --- | --- |
| `grade_score(sim_owner, factual_ok=None)` | `float` [0,1] | Combines answer/memory cosine with the LLM verdict, `W_SIM`/`1−W_SIM`. **`factual_ok=None` means the LLM had no opinion** and the score rests on similarity alone — a timed-out grader must never read as a wrong answer. |
| `answer_likelihood(score, p_correct)` | `dict` | Soft evidence. `score=1` → likelihood *is* `p_correct`; `score=0` → its complement, which is what collapses a clone's claim. |

---

## `engine/questions.py` — phrasing support

| Function | Returns | Notes |
| --- | --- | --- |
| `content_tokens(text)` | `list[str]` | Distinctive lowercase tokens (len>3, non-stopword) — what an answer would have to supply. |
| `leaks_answer(question, memory_text)` | `bool` | True if the question hands over its own answer: ≥60% of the memory's distinctive tokens echoed, or a 6-word verbatim run. **Every LLM-phrased question passes through this** — one that leaks lets an impostor answer correctly and concentrates the posterior on the wrong person. |
| `pick_target_attr(memory, mems_by_candidate, owner_id)` | `str\|None` | The `salient_attrs` key where other candidates hold *different* values — the attribute doing the identifying work. Populates `QuestionSpec.target_attr` for the UI. |
| `when_phrase(ts)` | `str` | `"earlier afternoon"`, `"yesterday morning"`, `"on Tuesday"`. Recency is the cue a clone cannot fake. |
| `fallback_question(memory, target_attr=None)` | `str` | Safe non-leaking template, by `memory.kind`. Used when the LLM is down, slow, or leaked. |

---

## `engine/engine.py` — `EntropyEngine`

```python
EntropyEngine(store, embedder, llm,
              tau_id=0.85, tau_reject=0.05, max_questions=5,
              prior_temp=PRIOR_TEMP, max_mem_per_candidate=30)
```

Implements `contracts.interfaces.Engine`. Constructor argument order matches
what `app/main.py` already passes.

### `start(candidates) -> AuthSession`
`candidates` is `store.narrow()`'s output. Softmaxes the cosines into the
prior, sets `_id`, `candidate_ids` (sorted by probability), `posterior`,
`entropy_bits`. Status is `in_progress`, or `rejected` if there are no
candidates at all. The caller sets `claimed_id` and `voice_vec` afterwards.

### `next_question(s) -> (s, QuestionSpec | None)`
Fresh-reads every candidate's memories, drops any already in `s.asked` or
`s.pending`, scores all remaining in one vectorised pass, returns the argmax.

Returns `(s, None)` when nothing is askable — budget spent, or every candidate
is out of memories (the post-wipe path). **`app/main.py` already handles this**
by calling `finalize(s, force=True)`.

`QuestionSpec.ig` reports *identification* bits even when selection ranked by
verification IG, so the UI's numbers stay in one currency with the entropy
meter.

### `grade_and_update(s, q, answer) -> AuthSession`
Embeds the answer, cosines it against the target memory, asks the LLM for a
factual verdict, combines into a score, converts to a likelihood, Bayes-updates
the posterior, recomputes entropy, appends an `AskedQuestion`, clears
`s.pending`, then calls `finalize()`.

If the target memory has vanished mid-session (a live wipe), the turn is
recorded with `graded=False` and the posterior is left untouched — no crash.

### `finalize(s, force=False) -> AuthSession`
The stop rules, in one place:

1. `max(posterior) > tau_id` → **identified** — unless a `claimed_id` was set
   and someone *else* crossed the bar, which is a **rejection**, not an
   identification of the bystander the clone happened to resemble.
2. `claimed_id`'s mass `< tau_reject` → **rejected** (the clone path).
3. `force`, or `len(asked) >= max_questions` → **rejected** (budget spent).
4. Otherwise **in_progress**.

### Degradation, all tested
- Dead LLM → templated questions, grading on embedding similarity alone.
- Memory wiped mid-session → turn recorded ungraded.
- Mixed embedding dimensions (someone re-seeded with a different model) →
  minority dimension filtered out rather than exploding the matrix build.
- Any `store.memories()` exception → treated as an empty list.

---

## `engine/llm.py` — `OpenRouterLlm(settings)`

Implements `contracts.interfaces.Llm`. OpenAI-compatible chat completions,
`temperature=0.2`, 12s timeout. Raises at construction if
`OPENROUTER_API_KEY` is unset, so `/health` reports it.

**Failure policy differs per call on purpose:**

- `phrase_question(memory_text) -> str` returns `""` on any failure; the engine
  then asks a safe templated question.
- `factual_check(answer, memory_text) -> bool` **raises**. The engine catches it
  and grades on similarity alone. Returning `False` on a timeout would mark a
  genuine user's correct answer wrong and false-reject them on stage.

The phrasing prompt forbids restating the memory's specifics; `leaks_answer()`
enforces it independently, because a prompt is not a guarantee.

---

## `voice/audio.py` — decoding

`web/app.js` records **`audio/webm`** (Opus), which neither resemblyzer,
librosa nor soundfile can open. Everything goes through here first.

| Function | Returns | Notes |
| --- | --- | --- |
| `decode_to_float32(audio, target_sr=16000)` | `(float32 mono, sr)` | Tries soundfile → stdlib `wave` → **ffmpeg**. Raises `DecodeError` if all three fail. |
| `duration_seconds(audio)` | `float` | |
| `to_wav_bytes(samples, sr)` | `bytes` | float32 mono → 16-bit PCM wav. |

**`ffmpeg` must be on PATH on the demo machine** — it is the only backend that
reads what the browser actually sends.

---

## `voice/encoder.py` — `ResemblyzerEncoder()`

`embed_voice(audio: bytes) -> list[float]` — 256-d, L2-normalised. Model loads
once in `__init__` (~1s); do not construct per request.

Clips shorter than resemblyzer's 1.6s window are padded, not rejected —
someone on stage will say two words.

**Raises `NoSpeechDetected`** when VAD strips the clip to nothing (silence, a
dead mic, a non-speech tone). This matters: `embed_utterance` on an empty array
returns a *constant* vector that is equidistant from every enrolled
voiceprint, so `narrow()` would return a confident-looking ranking built on
noise. **`app/main.py` should catch this in `/session/start` and return 400
"no speech detected — try again"** rather than letting it 500.

Measured on synthetic speech: same speaker across utterances ≈ 0.997 cosine,
cross-speaker 0.54–0.87.

---

## `voice/stt.py` — `ElevenLabsStt(settings)`

`transcribe(audio: bytes) -> str`. POSTs to
`https://api.elevenlabs.io/v1/speech-to-text` (multipart `file` + `model_id`,
`xi-api-key` header); transcript comes back on `text`.

Tries `scribe_v1` then `scribe_v2` — account access varies and a 4xx on the
first is not worth losing an answer over. **Returns `""` on any failure**; the
UI's typed-answer path is the backstop. Raises at construction if the key is
unset.

---

## `voice/clone.py` — Act 2

`clone_utterance(reference_audio, text, settings) -> bytes`

Instant voice clone → TTS at `similarity_boost=0.95` → deletes the temporary
voice so rehearsals don't burn account slots. The cloned utterance should embed
close enough to the target that `narrow()` still ranks them first — **the
biometric passing is the point**; the knowledge gate is what rejects them.

Falls back to the file at `CLONE_FALLBACK_AUDIO` if live cloning fails or is
slow (the build plan's armed fallback). Raises `CloneError` if neither works.

---

## Tuning dials

| Name | Where | Default | Raise it when |
| --- | --- | --- | --- |
| `PRIOR_TEMP` | env, `engine/engine.py` | `0.15` | The voice prior alone lands near `TAU_ID` — the run then identifies in one question and the entropy meter barely moves. |
| `TAU_ID` | `.env` | `0.85` | False accepts. |
| `TAU_REJECT` | `.env` | `0.05` | Clones are surviving too long. |
| `MAX_QUESTIONS` | `.env` | `5` | |
| `SIM_FLOOR` / `SIM_CEIL` | `engine/infogain.py` | `0.15` / `0.65` | **Calibrated against a hashing stand-in, not real embeddings.** Re-tune once OpenAI embeddings are live: these decide what counts as a correct answer. |
| `P_HIT` / `P_FLOOR` | `engine/infogain.py` | `0.95` / `0.05` | `P_HIT` is deliberately not 1.0 — real people forget, and assuming perfect recall false-rejects the genuine user. |

---

## Shared files this branch touched

- `contracts/interfaces.py` — removed the `Tts` Protocol.
- `contracts/api.md` — removed `question_audio_b64` from both responses.
- `app/main.py` — removed the `tts` subsystem, `_speak()`, and the
  `question_audio_b64` response fields. Questions are shown as text.
  (`voice/README.md` states the rule: change `main.py` in the same commit as a
  removed name. `web/app.js:79` already guards `if (audio)`, so the frontend
  no-ops without a change.)
- `requirements.txt` — dropped the unused `elevenlabs` SDK (STT and the clone
  rig use `requests`); pinned **`setuptools<81`**, without which
  `import resemblyzer` dies: `webrtcvad` imports `pkg_resources`, removed in
  setuptools 81+.

`ELEVENLABS_API_KEY` is still required (STT + clone rig). `ELEVENLABS_VOICE_ID`
is now unused.

### Still on Sam's side
1. Catch `voice.encoder.NoSpeechDetected` in `/session/start` → 400.
2. Optionally drop `play()` and `question_audio_b64` from `web/app.js` — it is
   inert now, not broken.

---

## Tests

```bash
python -m pytest tests/ -q      # 40 passed
```

- `tests/test_infogain.py` — Sam's original acceptance spec, **unmodified**.
- `tests/test_engine.py` — the three demo acts as tests, plus selection quality
  and degradation. Asserts the batch and scalar IG paths agree, so the unit
  tests still describe what actually runs.
- `tests/test_voice.py` — decoding (including a real browser-style webm/opus
  round-trip), Protocol conformance, credential handling, and the real encoder
  when resemblyzer is installed.
- `tests/doubles.py` — in-memory `FakeStore`, `FakeEmbedder`, `FakeLlm`,
  `DeadLlm`, and five personas. `build_world()` returns a seeded store.

**`FakeEmbedder` is a hashing vectoriser, not a random-vector-per-string mock.**
A random mock maps every distinct string to an orthogonal vector, so
`cosine(answer, memory)` is ~0 whether the answer is right or wrong and the
grading path silently tests nothing.

The personas are deliberately hostile: several pairs share a near-duplicate
memory (the standup pair, the Ethiopian-coffee pair, the Frankfurt-outage
pair), so a selector that ignores discriminability picks a question two
candidates can both answer — and a test catches it.
