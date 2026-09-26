"""The Checker: steps A–F as enabled by ``CheckerConfig`` (architecture §6).

Built so far — condition A: atomize (A) and the T1 check (C) on every claim.
Every other flag exists in the config, and switching one on before its
mechanism is built fails at construction: a flag that silently did nothing
would make an ablation row measure the wrong thing.

Across rounds, a sentence the Synthesizer did not rewrite is byte-identical
(enforced by ``assert_untouched``), so its claims and verdicts carry over
instead of being re-checked. Only new or changed sentences are atomized and
checked. The same mechanism lets a planted-error draft reuse its clean
draft's pass: only the corrupted sentences cost model calls.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from tcv.checker.atomize import atomize
from tcv.checker.verify_t1 import verify_t1
from tcv.config import CheckerConfig
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import (
    Claim,
    ClaimType,
    Draft,
    Passage,
    RetrievalPool,
    RevisionItem,
    RevisionPayload,
    RoundState,
    Usage,
    Verdict,
    VerdictKind,
)
from tcv.schemas._base import Schema

IMPLEMENTED_FLAGS: frozenset[str] = frozenset()  # condition A needs none
_CLAIM_NUM = re.compile(r"^r(\d+)c(\d{4})$")

_INSTRUCTION = {
    VerdictKind.UNSUPPORTED: ("The cited passages do not support this claim. Reword it to say only what they "
                              "support, cite a passage that does support it, or delete it."),
    VerdictKind.CONTRADICTED: "The cited passages contradict this claim. Correct it to agree with them, or delete it.",
    VerdictKind.UNCERTAIN: ("The checker could not confirm this claim from the cited passages. Make the claim "
                            "match what they say plainly, or cite a passage that states it directly."),
}
_NO_CITATION = "This claim has no citation. Add a citation to a passage that supports it, or delete it."


class CheckResult(Schema):
    claims: tuple[Claim, ...]
    verdicts: tuple[Verdict, ...]
    payload: RevisionPayload
    usage: Usage
    rechecked_sentences: tuple[str, ...] = ()  # sentences atomized and checked this round
    atomizer_fallbacks: tuple[str, ...] = ()


class UnbuiltMechanism(NotImplementedError):
    pass


class Checker:
    def __init__(self, gateway: Gateway, config: CheckerConfig, atomize_prompt: Prompt, t1_prompt: Prompt):
        unbuilt = config.enabled_flags() - IMPLEMENTED_FLAGS
        if unbuilt:
            raise UnbuiltMechanism(f"checker flags not built yet: {sorted(unbuilt)}")
        self._gateway = gateway
        self._config = config
        self._atomize_prompt = atomize_prompt
        self._t1_prompt = t1_prompt

    def check(self, draft: Draft, pools: Mapping[str, RetrievalPool], prior: RoundState | None = None) -> CheckResult:
        spent_before = self._gateway.spent
        passages: dict[str, Passage] = {}
        for pool in pools.values():
            for p in pool.passages():
                passages.setdefault(p.chunk_id, p)

        carried_claims: list[Claim] = []
        carried_verdicts: dict[str, Verdict] = {}
        if prior is not None:
            # Carry over only sentences that are *identical* (id, text, citations, section),
            # never merely same-ID: a planted error keeps its sentence's ID.
            prior_sentences = {s.sentence_id: s for s in prior.draft.sentences}
            unchanged = {s.sentence_id for s in draft.sentences if prior_sentences.get(s.sentence_id) == s}
            prior_verdicts = {v.claim_id: v for v in prior.verdicts}
            for c in prior.claims:
                if c.sentence_id in unchanged and c.claim_id in prior_verdicts:
                    carried_claims.append(c)
                    carried_verdicts[c.claim_id] = prior_verdicts[c.claim_id]
        done = {c.sentence_id for c in carried_claims}
        fresh = [s for s in draft.sentences if s.sentence_id not in done]

        # A — atomize new sentences; number new claims after any carried-over claim of this round
        same_round = [int(m[2]) for c in carried_claims if (m := _CLAIM_NUM.match(c.claim_id))
                      and int(m[1]) == draft.round]
        at = atomize(self._gateway, self._atomize_prompt, fresh, round_=draft.round,
                     batch_size=self._config.atomize_batch_size, start_index=max(same_round, default=-1) + 1)
        # B — routing is condition B; in condition A every claim is T1
        new_claims = [c.model_copy(update={"ctype": ClaimType.T1_DIRECT, "route_source": "default"})
                      for c in at.claims]
        # C — T1 check
        new_verdicts = verify_t1(self._gateway, self._t1_prompt, new_claims, passages,
                                 batch_size=self._config.batch_size,
                                 uncertain_below=self._config.uncertain_below)

        by_sentence_order = {s.sentence_id: i for i, s in enumerate(draft.sentences)}
        claims = sorted([*carried_claims, *new_claims], key=lambda c: (by_sentence_order[c.sentence_id], c.claim_id))
        if len({c.claim_id for c in claims}) != len(claims):
            raise AssertionError("duplicate claim ids after carry-over")  # would silently mix up verdicts
        verdict_of = {**carried_verdicts, **{v.claim_id: v for v in new_verdicts}}
        verdicts = tuple(verdict_of[c.claim_id] for c in claims)

        payload = build_payload(draft.round, claims, verdicts, passages)
        return CheckResult(claims=tuple(claims), verdicts=verdicts, payload=payload,
                           usage=_diff(self._gateway.spent, spent_before),
                           rechecked_sentences=tuple(s.sentence_id for s in fresh),
                           atomizer_fallbacks=tuple(at.fallback_sentences))


def build_payload(round_: int, claims: list[Claim], verdicts: tuple[Verdict, ...],
                  passages: Mapping[str, Passage]) -> RevisionPayload:
    """One item per failing claim. ERROR verdicts are left out: the Synthesizer
    cannot fix a failed check, and asking it to would rewrite a sentence
    nobody found wrong."""
    items = []
    for c, v in zip(claims, verdicts):
        if not v.is_failure or v.kind is VerdictKind.ERROR:
            continue
        instruction = _NO_CITATION if not c.citations else _INSTRUCTION.get(v.kind, "Fix or delete this claim.")
        if c.citations and v.rationale:
            instruction += f" Checker's reason: {v.rationale}"
        items.append(RevisionItem(
            sentence_ids=(c.sentence_id,), claim_text=c.text, ctype=c.ctype or ClaimType.T1_DIRECT, verdict=v.kind,
            passages=tuple(passages[cid] for cid in c.citations if cid in passages), hint=v.hint,
            instruction=instruction))
    return RevisionPayload(round=round_, items=tuple(items))


def _diff(after: Usage, before: Usage) -> Usage:
    return Usage(input_tokens=after.input_tokens - before.input_tokens,
                 output_tokens=after.output_tokens - before.output_tokens,
                 cache_read_tokens=after.cache_read_tokens - before.cache_read_tokens,
                 cache_write_tokens=after.cache_write_tokens - before.cache_write_tokens,
                 cost_usd=after.cost_usd - before.cost_usd,
                 wall_seconds=after.wall_seconds - before.wall_seconds,
                 n_calls=after.n_calls - before.n_calls)
