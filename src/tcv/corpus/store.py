"""On-disk layout for one corpus version.

    data/corpus/<version>/
        manifest.json            CorpusManifest
        documents/<doc_id>.json  {"document": Document, "pages": [{"page", "text"}]}
        chunks.jsonl             one Chunk per line
"""

from __future__ import annotations

import json
from pathlib import Path

from tcv.schemas import Chunk, CorpusManifest, Document

from .ingest import PageText
from .manifest import CorpusFrozenError


class CorpusStore:
    def __init__(self, data_root: str | Path, version: str):
        self.root = Path(data_root) / "corpus" / version
        self.version = version

    # -- paths
    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def chunks_path(self) -> Path:
        return self.root / "chunks.jsonl"

    def document_path(self, doc_id: str) -> Path:
        return self.root / "documents" / f"{doc_id}.json"

    # -- state
    def exists(self) -> bool:
        return self.manifest_path.exists()

    def is_frozen(self) -> bool:
        return self.exists() and self.read_manifest().frozen

    def _guard(self) -> None:
        if self.is_frozen():
            raise CorpusFrozenError(
                f"corpus {self.version} is frozen; bump the version in configs/corpus.yaml to change it"
            )

    # -- write
    def write(self, manifest: CorpusManifest, docs: list[tuple[Document, list[PageText]]],
              chunks: list[Chunk]) -> None:
        self._guard()
        (self.root / "documents").mkdir(parents=True, exist_ok=True)
        for doc, pages in docs:
            payload = {"document": doc.model_dump(mode="json"),
                       "pages": [{"page": p.page, "text": p.text} for p in pages]}
            self.document_path(doc.doc_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(c.model_dump_json() + "\n")
        self.write_manifest(manifest)

    def write_manifest(self, manifest: CorpusManifest) -> None:
        # Freezing an unfrozen manifest is allowed; changing a frozen one is not.
        if self.exists():
            current = self.read_manifest()
            if current.frozen and manifest != current:
                raise CorpusFrozenError(f"corpus {self.version} is frozen")
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    # -- read
    def read_manifest(self) -> CorpusManifest:
        return CorpusManifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))

    def read_chunks(self) -> list[Chunk]:
        with open(self.chunks_path, encoding="utf-8") as f:
            return [Chunk.model_validate_json(line) for line in f if line.strip()]

    def read_pages(self, doc_id: str) -> list[PageText]:
        payload = json.loads(self.document_path(doc_id).read_text(encoding="utf-8"))
        return [PageText(page=p["page"], text=p["text"]) for p in payload["pages"]]
