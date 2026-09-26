"""Drafts: the Synthesizer's output, parsed into cited sentences."""

from pydantic import model_validator

from ._base import Schema
from .ids import ChunkId, SentenceId


class Citation(Schema):
    chunk_id: ChunkId


class Sentence(Schema):
    """One sentence of the report.

    An unrevised sentence keeps its original ``sentence_id`` in later rounds,
    so sentence identity is stable across the loop. Only a rewritten sentence
    gets a new ID, and ``supersedes`` links it to the one it replaced.
    """

    sentence_id: SentenceId
    section: str
    text: str
    citations: tuple[Citation, ...] = ()
    supersedes: SentenceId | None = None


class Draft(Schema):
    round: int
    sections: tuple[str, ...]  # ordered headings
    sentences: tuple[Sentence, ...]

    @model_validator(mode="after")
    def _consistent(self) -> "Draft":
        ids = [s.sentence_id for s in self.sentences]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate sentence_id in draft")
        known = set(self.sections)
        stray = {s.section for s in self.sentences} - known
        if stray:
            raise ValueError(f"sentences reference unknown sections: {sorted(stray)}")
        return self

    def by_id(self, sid: str) -> Sentence:
        for s in self.sentences:
            if s.sentence_id == sid:
                return s
        raise KeyError(sid)

    def cited_chunks(self) -> dict[str, list[str]]:
        """chunk_id → sentence_ids citing it."""
        out: dict[str, list[str]] = {}
        for s in self.sentences:
            for c in s.citations:
                out.setdefault(c.chunk_id, []).append(s.sentence_id)
        return out
