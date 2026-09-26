"""Disk cache of model responses, keyed by everything that determines the output.

A re-run of an unchanged experiment costs nothing, and a crashed sweep
resumes without re-billing. Only successful responses are cached, so a
transient failure is retried on the next run rather than replayed forever.

    <root>/<first 2 hex of key>/<key>.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(**parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, key: str, record: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)  # atomic: a crash never leaves a half-written entry
