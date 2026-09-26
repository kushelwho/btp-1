"""Page text → overlapping, sentence-aligned chunks with exact character spans.

Chunks never cross a page boundary, so every chunk has one unambiguous page
for citation. ``chunk.text == page_text[char_start:char_end]`` always holds,
which is what lets a citation be traced back to the exact source text.

Deterministic: the same page text and parameters always yield the same chunk
IDs, so IDs are stable across re-ingestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tcv.schemas import Chunk
from tcv.schemas.ids import chunk_id

# A sentence ends at . ! ? followed by whitespace and an uppercase letter,
# digit, bracket or quote — or at a paragraph break.
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[\(\"'“])|\n\n")
_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class ChunkerConfig:
    target_words: int = 180
    max_words: int = 300
    overlap_words: int = 40
    min_words: int = 12  # trailing fragments shorter than this merge backwards

    def describe(self) -> str:
        return (f"sentence-window/target={self.target_words}w/max={self.max_words}w/"
                f"overlap={self.overlap_words}w/min={self.min_words}w")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of sentences, whitespace-trimmed. Covers all non-space text."""
    spans, start = [], 0
    for m in _SENT_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    out = []
    for s, e in spans:
        seg = text[s:e]
        ls = len(seg) - len(seg.lstrip())
        rs = len(seg.rstrip())
        if rs > ls:
            out.append((s + ls, s + rs))
    return out


def _split_long(text: str, span: tuple[int, int], max_words: int) -> list[tuple[int, int]]:
    """Break a single over-long "sentence" (tables, run-on text) at word boundaries."""
    s, e = span
    words = [(s + m.start(), s + m.end()) for m in _WORD.finditer(text[s:e])]
    return [(words[i][0], words[min(i + max_words, len(words)) - 1][1])
            for i in range(0, len(words), max_words)]


def _nwords(text: str, span: tuple[int, int]) -> int:
    return len(_WORD.findall(text[span[0]:span[1]]))


def chunk_page(doc_id: str, page: int, text: str, cfg: ChunkerConfig = ChunkerConfig()) -> list[Chunk]:
    units: list[tuple[int, int]] = []
    for sp in sentence_spans(text):
        units.extend(_split_long(text, sp, cfg.max_words) if _nwords(text, sp) > cfg.max_words else [sp])
    if not units:
        return []

    counts = [_nwords(text, u) for u in units]
    windows: list[tuple[int, int]] = []  # (first_unit, last_unit) inclusive
    i = 0
    while i < len(units):
        j, total = i, counts[i]
        while j + 1 < len(units) and total < cfg.target_words and total + counts[j + 1] <= cfg.max_words:
            j += 1
            total += counts[j]
        windows.append((i, j))
        if j == len(units) - 1:
            break
        # Next window starts early enough to overlap by ~overlap_words, but always advances.
        k, back = j, 0
        while k > i + 1 and back + counts[k] <= cfg.overlap_words:
            back += counts[k]
            k -= 1
        i = max(i + 1, k + 1 if back else j + 1)

    # Merge a tiny trailing window into its predecessor.
    if len(windows) > 1:
        a, b = windows[-1]
        if sum(counts[a:b + 1]) < cfg.min_words:
            pa, _ = windows[-2]
            windows[-2:] = [(pa, b)]

    chunks = []
    for n, (a, b) in enumerate(windows):
        start, end = units[a][0], units[b][1]
        chunks.append(Chunk(
            chunk_id=chunk_id(doc_id, page, n),
            doc_id=doc_id,
            page=page,
            char_start=start,
            char_end=end,
            text=text[start:end],
        ))
    return chunks
