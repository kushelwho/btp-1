"""Evaluation: seeded errors and human gold labels."""

from enum import StrEnum

from pydantic import model_validator

from ._base import Schema
from .claims import ClaimType
from .draft import Draft
from .ids import ClaimId, SentenceId
from .verdicts import VerdictKind


class ErrorClass(StrEnum):
    E1_NUMERIC = "E1"
    E2_ATTRIBUTION = "E2"
    E3_INSERTION = "E3"
    E4_CONTRADICTION = "E4"
    E5_OVERGENERALIZE = "E5"
    E6_COUNT = "E6"
    E7_FALSE_CONTRAST = "E7"
    E8_TREND = "E8"
    E9_INTERNAL = "E9"
    E10_HEDGE_STRIP = "E10"
    E11_OMISSION = "E11"


class SeededError(Schema):
    """Ground truth for one injected error."""

    error_id: str
    error_class: ErrorClass
    sentence_ids: tuple[SentenceId, ...]  # two for an internal contradiction
    original: str
    corrupted: str
    # Any of these counts as a catch — an off-by-one count is legitimately
    # caught by either PARTIALLY_SUPPORTED or CONTRADICTED.
    expected_verdicts: tuple[VerdictKind, ...]

    @model_validator(mode="after")
    def _arity(self) -> "SeededError":
        want = 2 if self.error_class is ErrorClass.E9_INTERNAL else 1
        if len(self.sentence_ids) != want:
            raise ValueError(f"{self.error_class} names {want} sentence(s)")
        if not self.expected_verdicts:
            raise ValueError("expected_verdicts must not be empty")
        return self


class SeededDraft(Schema):
    base_draft_id: str
    draft: Draft  # the corrupted draft
    errors: tuple[SeededError, ...]
    generator_version: str
    seed: int


class GoldLabel(Schema):
    """One human annotation for router validation."""

    claim_id: ClaimId
    annotator: str  # anonymised: "A1" | "A2"
    ctype: ClaimType
    notes: str = ""
