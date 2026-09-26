"""Corpus manifest: hashing, freezing, verification.

A frozen manifest pins the exact source files. Verification recomputes every
hash, so a silently replaced PDF is caught before it can invalidate results.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tcv.schemas import CorpusManifest


class CorpusFrozenError(RuntimeError):
    """Raised on an attempt to overwrite a frozen corpus version."""


def sha256_file(path: str | Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def freeze(manifest: CorpusManifest) -> CorpusManifest:
    return manifest.model_copy(update={"frozen": True})


def verify(manifest: CorpusManifest, papers_dir: str | Path) -> list[str]:
    """Return a list of problems; empty means every source file matches its hash."""
    problems = []
    for doc in manifest.documents:
        path = Path(papers_dir) / doc.filename
        if not path.exists():
            problems.append(f"{doc.doc_id}: missing file {path}")
        elif sha256_file(path) != doc.sha256:
            problems.append(f"{doc.doc_id}: hash mismatch for {path}")
    return problems
