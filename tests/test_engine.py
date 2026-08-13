"""Acceptance spec for engine/engine.py — the demo, as tests. Jabir — Task C.

The three claims we make on stage:
  1. a genuine speaker reaches `identified` in ~3 questions, entropy falling;
  2. a voice clone that passes the biometric is `rejected` by the knowledge gate;
  3. wiping a user's memories destroys the system's ability to authenticate them.
"""

from __future__ import annotations

import pytest

from engine import infogain
from engine.engine import EntropyEngine
from engine.questions import leaks_answer
from tests.doubles import (
    CLONE_ANSWERS,
    DeadLlm,
    FakeLlm,
    build_world,
    truthful_answer,
    voice_vector,
)

GENUINE = "u_ada"


@pytest.fixture
def world():
    store, embedder = build_world()
    return store, embedder, EntropyEngine(store, embedder, FakeLlm())


def run_session(engine, store, speaker_audio_vec, answer_fn, claimed_id=None, limit=6):
    """Drive a full session the way app/main.py does, returning the trace."""
    s = engine.start(store.narrow(speaker_audio_vec, 8))
    s.claimed_id = claimed_id
    entropies = [s.entropy_bits]
    for _ in range(limit):
        if s.status != "in_progress":
            break
        s, q = engine.next_question(s)
        if q is None:
            s = engine.finalize(s, force=True)
            break
        s.pending = q
        s = engine.grade_and_update(s, q, answer_fn(q))
        entropies.append(s.entropy_bits)
    return s, entropies


# -- the prior --------------------------------------------------------------


def test_start_builds_a_normalised_prior_that_does_not_decide(world):
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))

    assert sum(s.posterior.values()) == pytest.approx(1.0)
    assert s.candidate_ids[0] == GENUINE, "voice should still narrow correctly"
    assert s.entropy_bits > 1.0, "voice alone must leave real uncertainty"
    top = s.posterior[GENUINE]
    assert top < engine.tau_id, (
        f"voice prior alone hit {top:.2f} — the biometric would be authenticating, "
        "which is the exact failure this project exists to reject"
    )


# -- Act 1: the genuine run -------------------------------------------------


def test_genuine_speaker_is_identified_in_at_most_three_questions(world):
    store, _, engine = world
    s, _ = run_session(
        engine,
        store,
        voice_vector(GENUINE, jitter=0.35),
        lambda q: truthful_answer(store, q.memory_id, GENUINE),
        claimed_id=GENUINE,
    )
    assert s.status == "identified"
    assert s.leader[0] == GENUINE
    assert len(s.asked) <= 3, f"took {len(s.asked)} questions"


def test_entropy_is_non_increasing_across_correct_answers(world):
    store, _, engine = world
    _, entropies = run_session(
        engine,
        store,
        voice_vector(GENUINE, jitter=0.35),
        lambda q: truthful_answer(store, q.memory_id, GENUINE),
    )
    assert len(entropies) >= 2
    for before, after in zip(entropies, entropies[1:]):
        assert after <= before + 1e-9, f"entropy rose: {before:.4f} -> {after:.4f}"
    assert entropies[-1] < entropies[0] / 2


def test_the_engine_asks_the_leader_and_never_repeats_a_memory(world):
    store, _, engine = world
    s, _ = run_session(
        engine,
        store,
        voice_vector(GENUINE, jitter=0.35),
        lambda q: truthful_answer(store, q.memory_id, GENUINE),
    )
    asked_ids = [a.memory_id for a in s.asked]
    assert len(asked_ids) == len(set(asked_ids))
    assert s.asked[0].owner_id == GENUINE, "the first question should probe the leader"
    assert s.asked[0].ig > 0.0


def test_questions_never_leak_their_own_answer(world):
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    for _ in range(4):
        s, q = engine.next_question(s)
        if q is None:
            break
        memory = next(m for m in store.memories(q.owner_id) if m.id == q.memory_id)
        assert not leaks_answer(q.question_text, memory.text), q.question_text
        s.pending = q
        s = engine.grade_and_update(s, q, "no idea")
        if s.status != "in_progress":
            break


# -- Act 2: the clone -------------------------------------------------------


def test_clone_passes_the_biometric_but_is_rejected_by_the_knowledge_gate(world):
    store, _, engine = world
    # A good clone: the voice vector lands right on top of the target's.
    clone_vec = voice_vector(GENUINE, jitter=0.05)
    assert store.narrow(clone_vec, 8)[0][0] == GENUINE, "the biometric must pass"

    answers = iter(CLONE_ANSWERS)
    s, _ = run_session(
        engine, store, clone_vec, lambda q: next(answers), claimed_id=GENUINE
    )
    assert s.status == "rejected"
    assert s.posterior[GENUINE] < engine.tau_id


def test_clone_is_rejected_by_mass_collapse_not_by_running_out_of_budget(world):
    """The brief's clone path is `claimed_id`'s mass collapsing — not the
    budget expiring. Those look very different on the projector: one is the
    impostor being demolished, the other is a technicality after the engine
    spent four questions interrogating bystanders."""
    store, _, engine = world
    answers = iter(CLONE_ANSWERS)
    s, _ = run_session(
        engine,
        store,
        voice_vector(GENUINE, jitter=0.05),
        lambda q: next(answers),
        claimed_id=GENUINE,
    )
    assert s.status == "rejected"
    assert s.posterior[GENUINE] < engine.tau_reject, (
        f"claimed identity kept {s.posterior[GENUINE]:.2f} of the mass"
    )
    assert len(s.asked) < engine.max_questions, "should not need the full budget"
    assert all(a.owner_id == GENUINE for a in s.asked), (
        "with a claim on the table every question should probe the claim"
    )


def test_clone_answers_collapse_the_claimed_identity(world):
    store, _, engine = world
    clone_vec = voice_vector(GENUINE, jitter=0.05)
    s = engine.start(store.narrow(clone_vec, 8))
    s.claimed_id = GENUINE
    before = s.posterior[GENUINE]

    s, q = engine.next_question(s)
    s.pending = q
    s = engine.grade_and_update(s, q, CLONE_ANSWERS[0])
    assert s.posterior[GENUINE] < before, "a wrong answer must cost the claimed user mass"


def test_a_wrong_answer_on_someone_elses_memory_does_not_convict_them(world):
    """The clone answers a question drawn from Ben's memory. Ben is not the one
    being accused — his mass should not be the one that collapses."""
    store, embedder, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    ben_memory = store.memories("u_ben")[0]
    from contracts.models import QuestionSpec

    q = QuestionSpec(
        memory_id=ben_memory.id, owner_id="u_ben", ig=0.5, question_text="?"
    )
    s.pending = q
    before = dict(s.posterior)
    s = engine.grade_and_update(s, q, "I have absolutely no idea what that is.")
    assert s.posterior["u_ben"] < before["u_ben"]
    assert s.posterior[GENUINE] > before[GENUINE]


# -- Act 3: the wipe --------------------------------------------------------


def test_wiping_memory_leaves_the_engine_with_nothing_to_ask(world):
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    for uid in list(s.posterior):
        store.wipe_user_memory(uid)

    s, q = engine.next_question(s)
    assert q is None
    assert engine.finalize(s, force=True).status == "rejected"


def test_a_wipe_mid_session_is_survived_not_crashed(world):
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    s, q = engine.next_question(s)
    store.wipe_user_memory(q.owner_id)  # the memory disappears under us
    s.pending = q
    s = engine.grade_and_update(s, q, "something plausible")
    assert s.asked[-1].graded is False
    assert s.status in {"in_progress", "identified", "rejected"}


# -- degradation ------------------------------------------------------------


def test_a_dead_llm_degrades_to_templates_and_similarity_grading(world):
    store, embedder, _ = world
    engine = EntropyEngine(store, embedder, DeadLlm())
    s, entropies = run_session(
        engine,
        store,
        voice_vector(GENUINE, jitter=0.35),
        lambda q: truthful_answer(store, q.memory_id, GENUINE),
    )
    assert s.asked, "the engine must still ask questions with no LLM"
    assert all(a.q.strip() for a in s.asked)
    assert s.leader[0] == GENUINE
    assert entropies[-1] < entropies[0]


def test_finalize_force_ends_an_undecided_session_as_rejected(world):
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    assert engine.finalize(s, force=True).status == "rejected"


def test_max_questions_is_respected(world):
    store, embedder, _ = world
    engine = EntropyEngine(store, embedder, FakeLlm(), max_questions=2)
    answers = iter(CLONE_ANSWERS)
    s, _ = run_session(engine, store, voice_vector(GENUINE, jitter=0.05), lambda q: next(answers))
    assert len(s.asked) <= 2
    assert s.status == "rejected"


# -- selection quality ------------------------------------------------------


def test_selection_prefers_a_discriminating_memory_over_a_shared_one(world):
    """Ada and Ben share a near-identical standup memory. A selector that
    ignores discriminability would happily ask about it — and learn nothing."""
    store, _, engine = world
    s = engine.start(store.narrow(voice_vector(GENUINE, jitter=0.35), 8))
    _, q = engine.next_question(s)
    shared = next(m for m in store.memories(GENUINE) if "Standup" in m.text)
    assert q.memory_id != shared.id


def test_batch_info_gain_matches_the_scalar_contract_function():
    """The vectorised path and the documented scalar path must agree, or the
    unit tests on infogain stop saying anything about what actually runs."""
    import numpy as np

    posterior = {"a": 0.5, "b": 0.3, "c": 0.2}
    p = np.array([posterior[k] for k in posterior])
    for discrim in (1.0, 0.6, 0.2, 0.0):
        others = infogain.P_FLOOR + (infogain.P_HIT - infogain.P_FLOOR) * (1.0 - discrim)
        PC = np.array([[infogain.P_HIT, others, others]])
        batch = float(infogain.info_gain_batch(p, PC)[0])
        scalar = infogain.expected_info_gain(posterior, "a", discrim)
        assert batch == pytest.approx(scalar, abs=1e-6)


def test_discriminability_batch_matches_the_scalar_function():
    import numpy as np

    _, embedder = build_world()
    texts = ["red bicycle on valencia", "sharded the events table", "red bicycle on valencia street", "pottery class"]
    M = np.array([embedder.embed_text(t) for t in texts], dtype=np.float32)
    owners = np.array([0, 1, 2, 3])
    batch = infogain.discriminability_batch(M, owners)
    for i in range(len(texts)):
        others = [M[j].tolist() for j in range(len(texts)) if owners[j] != owners[i]]
        assert float(batch[i]) == pytest.approx(
            infogain.discriminability(M[i].tolist(), others), abs=1e-5
        )
