"""Corpus: documents, chunks, and the frozen manifest."""

from datetime import datetime

from pydantic import model_validator

from ._base import Schema
from .ids import ChunkId, DocId, parse_chunk_id


class Document(Schema):
    doc_id: DocId
    title: str
    source: str  # "arxiv:2305.14325v1" | "doi:10.3390/app15073676" | "local"
    year: int | None = None
    filename: str
    sha256: str
    n_pages: int
    ingested_at: datetime


class Chunk(Schema):
    chunk_id: ChunkId
    doc_id: DocId
    page: int  # 1-indexed
    char_start: int  # offset into the normalised page text
    char_end: int
    text: str

    @model_validator(mode="after")
    def _consistent(self) -> "Chunk":
        doc, page, _ = parse_chunk_id(self.chunk_id)
        if doc != self.doc_id or page != self.page:
            raise ValueError(f"{self.chunk_id} does not match doc_id={self.doc_id} page={self.page}")
        if not 0 <= self.char_start < self.char_end:
            raise ValueError(f"bad span [{self.char_start}, {self.char_end})")
        if len(self.text) != self.char_end - self.char_start:
            raise ValueError("text length does not match char span")
        return self


class CorpusManifest(Schema):
    version: str  # bumping this invalidates every prior run
    frozen: bool
    documents: tuple[Document, ...]
    chunker: str  # config string that produced the chunks
    embed_model: str  # pinned local model name
    n_chunks: int

    @model_validator(mode="after")
    def _unique_docs(self) -> "CorpusManifest":
        ids = [d.doc_id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate doc_id in manifest")
        return self

    def doc(self, doc_id: str) -> Document:
        for d in self.documents:
            if d.doc_id == doc_id:
                return d
        raise KeyError(doc_id)
