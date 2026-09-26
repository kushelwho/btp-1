"""Corpus ingestion tests.

Synthetic PDFs keep these independent of papers/ (which is git-ignored).
Several cases are regressions from bugs found on the real seed papers.
"""

import re
from pathlib import Path

import pymupdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tcv.corpus.chunk import ChunkerConfig, chunk_page, sentence_spans
from tcv.corpus.ingest import (
    extract_pages,
    looks_like_appendix_start,
    looks_like_reference,
    normalise_block,
)
from tcv.corpus.manifest import CorpusFrozenError, freeze, sha256_file, verify
from tcv.corpus.pipeline import ingest_corpus
from tcv.corpus.sources import CorpusConfig
from tcv.corpus.store import CorpusStore

# ---------------------------------------------------------------- helpers

LOREM = (
    "Multi-agent debate improves factual accuracy on several benchmarks. "
    "The checker verifies each claim against its cited passage. "
    "Aggregative claims range over several sources at once. "
    "A bounded loop caps the number of revision rounds. "
)


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Each page is a list of blocks; each block is placed in its own text box."""
    doc = pymupdf.open()
    for blocks in pages:
        page = doc.new_page()
        y = 60
        for text in blocks:
            height = 14 * (len(text) // 80 + 2)
            page.insert_textbox(pymupdf.Rect(60, y, 540, y + height), text, fontsize=10)
            y += height + 14
    doc.save(path)
    return path


# ---------------------------------------------------------------- normalisation


def test_normalise_joins_hyphenated_line_breaks_and_ligatures():
    assert normalise_block("veri-\nfication of claims") == "verification of claims"
    assert normalise_block("the ﬁrst ﬂow") == "the first flow"
    assert normalise_block("  many\n\n   spaces\t here ") == "many spaces here"


def test_normalise_keeps_hyphen_before_capital():
    # "GPT-\n4" style breaks followed by a non-lowercase char are not joined
    assert normalise_block("Multi-\nAgent") == "Multi- Agent"


# ---------------------------------------------------------------- reference detection


@pytest.mark.parametrize(
    "text",
    [
        "[12] N. Lee, W. Ping, P. Xu. Factuality enhanced language models. NeurIPS, 2022.",
        "Brown, T.; Mann, B.; Ryder, N. Language models are few-shot learners. arXiv 2020.",
        "Y. Du, S. Li, A. Torralba. Improving factuality. In Proceedings of ICML, 2024.",
    ],
)
def test_reference_entries_detected(text):
    assert looks_like_reference(text)


@pytest.mark.parametrize(
    "text",
    [
        "Workshop on Math-AI, 2022",  # regression: ended reference mode in Du et al.
        "Appl. Sci. 2025, 15, 3676 20 of 21",  # regression: MDPI running header
        "A. Slone, C. Anil, I. Schlag, T. Gutman-Solo, et al.",  # author list
        "5 Limitations and Discussion",
        "123–145",
    ],
)
def test_reference_fragments_do_not_end_reference_mode(text):
    assert not looks_like_appendix_start(text)


@pytest.mark.parametrize(
    "text",
    ["A Appendix", "Appendix A: Prompts", "A.1. System Prompt of the Solver Agent", "B Proofs of Properties",
     "APPENDIX"],
)
def test_appendix_headings_end_reference_mode(text):
    assert looks_like_appendix_start(text)


def test_extract_drops_references_but_keeps_trailing_appendix(tmp_path):
    header = "A Study of Verification"
    pdf = make_pdf(tmp_path / "p.pdf", [
        [header, LOREM, "1"],
        [header, LOREM, "References", "[1] A. Smith, B. Jones. Some paper. In Proceedings of ACL, 2023.",
         "Workshop on Math-AI, 2022", "2"],
        [header, "[2] C. Doe, D. Roe. Another paper. arXiv preprint, 2024.", "3"],
        [header, "A Appendix", "The appendix contains the full prompts used in every experiment.", "4"],
    ])
    pages = extract_pages(pdf)
    full = "\n".join(p.text for p in pages)
    assert "Smith" not in full and "Doe" not in full, "reference entries leaked"
    assert "Math-AI" not in full, "reference fragment leaked"
    assert "full prompts used in every experiment" in full, "appendix after references was dropped"
    assert header not in full, "running header not removed"
    assert not re.search(r"(^|\n)\d$", full, re.M), "page numbers not removed"
    assert [p.page for p in pages] == [1, 2, 3, 4]


def test_publisher_sidebar_on_page_one_is_dropped(tmp_path):
    """Regression: the MDPI metadata sidebar in Yang et al. read as reference entries."""
    body = "The proposed framework combines debate with voting to reduce hallucinations in practice. " * 3
    pdf = make_pdf(tmp_path / "mdpi.pdf", [
        ["Received: 30 December 2024", "Accepted: 19 March 2025", "Citation: Yang, Y.; Ma, Y.; Feng, H.;",
         "Cheng, Y.; Han, Z. Minimizing", "Copyright: © 2025 by the authors.", body],
        ["Received: this word on page two is ordinary body text and must be kept as is."],
    ])
    pages = extract_pages(pdf)
    assert "Citation" not in pages[0].text and "Han, Z." not in pages[0].text
    assert "combines debate with voting" in pages[0].text, "body text after the sidebar was dropped"
    assert "ordinary body text" in pages[1].text, "sidebar filtering must only apply to page 1"


# ---------------------------------------------------------------- chunking


def test_sentence_spans_are_trimmed_and_in_order():
    text = "First sentence here. Second one follows!  Third? [4] Fourth.\n\nNew paragraph"
    spans = sentence_spans(text)
    parts = [text[s:e] for s, e in spans]
    assert parts == ["First sentence here.", "Second one follows!", "Third?", "[4] Fourth.", "New paragraph"]


def test_chunks_are_exact_slices_with_sequential_ids():
    text = " ".join([LOREM] * 12)
    chunks = chunk_page("du-2023", 3, text)
    assert len(chunks) > 1
    for n, c in enumerate(chunks):
        assert c.chunk_id == f"du-2023#p3c{n}"
        assert text[c.char_start:c.char_end] == c.text
        assert len(c.text.split()) <= ChunkerConfig().max_words


def test_consecutive_chunks_overlap():
    text = " ".join([LOREM] * 12)
    chunks = chunk_page("du-2023", 1, text)
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start < a.char_end, "expected overlap between consecutive chunks"
        assert b.char_start > a.char_start, "chunking must always advance"


def test_overlong_sentence_is_split_at_word_boundaries():
    text = " ".join(f"tok{i}" for i in range(700))  # no sentence punctuation at all
    chunks = chunk_page("du-2023", 1, text, ChunkerConfig(max_words=300))
    assert all(len(c.text.split()) <= 300 for c in chunks)
    assert all(c.text == text[c.char_start:c.char_end] for c in chunks)


def test_chunking_is_deterministic():
    text = " ".join([LOREM] * 9)
    assert chunk_page("du-2023", 1, text) == chunk_page("du-2023", 1, text)


def test_empty_page_yields_no_chunks():
    assert chunk_page("du-2023", 1, "") == []
    assert chunk_page("du-2023", 1, "   \n\n  ") == []


sentence = st.text(alphabet="abcdefghij ", min_size=1, max_size=60).map(lambda s: s.strip() or "x")
pages_text = st.lists(sentence, min_size=1, max_size=80).map(
    lambda ss: " ".join(s[:1].upper() + s[1:] + "." for s in ss)
)


@settings(max_examples=150, deadline=None)
@given(text=pages_text, target=st.integers(5, 60), overlap=st.integers(0, 20))
def test_chunks_cover_every_word(text, target, overlap):
    """No text may be lost between chunks: every word lies inside some chunk."""
    cfg = ChunkerConfig(target_words=target, max_words=target + 40, overlap_words=overlap, min_words=3)
    chunks = chunk_page("du-2023", 1, text, cfg)
    covered = [False] * len(text)
    for c in chunks:
        assert text[c.char_start:c.char_end] == c.text
        for i in range(c.char_start, c.char_end):
            covered[i] = True
    for m in re.finditer(r"\S+", text):
        assert all(covered[m.start():m.end()]), f"word {m.group()!r} not covered"


# ---------------------------------------------------------------- manifest + store + pipeline


def _cfg(pdfs: dict[str, str], version: str = "vtest") -> CorpusConfig:
    return CorpusConfig.model_validate({
        "version": version,
        "papers_dir": "papers",
        "embed_model": "test-model",
        "documents": [
            {"doc_id": doc_id, "title": doc_id, "filename": fn, "source": "local"}
            for doc_id, fn in pdfs.items()
        ],
    })


@pytest.fixture
def corpus_dir(tmp_path):
    (tmp_path / "papers").mkdir()
    make_pdf(tmp_path / "papers" / "one.pdf", [[LOREM * 3], [LOREM * 2]])
    make_pdf(tmp_path / "papers" / "two.pdf", [[LOREM * 4]])
    return tmp_path


def test_ingest_writes_readable_corpus(corpus_dir):
    cfg = _cfg({"paper-one": "one.pdf", "paper-two": "two.pdf"})
    m = ingest_corpus(cfg, corpus_dir / "data", base_dir=corpus_dir)
    store = CorpusStore(corpus_dir / "data", "vtest")
    assert store.read_manifest() == m
    chunks = store.read_chunks()
    assert len(chunks) == m.n_chunks > 0
    for c in chunks:
        page_text = store.read_pages(c.doc_id)[c.page - 1].text
        assert page_text[c.char_start:c.char_end] == c.text  # citations trace to exact source text


def test_chunk_ids_stable_across_reingestion(corpus_dir):
    cfg = _cfg({"paper-one": "one.pdf"})
    ingest_corpus(cfg, corpus_dir / "a", base_dir=corpus_dir)
    ingest_corpus(cfg, corpus_dir / "b", base_dir=corpus_dir)
    a = CorpusStore(corpus_dir / "a", "vtest").read_chunks()
    b = CorpusStore(corpus_dir / "b", "vtest").read_chunks()
    assert a == b


def test_verify_detects_changed_and_missing_files(corpus_dir):
    cfg = _cfg({"paper-one": "one.pdf", "paper-two": "two.pdf"})
    m = ingest_corpus(cfg, corpus_dir / "data", base_dir=corpus_dir)
    papers = corpus_dir / "papers"
    assert verify(m, papers) == []
    make_pdf(papers / "one.pdf", [["a completely different document"]])
    (papers / "two.pdf").unlink()
    problems = verify(m, papers)
    assert any("paper-one" in p and "mismatch" in p for p in problems)
    assert any("paper-two" in p and "missing" in p for p in problems)


def test_frozen_corpus_refuses_overwrite(corpus_dir):
    cfg = _cfg({"paper-one": "one.pdf"})
    m = ingest_corpus(cfg, corpus_dir / "data", base_dir=corpus_dir)
    store = CorpusStore(corpus_dir / "data", "vtest")
    store.write_manifest(freeze(m))
    assert store.is_frozen()
    with pytest.raises(CorpusFrozenError):
        ingest_corpus(cfg, corpus_dir / "data", base_dir=corpus_dir)


def test_sha256_is_content_hash(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert sha256_file(a) == sha256_file(b)
    assert len(sha256_file(a)) == 64


def test_corpus_config_rejects_bad_source_and_duplicates():
    with pytest.raises(ValueError):
        CorpusConfig.model_validate({
            "version": "v", "embed_model": "m",
            "documents": [{"doc_id": "abc", "title": "t", "filename": "f", "source": "http://x"}],
        })
    with pytest.raises(ValueError):
        CorpusConfig.model_validate({
            "version": "v", "embed_model": "m",
            "documents": [{"doc_id": "abc", "title": "t", "filename": "f", "source": "local"}] * 2,
        })
