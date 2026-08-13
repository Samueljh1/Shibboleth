"""EntropyEngine — the centerpiece. Jabir — Task C. ⭐"""

from __future__ import annotations

from contracts.interfaces import Embedder, Llm, Store
from contracts.models import AuthSession, QuestionSpec


class EntropyEngine:
    """Implements contracts.interfaces.Engine."""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        llm: Llm,
        tau_id: float = 0.85,
        tau_reject: float = 0.05,
        max_questions: int = 5,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.tau_id = tau_id
        self.tau_reject = tau_reject
        self.max_questions = max_questions

    def start(self, candidates: list[tuple[str, float]]) -> AuthSession:
        """Prior from voice sims. Set _id, candidate_ids, posterior, entropy_bits."""
        raise NotImplementedError("engine/engine.py:start — Jabir")

    def next_question(self, s: AuthSession) -> tuple[AuthSession, QuestionSpec | None]:
        """argmax expected IG over unasked memories. None when nothing is askable."""
        raise NotImplementedError("engine/engine.py:next_question — Jabir")

    def grade_and_update(self, s: AuthSession, q: QuestionSpec, answer: str) -> AuthSession:
        """Grade -> likelihood -> bayes_update -> entropy -> append asked -> finalize."""
        raise NotImplementedError("engine/engine.py:grade_and_update — Jabir")

    def finalize(self, s: AuthSession, force: bool = False) -> AuthSession:
        """Stop rules -> status. force=True ends the session outright."""
        raise NotImplementedError("engine/engine.py:finalize — Jabir")
