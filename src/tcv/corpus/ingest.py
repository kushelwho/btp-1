"""PDF → page-mapped, normalised text.

Each page becomes one string. Chunk character spans index into exactly this
string, so the normalisation here is part of the corpus contract: change it
and the corpus version must be bumped.

Filtering, in order:
  * image blocks are dropped;
  * arXiv margin stamps and bare page numbers are dropped;
  * publisher metadata sidebars on page 1 (editors, dates, "Citation:",
    licence) are dropped;
  * running headers/footers (short text repeated on many pages) are dropped;
  * the reference list is dropped *entry by entry*. Appendices frequently
    follow the references (e.g. Du et al. has 15 pages of debate transcripts
    after them), so we cannot simply cut everything after "References".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

NORMALISER_VERSION = "norm-v2"  # v2: drops publisher front-matter sidebars on page 1

_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})
_HYPHEN_BREAK = re.compile(r"(\w)-\n([a-z])")
_WS = re.compile(r"[ \t\r\f\v\n]+")

_ARXIV_STAMP = re.compile(r"^arXiv:\s*\d{4}\.\d{4,5}v\d+")
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")
_REFS_HEADING = re.compile(r"^(\d+\.?\s*)?(references|bibliography)$", re.I)
_REFS_PREFIX = re.compile(r"^(\d+\.?\s*)?(references|bibliography)\s+", re.I)

# Publisher metadata sidebars (MDPI and similar): editors, dates, "Citation:",
# licence. They sit on page 1 as a run of one-line blocks.
_SIDEBAR_START = re.compile(r"^(?:Academic Editors?:|Received:|Revised:|Accepted:|Published:|Citation:|"
                            r"Copyright:|Licensee\b|Publisher'?s Note:)")
_SIDEBAR_LINE_MAX_WORDS = 8

_NUMBERED_REF = re.compile(r"^\[\d+\]")
_YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
_AUTHOR_INITIAL = re.compile(r"\b[A-Z]\.\s?(?:[A-Z]\.\s?)?[A-Z][a-zA-Z'\-]+|\b[A-Z][a-zA-Z'\-]+,\s[A-Z]\.")
_VENUE = re.compile(r"\b(et al\.|arXiv|Proceedings|Proc\.|Conference|Journal|Transactions|In\s+[A-Z])")


@dataclass(frozen=True)
class PageText:
    page: int  # 1-indexed
    text: str


def normalise_block(raw: str) -> str:
    t = raw.translate(_LIGATURES)
    t = _HYPHEN_BREAK.sub(r"\1\2", t)
    return _WS.sub(" ", t).strip()


def looks_like_reference(text: str) -> bool:
    if _NUMBERED_REF.match(text):
        return True
    if not _YEAR.search(text):
        return False
    authors = len(_AUTHOR_INITIAL.findall(text))
    return authors >= 2 or bool(_VENUE.search(text))


_APPENDIX_WORD = re.compile(r"^(?:[A-H]\.?\s+)?(?:Appendix|APPENDIX|Appendices|APPENDICES|Supplementary|SUPPLEMENTARY)\b")
_LETTER_HEADING = re.compile(r"^[A-H](?:\.\d+)*\.?\s+[A-Z][a-z]")


def looks_like_appendix_start(text: str) -> bool:
    """A strong signal that the reference list has ended.

    Deliberately strict: reference lists are full of short capitalised
    fragments ("Workshop on Math-AI, 2022") that look like headings, and
    exiting reference mode early leaks the rest of the list into the corpus.
    """
    if _APPENDIX_WORD.match(text):
        return True
    return (
        bool(_LETTER_HEADING.match(text))  # "A.1. System Prompt", "B Proofs"
        and len(text.split()) <= 12
        and "," not in text  # rules out author lists: "A. Slone, C. Anil"
        and not _YEAR.search(text)
        and not looks_like_reference(text)
    )


def _page_blocks(doc: pymupdf.Document) -> list[list[str]]:
    pages = []
    for page in doc:
        blocks = []
        for b in page.get_text("blocks"):
            if b[6] != 0:  # 1 = image block
                continue
            t = normalise_block(b[4])
            if t:
                blocks.append(t)
        pages.append(blocks)
    return pages


_DIGITS = re.compile(r"\d+")


def _shape(block: str) -> str:
    """Digits abstracted away, so "Appl. Sci. 2025, 15, 3676 19 of 21" matches every page."""
    return _DIGITS.sub("#", block)


def _repeated_furniture(pages: list[list[str]]) -> set[str]:
    """Shapes of short blocks appearing on at least 40% of pages (min 3): headers/footers."""
    if len(pages) < 3:
        return set()
    counts = Counter(s for blocks in pages for s in {_shape(b) for b in blocks if len(b.split()) <= 15})
    threshold = max(3, int(0.4 * len(pages)))
    return {s for s, n in counts.items() if n >= threshold}


def extract_pages(pdf_path: str | Path) -> list[PageText]:
    """Return one normalised text per page. Pages with no kept text are empty strings."""
    with pymupdf.open(pdf_path) as doc:
        pages = _page_blocks(doc)

    furniture = _repeated_furniture(pages)
    in_refs = False
    out: list[PageText] = []

    for i, blocks in enumerate(pages, start=1):
        kept: list[str] = []
        in_sidebar = False
        for b in blocks:
            if _ARXIV_STAMP.match(b) or _PAGE_NUMBER.match(b) or _shape(b) in furniture:
                continue
            if i == 1:
                if _SIDEBAR_START.match(b):
                    in_sidebar = True
                    continue
                if in_sidebar:
                    if len(b.split()) <= _SIDEBAR_LINE_MAX_WORDS:
                        continue  # continuation line of the sidebar
                    in_sidebar = False  # a full-length block: body text resumes
            if _REFS_HEADING.match(b):
                in_refs = True
                continue
            m = _REFS_PREFIX.match(b)
            if m and looks_like_reference(b[m.end():]):
                in_refs = True  # heading fused into the first entry's block
                continue
            if in_refs:
                if looks_like_appendix_start(b):
                    in_refs = False  # e.g. "A Appendix" — resume keeping text
                else:
                    continue  # a reference entry or a fragment of one
            kept.append(b)
        out.append(PageText(page=i, text="\n\n".join(kept)))
    return out
