"""Hybrid search: dense and BM25 rankings fused by weighted reciprocal rank.

Rank fusion rather than score addition, because cosine similarities and BM25
scores live on unrelated scales and would need per-query calibration to add.
Ties break on chunk_id, so identical queries always return identical lists.
"""

from __future__ import annotations

import numpy as np

from tcv.schemas import Passage

from .embed import Embedder
from .index import HybridIndex, tokenize


class HybridSearcher:
    def __init__(self, index: HybridIndex, embedder: Embedder, dense_weight: float = 0.6,
                 rrf_k: int = 60, candidates: int = 100):
        if not 0.0 <= dense_weight <= 1.0:
            raise ValueError("dense_weight must be in [0, 1]")
        if embedder.name != index.meta.embed_model:
            raise ValueError(f"query embedder {embedder.name} != index embedder {index.meta.embed_model}")
        self.index = index
        self.embedder = embedder
        self.w = dense_weight
        self.rrf_k = rrf_k
        self.candidates = candidates

    def _top(self, scores: np.ndarray, require_positive: bool) -> list[int]:
        # Sort by (-score, chunk_id) for deterministic ties.
        order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.index.chunks[i].chunk_id))
        if require_positive:  # BM25: zero means no query term occurs — not a match at all
            order = [i for i in order if scores[i] > 0]
        return order[: self.candidates]

    def search(self, query: str, k: int = 12) -> list[Passage]:
        if not query.strip():
            return []
        dense_scores = self.index.dense @ self.embedder.embed_query(query)
        bm25_scores = np.asarray(self.index.bm25.get_scores(tokenize(query)))

        fused: dict[int, float] = {}
        if self.w > 0:
            for rank, i in enumerate(self._top(dense_scores, require_positive=False), start=1):
                fused[i] = fused.get(i, 0.0) + self.w / (self.rrf_k + rank)
        if self.w < 1:
            for rank, i in enumerate(self._top(bm25_scores, require_positive=True), start=1):
                fused[i] = fused.get(i, 0.0) + (1 - self.w) / (self.rrf_k + rank)

        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], self.index.chunks[kv[0]].chunk_id))[:k]
        return [Passage(chunk=self.index.chunks[i], score=round(s, 8), retrieved_by=query) for i, s in ranked]
