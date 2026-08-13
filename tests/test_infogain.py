"""Acceptance spec for engine/infogain.py. Skips while the functions are stubs."""

import math

import pytest

from engine import infogain


def live(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotImplementedError:
        pytest.skip(f"{fn.__name__} not implemented yet")


def test_shannon_uniform_is_log2_n():
    p = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
    assert live(infogain.shannon, p) == pytest.approx(2.0)


def test_shannon_point_mass_is_zero():
    assert live(infogain.shannon, {"a": 1.0, "b": 0.0}) == pytest.approx(0.0)


def test_softmax_sums_to_one_and_ranks_by_score():
    out = live(infogain.softmax, {"a": 0.9, "b": 0.5, "c": 0.1})
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["a"] > out["b"] > out["c"]


def test_bayes_update_concentrates_on_high_likelihood():
    prior = {"a": 0.5, "b": 0.3, "c": 0.2}
    post = live(infogain.bayes_update, prior, {"a": 0.9, "b": 0.1, "c": 0.1})
    assert sum(post.values()) == pytest.approx(1.0)
    assert post["a"] > prior["a"]
    assert prior["a"] == 0.5  # inputs untouched


def test_bayes_update_survives_all_zero_likelihood():
    prior = {"a": 0.6, "b": 0.4}
    post = live(infogain.bayes_update, prior, {"a": 0.0, "b": 0.0})
    assert sum(post.values()) == pytest.approx(1.0)


def test_entropy_drops_on_a_correct_answer():
    """The demo's core claim: a right answer removes bits."""
    prior = {"a": 0.4, "b": 0.35, "c": 0.25}
    before = live(infogain.shannon, prior)
    after = live(infogain.shannon, live(infogain.bayes_update, prior, {"a": 0.95, "b": 0.05, "c": 0.05}))
    assert after < before


def test_discriminability_bounds():
    a = [1.0, 0.0, 0.0]
    assert live(infogain.discriminability, a, [[1.0, 0.0, 0.0]]) == pytest.approx(0.0, abs=1e-6)
    assert live(infogain.discriminability, a, [[0.0, 1.0, 0.0]]) == pytest.approx(1.0, abs=1e-6)


def test_info_gain_peaks_near_even_split():
    even = live(infogain.expected_info_gain, {"a": 0.5, "b": 0.5}, "a", 1.0)
    lopsided = live(infogain.expected_info_gain, {"a": 0.97, "b": 0.03}, "a", 1.0)
    assert even > lopsided
    assert even <= 1.0 + 1e-9  # can't gain more than the entropy present
    assert not math.isnan(even)
