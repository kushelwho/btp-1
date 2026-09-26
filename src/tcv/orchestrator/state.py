"""Persistence for one run, so it can be replayed and audited offline.

    data/runs/<run_id>/
        run.json              RunState without pools and rounds
        pools/<subtask>.json  RetrievalPool — full, including uncited passages
        rounds/<n>.json       RoundState — complete state of each round
        calls.jsonl           model-call ledger (written by the gateway)

Writes are atomic (temp file + rename), so a crash mid-write never leaves a
truncated file that a resumed run would then trust.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tcv.schemas import RetrievalPool, RoundState, RunState


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class StateStore:
    def __init__(self, data_root: str | Path, run_id: str):
        self.root = Path(data_root) / "runs" / run_id
        self.run_id = run_id

    @property
    def ledger_path(self) -> Path:
        return self.root / "calls.jsonl"

    def write_text(self, name: str, text: str) -> Path:
        path = self.root / name
        _atomic_write(path, text)
        return path

    def write_json(self, name: str, data: Any) -> Path:
        return self.write_text(name, json.dumps(data, indent=1, ensure_ascii=False, default=str))

    # -- pools
    def save_pool(self, pool: RetrievalPool) -> None:
        _atomic_write(self.root / "pools" / f"{pool.subtask_id}.json", pool.model_dump_json())

    def load_pools(self) -> list[RetrievalPool]:
        d = self.root / "pools"
        if not d.exists():
            return []
        return [RetrievalPool.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]

    # -- rounds
    def save_round(self, state: RoundState) -> None:
        _atomic_write(self.root / "rounds" / f"{state.round}.json", state.model_dump_json())

    def load_rounds(self) -> list[RoundState]:
        d = self.root / "rounds"
        if not d.exists():
            return []
        rounds = [RoundState.model_validate_json(p.read_text(encoding="utf-8")) for p in d.glob("*.json")]
        return sorted(rounds, key=lambda r: r.round)

    # -- run
    def save_run(self, run: RunState) -> None:
        """Header to run.json; pools and rounds to their own files."""
        if run.run_id != self.run_id:
            raise ValueError(f"run {run.run_id} does not belong in store {self.run_id}")
        for pool in run.pools:
            self.save_pool(pool)
        for r in run.rounds:
            self.save_round(r)
        _atomic_write(self.root / "run.json", run.model_copy(update={"pools": (), "rounds": ()}).model_dump_json(indent=2))

    def load_run(self) -> RunState:
        header = RunState.model_validate_json((self.root / "run.json").read_text(encoding="utf-8"))
        return header.model_copy(update={"pools": tuple(self.load_pools()), "rounds": tuple(self.load_rounds())})

    def is_complete(self) -> bool:
        """A run with a stop reason finished; a resumed sweep skips it."""
        p = self.root / "run.json"
        return p.exists() and RunState.model_validate_json(p.read_text(encoding="utf-8")).stop_reason is not None
