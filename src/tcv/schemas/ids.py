"""Stable string identifiers.

IDs are strings, never positional integers, so they survive re-ingestion and
re-ordering. Each ID embeds enough context to be readable in a log line
without a lookup: ``du-2023-multiagent-debate#p7c3`` is document, page 7,
chunk 3.
"""

import re
from typing import Annotated

from pydantic import StringConstraints

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"

DOC_ID_RE = re.compile(rf"^{_SLUG}$")
CHUNK_ID_RE = re.compile(rf"^(?P<doc>{_SLUG})#p(?P<page>[1-9]\d*)c(?P<idx>\d+)$")

DocId = Annotated[str, StringConstraints(pattern=DOC_ID_RE.pattern, min_length=3, max_length=64)]
ChunkId = Annotated[str, StringConstraints(pattern=CHUNK_ID_RE.pattern)]
SubTaskId = Annotated[str, StringConstraints(pattern=r"^st\d{2}$")]
SentenceId = Annotated[str, StringConstraints(pattern=r"^r\d+s\d{4}$")]
ClaimId = Annotated[str, StringConstraints(pattern=r"^r\d+c\d{4}$")]
AtomId = Annotated[str, StringConstraints(pattern=r"^r\d+c\d{4}a\d{2}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[0-9a-f]{12}$")]


def chunk_id(doc_id: str, page: int, idx: int) -> str:
    """Build a chunk ID. ``page`` is 1-indexed; ``idx`` is 0-indexed within the page."""
    if page < 1 or idx < 0:
        raise ValueError(f"page must be >= 1 and idx >= 0, got page={page}, idx={idx}")
    return f"{doc_id}#p{page}c{idx}"


def parse_chunk_id(cid: str) -> tuple[str, int, int]:
    """Inverse of :func:`chunk_id` → ``(doc_id, page, idx)``."""
    m = CHUNK_ID_RE.match(cid)
    if not m:
        raise ValueError(f"not a chunk id: {cid!r}")
    return m["doc"], int(m["page"]), int(m["idx"])


def subtask_id(n: int) -> str:
    return f"st{n:02d}"


def sentence_id(round_: int, n: int) -> str:
    return f"r{round_}s{n:04d}"


def claim_id(round_: int, n: int) -> str:
    return f"r{round_}c{n:04d}"


def atom_id(claim: str, n: int) -> str:
    return f"{claim}a{n:02d}"
