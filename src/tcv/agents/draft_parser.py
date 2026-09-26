"""Parse Synthesizer markdown into a ``Draft`` of cited sentences.

Expected model output::

    ## Section heading
    Sentence one supports X [[du-2023#p3c1]]. Sentence two [[gsar-2026#p4c0]][[march-2026#p2c2]].

Citations are ``[[chunk_id]]`` markers, possibly several per sentence and
possibly placed after the full stop — they are moved inside it before
sentence splitting, so a trailing citation is never attached to the *next*
sentence.

The parser never guesses: a malformed or unknown citation is reported, not
silently repaired, because a citation that points at nothing is exactly the
kind of error the Checker exists to catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tcv.schemas import Citation, Draft, Sentence
from tcv.schemas.ids import CHUNK_ID_RE, sentence_id

_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$")
_CITE = re.compile(r"\[\[([^\[\]]+)\]\]")
_TRAILING_CITES = re.compile(r"([.!?])((?:\s*\[\[[^\[\]]+\]\])+)")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+")

DEFAULT_SECTION = "Report"


@dataclass
class ParseResult:
    draft: Draft
    malformed_citations: list[str] = field(default_factory=list)  # not a chunk-id shape
    unknown_citations: list[str] = field(default_factory=list)  # well-formed but not in the evidence


def _split_ids(marker_body: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;]", marker_body) if p.strip()]


def parse_draft(markdown: str, round_: int = 1, known_chunks: set[str] | None = None) -> ParseResult:
    sections: list[str] = []
    rows: list[tuple[str, str, list[str]]] = []  # (section, text, citations)
    malformed: list[str] = []
    unknown: list[str] = []
    current = None
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        para = " ".join(paragraph)
        paragraph = []
        para = _TRAILING_CITES.sub(lambda m: f"{m.group(2).strip()}{m.group(1)}", para)
        for sent in _SENT_SPLIT.split(para):
            ids: list[str] = []
            for body in _CITE.findall(sent):
                for cid in _split_ids(body):
                    if not CHUNK_ID_RE.match(cid):
                        malformed.append(cid)
                    elif known_chunks is not None and cid not in known_chunks:
                        unknown.append(cid)
                    elif cid not in ids:
                        ids.append(cid)
            text = re.sub(r"\s{2,}", " ", _CITE.sub("", sent)).strip()
            text = re.sub(r"\s+([.!?,;:])", r"\1", text)
            if text:
                rows.append((current or DEFAULT_SECTION, text, ids))

    for raw in markdown.splitlines():
        line = raw.rstrip()
        m = _HEADING.match(line)
        if m:
            flush()
            current = m.group(1).strip()
            if current not in sections:
                sections.append(current)
            continue
        if not line.strip():
            flush()
            continue
        if _BULLET.match(line):
            flush()
            line = _BULLET.sub("", line)
        paragraph.append(line.strip())
    flush()

    if any(sec == DEFAULT_SECTION for sec, _, _ in rows) and DEFAULT_SECTION not in sections:
        sections.insert(0, DEFAULT_SECTION)

    sentences = tuple(
        Sentence(sentence_id=sentence_id(round_, n), section=sec, text=text,
                 citations=tuple(Citation(chunk_id=c) for c in ids))
        for n, (sec, text, ids) in enumerate(rows)
    )
    return ParseResult(draft=Draft(round=round_, sections=tuple(sections), sentences=sentences),
                       malformed_citations=malformed, unknown_citations=unknown)
