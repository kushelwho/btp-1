"""Planted-error generators: each must fire where it should and stay quiet where it shouldn't."""

import random
import re

import pytest
from conftest import make_chunk, make_passage

from tcv.checker.lexicon import modality
from tcv.eval import seed as S
from tcv.eval.base import BaseDraft, verify
from tcv.schemas import Citation, Draft, ErrorClass, PoolEntry, RetrievalPool, Sentence

A1, B1, C1 = "alpha-2024#p1c0", "beta-2025#p1c0", "gamma-2026#p1c0"
PASSAGES = {
    A1: make_passage(0).model_copy(update={"chunk": make_chunk("alpha-2024", 1, 0, "Alpha bounds its loop at three rounds.")}),
    B1: make_passage(0).model_copy(update={"chunk": make_chunk("beta-2025", 1, 0, "Beta trains its checker with RL.")}),
    C1: make_passage(0).model_copy(update={"chunk": make_chunk("gamma-2026", 1, 0, "Gamma reports 81.8% accuracy.")}),
}


def sent(text, sid="r1s0000", cites=(A1,), section="S"):
    return Sentence(sentence_id=sid, section=section, text=text, citations=tuple(Citation(chunk_id=c) for c in cites))


def ctx(sentences=None, seed=0, e9=None):
    sentences = sentences or [sent("placeholder.")]
    d = Draft(round=1, sections=tuple(dict.fromkeys(s.section for s in sentences)), sentences=tuple(sentences))
    return S.Context(draft=d, passages=dict(PASSAGES), rng=random.Random(seed), entities=[], e9_pairs=e9 or [])


# ---------------------------------------------------------------- E1 numbers


def test_numeric_changes_a_figure_but_not_names_or_references():
    c = S.gen_numeric(sent("GAMMA reaches 81.8% accuracy with GPT-4 in Table 2."), ctx())
    assert c is not None and "GPT-4" in c.text and "Table 2" in c.text and "81.8%" not in c.text
    assert S.gen_numeric(sent("GPT-4 and Llama-3 are used, see Section 3."), ctx()) is None


def test_numeric_moves_years_by_a_little():
    c = S.gen_numeric(sent("MARCH was published in 2026."), ctx())
    assert c is not None and re.search(r"20(24|25|27|28)", c.text)


# ---------------------------------------------------------------- E2 attribution


def test_attribution_cites_a_different_paper_and_keeps_the_text():
    c = S.gen_attribution(sent("Alpha bounds its loop.", cites=(A1,)), ctx())
    assert c.text is None and len(c.citations) == 1 and not c.citations[0].startswith("alpha-2024")
    assert S.gen_attribution(sent("Uncited.", cites=()), ctx()) is None


# ---------------------------------------------------------------- E3 insertion


def test_insertion_fabricates_a_sentence_about_a_named_system_citing_a_real_passage():
    c = S.gen_insertion(sent("GSAR bounds its recovery loop."), ctx())
    assert c.insert is not None and "GSAR" in c.insert.text
    assert c.insert.sentence_id == "r1s9000" and c.insert.citations[0].chunk_id == A1
    assert S.gen_insertion(sent("the loop is bounded."), ctx()) is None  # no named system to attach it to


# ---------------------------------------------------------------- E4 contradiction


@pytest.mark.parametrize("text, expected", [
    ("MARCH does not share the draft with the checker.", "MARCH does share the draft with the checker."),
    ("Debate improves factual accuracy.", "Debate degrades factual accuracy."),
    ("The checker is blinded to the answer.", "The checker is not blinded to the answer."),
    ("GSAR uses a typed partition.", "GSAR does not use a typed partition."),
])
def test_contradiction_rules(text, expected):
    assert S.gen_contradiction(sent(text), ctx()).text == expected


# ---------------------------------------------------------------- E5 over-generalisation


@pytest.mark.parametrize("text, expected", [
    ("Several frameworks bound their loop.", "All frameworks bound their loop."),
    ("Debate often improves accuracy.", "Debate always improves accuracy."),
    ("Tool-MAD outperforms MADKE on FEVER.", "Tool-MAD consistently outperforms MADKE on FEVER."),
])
def test_overgeneralization_rules(text, expected):
    assert S.gen_overgeneralize(sent(text), ctx()).text == expected


def test_overgeneralization_skips_claims_that_are_already_universal():
    assert S.gen_overgeneralize(sent("All frameworks always bound their loop."), ctx()) is None


# ---------------------------------------------------------------- E6 miscount


def test_count_moves_k_of_n_by_one_within_range():
    c = S.gen_count(sent("Three of the five surveyed frameworks bound their loop."), ctx())
    assert c.text in {"Two of the five surveyed frameworks bound their loop.",
                      "Four of the five surveyed frameworks bound their loop."}


def test_count_changes_a_count_of_kinds_but_not_of_parts():
    c = S.gen_count(sent("These systems follow three primary architectural designs."), ctx())
    assert c is not None and "three" not in c.text and ("two" in c.text or "four" in c.text)
    assert S.gen_count(sent("MARCH uses three agents."), ctx()) is None  # parts of one system: that's E1 territory


# ---------------------------------------------------------------- E7 false contrast


def test_false_contrast_turns_a_stated_similarity_into_a_contrast():
    prev = sent("ClaimVerAgents deploys specialist agents.", sid="r1s0000")
    s = sent("GSAR similarly deploys specialist agents.", sid="r1s0001")
    c = S.gen_false_contrast(s, ctx([prev, s]))
    assert c.text == "Unlike ClaimVerAgents, GSAR deploys specialist agents."


def test_false_contrast_from_both_with_verb_agreement():
    c = S.gen_false_contrast(sent("Both GSAR and MARCH rely on a checker."), ctx())
    assert c.text == "Unlike MARCH, GSAR relies on a checker."


def test_false_contrast_needs_a_stated_similarity_and_named_systems():
    assert S.gen_false_contrast(sent("GSAR deploys specialist agents."), ctx()) is None
    assert S.gen_false_contrast(sent("Both frameworks and methods rely on checks."), ctx()) is None


# ---------------------------------------------------------------- E8 trend


def test_trend_reverses_direction_only_within_a_temporal_frame():
    c = S.gen_trend(sent("Since 2023, frameworks have increasingly relied on retrieval."), ctx())
    assert c.text == "Since 2023, frameworks have decreasingly relied on retrieval."
    assert S.gen_trend(sent("Retrieval increases accuracy."), ctx()) is None  # no time frame → not a trend


def test_trend_invents_a_direction_for_recent_work():
    c = S.gen_trend(sent("Recent multi-agent frameworks rely on retrieval."), ctx())
    assert c.text == "Recent multi-agent frameworks increasingly rely on retrieval."


# ---------------------------------------------------------------- E10 strengthened wording


@pytest.mark.parametrize("text", [
    "These results suggest that retrieval is the bottleneck.",
    "Debate may improve factuality.",
    "Du et al. report that debate improves accuracy.",
])
def test_hedge_strip_raises_strength_by_at_least_two_steps(text):
    c = S.gen_hedge_strip(sent(text), ctx())
    assert c is not None and modality(c.text).rank >= modality(text).rank + 2


def test_hedge_strip_skips_sentences_already_near_the_top():
    assert S.gen_hedge_strip(sent("This demonstrates the effect."), ctx()) is None


# ---------------------------------------------------------------- inject


def _base(n=12):
    texts = [
        "Three of the five surveyed frameworks bound their loop.", "Debate often improves accuracy.",
        "GSAR uses a typed partition.", "ClaimVerAgents deploys specialist agents.",
        "GSAR similarly deploys specialist agents.", "Gamma reaches 81.8% accuracy.",
        "These results suggest that retrieval is the bottleneck.",
        "Since 2023, frameworks have increasingly relied on retrieval.", "MARCH trains with PPO.",
        "The checker is blinded to the answer.", "Tool-MAD outperforms MADKE on HotpotQA.",
        "Beta trains its checker with RL.",
    ][:n]
    sents = tuple(sent(t, sid=f"r1s{i:04d}", cites=([A1, B1, C1][i % 3],)) for i, t in enumerate(texts))
    pool = RetrievalPool(subtask_id="st01", entries=tuple(PoolEntry(passage=p) for p in PASSAGES.values()))
    return BaseDraft(base_id="q99-test", query_id="q99", query="q", source="test",
                     draft=Draft(round=1, sections=("S",), sentences=sents), pools=(pool,))


def test_inject_is_reproducible_and_respects_one_error_per_sentence():
    a, b = S.inject(_base(), seed=1), S.inject(_base(), seed=1)
    assert a.seeded == b.seeded
    named = [sid for e in a.seeded.errors for sid in e.sentence_ids]
    assert len(named) == len(set(named))
    assert len(a.seeded.errors) <= 8
    assert S.inject(_base(), seed=2).seeded != a.seeded


def test_inject_records_ground_truth_that_matches_the_draft():
    rep = S.inject(_base(), seed=0, max_errors=9)
    d = rep.seeded.draft
    assert len({s.sentence_id for s in d.sentences}) == len(d.sentences)
    for e in rep.seeded.errors:
        assert e.expected_verdicts == S.EXPECTED[e.error_class]
        for sid in e.sentence_ids:
            s = d.by_id(sid)
            assert S._render(s) == e.corrupted or e.error_class is ErrorClass.E9_INTERNAL
    untouched = {sid for e in rep.seeded.errors for sid in e.sentence_ids}
    base = {s.sentence_id: s for s in _base().draft.sentences}
    for s in d.sentences:
        if s.sentence_id not in untouched and s.sentence_id in base:
            assert s == base[s.sentence_id], "a sentence without a planted error must be unchanged"


def test_inject_reports_classes_the_draft_cannot_take():
    rep = S.inject(_base(n=2), seed=0, classes=[ErrorClass.E8_TREND, ErrorClass.E6_COUNT])
    assert ErrorClass.E8_TREND in rep.not_applicable


def test_e9_pairs_from_file_insert_a_contradicting_sentence_far_away():
    pairs = {"q99-test": [{"target": "r1s0002", "contradicting": "GSAR does not use a typed partition.",
                           "cite": A1, "after": "r1s0010"}]}
    rep = S.inject(_base(), seed=0, classes=[ErrorClass.E9_INTERNAL], e9_pairs=pairs)
    (e,) = rep.seeded.errors
    assert e.error_class is ErrorClass.E9_INTERNAL and e.sentence_ids[0] == "r1s0002"
    ids = [s.sentence_id for s in rep.seeded.draft.sentences]
    assert ids.index(e.sentence_ids[1]) == ids.index("r1s0010") + 1


def test_verify_drops_sentences_and_marks_clean():
    b = verify(_base(), by="KR", drop=["r1s0001"])
    assert b.verified and b.verified_by == "KR" and "r1s0001" not in {s.sentence_id for s in b.draft.sentences}
    with pytest.raises(ValueError):
        verify(_base(), by="KR", drop=["r1s9999"])



# ---------------------------------------------------------------- rules widened after previewing real drafts


def test_numeric_skips_zero_and_rating_scales_and_prefers_results():
    assert S.gen_numeric(sent("Agents assign confidence scores (0–100) to snippets."), ctx()) is None
    c = S.gen_numeric(sent("Scores of 0.82 for real news, on a 1–5 scale, over 2 rounds."), ctx())
    assert "0.82" not in c.text and "1–5" in c.text and "2 rounds" in c.text


def test_false_contrast_from_an_example_of_the_group():
    c = S.gen_false_contrast(sent("Dynamic debate frameworks like Tool-MAD integrate external retrieval."), ctx())
    assert c.text == "Unlike Tool-MAD, dynamic debate frameworks integrate external retrieval."


def test_trend_invented_for_recent_literature():
    c = S.gen_trend(sent("Recent literature identifies several paradigms."), ctx())
    assert c.text == "Recent literature increasingly identifies several paradigms."


def test_hedge_strip_adds_an_overclaiming_lead_in_to_a_plain_result():
    c = S.gen_hedge_strip(sent("Tool-MAD achieves a 5.5% accuracy improvement."), ctx())
    assert c.text == "It is conclusively established that Tool-MAD achieves a 5.5% accuracy improvement."
    assert modality(c.text).rank - modality("Tool-MAD achieves a 5.5% accuracy improvement.").rank >= 2
    assert S.gen_hedge_strip(sent("The report has four sections."), ctx()) is None  # not a result


def test_numeric_leaves_math_and_unit_intervals_alone():
    assert S.gen_numeric(sent("GSAR computes a score $S \\in [0, 1]$ from a partition."), ctx()) is None
    assert S.gen_numeric(sent("Scores lie in [0, 1] for every claim."), ctx()) is None
