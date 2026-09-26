"""Phase 1 exit gate: do natural synthesis drafts contain aggregative claims?

The whole thesis rests on long reports containing claims whose truth ranges
over several sources (counts, comparisons, contrasts, trends, sweeping
statements). If ordinary synthesis drafts rarely contain them, the core
mechanisms cannot be tested, and the queries must be redesigned before
anything else is built.

This module drafts one report per query and counts aggregative *candidates*
with the lexical pre-pass. The counts are a screening signal for the team to
review against the draft itself, not a measurement.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tcv.agents.draft_parser import parse_draft
from tcv.checker.lexicon import LEXICON_VERSION, aggregative_operator, is_discourse
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import CorpusManifest, Draft, RetrievalPool

# Provisional screening threshold, to be confirmed by the team on review.
MIN_AGGREGATIVE_PER_REPORT = 3


def format_passages(pool: RetrievalPool, manifest: CorpusManifest) -> str:
    blocks = []
    for p in pool.passages():
        doc = manifest.doc(p.chunk.doc_id)
        year = f" ({doc.year})" if doc.year else ""
        blocks.append(f"[[{p.chunk_id}]] — {doc.title}{year}, page {p.chunk.page}\n{p.chunk.text}")
    return "\n\n---\n\n".join(blocks)


def prompt_variables(query: str, pool: RetrievalPool, manifest: CorpusManifest) -> dict[str, str]:
    return {
        "query": query,
        "passages": format_passages(pool, manifest),
        "n_passages": str(len(pool.entries)),
        "n_documents": str(len({p.chunk.doc_id for p in pool.passages()})),
    }


@dataclass
class PilotAnalysis:
    query_id: str
    n_sentences: int
    n_cited: int
    n_discourse: int
    n_aggregative: int
    aggregative_by_operator: dict[str, int]
    aggregative_sentences: list[dict[str, str]]
    n_multi_doc: int  # sentences citing >= 2 different papers — a structural signal, independent of wording
    documents_cited: int
    documents_in_pool: int
    malformed_citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    lexicon_version: str = LEXICON_VERSION
    screen_passed: bool = False

    def summary(self) -> str:
        ops = ", ".join(f"{k}={v}" for k, v in sorted(self.aggregative_by_operator.items())) or "none"
        return (f"{self.query_id}: {self.n_sentences} sentences, {self.n_cited} cited, "
                f"{self.n_discourse} discourse, {self.n_aggregative} aggregative candidates ({ops}), "
                f"{self.n_multi_doc} citing 2+ papers; "
                f"cites {self.documents_cited}/{self.documents_in_pool} papers; "
                f"bad citations: {len(self.malformed_citations) + len(self.unknown_citations)}; "
                f"screen {'PASS' if self.screen_passed else 'FAIL'}")


def analyse(query_id: str, draft: Draft, pool: RetrievalPool, malformed: list[str],
            unknown: list[str]) -> PilotAnalysis:
    aggregative, ops = [], Counter()
    discourse = 0
    for s in draft.sentences:
        if is_discourse(s.text):
            discourse += 1
            continue
        op = aggregative_operator(s.text)
        if op is not None:
            ops[op.value] += 1
            aggregative.append({"sentence_id": s.sentence_id, "operator": op.value, "text": s.text})
    cited_docs = {c.chunk_id.split("#")[0] for s in draft.sentences for c in s.citations}
    multi_doc = sum(1 for s in draft.sentences if len({c.chunk_id.split("#")[0] for c in s.citations}) >= 2)
    return PilotAnalysis(
        query_id=query_id,
        n_sentences=len(draft.sentences),
        n_cited=sum(1 for s in draft.sentences if s.citations),
        n_discourse=discourse,
        n_aggregative=len(aggregative),
        aggregative_by_operator=dict(ops),
        aggregative_sentences=aggregative,
        n_multi_doc=multi_doc,
        documents_cited=len(cited_docs),
        documents_in_pool=len({p.chunk.doc_id for p in pool.passages()}),
        malformed_citations=malformed,
        unknown_citations=unknown,
        screen_passed=len(aggregative) >= MIN_AGGREGATIVE_PER_REPORT,
    )


def run_pilot(query_id: str, query: str, pool: RetrievalPool, manifest: CorpusManifest, gateway: Gateway,
              prompt: Prompt, out_dir: str | Path) -> PilotAnalysis:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pool.json").write_text(pool.model_dump_json(indent=1), encoding="utf-8")

    res = gateway.call("synthesizer", prompt, prompt_variables(query, pool, manifest))
    (out / "draft.md").write_text(res.text, encoding="utf-8")

    parsed = parse_draft(res.text, round_=1, known_chunks={p.chunk_id for p in pool.passages()})
    (out / "draft.json").write_text(parsed.draft.model_dump_json(indent=1), encoding="utf-8")

    analysis = analyse(query_id, parsed.draft, pool, parsed.malformed_citations, parsed.unknown_citations)
    (out / "analysis.json").write_text(json.dumps({**asdict(analysis), "call_id": res.call_id,
                                                   "cost_usd": res.usage.cost_usd, "cached": res.cached},
                                                  indent=1), encoding="utf-8")
    return analysis
