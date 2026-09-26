"""Metrics on hand-built cases where every number is known in advance."""

import pytest

from tcv.eval.metrics import aggregate, render_markdown, score_clean, score_planted
from tcv.schemas import Claim, ClaimType, Draft, ErrorClass, SeededDraft, SeededError, Sentence, Verdict, VerdictKind

K = VerdictKind


def v(sid, kind, cid=None):
    return Verdict(claim_id=cid or f"r1c{int(sid[-4:]):04d}", sentence_id=sid, kind=kind, step="C.T1", rationale="x")


def err(i, cls, sids, expected):
    return SeededError(error_id=f"e{i}", error_class=cls, sentence_ids=tuple(sids), original="a", corrupted="b",
                       expected_verdicts=tuple(expected))


def seeded(errors, seed=0):
    d = Draft(round=1, sections=("S",), sentences=(Sentence(sentence_id="r1s0000", section="S", text="x"),))
    return SeededDraft(base_draft_id="b1", draft=d, errors=tuple(errors), generator_version="t", seed=seed)


def test_catch_needs_an_expected_verdict_while_flag_takes_any_failure():
    sd = seeded([err(0, ErrorClass.E10_HEDGE_STRIP, ["r1s0001"], [K.OVERCLAIM]),
                 err(1, ErrorClass.E1_NUMERIC, ["r1s0002"], [K.CONTRADICTED, K.UNSUPPORTED])])
    s = score_planted("A", sd, [v("r1s0001", K.UNSUPPORTED), v("r1s0002", K.CONTRADICTED)])
    by = {o.error_class: o for o in s.outcomes}
    assert (by["E10"].caught, by["E10"].flagged) == (False, True)  # the baseline flagged it, but not as an overclaim
    assert (by["E1"].caught, by["E1"].flagged) == (True, True)


def test_failed_checks_and_missing_verdicts_are_unscored_and_abstentions_are_not_catches():
    sd = seeded([err(0, ErrorClass.E1_NUMERIC, ["r1s0001"], [K.CONTRADICTED]),
                 err(1, ErrorClass.E3_INSERTION, ["r1s9000"], [K.UNSUPPORTED]),
                 err(2, ErrorClass.E4_CONTRADICTION, ["r1s0003"], [K.CONTRADICTED])])
    s = score_planted("A", sd, [v("r1s0001", K.ERROR), v("r1s0003", K.UNCERTAIN)])
    by = {o.error_class: o for o in s.outcomes}
    assert by["E1"].unscored and by["E3"].unscored  # check failed / no claim at all
    assert by["E4"].abstained and not by["E4"].caught and not by["E4"].flagged


def test_e9_counts_a_catch_on_either_named_sentence():
    sd = seeded([err(0, ErrorClass.E9_INTERNAL, ["r1s0001", "r1s9000"], [K.INTERNALLY_INCONSISTENT])])
    s = score_planted("E", sd, [v("r1s0001", K.SUPPORTED), v("r1s9000", K.INTERNALLY_INCONSISTENT, "r1c9000")])
    assert s.outcomes[0].caught


def test_fpr_by_type_excludes_abstentions_and_failed_checks():
    claims = [Claim(claim_id=f"r1c{i:04d}", sentence_id=f"r1s{i:04d}", text="t", surface="t", ctype=ClaimType.T1_DIRECT)
              for i in range(5)]
    verdicts = [v("r1s0000", K.SUPPORTED), v("r1s0001", K.UNSUPPORTED), v("r1s0002", K.UNCERTAIN),
                v("r1s0003", K.ERROR), v("r1s0004", K.SUPPORTED)]
    s = score_clean("A", "b1", claims, verdicts, type_of={"r1c0004": ClaimType.T4_DISCOURSE})
    assert s.claims_by_type == {"T1": 3, "T4": 1}  # the ERROR claim is left out
    assert s.failing_by_type == {"T1": 1} and s.abstained_by_type == {"T1": 1}


def test_aggregate_pools_per_class_never_across_classes_with_bootstrap_bounds():
    passes = []
    for seed, (c1, c5) in enumerate([(True, False), (True, False), (False, False), (True, True)]):
        sd = seeded([err(0, ErrorClass.E1_NUMERIC, ["r1s0001"], [K.CONTRADICTED]),
                     err(1, ErrorClass.E5_OVERGENERALIZE, ["r1s0002"], [K.COUNTEREXAMPLE_FOUND])], seed=seed)
        passes.append(score_planted("A", sd, [v("r1s0001", K.CONTRADICTED if c1 else K.SUPPORTED),
                                              v("r1s0002", K.COUNTEREXAMPLE_FOUND if c5 else K.SUPPORTED)],
                                    cost_usd=0.01, n_calls=1))
    rep = aggregate(passes, n_boot=500)["A"]
    assert rep.catch["E1"].rate == pytest.approx(0.75) and rep.catch["E5"].rate == pytest.approx(0.25)
    assert rep.catch["E1"].ci_low <= 0.75 <= rep.catch["E1"].ci_high
    assert rep.cost_usd == pytest.approx(0.04) and rep.n_planted_passes == 4
    md = render_markdown({"A": rep})
    assert "| E1 | 0.75" in md and "| E5 | 0.25" in md


def test_bootstrap_is_reproducible():
    sd = seeded([err(0, ErrorClass.E1_NUMERIC, ["r1s0001"], [K.CONTRADICTED])])
    passes = [score_planted("A", sd.model_copy(update={"seed": i}), [v("r1s0001", K.CONTRADICTED if i % 2 else K.SUPPORTED)])
              for i in range(6)]
    assert aggregate(passes, seed=3)["A"].catch == aggregate(passes, seed=3)["A"].catch
