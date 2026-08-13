"""Pure information-theory functions. Jabir — Task C. ⭐

No I/O — plain dicts and vectors, so every one is unit-testable on its own.
`tests/test_infogain.py` is the acceptance spec.

Everything numeric goes through numpy. That is not decoration: memories are
1536-d and voiceprints 256-d, and question selection scores every candidate
memory against every *other* candidate's memories — O(N²) cosines at ~200
memories per session. As Python loops that is seconds of dead air in a live
demo; as one `M @ M.T` it is sub-millisecond. The scalar functions below keep
the simple signatures the contract specifies; the `*_batch` functions do the
whole candidate set in one vectorised pass and are what `engine.py` calls.

The model
---------
For a question drawn from memory `m` owned by candidate `o`, define

    p_correct[u] = P(the answer grades as correct | the speaker really is u)

  * for the owner `o` this is high (`P_HIT`) — they lived it;
  * for anyone else it scales with how much *their* memories overlap `m`. If
    another candidate has a near-identical memory they answer correctly too
    and the question is worthless. That overlap is exactly `1 - discriminability`.

Expected information gain is then the mutual information between the binary
outcome and identity — computed exactly from the posterior and `p_correct`,
not approximated.
"""

from __future__ import annotations

import numpy as np

# --- tunables --------------------------------------------------------------

P_HIT = 0.95
"""P(correct | you own the memory). Not 1.0 — real people forget, and a
threshold that assumes perfect recall false-rejects the genuine user."""

P_FLOOR = 0.05
"""P(correct | the memory is a stranger's and you are guessing)."""

SIM_FLOOR = 0.15
"""Answer/memory cosine at or below which grading reads the answer as wrong."""

SIM_CEIL = 0.65
"""Answer/memory cosine at or above which grading reads the answer as right."""

W_SIM = 0.55
"""Weight on embedding similarity when combined with the LLM factual check."""

_EPS = 1e-12


# --- distributions ---------------------------------------------------------


def shannon(posterior: dict[str, float]) -> float:
    """Entropy in bits: -sum(p*log2 p) over p>0. Uniform n -> log2 n; point mass -> 0."""
    if not posterior:
        return 0.0
    p = np.fromiter(posterior.values(), dtype=np.float64, count=len(posterior))
    p = p[p > _EPS]
    if p.size == 0:
        return 0.0
    return float(max(0.0, -np.sum(p * np.log2(p))))


def softmax(scores: dict[str, float], temp: float = 0.15) -> dict[str, float]:
    """Temperature softmax over voice sims -> the prior. Subtract the max first.

    `temp` is what decides how much the voice is allowed to claim. Speaker
    cosines sit in a narrow band (same speaker ~0.9, different ~0.65), so too
    cold a temperature quietly promotes the biometric to *authenticator* —
    the exact failure this project exists to reject. At 0.15 a clean match
    leads with ~0.35 of the mass and ~2 bits are still on the table.
    """
    if not scores:
        return {}
    keys = list(scores)
    v = np.fromiter((scores[k] for k in keys), dtype=np.float64, count=len(keys))
    e = np.exp((v - v.max()) / max(float(temp), 1e-3))
    total = float(e.sum())
    if total < _EPS:
        return {k: 1.0 / len(keys) for k in keys}
    return {k: float(x) for k, x in zip(keys, e / total)}


def bayes_update(
    posterior: dict[str, float], likelihood: dict[str, float]
) -> dict[str, float]:
    """prior * likelihood, renormalised. Doesn't mutate inputs; survives an
    all-zero likelihood by falling back to the prior (a clone answering
    gibberish must not divide by zero)."""
    if not posterior:
        return {}
    keys = list(posterior)
    p = np.fromiter((posterior[k] for k in keys), dtype=np.float64, count=len(keys))
    lik = np.fromiter(
        (max(0.0, float(likelihood.get(k, 0.0))) for k in keys),
        dtype=np.float64,
        count=len(keys),
    )
    w = np.clip(p, 0.0, None) * lik
    total = float(w.sum())
    if total < _EPS:
        prior_total = float(np.clip(p, 0.0, None).sum())
        if prior_total < _EPS:
            return {k: 1.0 / len(keys) for k in keys}
        return {k: float(x) for k, x in zip(keys, np.clip(p, 0.0, None) / prior_total)}
    return {k: float(x) for k, x in zip(keys, w / total)}


def leader(posterior: dict[str, float]) -> tuple[str | None, float]:
    """(argmax id, its probability). Mirrors AuthSession.leader for pure use."""
    if not posterior:
        return None, 0.0
    uid = max(posterior, key=posterior.__getitem__)
    return uid, float(posterior[uid])


# --- vectors ---------------------------------------------------------------


def as_matrix(vecs) -> np.ndarray:
    """(n, d) float32 matrix from a sequence of vectors; (0, 0) when empty."""
    if vecs is None or len(vecs) == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return np.asarray(vecs, dtype=np.float32)


def l2_normalize(M: np.ndarray) -> np.ndarray:
    """Row-wise unit norm. Zero rows stay zero, so they score 0 against
    everything instead of producing NaNs."""
    if M.size == 0:
        return M
    n = np.linalg.norm(M, axis=-1, keepdims=True)
    return M / np.where(n < _EPS, 1.0, n)


def cosine_matrix(A, B=None) -> np.ndarray:
    """Full pairwise cosine matrix in one matmul. B defaults to A."""
    MA = l2_normalize(as_matrix(A))
    MB = MA if B is None else l2_normalize(as_matrix(B))
    if MA.size == 0 or MB.size == 0:
        return np.zeros((MA.shape[0], 0 if MB.size == 0 else MB.shape[0]), dtype=np.float32)
    return MA @ MB.T


def discriminability(memory_vec: list[float], other_vecs: list[list[float]]) -> float:
    """1 - max cosine against the nearest memory of any OTHER candidate, in [0,1].
    High means: only this person could answer it."""
    if not len(memory_vec) or other_vecs is None or len(other_vecs) == 0:
        return 1.0
    sims = cosine_matrix([memory_vec], other_vecs)
    if sims.size == 0:
        return 1.0
    nearest = float(np.clip(sims.max(), 0.0, 1.0))
    return float(np.clip(1.0 - nearest, 0.0, 1.0))


def discriminability_batch(M: np.ndarray, owners: np.ndarray) -> np.ndarray:
    """Discriminability for EVERY memory at once. `M` is (n, d), `owners` is
    (n,) of owner-column indices. One matmul instead of n² cosine calls."""
    if M.size == 0:
        return np.zeros((0,), dtype=np.float32)
    S = np.clip(l2_normalize(M) @ l2_normalize(M).T, 0.0, 1.0)
    same_owner = owners[:, None] == owners[None, :]
    S = np.where(same_owner, -1.0, S)  # only other candidates count
    nearest = S.max(axis=1)
    nearest = np.where(nearest < 0.0, 0.0, nearest)  # nobody else has anything
    return (1.0 - nearest).astype(np.float32)


# --- question value --------------------------------------------------------


def hit_probabilities(
    posterior_keys: list[str],
    owner_id: str,
    memory_vec: list[float],
    memories_by_candidate: dict[str, list[list[float]]],
    p_hit: float = P_HIT,
    p_floor: float = P_FLOOR,
) -> dict[str, float]:
    """P(answer grades correct | speaker is u), for each candidate u."""
    out: dict[str, float] = {}
    for uid in posterior_keys:
        if uid == owner_id:
            out[uid] = p_hit
            continue
        others = memories_by_candidate.get(uid) or []
        overlap = 1.0 - discriminability(memory_vec, others)
        out[uid] = p_floor + (p_hit - p_floor) * overlap
    return out


def hit_probability_matrix(
    M: np.ndarray,
    owners: np.ndarray,
    n_candidates: int,
    p_hit: float = P_HIT,
    p_floor: float = P_FLOOR,
) -> np.ndarray:
    """(n_memories, n_candidates) matrix of p_correct, in one vectorised pass.

    Entry [i, u] is P(a speaker who is really candidate u answers memory i
    correctly): `p_hit` when u owns i, otherwise scaled by how well u's own
    best-matching memory covers i.
    """
    if M.size == 0:
        return np.zeros((0, n_candidates), dtype=np.float32)
    S = np.clip(l2_normalize(M) @ l2_normalize(M).T, 0.0, 1.0)
    # best overlap of each memory against each candidate's memory set
    overlap = np.zeros((M.shape[0], n_candidates), dtype=np.float32)
    for u in range(n_candidates):
        cols = owners == u
        if cols.any():
            overlap[:, u] = S[:, cols].max(axis=1)
    P = p_floor + (p_hit - p_floor) * overlap
    P[np.arange(M.shape[0]), owners] = p_hit  # the owner always knows
    return P


def expected_info_gain(
    posterior: dict[str, float], owner_id: str, discrim: float
) -> float:
    """IG(q) = H(posterior) - sum_a P(a) * H(posterior | answer=a).

    Two-outcome: the answer either matches owner_id's memory or it doesn't.
    P(match | u) is `P_HIT` for the owner and scales with `1 - discrim` for
    everyone else, so this is the exact mutual information between the outcome
    and identity — no approximation, and it is what peaks when the owner sits
    near p=0.5. That is the question worth asking.
    """
    if not posterior:
        return 0.0
    d = float(np.clip(discrim, 0.0, 1.0))
    others = P_FLOOR + (P_HIT - P_FLOOR) * (1.0 - d)
    p_correct = {u: (P_HIT if u == owner_id else others) for u in posterior}
    return expected_info_gain_pc(posterior, p_correct)


def expected_info_gain_pc(
    posterior: dict[str, float], p_correct: dict[str, float]
) -> float:
    """Exact expected information gain, in bits, from per-candidate hit
    probabilities. Sharper than the scalar form because each rival candidate
    is scored on its own overlap rather than on the worst case."""
    if not posterior:
        return 0.0
    keys = list(posterior)
    p = np.fromiter((posterior[k] for k in keys), dtype=np.float64, count=len(keys))
    pc = np.clip(
        np.fromiter(
            (p_correct.get(k, P_FLOOR) for k in keys), dtype=np.float64, count=len(keys)
        ),
        0.0,
        1.0,
    )
    return float(_ig_rows(p[None, :], pc[None, :])[0])


def _row_entropy(P: np.ndarray) -> np.ndarray:
    """Entropy in bits of each row of a (n, c) distribution matrix."""
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(P > _EPS, P * np.log2(np.where(P > _EPS, P, 1.0)), 0.0)
    return -terms.sum(axis=1)


def _ig_rows(post: np.ndarray, PC: np.ndarray) -> np.ndarray:
    """Vectorised IG for n questions at once.

    `post` is (n, c) — normally one posterior broadcast to every row — and
    `PC` is (n, c) of hit probabilities. Returns (n,) bits.
    """
    h0 = _row_entropy(post)
    p_right = np.clip((post * PC).sum(axis=1), 0.0, 1.0)
    p_wrong = 1.0 - p_right

    denom_r = np.where(p_right > _EPS, p_right, 1.0)[:, None]
    denom_w = np.where(p_wrong > _EPS, p_wrong, 1.0)[:, None]
    post_right = (post * PC) / denom_r
    post_wrong = (post * (1.0 - PC)) / denom_w

    expected = p_right * _row_entropy(post_right) + p_wrong * _row_entropy(post_wrong)
    ig = h0 - expected
    # A foregone outcome carries no information; guard the degenerate rows.
    ig = np.where((p_right <= _EPS) | (p_wrong <= _EPS), 0.0, ig)
    return np.clip(ig, 0.0, None)


def info_gain_batch(posterior_vec: np.ndarray, PC: np.ndarray) -> np.ndarray:
    """IG in bits for every candidate memory at once. `PC` is the
    (n_memories, n_candidates) matrix from `hit_probability_matrix`."""
    if PC.size == 0:
        return np.zeros((0,), dtype=np.float32)
    post = np.broadcast_to(posterior_vec[None, :], PC.shape)
    return _ig_rows(post.astype(np.float64), PC.astype(np.float64)).astype(np.float32)


def _binary_entropy(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 0.0, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(q > _EPS, q * np.log2(np.where(q > _EPS, q, 1.0)), 0.0)
        b = np.where(1 - q > _EPS, (1 - q) * np.log2(np.where(1 - q > _EPS, 1 - q, 1.0)), 0.0)
    return -(a + b)


def info_gain_verify_batch(
    posterior_vec: np.ndarray, PC: np.ndarray, claimed_idx: int
) -> np.ndarray:
    """IG about the single bit "is the speaker the claimed user?".

    When someone *claims* an identity the task stops being identification and
    becomes verification, and the two want different questions. Identification
    IG chases whichever candidate currently leads — so the moment a clone's
    first wrong answer knocks the claimed user down, the engine wanders off to
    interrogate bystanders. It still rejects, but only by running out of
    budget, and the claimed user drifts back up as the other candidates fail
    questions that were never about them. On the projector that reads as the
    system nearly accepting the impostor.

    Targeting the claim keeps every question pointed at the one bit the demo
    is about, which is also the brief's stated clone path: the claimed
    identity's mass collapses.
    """
    if PC.size == 0:
        return np.zeros((0,), dtype=np.float32)
    post = posterior_vec.astype(np.float64)
    P = PC.astype(np.float64)

    p_claimed = float(post[claimed_idx])
    p_right = np.clip((post[None, :] * P).sum(axis=1), 0.0, 1.0)
    p_wrong = 1.0 - p_right

    joint_r = post[claimed_idx] * P[:, claimed_idx]
    joint_w = post[claimed_idx] * (1.0 - P[:, claimed_idx])
    given_r = joint_r / np.where(p_right > _EPS, p_right, 1.0)
    given_w = joint_w / np.where(p_wrong > _EPS, p_wrong, 1.0)

    expected = p_right * _binary_entropy(given_r) + p_wrong * _binary_entropy(given_w)
    gain = _binary_entropy(np.array(p_claimed)) - expected
    gain = np.where((p_right <= _EPS) | (p_wrong <= _EPS), 0.0, gain)
    return np.clip(gain, 0.0, None).astype(np.float32)


# --- grading ---------------------------------------------------------------


def grade_score(
    sim_owner: float,
    factual_ok: bool | None = None,
    sim_floor: float = SIM_FLOOR,
    sim_ceil: float = SIM_CEIL,
    w_sim: float = W_SIM,
) -> float:
    """(answer/memory cosine, LLM verdict) -> a score in [0, 1].

    Two graders because each covers the other's blind spot: the embedding
    catches "right topic, right texture", the LLM catches the names and
    numbers an embedding smears over. `factual_ok=None` means the LLM had no
    opinion and the score rests on similarity alone — a dead LLM call must
    never be read as a wrong answer.
    """
    span = max(sim_ceil - sim_floor, _EPS)
    sim_component = float(np.clip((sim_owner - sim_floor) / span, 0.0, 1.0))
    if factual_ok is None:
        return sim_component
    w = float(np.clip(w_sim, 0.0, 1.0))
    return float(np.clip(w * sim_component + (1.0 - w) * (1.0 if factual_ok else 0.0), 0.0, 1.0))


def answer_likelihood(score: float, p_correct: dict[str, float]) -> dict[str, float]:
    """P(this graded answer | speaker is u), as soft evidence.

    score=1 -> the likelihood *is* p_correct: a right answer is evidence for
    whoever was likely to get it right. score=0 -> its complement, which is
    what collapses a clone's claimed identity — the claimed user was the one
    person almost certain to know.
    """
    s = float(np.clip(score, 0.0, 1.0))
    return {
        u: s * float(np.clip(p, 0.0, 1.0)) + (1.0 - s) * (1.0 - float(np.clip(p, 0.0, 1.0)))
        for u, p in p_correct.items()
    }
