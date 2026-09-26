"""Checker step C, T1 path — each claim against only the passages it cites.

Blind to the rest of the draft (FR-7.1, adopted from MARCH). Judges content,
not wording strength (that is condition F). Below the confidence threshold
the verdict is UNCERTAIN rather than a guess (FR-7.9). A failed model call
marks its claims ERROR and the run continues (NFR-4.1).

Misattribution — re-checking a failed claim against the whole pool — is
condition C and not part of this module yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import Claim, Passage, Verdict, VerdictKind

STEP = "C.T1"


class T1Judgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["supported", "contradicted", "unsupported"]
    confidence: float
    evidence: list[str]
    rationale: str


_KIND = {"supported": VerdictKind.SUPPORTED, "contradicted": VerdictKind.CONTRADICTED,
         "unsupported": VerdictKind.UNSUPPORTED}


def verify_t1(gateway: Gateway, prompt: Prompt, claims: Sequence[Claim], passages: Mapping[str, Passage],
              batch_size: int = 15, uncertain_below: float = 0.55) -> list[Verdict]:
    """One verdict per claim, in input order. ``passages`` maps chunk_id → Passage (all pools)."""
    verdicts: list[Verdict | None] = [None] * len(claims)
    to_check: list[int] = []
    items = []
    for i, c in enumerate(claims):
        shown = [passages[cid] for cid in c.citations if cid in passages]
        if not c.citations:
            verdicts[i] = Verdict(claim_id=c.claim_id, sentence_id=c.sentence_id, kind=VerdictKind.UNSUPPORTED,
                                  step=STEP, rationale="no citation")
        elif not shown:
            verdicts[i] = Verdict(claim_id=c.claim_id, sentence_id=c.sentence_id, kind=VerdictKind.UNSUPPORTED,
                                  step=STEP, rationale="cited passages are not in the evidence pool")
        else:
            to_check.append(i)
            items.append({"claim_id": c.claim_id, "claim": c.text,
                          "passages": [{"chunk_id": p.chunk_id, "text": p.chunk.text} for p in shown]})

    results = gateway.call_batch("judge", prompt, items, T1Judgement, per_request=batch_size) if items else []
    for i, r in zip(to_check, results):
        c = claims[i]
        call_ids = (r.call_id,) if r.call_id else ()
        if not r.ok:
            verdicts[i] = Verdict(claim_id=c.claim_id, sentence_id=c.sentence_id, kind=VerdictKind.ERROR, step=STEP,
                                  rationale=f"check failed: {r.error}"[:500], call_ids=call_ids)
            continue
        j = r.value
        cited = set(c.citations)
        evidence = tuple(dict.fromkeys(e for e in j.evidence if e in cited))
        confidence = min(max(j.confidence, 0.0), 1.0)
        kind = _KIND[j.label] if confidence >= uncertain_below else VerdictKind.UNCERTAIN
        rationale = j.rationale.strip() or j.label
        if kind is VerdictKind.UNCERTAIN:
            rationale = f"abstained (model said {j.label} at confidence {confidence:.2f}): {rationale}"
        verdicts[i] = Verdict(claim_id=c.claim_id, sentence_id=c.sentence_id, kind=kind, step=STEP,
                              evidence=evidence, rationale=rationale, confidence=confidence, call_ids=call_ids)
    return verdicts  # type: ignore[return-value]
