"""Gold passages per query, for oracle retrieval (ER-5, N9).

Gold passages are human judgments — "these are the passages a good report
on this question needs" — so the confirmed list lives in a tracked file,
``configs/gold/<query_id>.yaml``, not under the git-ignored ``data/``.

    propose   candidates = every passage any run retrieved for the question,
              plus the top search hits for the question and its probes,
              written to data/gold/candidates/<query_id>.yaml with keep: false
    confirm   the entries a person set to keep: true become the gold file
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from tcv.schemas import Passage, RetrievalPool


def candidates_path(data_root: str | Path, query_id: str) -> Path:
    return Path(data_root) / "gold" / "candidates" / f"{query_id}.yaml"


def gold_path(query_id: str, root: str | Path = "configs/gold") -> Path:
    return Path(root) / f"{query_id}.yaml"


def pools_from_runs(data_root: str | Path, query_id: str) -> list[RetrievalPool]:
    """Pools of every saved run for this query (any condition, finished or not)."""
    out = []
    for run_json in sorted((Path(data_root) / "runs").glob("*/run.json")):
        if json.loads(run_json.read_text(encoding="utf-8")).get("query_id") != query_id:
            continue
        for p in sorted((run_json.parent / "pools").glob("*.json")):
            out.append(RetrievalPool.model_validate_json(p.read_text(encoding="utf-8")))
    return out


def propose(query_id: str, query: str, search_hits: list[Passage], pools: list[RetrievalPool]) -> str:
    """YAML for a person: one entry per candidate passage, keep: false by default."""
    seen: dict[str, tuple[Passage, set[str]]] = {}
    for p in search_hits:
        seen.setdefault(p.chunk_id, (p, set()))[1].add("search")
    for pool in pools:
        for p in pool.passages():
            seen.setdefault(p.chunk_id, (p, set()))[1].add("run pool")
    rank = {p.chunk_id: i for i, p in enumerate(search_hits)}
    ordered = sorted(seen.values(), key=lambda t: (rank.get(t[0].chunk_id, len(rank)), t[0].chunk_id))
    entries = [{"chunk_id": p.chunk_id, "keep": False, "found_by": sorted(src),
                "text": " ".join(p.chunk.text.split())[:400]} for p, src in ordered]
    header = (f"# Gold-passage candidates for {query_id}: {query}\n"
              "# Set keep: true on every passage a good report on this question needs, then run:\n"
              f"#   uv run tcv gold confirm --query {query_id} --by <your-name>\n")
    return header + yaml.safe_dump({"query_id": query_id, "candidates": entries}, sort_keys=False,
                                   allow_unicode=True, width=110)


def confirm(candidates_file: str | Path, by: str) -> dict:
    data = yaml.safe_load(Path(candidates_file).read_text(encoding="utf-8"))
    kept = [c["chunk_id"] for c in data["candidates"] if c.get("keep") is True]
    if not kept:
        raise ValueError("no candidate is marked keep: true")
    return {"query_id": data["query_id"], "confirmed_by": by, "confirmed_on": date.today().isoformat(),
            "chunks": kept}


def load_gold(query_id: str, root: str | Path = "configs/gold") -> list[str]:
    p = gold_path(query_id, root)
    if not p.exists():
        raise FileNotFoundError(f"no gold passages for {query_id}: create them with `tcv gold propose/confirm`")
    return list(yaml.safe_load(p.read_text(encoding="utf-8"))["chunks"])
