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
