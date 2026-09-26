"""Retrieval: sub-tasks, passages, and the retrieval pool."""

from pydantic import model_validator

from ._base import Schema
from .corpus import Chunk
from .ids import ChunkId, SentenceId, SubTaskId


class SubTask(Schema):
    subtask_id: SubTaskId
    heading: str  # report section this feeds
    question: str
    order: int


class Passage(Schema):
    chunk: Chunk
    score: float  # retrieval score — for analysis only, never for decisions
    retrieved_by: str  # the query string that found it

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id


class PoolEntry(Schema):
    passage: Passage
    cited: bool = False  # a flag, never a filter
    cited_by: tuple[SentenceId, ...] = ()


class RetrievalPool(Schema):
    """Everything the Researcher found for one sub-task, cited or not.

    The disconfirming sweep reads the *uncited* entries, and misattribution
    detection reads *all* of them. There is deliberately no method that
    removes an entry: dropping uncited passages would make both mechanisms
    impossible, and would only surface much later as silently missing
    counterexamples.
    """

    subtask_id: SubTaskId
    entries: tuple[PoolEntry, ...]

    @model_validator(mode="after")
    def _unique_chunks(self) -> "RetrievalPool":
        ids = [e.passage.chunk_id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate chunk in pool {self.subtask_id}")
        return self

    def passages(self) -> list[Passage]:
        return [e.passage for e in self.entries]

    def uncited(self) -> list[Passage]:
        return [e.passage for e in self.entries if not e.cited]

    def cited(self) -> list[Passage]:
        return [e.passage for e in self.entries if e.cited]

    def get(self, chunk_id: ChunkId) -> Passage | None:
        for e in self.entries:
            if e.passage.chunk_id == chunk_id:
                return e.passage
        return None

    def with_citations(self, citations: dict[str, list[str]]) -> "RetrievalPool":
        """Return a new pool with citation flags set.

        ``citations`` maps chunk_id → sentence_ids citing it. Chunks not in the
        mapping keep their current flags. Entries are never removed.
        """
        new = []
        for e in self.entries:
            by = citations.get(e.passage.chunk_id)
            if by:
                merged = tuple(dict.fromkeys((*e.cited_by, *by)))
                new.append(PoolEntry(passage=e.passage, cited=True, cited_by=merged))
            else:
                new.append(e)
        return RetrievalPool(subtask_id=self.subtask_id, entries=tuple(new))
