"""Researcher — the only component with access to retrieval.

This monopoly is structural, enforced by an import contract: no other
component can put text into the evidence pool, so nothing downstream can
slip in "facts" from a model's memory and present them as retrieved.

Per sub-task: the model proposes search queries (one batched call for all
sub-tasks), code runs them, and the merged hits become that sub-task's
pool. The pool is the complete evidence set — cited or not, nothing in it
is ever removed (invariant I-2).

Oracle mode (N9) replaces search with human-confirmed gold passages: every
sub-task's pool holds all of them, ordered by how well each matches that
sub-task. Comparing oracle and real runs separates retrieval errors from
checking errors.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from tcv.config import RetrievalConfig
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.retrieval.search import HybridSearcher
from tcv.schemas import Passage, PoolEntry, RetrievalPool, SubTask


class SearchQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[str]


class Researcher:
    def __init__(self, searcher: HybridSearcher, gateway: Gateway | None = None, prompt: Prompt | None = None,
                 config: RetrievalConfig = RetrievalConfig(), gold: Sequence[str] | None = None):
        self._searcher = searcher
        self._gateway = gateway
        self._prompt = prompt
        self._config = config
        if config.oracle and not gold:
            raise ValueError("oracle retrieval needs gold passages (configs/gold/<query>.yaml)")
        self._gold = list(gold or [])

    def search_pool(self, subtask_id: str, queries: list[str], k_per_query: int = 12,
                    k_total: int = 30) -> RetrievalPool:
        """Run several queries and merge them into one pool.

        Each chunk appears once, keeping its best-scoring hit.
        """
        best: dict[str, Passage] = {}
        for q in queries:
            for p in self._searcher.search(q, k=k_per_query):
                cur = best.get(p.chunk_id)
                if cur is None or p.score > cur.score:
                    best[p.chunk_id] = p
        ranked = sorted(best.values(), key=lambda p: (-p.score, p.chunk_id))[:k_total]
        return RetrievalPool(subtask_id=subtask_id, entries=tuple(PoolEntry(passage=p) for p in ranked))

    def research(self, subtasks: Sequence[SubTask]) -> dict[str, RetrievalPool]:
        """One pool per sub-task, keyed by sub-task id.

        Query writing is batched into a single model call for all sub-tasks.
        If the model fails for a sub-task, that sub-task still gets a pool
        from its question and heading alone — a weaker pool, never a missing one.
        """
        if self._config.oracle:
            return self.gold_pools(subtasks, self._gold)
        if self._gateway is None or self._prompt is None:
            raise RuntimeError("Researcher.research needs a gateway and a query prompt")
        items = [{"subtask_id": st.subtask_id, "heading": st.heading, "question": st.question} for st in subtasks]
        results = self._gateway.call_batch(
            "economy", self._prompt, items, SearchQueries,
            shared={"n_queries": str(self._config.queries_per_subtask)})
        pools = {}
        for st, r in zip(subtasks, results):
            model_queries = [q.strip() for q in (r.value.queries if r.ok else []) if q.strip()]
            queries = list(dict.fromkeys([st.question, *model_queries[: self._config.queries_per_subtask],
                                          st.heading]))
            pools[st.subtask_id] = self.search_pool(st.subtask_id, queries, k_per_query=self._config.k_per_query,
                                                    k_total=self._config.k_per_subtask)
        return pools

    def gold_pools(self, subtasks: Sequence[SubTask], gold: Sequence[str]) -> dict[str, RetrievalPool]:
        """Oracle pools: all gold passages in every sub-task's pool, best match to that sub-task first."""
        by_id = {c.chunk_id: c for c in self._searcher.index.chunks}
        missing = [cid for cid in gold if cid not in by_id]
        if missing:
            raise ValueError(f"gold passages not in the corpus: {missing[:5]}")
        pools = {}
        for st in subtasks:
            rank = {p.chunk_id: (i, p.score) for i, p in enumerate(self._searcher.search(st.question, k=len(by_id)))}
            ordered = sorted(dict.fromkeys(gold), key=lambda cid: (rank.get(cid, (len(by_id), 0.0))[0], cid))
            pools[st.subtask_id] = RetrievalPool(subtask_id=st.subtask_id, entries=tuple(
                PoolEntry(passage=Passage(chunk=by_id[cid], score=rank.get(cid, (0, 0.0))[1], retrieved_by="oracle"))
                for cid in ordered))
        return pools
