"""Claims: what the Checker verifies.

Every field used by the later mechanisms (modality, atoms, aggregate specs)
exists from the start, even where the core scope does not populate it yet.
Adding a field to a schema several components already build against is the
most expensive change available.
"""

from enum import StrEnum

from pydantic import model_validator

from ._base import Schema
from .ids import AtomId, ChunkId, ClaimId, SentenceId


class ClaimType(StrEnum):
    T1_DIRECT = "T1"  # one passage can settle it
    T2_AGGREGATIVE = "T2"  # truth ranges over a set of passages
    T3_INFERENTIAL = "T3"  # reasoned extension beyond the evidence
    T4_DISCOURSE = "T4"  # structural scaffolding, not a factual claim


class Modality(StrEnum):
    """How strongly a claim is worded. Kept through atomization, never stripped."""

    NONE = "none"  # no modal marker — a bare assertion
    SUGGESTS = "suggests"
    INDICATES = "indicates"
    SHOWS = "shows"
    DEMONSTRATES = "demonstrates"
    PROVES = "proves"

    @property
    def rank(self) -> int:
        # A bare assertion reads roughly as strongly as "shows".
        return {
            "suggests": 1,
            "indicates": 2,
            "shows": 3,
            "none": 3,
            "demonstrates": 4,
            "proves": 5,
        }[self.value]


class Operator(StrEnum):
    """Aggregation operators for aggregative (T2) claims."""

    COUNT = "count"  # "three of five X do Y"
    PROPORTION = "proportion"  # "most X do Y"
    UNIVERSAL = "universal"  # "all X", "consistently", "never"
    EXISTENTIAL = "existential"  # "at least one X", "only one X"
    COMPARISON = "comparison"  # "X outperforms Y"
    CONTRAST = "contrast"  # "unlike X, Y does Z"
    TREND = "trend"  # "from 2023 to 2026, X increased"
    UNSUPPORTED = "unsupported"  # aggregative, but operator not recognised


class Atom(Schema):
    """One constituent fact of an aggregative claim."""

    atom_id: AtomId
    subject: str  # "GSAR"
    predicate: str  # "bounds its correction loop"
    text: str  # "GSAR bounds its correction loop"
    citation: ChunkId | None = None
    value: float | None = None  # for COMPARISON / TREND
    unit: str | None = None  # comparisons across different units are undecidable
    time_key: str | None = None  # for TREND: "2023", "2024-Q2", ...


class AggregateSpec(Schema):
    """What an aggregative claim asserts about its atoms."""

    operator: Operator
    domain: tuple[str, ...]  # the population, e.g. ("GSAR", "MARCH", "Tool-MAD")
    claimed_count: int | None = None  # COUNT
    claimed_proportion: str | None = None  # PROPORTION: "most", "few", "half", ...
    polarity: bool = True  # UNIVERSAL: all-hold (True) vs none-hold (False)
    direction: str | None = None  # COMPARISON: gt/lt/ge/le · TREND: increasing/decreasing
    contrast_subject: str | None = None  # CONTRAST: the X in "unlike X"

    @model_validator(mode="after")
    def _fields_match_operator(self) -> "AggregateSpec":
        op = self.operator
        if op is Operator.COUNT and self.claimed_count is None:
            raise ValueError("COUNT requires claimed_count")
        if op is Operator.PROPORTION and not self.claimed_proportion:
            raise ValueError("PROPORTION requires claimed_proportion")
        if op is Operator.COMPARISON and self.direction not in {"gt", "lt", "ge", "le"}:
            raise ValueError("COMPARISON requires direction in gt/lt/ge/le")
        if op is Operator.TREND and self.direction not in {"increasing", "decreasing"}:
            raise ValueError("TREND requires direction increasing/decreasing")
        if op is Operator.CONTRAST and not self.contrast_subject:
            raise ValueError("CONTRAST requires contrast_subject")
        return self


class Claim(Schema):
    claim_id: ClaimId
    sentence_id: SentenceId
    text: str  # normalised proposition
    surface: str  # original wording, modality intact
    modality: Modality = Modality.NONE
    citations: tuple[ChunkId, ...] = ()
    ctype: ClaimType | None = None  # set by the router
    route_confidence: float | None = None
    route_source: str | None = None  # "lexical" | "model" | "default"
    atoms: tuple[Atom, ...] = ()  # set by aggregative decomposition
    aggregate: AggregateSpec | None = None

    @model_validator(mode="after")
    def _aggregate_only_on_t2(self) -> "Claim":
        if self.aggregate is not None and self.ctype is not ClaimType.T2_AGGREGATIVE:
            raise ValueError("aggregate spec is only valid on T2 claims")
        if self.route_source not in {None, "lexical", "model", "default"}:
            raise ValueError(f"unknown route_source {self.route_source!r}")
        return self
