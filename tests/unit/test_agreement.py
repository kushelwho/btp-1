"""Cohen's κ on cases with known answers."""

import pytest

from tcv.eval.agreement import cohen_kappa


def test_perfect_agreement_is_one_and_chance_level_is_zero():
    assert cohen_kappa(list("AABB"), list("AABB")).kappa == pytest.approx(1.0)
    # a says A,A,B,B; b says A,B,A,B → observed 0.5, expected 0.5 → κ 0
    assert cohen_kappa(list("AABB"), list("ABAB")).kappa == pytest.approx(0.0)


def test_textbook_example():
    # 50 items: both yes 20, both no 15, a-yes/b-no 5, a-no/b-yes 10 → po 0.70, pe 0.50 → κ 0.40
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    agr = cohen_kappa(a, b)
    assert agr.observed == pytest.approx(0.70) and agr.kappa == pytest.approx(0.40)
    assert agr.table == {"y": {"y": 20, "n": 5}, "n": {"y": 10, "n": 15}}


def test_single_label_everywhere_has_undefined_kappa():
    assert cohen_kappa(["T1"] * 5, ["T1"] * 5).kappa is None
