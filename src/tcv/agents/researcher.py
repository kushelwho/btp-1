"""Researcher — the only component with access to retrieval.

This monopoly is structural, enforced by an import contract: no other
component can put text into the evidence pool, so nothing downstream can
slip in "facts" from a model's memory and present them as retrieved.

Phase 1 provides retrieval-only pool building. Phase 2 adds model-written
search queries per sub-task on top of ``search_pool``.
"""

from __future__ import annotations

from tcv.retrieval.search import HybridSearcher
from tcv.schemas import Passage, PoolEntry, RetrievalPool


class Researcher:
    def __init__(self, searcher: HybridSearcher):
        self._searcher = searcher

    def search_pool(self, subtask_id: str, queries: list[str], k_per_query: int = 12,
                    k_total: int = 30) -> RetrievalPool:
        """Run several queries and merge them into one pool.

        Each chunk appears once, keeping its best-scoring hit. The pool is the
        *complete* evidence set: nothing found here is ever removed later,
        whether or not the Synthesizer ends up citing it.
        """
        best: dict[str, Passage] = {}
        for q in queries:
            for p in self._searcher.search(q, k=k_per_query):
                cur = best.get(p.chunk_id)
                if cur is None or p.score > cur.score:
                    best[p.chunk_id] = p
        ranked = sorted(best.values(), key=lambda p: (-p.score, p.chunk_id))[:k_total]
        return RetrievalPool(subtask_id=subtask_id, entries=tuple(PoolEntry(passage=p) for p in ranked))
