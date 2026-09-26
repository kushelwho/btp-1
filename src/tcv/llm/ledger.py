"""Append-only JSONL log of every model call.

Every verdict stores the call IDs it came from, so any decision can be traced
back to the exact prompt, model, and cost through this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    ts: datetime
    run_id: str | None
    role: str
    model: str  # model that actually served the response (may be a fallback)
    requested_model: str
    prompt: str  # "name@version"
    prompt_sha256: str
    cache_key: str
    n_items: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    local_cache_hit: bool = False
    status: str  # ok | refusal | invalid_output | error | budget
    error: str | None = None


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._n = self._count_existing()

    def _count_existing(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def next_call_id(self) -> str:
        self._n += 1
        return f"c_{self._n:06d}"

    def append(self, entry: LedgerEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def entries(self) -> list[LedgerEntry]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [LedgerEntry.model_validate_json(line) for line in f if line.strip()]

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
