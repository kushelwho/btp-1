"""The corpus source list (configs/corpus.yaml), validated."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from tcv.schemas.ids import DocId

from .chunk import ChunkerConfig


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceEntry(_Cfg):
    doc_id: DocId
    title: str
    filename: str
    source: str
    year: int | None = None

    @model_validator(mode="after")
    def _source_form(self) -> "SourceEntry":
        if not (self.source == "local" or self.source.startswith(("arxiv:", "doi:"))):
            raise ValueError(f"source must be arxiv:…, doi:… or local, got {self.source!r}")
        return self


class ChunkerSettings(_Cfg):
    target_words: int = 180
    max_words: int = 300
    overlap_words: int = 40
    min_words: int = 12

    def to_config(self) -> ChunkerConfig:
        return ChunkerConfig(**self.model_dump())


class CorpusConfig(_Cfg):
    version: str
    papers_dir: str = "papers"
    embed_model: str
    chunker: ChunkerSettings = ChunkerSettings()
    documents: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _unique(self) -> "CorpusConfig":
        ids = [d.doc_id for d in self.documents]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate doc_id(s): {sorted(dupes)}")
        return self


def load_corpus_config(path: str | Path) -> CorpusConfig:
    with open(path, encoding="utf-8") as f:
        return CorpusConfig.model_validate(yaml.safe_load(f))
