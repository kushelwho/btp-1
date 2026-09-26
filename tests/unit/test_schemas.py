"""Schema contract tests.

These pin down the properties the rest of the system relies on: IDs are
well-formed and parseable, boundary objects are immutable and reject unknown
fields, everything survives a JSON round-trip (so runs are replayable), and
the retrieval pool can never lose its uncited passages.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from conftest import DOC, NOW, make_chunk, make_draft, make_passage, make_pool
from tcv.schemas import (
    AggregateSpec,
    Chunk,
    Claim,
    ClaimType,
    CorpusManifest,
    Document,
    Draft,
    ErrorClass,
    Escalation,
    EscalationKind,
    Modality,
    Operator,
    RepairHint,
    RetrievalPool,
    RevisionItem,
    RoundState,
    RunState,
    SeededError,
    Sentence,
    SubTask,
    Usage,
    Verdict,
    VerdictKind,
)
from tcv.schemas.ids import chunk_id, parse_chunk_id

# ---------------------------------------------------------------- identifiers

slugs = st.from_regex(r"[a-z0-9]{1,8}(-[a-z0-9]{1,8}){0,4}", fullmatch=True).filter(lambda s: 3 <= len(s) <= 64)


@given(doc=slugs, page=st.integers(1, 9999), idx=st.integers(0, 9999))
def test_chunk_id_round_trips(doc, page, idx):
    assert parse_chunk_id(chunk_id(doc, page, idx)) == (doc, page, idx)


@pytest.mark.parametrize(
    "bad",
    ["Du-2023#p1c0", "du_2023#p1c0", "du-2023#p0c0", "du-2023#c0", "du-2023-#p1c0", "du-2023#p1c"],
)
def test_malformed_chunk_ids_rejected(bad):
    with pytest.raises(ValueError):
        parse_chunk_id(bad)


def test_chunk_id_builder_rejects_page_zero():
    with pytest.raises(ValueError):
        chunk_id(DOC, 0, 0)


# ---------------------------------------------------------------- base behaviour


def test_boundary_objects_are_immutable():
    c = make_chunk()
    with pytest.raises(ValidationError):
        c.text = "changed"


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        SubTask(subtask_id="st01", heading="h", question="q", order=0, surprise=1)


# ---------------------------------------------------------------- corpus


def test_chunk_must_match_its_id():
    with pytest.raises(ValidationError):
        Chunk(chunk_id=chunk_id(DOC, 2, 0), doc_id=DOC, page=1, char_start=0, char_end=4, text="abcd")


def test_chunk_text_must_match_span():
    with pytest.raises(ValidationError):
        Chunk(chunk_id=chunk_id(DOC, 1, 0), doc_id=DOC, page=1, char_start=0, char_end=10, text="abc")


def test_manifest_rejects_duplicate_documents():
    doc = Document(doc_id=DOC, title="t", source="local", filename="f.pdf", sha256="0" * 64, n_pages=1, ingested_at=NOW)
    with pytest.raises(ValidationError):
        CorpusManifest(version="v1", frozen=False, documents=(doc, doc), chunker="c", embed_model="m", n_chunks=0)


# ---------------------------------------------------------------- retrieval pool


def test_pool_has_no_removal_method():
    """Uncited passages must survive — the sweep and misattribution checks read them."""
    forbidden = {"remove", "prune", "drop", "discard", "pop", "filter", "delete", "clear"}
    methods = {m for m in dir(RetrievalPool) if not m.startswith("_")}
    assert not (methods & forbidden), f"pool exposes a removal-like method: {methods & forbidden}"


def test_with_citations_flags_but_never_removes(pool):
    first = pool.entries[0].passage.chunk_id
    flagged = pool.with_citations({first: ["r1s0000"]})
    assert len(flagged.entries) == len(pool.entries)
    assert [p.chunk_id for p in flagged.cited()] == [first]
    assert first not in {p.chunk_id for p in flagged.uncited()}
    assert len(flagged.uncited()) == len(pool.entries) - 1
    # original unchanged
    assert pool.cited() == []


def test_with_citations_accumulates_citing_sentences(pool):
    cid = pool.entries[0].passage.chunk_id
    p = pool.with_citations({cid: ["r1s0000"]}).with_citations({cid: ["r1s0001", "r1s0000"]})
    assert p.entries[0].cited_by == ("r1s0000", "r1s0001")


def test_pool_rejects_duplicate_chunks():
    from tcv.schemas import PoolEntry

    e = PoolEntry(passage=make_passage(0))
    with pytest.raises(ValidationError):
        RetrievalPool(subtask_id="st01", entries=(e, e))


# ---------------------------------------------------------------- draft


def test_draft_rejects_duplicate_sentence_ids():
    s = Sentence(sentence_id="r1s0000", section="Intro", text="x")
    with pytest.raises(ValidationError):
        Draft(round=1, sections=("Intro",), sentences=(s, s))


def test_draft_rejects_unknown_section():
    s = Sentence(sentence_id="r1s0000", section="Nowhere", text="x")
    with pytest.raises(ValidationError):
        Draft(round=1, sections=("Intro",), sentences=(s,))


def test_draft_cited_chunks(draft):
    cited = draft.cited_chunks()
    assert len(cited) == 3
    assert all(len(v) == 1 for v in cited.values())


# ---------------------------------------------------------------- claims


def test_modality_ladder_is_ordered():
    ladder = [Modality.SUGGESTS, Modality.INDICATES, Modality.SHOWS, Modality.DEMONSTRATES, Modality.PROVES]
    assert [m.rank for m in ladder] == sorted(m.rank for m in ladder)
    assert Modality.NONE.rank == Modality.SHOWS.rank


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operator": Operator.COUNT},
        {"operator": Operator.PROPORTION},
        {"operator": Operator.COMPARISON, "direction": "sideways"},
        {"operator": Operator.TREND, "direction": "gt"},
        {"operator": Operator.CONTRAST},
    ],
)
def test_aggregate_spec_requires_operator_fields(kwargs):
    with pytest.raises(ValidationError):
        AggregateSpec(domain=("A", "B"), **kwargs)


def test_aggregate_only_allowed_on_t2():
    spec = AggregateSpec(operator=Operator.COUNT, domain=("A", "B"), claimed_count=1)
    with pytest.raises(ValidationError):
        Claim(claim_id="r1c0000", sentence_id="r1s0000", text="t", surface="t", ctype=ClaimType.T1_DIRECT, aggregate=spec)
    ok = Claim(claim_id="r1c0000", sentence_id="r1s0000", text="t", surface="t", ctype=ClaimType.T2_AGGREGATIVE, aggregate=spec)
    assert ok.aggregate.claimed_count == 1


# ---------------------------------------------------------------- verdicts


def test_repair_hint_allows_only_one_kind():
    with pytest.raises(ValidationError):
        RepairHint(swap_citation_to=chunk_id(DOC, 1, 0), downgrade_to=Modality.SUGGESTS)


def test_repair_hint_observed_and_claimed_travel_together():
    with pytest.raises(ValidationError):
        RepairHint(observed="2")
    assert RepairHint(observed="2", claimed="3").observed == "2"


def test_repair_hint_cannot_be_empty():
    with pytest.raises(ValidationError):
        RepairHint()


@pytest.mark.parametrize("kind", list(VerdictKind))
def test_is_failure_partition(kind):
    v = Verdict(claim_id="r1c0000", sentence_id="r1s0000", kind=kind, step="C.T1", rationale="r")
    passing = {VerdictKind.SUPPORTED, VerdictKind.EXEMPT, VerdictKind.INFERENCE_RETAINED}
    assert v.is_failure == (kind not in passing)


# ---------------------------------------------------------------- payload / eval arity


def test_revision_item_arity():
    base = dict(claim_text="c", ctype=ClaimType.T1_DIRECT, passages=(), instruction="fix")
    RevisionItem(sentence_ids=("r1s0000",), verdict=VerdictKind.UNSUPPORTED, **base)
    with pytest.raises(ValidationError):
        RevisionItem(sentence_ids=("r1s0000", "r1s0001"), verdict=VerdictKind.UNSUPPORTED, **base)
    with pytest.raises(ValidationError):
        RevisionItem(sentence_ids=("r1s0000",), verdict=VerdictKind.INTERNALLY_INCONSISTENT, **base)
    RevisionItem(sentence_ids=("r1s0000", "r1s0001"), verdict=VerdictKind.INTERNALLY_INCONSISTENT, **base)


def test_seeded_error_arity():
    base = dict(error_id="e1", original="a", corrupted="b", expected_verdicts=(VerdictKind.CONTRADICTED,))
    with pytest.raises(ValidationError):
        SeededError(error_class=ErrorClass.E9_INTERNAL, sentence_ids=("r1s0000",), **base)
    SeededError(error_class=ErrorClass.E9_INTERNAL, sentence_ids=("r1s0000", "r1s0001"), **base)
    with pytest.raises(ValidationError):
        SeededError(error_class=ErrorClass.E6_COUNT, sentence_ids=("r1s0000",), error_id="e", original="a",
                    corrupted="b", expected_verdicts=())


# ---------------------------------------------------------------- run state


def test_usage_adds():
    a = Usage(input_tokens=10, cost_usd=0.5, n_calls=1)
    b = Usage(input_tokens=5, cost_usd=0.25, n_calls=2)
    total = a + b
    assert (total.input_tokens, total.cost_usd, total.n_calls) == (15, 0.75, 3)


def test_escalation_render():
    assert "section 4" in Escalation(kind=EscalationKind.INCONSISTENT, section="section 4").render()
    assert Escalation(kind=EscalationKind.NO_SUPPORT).render().startswith("unverified")


def test_run_state_json_round_trip():
    """A run must be replayable from disk, so every nested type must round-trip exactly."""
    draft = make_draft()
    claim = Claim(
        claim_id="r1c0000", sentence_id="r1s0000", text="t", surface="may suggest t",
        modality=Modality.SUGGESTS, ctype=ClaimType.T2_AGGREGATIVE,
        aggregate=AggregateSpec(operator=Operator.COUNT, domain=("A", "B", "C"), claimed_count=2),
    )
    verdict = Verdict(
        claim_id="r1c0000", sentence_id="r1s0000", kind=VerdictKind.PARTIALLY_SUPPORTED,
        step="C.T2.compose", rationale="2 of 3 hold", hint=RepairHint(observed="1", claimed="2"),
    )
    run = RunState(
        run_id="run_0123456789ab", query_id="q01", condition="C", config_hash="h", corpus_version="v1",
        seed=0, subtasks=(SubTask(subtask_id="st01", heading="Intro", question="q", order=0),),
        pools=(make_pool().with_citations({chunk_id(DOC, 1, 0): ["r1s0000"]}),),
        rounds=(RoundState(round=1, draft=draft, claims=(claim,), verdicts=(verdict,)),),
        stop_reason="max_rounds", total_usage=Usage(n_calls=3),
    )
    again = RunState.model_validate_json(run.model_dump_json())
    assert again == run
