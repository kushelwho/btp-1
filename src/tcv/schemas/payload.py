"""Revision payload: the Checker's targeted instructions to the Synthesizer."""

from pydantic import model_validator

from ._base import Schema
from .claims import ClaimType
from .ids import SentenceId
from .retrieval import Passage
from .verdicts import RepairHint, VerdictKind


class RevisionItem(Schema):
    sentence_ids: tuple[SentenceId, ...]  # two only for an internal contradiction
    claim_text: str
    ctype: ClaimType
    verdict: VerdictKind
    passages: tuple[Passage, ...]  # every passage involved, both sides of a conflict
    hint: RepairHint | None = None
    instruction: str  # rendered from the hint for the prompt

    @model_validator(mode="after")
    def _arity(self) -> "RevisionItem":
        n = len(self.sentence_ids)
        if self.verdict is VerdictKind.INTERNALLY_INCONSISTENT:
            if n != 2:
                raise ValueError("an internal contradiction names exactly two sentences")
        elif n != 1:
            raise ValueError("a revision item names exactly one sentence")
        return self


class RevisionPayload(Schema):
    """Sentences not named here must come back byte-identical after revision."""

    round: int
    items: tuple[RevisionItem, ...]

    def named_sentences(self) -> set[str]:
        return {sid for item in self.items for sid in item.sentence_ids}
