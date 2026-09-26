"""Run state: everything needed to replay a run offline."""

from enum import StrEnum

from ._base import Schema
from .claims import Claim
from .draft import Draft
from .ids import RunId, SentenceId
from .payload import RevisionPayload
from .retrieval import RetrievalPool, SubTask
from .verdicts import Verdict


class Usage(Schema):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    wall_seconds: float = 0.0
    n_calls: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            wall_seconds=self.wall_seconds + other.wall_seconds,
            n_calls=self.n_calls + other.n_calls,
        )


class RoundState(Schema):
    """Complete state of one round, persisted verbatim."""

    round: int
    draft: Draft
    claims: tuple[Claim, ...]
    verdicts: tuple[Verdict, ...]
    payload: RevisionPayload | None = None  # None on the final round
    usage: Usage = Usage()
    newly_failed_clean: tuple[SentenceId, ...] = ()  # error displacement


class EscalationKind(StrEnum):
    NO_SUPPORT = "no_support"
    AGGREGATION = "aggregation"
    COUNTEREXAMPLE = "counterexample"
    INCONSISTENT = "inconsistent"
    OVERCLAIM = "overclaim"
    INFERENCE = "inference"


ESCALATION_TEXT = {
    EscalationKind.NO_SUPPORT: "unverified — no supporting passage",
    EscalationKind.AGGREGATION: "unverified — aggregation not confirmed",
    EscalationKind.COUNTEREXAMPLE: "unverified — counterexample found",
    EscalationKind.INCONSISTENT: "inconsistent with {section}",
    EscalationKind.OVERCLAIM: "overclaim — evidence weaker than stated",
    EscalationKind.INFERENCE: "inference — not directly evidenced",
}


class Escalation(Schema):
    kind: EscalationKind
    section: str | None = None  # only for INCONSISTENT

    def render(self) -> str:
        return ESCALATION_TEXT[self.kind].format(section=self.section or "another section")


class RunState(Schema):
    run_id: RunId
    query_id: str
    condition: str  # "A".."F", "zeroshot", "debate"
    config_hash: str
    corpus_version: str
    seed: int
    subtasks: tuple[SubTask, ...]
    pools: tuple[RetrievalPool, ...]
    rounds: tuple[RoundState, ...] = ()
    stop_reason: str | None = None  # "resolved" | "max_rounds" | "budget"
    total_usage: Usage = Usage()


class FinalReport(Schema):
    run_id: RunId
    draft: Draft
    labels: dict[SentenceId, Escalation] = {}
    evidence_concentration: float | None = None
