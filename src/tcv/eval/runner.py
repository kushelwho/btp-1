"""Planted-error sweeps (ER-8): base drafts × seeds × conditions, from one YAML file.

Per (condition, base draft):
  1. a **clean pass** — the checker over the verified base draft (→ FPR);
  2. one **planted pass** per seed — the checker over the corrupted draft,
     with the clean pass as ``prior``: untouched sentences are identical, so
     their claims and verdicts carry over and only the planted sentences cost
     model calls.

A single checking pass, never the full loop (architecture §11.1): this
isolates checker quality from revision behaviour.

Every finished pass is saved and skipped on the next run, so a sweep stopped
by quota resumes where it left off. A pass with a failed check is *not*
saved — it is re-run next time rather than scored with holes in it.
Conditions are config files, so adding one needs no code (ER-8).

    data/seeded/<generator_version>/<base>/<seed>.json        SeededDraft
    data/results/<sweep>/<condition>/<base>/clean.json        CheckResult
    data/results/<sweep>/<condition>/<base>/seed<N>.json      CheckResult
    data/results/<sweep>/metrics.json, report.md, calls.jsonl
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from tcv.checker.pipeline import Checker, CheckResult
from tcv.eval import seed as S
from tcv.eval.base import BaseDraftStore
from tcv.eval.metrics import PassScore, aggregate, render_markdown, score_clean, score_planted, to_json
from tcv.llm.gateway import GatewayError
from tcv.llm.provider import QuotaExhausted
from tcv.schemas import ErrorClass, RoundState, SeededDraft, VerdictKind


class SweepConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    base_drafts: list[str]
    seeds: list[int]
    conditions: list[str]  # letters or condition file paths
    classes: list[ErrorClass] = list(S.RULE_BASED)
    max_errors: int = 8
    e9_pairs: str | None = None
    require_verified: bool = True


def load_sweep(path: str | Path) -> SweepConfig:
    return SweepConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def _save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _has_errors(r: CheckResult) -> int:
    return sum(v.kind is VerdictKind.ERROR for v in r.verdicts)


@dataclass
class SweepProgress:
    done: int = 0
    skipped: int = 0  # already finished on an earlier run
    incomplete: list[str] = field(default_factory=list)  # passes with failed checks — re-run next time
    unverified: list[str] = field(default_factory=list)
    stopped: str | None = None  # quota exhausted, etc.


class Sweep:
    def __init__(self, cfg: SweepConfig, data_root: str | Path):
        self.cfg = cfg
        self.data = Path(data_root)
        self.root = self.data / "results" / cfg.name
        self.bases = BaseDraftStore(data_root)

    def _pass_path(self, condition: str, base_id: str, seed: int | None) -> Path:
        return self.root / condition / base_id / ("clean.json" if seed is None else f"seed{seed}.json")

    def seeded(self, base_id: str, seed: int) -> SeededDraft:
        path = self.data / "seeded" / S.GENERATOR_VERSION / base_id / f"{seed}.json"
        if path.exists():
            return SeededDraft.model_validate_json(path.read_text(encoding="utf-8"))
        rep = S.inject(self.bases.load(base_id), seed=seed, classes=self.cfg.classes, max_errors=self.cfg.max_errors,
                       e9_pairs=S.load_e9_pairs(self.cfg.e9_pairs) if self.cfg.e9_pairs else None)
        _save(path, rep.seeded.model_dump_json(indent=1))
        _save(path.with_suffix(".notes.json"), json.dumps({"notes": rep.notes,
                                                           "not_applicable": [c.value for c in rep.not_applicable]},
                                                          indent=1))
        return rep.seeded

    def run(self, checker_for: Callable[[str], tuple[str, Checker]], log: Callable[[str], None] = print) -> SweepProgress:
        """``checker_for(condition)`` → (condition label, Checker built from that condition's config)."""
        prog = SweepProgress()
        for cond in self.cfg.conditions:
            label, checker = checker_for(cond)
            for base_id in self.cfg.base_drafts:
                base = self.bases.load(base_id)
                if not base.verified:
                    prog.unverified.append(base_id)
                    if self.cfg.require_verified:
                        log(f"skip {base_id}: unverified (set require_verified: false for a development sweep)")
                        continue
                pools = base.pool_map()
                try:
                    clean = self._pass(label, base_id, None, lambda: checker.check(base.draft, pools), prog, log)
                    if clean is None:
                        continue  # planted passes need a complete clean pass to carry over from
                    prior = RoundState(round=base.draft.round, draft=base.draft, claims=clean.claims,
                                       verdicts=clean.verdicts)
                    for seed in self.cfg.seeds:
                        sd = self.seeded(base_id, seed)
                        self._pass(label, base_id, seed, lambda sd=sd: checker.check(sd.draft, pools, prior), prog, log)
                except GatewayError as e:
                    if isinstance(e.__cause__, QuotaExhausted):
                        prog.stopped = str(e.__cause__)
                        log(f"stopping: {prog.stopped}")
                        return prog
                    raise
        return prog

    def _pass(self, label, base_id, seed, run: Callable[[], CheckResult], prog: SweepProgress, log) -> CheckResult | None:
        path = self._pass_path(label, base_id, seed)
        name = f"{label}/{base_id}/{'clean' if seed is None else f'seed{seed}'}"
        if path.exists():
            prog.skipped += 1
            return CheckResult.model_validate_json(path.read_text(encoding="utf-8"))
        result = run()
        if n := _has_errors(result):
            prog.incomplete.append(name)
            log(f"{name}: {n} failed check(s) — not saved, re-run later")
            return None
        _save(path, result.model_dump_json())
        prog.done += 1
        fails = sum(v.is_failure for v in result.verdicts)
        log(f"{name}: {len(result.verdicts)} claims ({len(result.rechecked_sentences)} sentences checked), "
            f"{fails} failing, ${result.usage.cost_usd:.4f}")
        return result

    # -- scoring

    def scores(self) -> list[PassScore]:
        out = []
        if not self.root.exists():
            return out
        for cond_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for base_dir in sorted(p for p in cond_dir.iterdir() if p.is_dir()):
                for f in sorted(base_dir.glob("*.json")):
                    r = CheckResult.model_validate_json(f.read_text(encoding="utf-8"))
                    if f.stem == "clean":
                        out.append(score_clean(cond_dir.name, base_dir.name, r.claims, r.verdicts,
                                               cost_usd=r.usage.cost_usd, n_calls=r.usage.n_calls))
                    else:
                        sd = self.seeded(base_dir.name, int(f.stem.removeprefix("seed")))
                        out.append(score_planted(cond_dir.name, sd, r.verdicts, cost_usd=r.usage.cost_usd,
                                                 n_calls=r.usage.n_calls))
        return out

    def report(self, n_boot: int = 2000) -> tuple[Path, Path]:
        reports = aggregate(self.scores(), n_boot=n_boot)
        unverified = [b for b in self.cfg.base_drafts if not self.bases.load(b).verified]
        header = [f"# Planted-error sweep: {self.cfg.name}", "",
                  f"Base drafts: {', '.join(self.cfg.base_drafts)} · seeds {self.cfg.seeds} · "
                  f"generator `{S.GENERATOR_VERSION}`", ""]
        if unverified:
            header += [f"> ⚠ **Development numbers only** — unverified base drafts: {', '.join(unverified)}. "
                       "A flag on an untouched sentence may be a real error, not a false alarm.", ""]
        md = "\n".join(header) + render_markdown(reports)
        _save(self.root / "metrics.json", json.dumps(to_json(reports), indent=1))
        _save(self.root / "report.md", md)
        return self.root / "metrics.json", self.root / "report.md"
