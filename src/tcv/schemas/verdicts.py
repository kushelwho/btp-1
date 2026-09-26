"""Verdicts: what the Checker decided about each claim, and why."""

from enum import StrEnum

from pydantic import model_validator

from ._base import Schema
from .claims import Modality
from .ids import ChunkId, ClaimId, SentenceId


class VerdictKind(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    MISATTRIBUTED = "misattributed"  # true fact, wrong citation
    PARTIALLY_SUPPORTED = "partially_supported"  # atoms hold, aggregate fails
    COUNTEREXAMPLE_FOUND = "counterexample_found"  # uncited passage disproves it
    INTERNALLY_INCONSISTENT = "internally_inconsistent"  # contradicts another claim
    OVERCLAIM = "overclaim"  # worded more strongly than the evidence allows
    INFERENCE_RETAINED = "inference_retained"  # T3 that nothing contradicts
    EXEMPT = "exempt"  # T4, deliberately not checked
    UNCERTAIN = "uncertain"  # checker abstained
    ERROR = "error"  # the check itself failed (e.g. API error)


PASSING = frozenset({VerdictKind.SUPPORTED, VerdictKind.EXEMPT, VerdictKind.INFERENCE_RETAINED})


class RepairHint(Schema):
    """Machine-readable instruction for the Synthesizer.

    At most one repair *kind* is set. ``observed``/``claimed`` belong together
    (aggregate mismatch); ``note`` may accompany any kind.
    """

    swap_citation_to: ChunkId | None = None  # MISATTRIBUTED
    observed: str | None = None  # PARTIALLY_SUPPORTED, e.g. "2"
    claimed: str | None = None  #                     e.g. "3"
    counterexample: ChunkId | None = None  # COUNTEREXAMPLE_FOUND
    conflicts_with: SentenceId | None = None  # INTERNALLY_INCONSISTENT
    downgrade_to: Modality | None = None  # OVERCLAIM
    note: str | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> "RepairHint":
        if (self.observed is None) != (self.claimed is None):
            raise ValueError("observed and claimed must be set together")
        kinds = [
            self.swap_citation_to is not None,
            self.observed is not None,
            self.counterexample is not None,
            self.conflicts_with is not None,
            self.downgrade_to is not None,
        ]
        if sum(kinds) > 1:
            raise ValueError("a repair hint may carry only one repair kind")
        if sum(kinds) == 0 and self.note is None:
            raise ValueError("empty repair hint")
        return self


class Verdict(Schema):
    claim_id: ClaimId
    sentence_id: SentenceId
    kind: VerdictKind
    step: str  # "C.T1", "C.T2.compose", "C.T2.sweep", "D", "E", ...
    evidence: tuple[ChunkId, ...] = ()  # passages the decision rested on
    rationale: str  # model's short reason, or an operator trace
    confidence: float | None = None
    hint: RepairHint | None = None
    call_ids: tuple[str, ...] = ()  # ledger IDs — every verdict is traceable to its calls

    @property
    def is_failure(self) -> bool:
        return self.kind not in PASSING
