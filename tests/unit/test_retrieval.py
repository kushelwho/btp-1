"""Retrieval tests — fast, using the deterministic hashing embedder."""

import pytest

from conftest import make_chunk
from tcv.retrieval.embed import HashingEmbedder
from tcv.retrieval.index import HybridIndex, IndexStaleError, tokenize
from tcv.retrieval.search import HybridSearcher

TEXTS = [
    "Multi-agent debate lets several model instances argue until they reach consensus.",
    "The checker verifies each atomic claim against its cited passage using entailment.",
    "A zero-tolerance reward penalises the whole trajectory for any unsupported claim.",
    "Reciprocal rank fusion combines dense and lexical rankings without score calibration.",
    "Bounded recovery caps the number of correction rounds under an explicit compute budget.",
    "The corpus manifest pins every source document by its SHA-256 content hash.",
]


@pytest.fixture
def chunks():
    return [make_chunk(doc="seed-doc", page=1, idx=i, text=t) for i, t in enumerate(TEXTS)]


@pytest.fixture
def embedder():
    return HashingEmbedder(dim=512)


@pytest.fixture
def index(chunks, embedder):
    return HybridIndex.build(chunks, embedder, corpus_version="vtest")


def test_tokenize_drops_stopwords_and_keeps_hyphenated_terms():
    assert tokenize("The zero-tolerance reward of a model") == ["zero-tolerance", "reward", "model"]


def test_topical_query_ranks_matching_chunk_first(index, embedder):
    hits = HybridSearcher(index, embedder).search("zero-tolerance reward trajectory", k=3)
    assert hits[0].chunk.text == TEXTS[2]


def test_results_are_ordered_bounded_and_labelled(index, embedder):
    hits = HybridSearcher(index, embedder).search("claim entailment checker", k=4)
    assert 0 < len(hits) <= 4
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert all(h.retrieved_by == "claim entailment checker" for h in hits)


def test_search_is_deterministic(index, embedder):
    s = HybridSearcher(index, embedder)
    assert s.search("rank fusion dense lexical", k=5) == s.search("rank fusion dense lexical", k=5)


def test_lexical_only_mode_ignores_chunks_without_query_terms(index, embedder):
    hits = HybridSearcher(index, embedder, dense_weight=0.0).search("manifest", k=6)
    assert [h.chunk.text for h in hits] == [TEXTS[5]]


def test_empty_query_returns_nothing(index, embedder):
    assert HybridSearcher(index, embedder).search("   ") == []


def test_save_load_round_trip(index, embedder, chunks, tmp_path):
    index.save(tmp_path / "idx")
    loaded = HybridIndex.load(tmp_path / "idx", chunks, embed_model=embedder.name)
    q = "compute budget for correction rounds"
    assert HybridSearcher(loaded, embedder).search(q) == HybridSearcher(index, embedder).search(q)


def test_load_rejects_index_built_from_other_chunks(index, chunks, tmp_path):
    index.save(tmp_path / "idx")
    with pytest.raises(IndexStaleError):
        HybridIndex.load(tmp_path / "idx", chunks[:-1])


def test_load_rejects_wrong_embedding_model(index, chunks, tmp_path):
    index.save(tmp_path / "idx")
    with pytest.raises(IndexStaleError):
        HybridIndex.load(tmp_path / "idx", chunks, embed_model="some-other-model")


def test_searcher_rejects_mismatched_query_embedder(index):
    with pytest.raises(ValueError):
        HybridSearcher(index, HashingEmbedder(dim=64))


def test_dense_weight_must_be_a_fraction(index, embedder):
    with pytest.raises(ValueError):
        HybridSearcher(index, embedder, dense_weight=1.5)


def test_cannot_index_empty_corpus(embedder):
    with pytest.raises(ValueError):
        HybridIndex.build([], embedder, corpus_version="vtest")
