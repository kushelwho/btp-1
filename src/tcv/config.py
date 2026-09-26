"""Run configuration: a base file plus one overlay per ablation condition.

Conditions differ *only* here (invariant I-7): the Checker reads feature
flags from ``CheckerConfig`` and never asks which condition it is running.
The resolved config is hashed, and the hash is stored with every run, so a
result always traces back to the exact settings that produced it.

    configs/run/base.yaml             retrieval, planner, checker, loop defaults
    configs/conditions/A_baseline.yaml   overlay for condition A
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetrievalConfig(_Cfg):
    k_per_query: int = Field(12, ge=1)
    k_per_subtask: int = Field(12, ge=1)  # pool size per sub-task, after merging queries
    queries_per_subtask: int = Field(3, ge=1, le=6)  # model-written, on top of the sub-task question
    oracle: bool = False  # N9: pools from human-confirmed gold passages instead of search (configs/gold/)


class PlannerConfig(_Cfg):
    min_subtasks: int = Field(5, ge=1)
    max_subtasks: int = Field(8, ge=1)

    @model_validator(mode="after")
    def _range(self) -> "PlannerConfig":
        if self.min_subtasks > self.max_subtasks:
            raise ValueError("min_subtasks > max_subtasks")
        return self


class SynthesizerConfig(_Cfg):
    uncited_retries: int = Field(1, ge=0)  # regenerations when factual sentences come back uncited


class CheckerConfig(_Cfg):
    # Condition flags (architecture §9.2). All off = condition A: every claim is T1.
    route: bool = False  # B
    t4_exempt: bool = False  # B
    t3_defeasible: bool = False  # B
    compose: bool = False  # C
    misattribution: bool = False  # C
    depgraph: bool = False  # C
    sweep: bool = False  # D
    consistency: bool = False  # E
    assertiveness: bool = False  # F
    # Tuning
    batch_size: int = Field(15, ge=1)  # claims per verification call
    atomize_batch_size: int = Field(15, ge=1)  # sentences per atomization call
    uncertain_below: float = Field(0.55, ge=0.0, le=1.0)  # abstain below this confidence (FR-7.9)
    max_pairs: int = 60  # Step E cap
    sweep_max_passages: int = 20

    def enabled_flags(self) -> set[str]:
        return {name for name, v in self.model_dump().items() if v is True}


class LoopConfig(_Cfg):
    max_rounds: int = Field(3, ge=1)


class RunConfig(_Cfg):
    condition: str
    models: str = "configs/models.yaml"  # model roles + budget live there
    retrieval: RetrievalConfig = RetrievalConfig()
    planner: PlannerConfig = PlannerConfig()
    synthesizer: SynthesizerConfig = SynthesizerConfig()
    checker: CheckerConfig = CheckerConfig()
    loop: LoopConfig = LoopConfig()


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_run_config(condition_path: str | Path, base_path: str | Path = "configs/run/base.yaml") -> RunConfig:
    with open(base_path, encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    with open(condition_path, encoding="utf-8") as f:
        overlay = yaml.safe_load(f) or {}
    return RunConfig.model_validate(_merge(base, overlay))


def config_hash(cfg: RunConfig, models_text: str) -> str:
    """Hash of the resolved run config *and* the model config it points at."""
    blob = json.dumps({"run": cfg.model_dump(mode="json"), "models": models_text}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def resolved(cfg: RunConfig) -> dict[str, Any]:
    return cfg.model_dump(mode="json")
