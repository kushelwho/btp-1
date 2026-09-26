"""Checker step A — sentences into claims, wording strength kept (FR-5).

Every sentence yields at least one claim. Deciding that "We now turn to
evaluation" needs no check is the router's job from condition B on; an
atomizer that silently dropped such sentences would make the condition-A
baseline look better than standard checking really is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from tcv.checker.lexicon import modality as lexical_modality
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import Claim, Modality, Sentence
from tcv.schemas.ids import claim_id


class AtomizedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    surface: str
    modality: Modality


class SentenceClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[AtomizedClaim]


@dataclass
class AtomizeResult:
    claims: list[Claim]
    fallback_sentences: list[str] = field(default_factory=list)  # atomizer failed → whole sentence is one claim


def atomize(gateway: Gateway, prompt: Prompt, sentences: Sequence[Sentence], round_: int,
            batch_size: int = 15, start_index: int = 0) -> AtomizeResult:
    """Claims for ``sentences``, numbered ``r<round>c<n>`` from ``start_index``.

    Each claim inherits its sentence's citations. If the model fails on a
    sentence (or returns nothing for it), the sentence itself becomes the
    claim, with modality read by the lexicon — degraded, never dropped.
    """
    if not sentences:
        return AtomizeResult(claims=[])
    items = [{"sentence_id": s.sentence_id, "section": s.section, "text": s.text} for s in sentences]
    results = gateway.call_batch("economy", prompt, items, SentenceClaims, per_request=batch_size)

    claims: list[Claim] = []
    fallback: list[str] = []
    n = start_index
    for s, r in zip(sentences, results):
        got = [c for c in (r.value.claims if r.ok else []) if c.text.strip()]
        if not got:
            fallback.append(s.sentence_id)
            got = [AtomizedClaim(text=s.text, surface=s.text, modality=lexical_modality(s.text))]
        for c in got:
            claims.append(Claim(
                claim_id=claim_id(round_, n), sentence_id=s.sentence_id,
                text=c.text.strip(), surface=c.surface.strip() or c.text.strip(), modality=c.modality,
                citations=tuple(cit.chunk_id for cit in s.citations),
            ))
            n += 1
    return AtomizeResult(claims=claims, fallback_sentences=fallback)
