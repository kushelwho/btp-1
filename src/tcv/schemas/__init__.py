"""Every type that crosses a component boundary.

Frozen at the end of Phase 1. After that, a change requires: editing
architecture.md, bumping SCHEMA_VERSION, and noting it in checklist.md.
"""

from ._base import Schema
from .claims import AggregateSpec, Atom, Claim, ClaimType, Modality, Operator
from .corpus import Chunk, CorpusManifest, Document
from .draft import Citation, Draft, Sentence
from .eval import ErrorClass, GoldLabel, SeededDraft, SeededError
from .payload import RevisionItem, RevisionPayload
from .retrieval import Passage, PoolEntry, RetrievalPool, SubTask
from .run import (
    Escalation,
    EscalationKind,
    FinalReport,
    RoundState,
    RunState,
    Usage,
)
from .verdicts import PASSING, RepairHint, Verdict, VerdictKind

SCHEMA_VERSION = "1.0"

__all__ = [
    "SCHEMA_VERSION",
    "PASSING",
    "AggregateSpec",
    "Atom",
    "Chunk",
    "Citation",
    "Claim",
    "ClaimType",
    "CorpusManifest",
    "Document",
    "Draft",
    "ErrorClass",
    "Escalation",
    "EscalationKind",
    "FinalReport",
    "GoldLabel",
    "Modality",
    "Operator",
    "Passage",
    "PoolEntry",
    "RepairHint",
    "RetrievalPool",
    "RevisionItem",
    "RevisionPayload",
    "RoundState",
    "RunState",
    "Schema",
    "SeededDraft",
    "SeededError",
    "Sentence",
    "SubTask",
    "Usage",
    "Verdict",
    "VerdictKind",
]
