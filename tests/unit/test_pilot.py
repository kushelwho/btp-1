"""Researcher pool-building and pilot analysis tests (offline)."""

import json

from conftest import NOW, make_chunk
from tcv.agents.researcher import Researcher
from tcv.eval.pilot import analyse, run_pilot
from tcv.llm.cache import ResponseCache
from tcv.llm.gateway import Gateway, ModelsConfig, RoleConfig
from tcv.llm.ledger import Ledger
from tcv.llm.prompts import load_prompt
from tcv.llm.provider import FakeProvider
from tcv.agents.draft_parser import parse_draft
from tcv.retrieval.embed import HashingEmbedder
from tcv.retrieval.index import HybridIndex
from tcv.retrieval.search import HybridSearcher
from tcv.schemas import CorpusManifest, Document

TEXTS = {
    "du-2023": ["Multiple model instances debate over several rounds and converge on an answer.",
                "Debate improves factual accuracy on six reasoning benchmarks."],
    "march-2026": ["The checker verifies claims without seeing the solver's original answer.",
                   "A zero-tolerance reward penalises the entire trajectory."],
    "gsar-2026": ["Claims are typed as grounded, ungrounded, contradicted, or complementary.",
                  "An explicit compute budget bounds the number of replanning iterations."],
}


def _setup(tmp_path):
    chunks = [make_chunk(doc=d, page=1, idx=i, text=t) for d, ts in TEXTS.items() for i, t in enumerate(ts)]
    emb = HashingEmbedder(dim=512)
    searcher = HybridSearcher(HybridIndex.build(chunks, emb, "vtest"), emb)
    manifest = CorpusManifest(
        version="vtest", frozen=False, chunker="c", embed_model=emb.name, n_chunks=len(chunks),
        documents=tuple(Document(doc_id=d, title=d.upper(), source="local", year=2025, filename=f"{d}.pdf",
                                 sha256="0" * 64, n_pages=1, ingested_at=NOW) for d in TEXTS),
    )
    return Researcher(searcher), manifest


def test_search_pool_merges_queries_without_duplicates(tmp_path):
    researcher, _ = _setup(tmp_path)
    pool = researcher.search_pool("st00", ["debate rounds converge", "debate factual accuracy benchmarks"],
                                  k_per_query=6, k_total=10)
    ids = [p.chunk_id for p in pool.passages()]
    assert len(ids) == len(set(ids)) and len(ids) <= 10
    assert all(not e.cited for e in pool.entries)  # nothing is cited until a draft cites it


def test_search_pool_respects_k_total(tmp_path):
    researcher, _ = _setup(tmp_path)
    assert len(researcher.search_pool("st00", ["claims checker budget debate"], k_total=2).entries) == 2


DRAFT = """\
# Verification in multi-agent systems
## Mechanisms
We now turn to how claims are checked.
Unlike debate, MARCH hides the answer from the checker [[march-2026#p1c0]].
Two of the three frameworks bound their loop [[gsar-2026#p1c1]][[march-2026#p1c1]].
Debate consistently improves accuracy [[du-2023#p1c1]].
GSAR types claims four ways [[gsar-2026#p1c0]].
A made-up reference [[du-2023#p9c9]].
"""


def test_pilot_analysis_counts_aggregative_candidates(tmp_path):
    researcher, _ = _setup(tmp_path)
    pool = researcher.search_pool("st00", ["checker claims debate budget"], k_total=6)
    parsed = parse_draft(DRAFT, known_chunks={p.chunk_id for p in pool.passages()})
    a = analyse("q99", parsed.draft, pool, parsed.malformed_citations, parsed.unknown_citations)
    assert a.n_discourse == 1
    assert a.aggregative_by_operator == {"contrast": 1, "count": 1, "universal": 1}
    assert a.n_aggregative == 3 and a.screen_passed
    assert a.unknown_citations == ["du-2023#p9c9"]


def test_run_pilot_end_to_end_with_fake_model(tmp_path):
    researcher, manifest = _setup(tmp_path)
    pool = researcher.search_pool("st00", ["checker claims debate budget"], k_total=6)
    provider = FakeProvider(lambda req: DRAFT)
    gw = Gateway(provider=provider,
                 models=ModelsConfig(roles={"synthesizer": RoleConfig(model="claude-opus-5", max_tokens=100)}),
                 cache=ResponseCache(tmp_path / "cache"), ledger=Ledger(tmp_path / "calls.jsonl"))
    a = run_pilot("q99", "How do frameworks verify claims?", pool, manifest, gw,
                  load_prompt("pilot/draft@1"), tmp_path / "out")

    assert a.n_aggregative == 3
    user = provider.requests[0].user
    assert "How do frameworks verify claims?" in user
    assert all(f"[[{p.chunk_id}]]" in user for p in pool.passages())  # every pooled passage shown
    saved = json.loads((tmp_path / "out" / "analysis.json").read_text())
    assert saved["n_aggregative"] == 3 and saved["call_id"]
    assert {f.name for f in (tmp_path / "out").iterdir()} == {"pool.json", "draft.md", "draft.json", "analysis.json"}
