"""Draft parser tests."""

from tcv.agents.draft_parser import DEFAULT_SECTION, parse_draft

MD = """\
## Verification mechanisms
MARCH blinds the checker to the answer [[march-2026#p2c0]]. Du et al. rely on consensus instead. [[du-2023#p1c0]]

GSAR types claims four ways [[gsar-2026#p4c0]][[gsar-2026#p5c1]].

## Cost
- Tool-MAD caps the number of rounds [[tool-mad-2026#p3c2]].
- Three of the five frameworks bound their loop [[gsar-2026#p6c0, march-2026#p9c1]].
"""


def test_sections_sentences_and_citations():
    r = parse_draft(MD)
    d = r.draft
    assert d.sections == ("Verification mechanisms", "Cost")
    texts = [s.text for s in d.sentences]
    assert texts == [
        "MARCH blinds the checker to the answer.",
        "Du et al. rely on consensus instead.",
        "GSAR types claims four ways.",
        "Tool-MAD caps the number of rounds.",
        "Three of the five frameworks bound their loop.",
    ]
    assert [len(s.citations) for s in d.sentences] == [1, 1, 2, 1, 2]
    assert d.sentences[0].section == "Verification mechanisms" and d.sentences[4].section == "Cost"


def test_citation_after_full_stop_stays_with_its_sentence():
    d = parse_draft("Debate converges. [[du-2023#p2c0]] Blinding helps [[march-2026#p1c0]].").draft
    assert [c.chunk_id for c in d.sentences[0].citations] == ["du-2023#p2c0"]
    assert [c.chunk_id for c in d.sentences[1].citations] == ["march-2026#p1c0"]


def test_sentence_ids_are_sequential_and_round_scoped():
    d = parse_draft(MD, round_=2).draft
    assert [s.sentence_id for s in d.sentences] == [f"r2s{i:04d}" for i in range(5)]


def test_uncited_sentence_is_kept_with_no_citations():
    d = parse_draft("## Intro\nWe now turn to evaluation.").draft
    assert d.sentences[0].citations == ()


def test_malformed_and_unknown_citations_are_reported_not_repaired():
    r = parse_draft("A claim [[not a chunk id]]. Another [[du-2023#p9c9]]. Fine [[du-2023#p1c0]].",
                    known_chunks={"du-2023#p1c0"})
    assert r.malformed_citations == ["not a chunk id"]
    assert r.unknown_citations == ["du-2023#p9c9"]
    assert [len(s.citations) for s in r.draft.sentences] == [0, 0, 1]


def test_text_before_any_heading_goes_to_default_section():
    d = parse_draft("Opening line [[du-2023#p1c0]].\n## Body\nMore [[du-2023#p2c0]].").draft
    assert d.sections[0] == DEFAULT_SECTION and d.sentences[0].section == DEFAULT_SECTION
