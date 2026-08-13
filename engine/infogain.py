"""Pure information-theory functions. Jabir — Task C. ⭐

No I/O — plain dicts and vectors, so every one is unit-testable on its own.
`tests/test_infogain.py` is the acceptance spec; it skips while these are stubs.
"""

from __future__ import annotations


def shannon(posterior: dict[str, float]) -> float:
    """Entropy in bits: -sum(p*log2 p) over p>0. Uniform n -> log2 n; point mass -> 0."""
    raise NotImplementedError("shannon — Jabir")


def softmax(scores: dict[str, float], temp: float = 0.15) -> dict[str, float]:
    """Temperature softmax over voice sims -> the prior. Subtract the max first."""
    raise NotImplementedError("softmax — Jabir")


def bayes_update(posterior: dict[str, float], likelihood: dict[str, float]) -> dict[str, float]:
    """prior * likelihood, renormalised. Don't mutate inputs; survive all-zero
    likelihoods by falling back to the prior (a clone answering gibberish must
    not divide by zero)."""
    raise NotImplementedError("bayes_update — Jabir")


def discriminability(memory_vec: list[float], other_vecs: list[list[float]]) -> float:
    """1 - max cosine against the nearest memory of any OTHER candidate, in [0,1].
    High means: only this person could answer it."""
    raise NotImplementedError("discriminability — Jabir")


def expected_info_gain(posterior: dict[str, float], owner_id: str, discrim: float) -> float:
    """IG(q) = H(posterior) - sum_a P(a) * H(posterior | answer=a).

    Two-outcome approximation: the answer either matches owner_id's memory or
    not, P(match) ~= posterior[owner_id], scaled by discriminability. Peaks when
    the owner sits near p=0.5 — that's the question worth asking.
    """
    raise NotImplementedError("expected_info_gain — Jabir")
