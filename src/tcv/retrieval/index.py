"""Hybrid index: exact dense cosine + BM25 over the corpus chunks.

The corpus is small (tens of papers, thousands of chunks), so dense search is
an exact matrix product rather than an approximate index — deterministic, and
fast enough.

    data/index/<corpus_version>/
        dense.npy       (n_chunks, dim) float32, L2-normalised
        chunk_ids.json  row order
        meta.json       IndexMeta
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict
from rank_bm25 import BM25Okapi

from tcv.schemas import Chunk

from .embed import Embedder

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "which with we our their they these those than then there such can may also not but into".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class IndexStaleError(RuntimeError):
    """The saved index does not match the corpus it is being loaded against."""


class IndexMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_version: str
    embed_model: str
    dim: int
    n_chunks: int
    chunk_ids_sha256: str


def _ids_hash(chunks: list[Chunk]) -> str:
    return hashlib.sha256("\n".join(c.chunk_id for c in chunks).encode()).hexdigest()


@dataclass
class HybridIndex:
    chunks: list[Chunk]
    dense: np.ndarray
    bm25: BM25Okapi
    meta: IndexMeta

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder, corpus_version: str) -> "HybridIndex":
        if not chunks:
            raise ValueError("cannot build an index over zero chunks")
        dense = embedder.embed_documents([c.text for c in chunks])
        meta = IndexMeta(corpus_version=corpus_version, embed_model=embedder.name, dim=int(dense.shape[1]),
                         n_chunks=len(chunks), chunk_ids_sha256=_ids_hash(chunks))
        return cls(chunks=chunks, dense=dense, bm25=BM25Okapi([tokenize(c.text) for c in chunks]), meta=meta)

    def save(self, directory: str | Path) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        np.save(d / "dense.npy", self.dense)
        (d / "chunk_ids.json").write_text(json.dumps([c.chunk_id for c in self.chunks]), encoding="utf-8")
        (d / "meta.json").write_text(self.meta.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path, chunks: list[Chunk], embed_model: str | None = None) -> "HybridIndex":
        """Load a saved index, verifying it was built from exactly these chunks."""
        d = Path(directory)
        meta = IndexMeta.model_validate_json((d / "meta.json").read_text(encoding="utf-8"))
        if meta.chunk_ids_sha256 != _ids_hash(chunks):
            raise IndexStaleError(f"index at {d} was built from a different set of chunks; rebuild it")
        if embed_model is not None and meta.embed_model != embed_model:
            raise IndexStaleError(f"index built with {meta.embed_model}, expected {embed_model}")
        dense = np.load(d / "dense.npy")
        if dense.shape != (meta.n_chunks, meta.dim):
            raise IndexStaleError(f"dense matrix shape {dense.shape} does not match meta")
        return cls(chunks=chunks, dense=dense, bm25=BM25Okapi([tokenize(c.text) for c in chunks]), meta=meta)
