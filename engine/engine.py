"""EntropyEngine — the centerpiece. Jabir — Task C. ⭐

    start()            prior over candidates from voice cosine sims
    next_question()    argmax expected information gain over unasked memories
    grade_and_update() grade -> likelihood -> Bayes -> entropy -> asked
    finalize()         the stop rules, in one place

Memories are re-read from the Store on every call and never cached across
calls. That costs a query and buys the Act 3 demo beat: wipe a user's
memory_events live and the very next question selection has nothing to ask
them, so the system genuinely cannot authenticate them any more.

Selection is fully vectorised (see `infogain`): one matmul scores every
candidate memory against every other candidate's memories, then one broadcast
computes information gain for all of them at once. At ~8 candidates x ~25
memories that is the difference between a visible stall and no stall at all.
"""

from __future__ import annotations

import os
import uuid

import numpy as np

from contracts.interfaces import Embedder, Llm, Store
from contracts.models import AskedQuestion, AuthSession, MemoryEvent, QuestionSpec

from engine import infogain as ig
from engine.questions import fallback_question, leaks_answer, pick_target_attr

MAX_MEM_PER_CANDIDATE = 30
"""Bound per-step work so selection stays snappy however rich the personas get."""

PRIOR_TEMP = float(os.getenv("PRIOR_TEMP", "0.15"))
"""Softmax temperature on voice sims. See infogain.softmax — this is the dial
that keeps the biometric a *narrowing* step rather than the authenticator.

Env-tunable because it is the one number worth adjusting between the dry run
and the stage: raise it if the voice prior alone is landing too close to
TAU_ID (the demo then identifies in one question and the entropy meter barely
moves), lower it if narrowing looks weak on the day's microphone."""


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
        min_questions: int = 3,
        prior_temp: float = PRIOR_TEMP,
        max_mem_per_candidate: int = MAX_MEM_PER_CANDIDATE,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.tau_id = tau_id
        self.tau_reject = tau_reject
        self.max_questions = max_questions
        self.min_questions = min_questions
        self.prior_temp = prior_temp
        self.max_mem_per_candidate = max_mem_per_candidate

    # -- Engine protocol ---------------------------------------------------

    def start(self, candidates: list[tuple[str, float]]) -> AuthSession:
        """Prior from voice sims. Voice narrows the field; it never decides."""
        sims = {uid: float(sim) for uid, sim in candidates}
        posterior = ig.softmax(sims, temp=self.prior_temp)
        return AuthSession(
            _id="s_" + uuid.uuid4().hex[:12],
            candidate_ids=sorted(posterior, key=posterior.__getitem__, reverse=True),
            posterior=posterior,
            entropy_bits=ig.shannon(posterior),
            status="in_progress" if posterior else "rejected",
        )

    def next_question(self, s: AuthSession) -> tuple[AuthSession, QuestionSpec | None]:
        """argmax expected IG over unasked memories. None when nothing is askable."""
        if self._graded(s) >= self.max_questions:
            return s, None

        mems = self._memories(s)

        # Always ask about ONE person: the claimed identity if there is one,
        # otherwise the current best match. Ranking purely on information gain
        # lets questions be drawn from a STRANGER'S life -- unanswerable by
        # definition, so a genuine speaker fails them and the session spirals.
        # The focus is recomputed every turn, so if the leader changes the
        # questions follow it.
        # Anyone the speaker has passed on is out of the running for FOCUS:
        # "I don't know" means we are asking the wrong person, so move to the
        # next most probable one rather than pressing the same wrong life.
        skipped = set(s.skipped or ())
        focus = None
        if s.claimed_id and s.claimed_id not in skipped and mems.get(s.claimed_id):
            focus = s.claimed_id
        else:
            for uid in sorted(s.posterior, key=s.posterior.__getitem__, reverse=True):
                if uid not in skipped and mems.get(uid):
                    focus = uid
                    break
        if focus is None:  # every candidate passed over -- nothing left to ask
            return s, None
        mems = {focus: mems[focus]}

        pool = self._askable(s, mems)
        if not pool:
            # Every candidate is out of unasked memories — this is what a wiped
            # user looks like. The API finalises on None.
            return s, None

        M = ig.as_matrix([m.embedding for m, _ in pool])
        owners = np.array([owner_col for _, owner_col in pool], dtype=np.int64)
        order = list(s.posterior)
        post_vec = np.array([s.posterior[u] for u in order], dtype=np.float64)

        PC = ig.hit_probability_matrix(M, owners, len(order))
        gains = ig.info_gain_batch(post_vec, PC)
        discrim = ig.discriminability_batch(M, owners)

        # With a claimed identity this is verification, not identification:
        # select on the bit "is this the claimed user?" so every question stays
        # pointed at the claim. Without one, plain identification IG.
        rank_by = gains
        if s.claimed_id is not None and s.claimed_id in s.posterior:
            rank_by = ig.info_gain_verify_batch(
                post_vec, PC, order.index(s.claimed_id)
            )

        # Tie-break — and the documented fallback ranking — is raw
        # discriminability weighted by belief in the owner, so a flat IG
        # surface still yields the sharpest question the leader owns.
        owner_belief = post_vec[owners]
        best = int(np.lexsort((discrim * owner_belief, np.round(rank_by, 9)))[-1])

        memory = pool[best][0]
        owner_id = order[owners[best]]
        target_attr = pick_target_attr(memory, mems, owner_id)
        return s, QuestionSpec(
            memory_id=memory.id,
            owner_id=owner_id,
            target_attr=target_attr,
            ig=float(gains[best]),
            question_text=self._phrase(memory, target_attr),
        )

    @staticmethod
    def _graded(s: AuthSession) -> int:
        """Turns that actually produced evidence.

        Skips must not consume the budget: passing on a stranger's question is
        how the speaker steers us to the right person, and charging them for it
        would run the session out before we ever asked them anything. The
        session still terminates -- next_question returns None once every
        candidate has been passed over.
        """
        return sum(1 for a in s.asked if not a.skipped)

    def skip(self, s: AuthSession, q: QuestionSpec) -> AuthSession:
        """The speaker said 'I don't know' -- retarget instead of penalising.

        A miss is evidence someone is not who they claim. A skip is evidence we
        are questioning the wrong PERSON, which is a different thing and must
        not collapse their probability: the speaker may simply never have been
        this candidate. Mark the candidate passed over so next_question moves
        to the next most probable one, and record the turn without a grade.
        """
        if q.owner_id and q.owner_id not in s.skipped:
            s.skipped.append(q.owner_id)
        s.asked.append(
            AskedQuestion(
                q=q.question_text,
                memory_id=q.memory_id,
                owner_id=q.owner_id,
                target_attr=q.target_attr,
                ig=q.ig,
                answer=None,
                graded=False,
                skipped=True,
                correct=None,
                entropy_after=s.entropy_bits,
            )
        )
        return self.finalize(s)

    def grade_and_update(
        self, s: AuthSession, q: QuestionSpec, answer: str
    ) -> AuthSession:
        """Grade -> likelihood -> bayes_update -> entropy -> append asked -> finalize."""
        mems = self._memories(s)
        target = self._find(mems, q)

        correct: bool | None = None
        if target is not None:
            sim = self._answer_similarity(answer, target)
            factual = self._factual_check(answer, target.text, q.question_text)
            score = ig.grade_score(sim, factual)
            correct = score >= 0.5

            p_correct = ig.hit_probabilities(
                list(s.posterior),
                q.owner_id,
                target.embedding,
                {uid: [m.embedding for m in ms] for uid, ms in mems.items()},
            )
            s.posterior = ig.bayes_update(s.posterior, ig.answer_likelihood(score, p_correct))
            s.entropy_bits = ig.shannon(s.posterior)
            s.candidate_ids = sorted(s.posterior, key=s.posterior.__getitem__, reverse=True)
        # else: the memory vanished mid-session (a live wipe, or a stale
        # session). Record the turn as ungraded rather than crashing the demo.

        s.asked.append(
            AskedQuestion(
                q=q.question_text,
                memory_id=q.memory_id,
                owner_id=q.owner_id,
                target_attr=q.target_attr,
                ig=q.ig,
                answer=answer,
                graded=target is not None,
                correct=correct,
                entropy_after=s.entropy_bits,
            )
        )
        s.pending = None
        return self.finalize(s)

    def finalize(self, s: AuthSession, force: bool = False) -> AuthSession:
        """Stop rules -> status. force=True ends the session outright."""
        top_id, top_p = s.leader
        if top_id is None:
            s.status = "rejected"
            return s

        # Concentration is not evidence. Answering nothing correctly still
        # shuffles mass between candidates, and with a small pool it can drift
        # past tau_id -- letting someone who knew none of the answers be
        # "identified" as whoever the misses happened to favour. Identification
        # requires at least one answer that actually graded correct.
        knows_something = any(a.correct for a in s.asked)

        if top_p > self.tau_id and knows_something:
            # Someone crossed the bar — but if a specific identity was claimed
            # and the evidence points elsewhere, that is a rejection, not an
            # identification of the bystander the clone happened to resemble.
            s.status = "identified" if (s.claimed_id in (None, top_id)) else "rejected"
            return s

        if (
            s.claimed_id is not None
            and s.posterior.get(s.claimed_id, 0.0) < self.tau_reject
            and self._graded(s) >= self.min_questions
        ):
            # The clone path -- but only after min_questions. One wrong answer
            # is a bad memory, not proof of an impostor; a clone stays wrong.
            s.status = "rejected"
            return s

        if force or self._graded(s) >= self.max_questions:
            s.status = "rejected"  # budget spent with no winner, or no evidence
            return s

        s.status = "in_progress"
        return s

    # -- internals ---------------------------------------------------------

    def _memories(self, s: AuthSession) -> dict[str, list[MemoryEvent]]:
        """Fresh read every call — the live wipe demo depends on it.

        Embeddings are backfilled if the store handed us any without one, so a
        half-seeded corpus degrades to slower rather than broken.
        """
        out: dict[str, list[MemoryEvent]] = {}
        for uid in s.posterior:
            try:
                found = list(self.store.memories(uid) or [])
            except Exception:
                found = []
            found.sort(key=lambda m: m.ts, reverse=True)  # recent = more discriminating
            found = found[: self.max_mem_per_candidate]
            for m in found:
                if not m.embedding:
                    m.embedding = self._embed(m.text)
            out[uid] = [m for m in found if m.embedding]
        return self._align_dims(out)

    @staticmethod
    def _align_dims(mems: dict[str, list[MemoryEvent]]) -> dict[str, list[MemoryEvent]]:
        """Drop odd-length embeddings so the matrix build can't explode.

        Mixed dimensions mean someone re-seeded with a different embedding
        model; the majority dimension is the live one.
        """
        dims: dict[int, int] = {}
        for ms in mems.values():
            for m in ms:
                dims[len(m.embedding)] = dims.get(len(m.embedding), 0) + 1
        if len(dims) <= 1:
            return mems
        keep = max(dims, key=dims.__getitem__)
        return {uid: [m for m in ms if len(m.embedding) == keep] for uid, ms in mems.items()}

    def _askable(
        self, s: AuthSession, mems: dict[str, list[MemoryEvent]]
    ) -> list[tuple[MemoryEvent, int]]:
        """(memory, owner column index) for every memory not already used."""
        used = {a.memory_id for a in s.asked}
        if s.pending is not None:
            used.add(s.pending.memory_id)
        order = list(s.posterior)
        return [
            (m, col)
            for col, uid in enumerate(order)
            for m in mems.get(uid, [])
            if m.id not in used
        ]

    @staticmethod
    def _find(mems: dict[str, list[MemoryEvent]], q: QuestionSpec) -> MemoryEvent | None:
        for m in mems.get(q.owner_id, []):
            if m.id == q.memory_id:
                return m
        return next(
            (m for ms in mems.values() for m in ms if m.id == q.memory_id), None
        )

    def _answer_similarity(self, answer: str, target: MemoryEvent) -> float:
        vec = self._embed(answer or "")
        if not vec or len(vec) != len(target.embedding):
            return 0.0
        return float(ig.cosine_matrix([vec], [target.embedding])[0, 0])

    def _embed(self, text: str) -> list[float]:
        try:
            return list(self.embedder.embed_text(text))
        except Exception:
            return []

    def _factual_check(
        self, answer: str, memory_text: str, question: str | None = None
    ) -> bool | None:
        if not (answer or "").strip():
            return False
        try:
            try:
                return bool(self.llm.factual_check(answer, memory_text, question))
            except TypeError:  # graders that predate the question argument
                return bool(self.llm.factual_check(answer, memory_text))
        except Exception:
            # No verdict available: fall back to similarity alone rather than
            # scoring a genuine user wrong because OpenRouter timed out.
            return None

    def _phrase(self, memory: MemoryEvent, target_attr: str | None) -> str:
        """Ask the LLM for a natural question — but never ship one that leaks."""
        try:
            text = (self.llm.phrase_question(memory.text) or "").strip()
        except Exception:
            text = ""
        if text:
            try:
                from engine.llm import is_yes_no
            except Exception:
                is_yes_no = lambda _q: False  # noqa: E731
            if is_yes_no(text):
                text = ""  # closed question -> unanswerable specifics -> false reject
        if not text or leaks_answer(text, memory.text):
            return fallback_question(memory, target_attr)
        return text
