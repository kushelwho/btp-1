"""The synthesis query set (configs/queries.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    shape: Literal["single-topic", "comparative", "temporal", "tension"]
    text: str
    probes: tuple[str, ...] = ()
    known_tension: str | None = None


class QuerySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    queries: tuple[Query, ...]

    @model_validator(mode="after")
    def _unique(self) -> "QuerySet":
        ids = [q.id for q in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate query id")
        return self

    def get(self, qid: str) -> Query:
        for q in self.queries:
            if q.id == qid:
                return q
        raise KeyError(f"unknown query {qid!r}; known: {[q.id for q in self.queries]}")


def load_queries(path: str | Path) -> QuerySet:
    with open(path, encoding="utf-8") as f:
        return QuerySet.model_validate(yaml.safe_load(f))
