"""Shared builders for tests. Small, valid objects with overridable fields."""

from datetime import datetime, timezone

import pytest

from tcv.schemas import (
    Chunk,
    Citation,
    Draft,
    Passage,
    PoolEntry,
    RetrievalPool,
    Sentence,
)
from tcv.schemas.ids import chunk_id

DOC = "du-2023-multiagent-debate"
NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def make_chunk(doc: str = DOC, page: int = 1, idx: int = 0, text: str = "Debate improves factuality.") -> Chunk:
    return Chunk(
        chunk_id=chunk_id(doc, page, idx),
        doc_id=doc,
        page=page,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def make_passage(idx: int = 0, text: str | None = None, page: int = 1, doc: str = DOC) -> Passage:
    return Passage(
        chunk=make_chunk(doc=doc, page=page, idx=idx, text=text or f"passage number {idx}"),
        score=1.0 / (idx + 1),
        retrieved_by="test query",
    )


def make_pool(n: int = 3, subtask: str = "st01") -> RetrievalPool:
    return RetrievalPool(
        subtask_id=subtask,
        entries=tuple(PoolEntry(passage=make_passage(i)) for i in range(n)),
    )


def make_draft(n: int = 3, round_: int = 1) -> Draft:
    sents = tuple(
        Sentence(
            sentence_id=f"r{round_}s{i:04d}",
            section="Introduction",
            text=f"Sentence {i}.",
            citations=(Citation(chunk_id=chunk_id(DOC, 1, i)),),
        )
        for i in range(n)
    )
    return Draft(round=round_, sections=("Introduction",), sentences=sents)


@pytest.fixture
def pool() -> RetrievalPool:
    return make_pool()


@pytest.fixture
def draft() -> Draft:
    return make_draft()
