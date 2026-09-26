"""End-to-end over the 6 real seed papers: ingestion quality and retrieval.

Slow (loads the real embedding model) and skipped when papers/ is absent —
papers/ is git-ignored, so a fresh clone won't have the PDFs.

    uv run pytest -m slow
"""

import re
from pathlib import Path

import pytest

from tcv.corpus.pipeline import ingest_corpus
from tcv.corpus.sources import load_corpus_config
from tcv.corpus.store import CorpusStore

ROOT = Path(__file__).resolve().parents[2]
CFG = load_corpus_config(ROOT / "configs" / "corpus.yaml")
HAVE_PAPERS = all((ROOT / CFG.papers_dir / d.filename).exists() for d in CFG.documents)

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not HAVE_PAPERS, reason="seed PDFs not present in papers/")]

REF_ENTRY = re.compile(r"(^|\s)\[\d+\]\s+[A-Z]\.|\b[A-Z][a-z]+, [A-Z]\.;")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    manifest = ingest_corpus(CFG, data, base_dir=ROOT)
    return manifest, CorpusStore(data, CFG.version), data


def test_every_seed_paper_is_ingested(corpus):
    manifest, store, _ = corpus
    chunks = store.read_chunks()
    per_doc = {d.doc_id: sum(c.doc_id == d.doc_id for c in chunks) for d in manifest.documents}
    assert all(n >= 15 for n in per_doc.values()), per_doc


def test_reference_lists_do_not_leak_into_chunks(corpus):
    _, store, _ = corpus
    leaky = [c.chunk_id for c in store.read_chunks() if len(REF_ENTRY.findall(c.text)) >= 2]
    assert leaky == [], f"reference entries leaked into {leaky}"


def test_appendix_after_references_is_kept(corpus):
    """Du et al.'s appendix (debate transcripts) follows its reference list."""
    _, store, _ = corpus
    du_pages = {c.page for c in store.read_chunks() if c.doc_id == "du-2023"}
    assert max(du_pages) >= 13, "appendix pages after the references were dropped"


def test_retrieval_finds_the_right_paper(corpus):
    from tcv.retrieval.embed import SentenceTransformerEmbedder
    from tcv.retrieval.index import HybridIndex
    from tcv.retrieval.search import HybridSearcher

    _, store, _ = corpus
    emb = SentenceTransformerEmbedder(CFG.embed_model)
    searcher = HybridSearcher(HybridIndex.build(store.read_chunks(), emb, CFG.version), emb)
    probes = {
        "zero-tolerance reward penalises the entire trajectory": "march-2026",
        "four-way typology grounded ungrounded contradicted complementary": "gsar-2026",
        "entropy compression to reduce token usage": "yang-2025",
        "each debating agent gets a different external tool": "tool-mad-2026",
        "stopping the verifier from being swayed by the answer it is checking": "march-2026",
    }
    for q, want in probes.items():
        top3 = [p.chunk.doc_id for p in searcher.search(q, k=3)]
        assert want in top3, f"{q!r}: expected {want} in top 3, got {top3}"
