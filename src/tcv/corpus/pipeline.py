"""End-to-end ingestion: source list → documents, chunks, manifest on disk."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from tcv.schemas import Chunk, CorpusManifest, Document

from .chunk import chunk_page
from .ingest import NORMALISER_VERSION, PageText, extract_pages
from .manifest import sha256_file
from .sources import CorpusConfig
from .store import CorpusStore


def ingest_corpus(cfg: CorpusConfig, data_root: str | Path, base_dir: str | Path = ".") -> CorpusManifest:
    """Ingest every source in ``cfg`` and write the corpus. Returns an unfrozen manifest."""
    papers = Path(base_dir) / cfg.papers_dir
    chunker = cfg.chunker.to_config()
    now = datetime.now(timezone.utc)

    docs: list[tuple[Document, list[PageText]]] = []
    chunks: list[Chunk] = []
    for src in cfg.documents:
        path = papers / src.filename
        if not path.exists():
            raise FileNotFoundError(f"{src.doc_id}: {path} not found")
        pages = extract_pages(path)
        with pymupdf.open(path) as pdf:
            n_pages = len(pdf)
        doc = Document(
            doc_id=src.doc_id, title=src.title, source=src.source, year=src.year,
            filename=src.filename, sha256=sha256_file(path), n_pages=n_pages, ingested_at=now,
        )
        docs.append((doc, pages))
        for p in pages:
            chunks.extend(chunk_page(src.doc_id, p.page, p.text, chunker))

    manifest = CorpusManifest(
        version=cfg.version,
        frozen=False,
        documents=tuple(d for d, _ in docs),
        chunker=f"{NORMALISER_VERSION}/{chunker.describe()}",
        embed_model=cfg.embed_model,
        n_chunks=len(chunks),
    )
    CorpusStore(data_root, cfg.version).write(manifest, docs, chunks)
    return manifest
