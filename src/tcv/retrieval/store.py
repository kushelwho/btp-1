"""Locating and loading the index for a corpus version."""

from __future__ import annotations

from pathlib import Path

from tcv.schemas import Chunk

from .embed import Embedder, SentenceTransformerEmbedder
from .index import HybridIndex
from .search import HybridSearcher


def index_dir(data_root: str | Path, corpus_version: str) -> Path:
    return Path(data_root) / "index" / corpus_version


def build_and_save(chunks: list[Chunk], embedder: Embedder, data_root: str | Path,
                   corpus_version: str) -> HybridIndex:
    index = HybridIndex.build(chunks, embedder, corpus_version)
    index.save(index_dir(data_root, corpus_version))
    return index


def load_searcher(chunks: list[Chunk], data_root: str | Path, corpus_version: str, embed_model: str,
                  device: str = "cpu", dense_weight: float = 0.6) -> HybridSearcher:
    embedder = SentenceTransformerEmbedder(embed_model, device=device)
    index = HybridIndex.load(index_dir(data_root, corpus_version), chunks, embed_model=embed_model)
    return HybridSearcher(index, embedder, dense_weight=dense_weight)
