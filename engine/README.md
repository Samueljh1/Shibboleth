# `engine/` — Task C · **owner: Jabir** ⭐ the centerpiece

Posterior over candidates → ask the max-expected-information-gain question →
grade against stored memory → Bayes update → identified or rejected. Shannon
entropy in bits is the number on the projector.

| File | Contents |
| --- | --- |
| `infogain.py` | pure functions: `shannon`, `softmax`, `bayes_update`, `discriminability`, `expected_info_gain` |
| `engine.py` | `EntropyEngine` implementing `contracts.interfaces.Engine` |
| `llm.py` | `OpenRouterLlm` implementing `contracts.interfaces.Llm` |

Keep `infogain.py` free of I/O — that is what makes it testable in the time we
have, and the tests are the argument that the math is real.

## The loop

1. **Prior** — `start()`: `P(user) ∝ softmax(voice cosine sim)` over the top-k hits.
2. **Select** — per candidate memory, `discriminability = 1 - max cosine against the nearest memory of any OTHER candidate`; expected IG under the current posterior; argmax.
   *If the IG math is running late:* rank by raw discriminability owned by the leader. Still demos well, swap the real thing in after.
3. **Phrase** — `llm.phrase_question(memory.text)`, without leaking the answer.
4. **Grade** — `cosine(embed(answer), target_memory)` combined with `llm.factual_check` for names and numbers → likelihood.
5. **Update** — Bayes, recompute entropy, append to `session.asked`.
6. **Stop** — `max(posterior) > TAU_ID` → identified; budget spent with no winner, or `claimed_id` mass below `TAU_REJECT` → rejected (the clone path).

**Done when:** entropy is non-increasing across correct answers; a clone
transcript drives the claimed user's mass down to `rejected`; a genuine
transcript hits `identified` in ≤ ~3 questions on the seed personas.
`tests/test_infogain.py` encodes this — it skips while the functions are stubs.

**Don't touch:** `voice/`, `web/`, `store/`, `app/`. Depend only on `contracts/`
plus the injected `Store` / `Llm` / `Embedder`.

---

## Status — implemented (branch `jabir/a-c-voice-engine`)

All five `infogain` functions and all four `Engine` methods are live. Sam's
`tests/test_infogain.py` passes unmodified; `tests/test_engine.py` adds the
three demo acts as tests. `tests/doubles.py` holds in-memory Store/Embedder/Llm
so none of it needs Atlas or a key.

**Everything numeric is numpy.** Selection scores every candidate memory
against every *other* candidate's memories — O(N²) cosines at ~200 memories a
session. As Python loops that is seconds of dead air; as one `M @ M.T` plus one
broadcast it is sub-millisecond:

| function | shape | what it replaces |
| --- | --- | --- |
| `cosine_matrix(A, B)` | one matmul | n·m cosine calls |
| `discriminability_batch(M, owners)` | (n,) | n `discriminability()` calls |
| `hit_probability_matrix(M, owners, c)` | (n, c) | n·c overlap scans |
| `info_gain_batch(post, PC)` | (n,) | n `expected_info_gain()` calls |

The scalar contract functions are kept and tested, and
`test_batch_info_gain_matches_the_scalar_contract_function` asserts the two
paths agree — so the unit tests still describe what actually runs.

`expected_info_gain` is the exact mutual information between the binary
outcome and identity, not the two-outcome approximation the stub described:
`p_correct[owner] = P_HIT`, `p_correct[other] = P_FLOOR + (P_HIT−P_FLOOR)·(1−discrim)`.
It still peaks near an even split, so the documented behaviour holds.

Extra file: `engine/questions.py` — leak detection (a question that restates
its own memory lets an impostor answer correctly), `target_attr` selection, and
the non-leaking templates used when the LLM is slow or down.

**Degradation, all tested:** a dead OpenRouter still asks templated questions
and grades on embedding similarity alone (a timeout must never read as a wrong
answer); a memory wiped mid-session records the turn ungraded instead of
crashing; mixed embedding dimensions are filtered rather than fatal.

**One dial for the day:** `PRIOR_TEMP` (env, default 0.15). If the voice prior
alone lands near `TAU_ID`, the run identifies in one question and the entropy
meter barely moves — raise it. Current trace on the 5 test personas:
genuine 1.31 → 0.48 bits, identified in 1; clone rejected after 4 with the
claimed identity's mass collapsing on the first wrong answer; post-wipe
`next_question` returns `None` and the session finalises rejected.

Full function-by-function reference: [docs/voice-and-engine.md](../docs/voice-and-engine.md)
