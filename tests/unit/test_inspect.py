"""Inspector page: escaped, coloured by worst verdict, planted errors tagged."""

from conftest import make_chunk, make_passage

from tcv.inspect.html import render
from tcv.schemas import (Citation, Claim, Draft, ErrorClass, SeededDraft, SeededError, Sentence, Verdict,
                         VerdictKind)

A1 = "alpha-2024#p1c0"


def test_page_colours_by_worst_verdict_escapes_text_and_tags_planted_errors():
    d = Draft(round=1, sections=("S",), sentences=(
        Sentence(sentence_id="r1s0000", section="S", text="Alpha <b>bounds</b> & loops.", citations=(Citation(chunk_id=A1),)),
        Sentence(sentence_id="r1s0001", section="S", text="Beta is fine.", citations=(Citation(chunk_id=A1),)),
    ))
    claims = [Claim(claim_id="r1c0000", sentence_id="r1s0000", text="a", surface="a", citations=(A1,)),
              Claim(claim_id="r1c0001", sentence_id="r1s0000", text="b", surface="b", citations=(A1,)),
              Claim(claim_id="r1c0002", sentence_id="r1s0001", text="c", surface="c", citations=(A1,))]
    verdicts = [Verdict(claim_id="r1c0000", sentence_id="r1s0000", kind=VerdictKind.SUPPORTED, step="C.T1", rationale="ok"),
                Verdict(claim_id="r1c0001", sentence_id="r1s0000", kind=VerdictKind.CONTRADICTED, step="C.T1",
                        rationale="says <the opposite>"),
                Verdict(claim_id="r1c0002", sentence_id="r1s0001", kind=VerdictKind.SUPPORTED, step="C.T1", rationale="ok")]
    planted = SeededDraft(base_draft_id="b", draft=d, generator_version="t", seed=0, errors=(SeededError(
        error_id="e0", error_class=ErrorClass.E4_CONTRADICTION, sentence_ids=("r1s0000",), original="Alpha bounds.",
        corrupted="Alpha <b>bounds</b> & loops.", expected_verdicts=(VerdictKind.CONTRADICTED,)),))
    page = render("T", d, claims, verdicts, {A1: make_passage(0).model_copy(update={"chunk": make_chunk("alpha-2024", 1, 0, "P")})},
                  planted=planted)
    assert '<span class="s bad" data-id="r1s0000">' in page  # worst of supported + contradicted
    assert '<span class="s ok" data-id="r1s0001">' in page
    assert "<b>bounds</b>" not in page and "Alpha &lt;b&gt;bounds&lt;/b&gt; &amp; loops." in page
    assert "says &lt;the opposite&gt;" in page and '<span class="tag">E4</span>' in page
