"""The run loop (architecture §5.5, §12).

    plan → research → draft → [check → revise] × up to N rounds

Stops as soon as one of these holds, checked after each round's check:
  * ``resolved``     — no failing verdicts;
  * ``budget``       — the run's spending cap is reached (FR-11.3);
  * ``max_rounds``   — round N has been checked (FR-11.1).

Every round is persisted before the next begins (FR-11.4, I-6). A provider
failure (e.g. quota) propagates with the run left *incomplete* — no stop
reason — so re-running it replays every finished call from the response
cache and continues where it stopped.

A round in which any check *failed* (verdict ``error``: the model call broke,
not the claim) also leaves the run incomplete, via ``RunIncomplete``. Letting
it finish would bake unchecked claims into a "complete" result that a sweep
then skips forever; stopping means the next attempt re-sends only the failed
checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tcv.agents.planner import Planner
from tcv.agents.researcher import Researcher
from tcv.agents.synthesizer import Synthesizer, assert_untouched
from tcv.checker.pipeline import Checker
from tcv.config import LoopConfig
from tcv.llm.gateway import BudgetExceeded, Gateway
from tcv.orchestrator.report import final_report, render_report_md
from tcv.orchestrator.state import StateStore
from tcv.schemas import Draft, RetrievalPool, RoundState, RunState, SubTask, VerdictKind


class RunIncomplete(RuntimeError):
    """The run stopped early and should be resumed later (state is saved)."""


@dataclass(frozen=True)
class RunMeta:
    run_id: str
    query_id: str
    query: str
    condition: str
    config_hash: str
    corpus_version: str
    seed: int = 0


@dataclass
class RunNotes:
    """Diagnostics that do not belong in the frozen run schema, written to notes.json."""

    draft_calls: list[str] = field(default_factory=list)
    uncited_after_retries: list[str] = field(default_factory=list)
    malformed_citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    revisions: list[dict] = field(default_factory=list)
    atomizer_fallbacks: list[str] = field(default_factory=list)


def _flag_citations(pools: dict[str, RetrievalPool], draft: Draft) -> dict[str, RetrievalPool]:
    cited = draft.cited_chunks()
    return {sid: pool.with_citations(cited) for sid, pool in pools.items()}


class Orchestrator:
    def __init__(self, planner: Planner, researcher: Researcher, synthesizer: Synthesizer, checker: Checker,
                 gateway: Gateway, store: StateStore, config: LoopConfig):
        self.planner, self.researcher, self.synthesizer, self.checker = planner, researcher, synthesizer, checker
        self.gateway, self.store, self.config = gateway, store, config

    def run(self, meta: RunMeta) -> RunState:
        notes = RunNotes()
        state = RunState(run_id=meta.run_id, query_id=meta.query_id, condition=meta.condition,
                         config_hash=meta.config_hash, corpus_version=meta.corpus_version, seed=meta.seed,
                         subtasks=(), pools=())
        rounds: list[RoundState] = []
        subtasks: tuple[SubTask, ...] = ()
        pools: dict[str, RetrievalPool] = {}
        stop: str | None = None
        try:
            subtasks = self.planner.plan(meta.query)
            pools = self.researcher.research(subtasks)
            for pool in pools.values():
                self.store.save_pool(pool)

            dr = self.synthesizer.draft(meta.query, subtasks, pools)
            notes.draft_calls = dr.call_ids
            notes.uncited_after_retries = dr.uncited_factual
            notes.malformed_citations += dr.malformed_citations
            notes.unknown_citations += dr.unknown_citations
            draft = dr.draft
            pools = _flag_citations(pools, draft)

            prior: RoundState | None = None
            for r in range(1, self.config.max_rounds + 1):
                result = self.checker.check(draft, pools, prior)
                notes.atomizer_fallbacks += list(result.atomizer_fallbacks)
                errored = [v for v in result.verdicts if v.kind is VerdictKind.ERROR]
                if errored:
                    self.store.save_round(RoundState(round=r, draft=draft, claims=result.claims,
                                                     verdicts=result.verdicts, payload=result.payload,
                                                     usage=result.usage))
                    self._save(state, subtasks, pools, rounds, None, notes)
                    raise RunIncomplete(f"round {r}: {len(errored)} claim check(s) failed "
                                        f"(e.g. {errored[0].rationale[:120]})")
                failing = [v for v in result.verdicts if v.is_failure]
                if not failing:
                    stop = "resolved"
                elif self.gateway.budget_exceeded:
                    stop = "budget"
                elif r == self.config.max_rounds:
                    stop = "max_rounds"
                rs = RoundState(round=r, draft=draft, claims=result.claims, verdicts=result.verdicts,
                                payload=None if stop else result.payload, usage=result.usage)
                rounds.append(rs)
                self.store.save_round(rs)
                self._save(state, subtasks, pools, rounds, None, notes)
                if stop:
                    break

                rev = self.synthesizer.revise(meta.query, draft, result.payload, pools, subtasks)
                assert_untouched(draft, rev.draft, result.payload)
                notes.revisions.append({"round": r, "call_id": rev.call_id, "replaced": rev.replaced,
                                        "ignored": rev.ignored, "skipped": rev.skipped})
                notes.malformed_citations += rev.malformed_citations
                notes.unknown_citations += rev.unknown_citations
                draft = rev.draft
                pools = _flag_citations(pools, draft)
                prior = rs
        except BudgetExceeded:
            stop = "budget"

        final = self._save(state, subtasks, pools, rounds, stop, notes)
        if rounds:
            report = final_report(final, rounds[-1])
            self.store.write_text("final.json", report.model_dump_json(indent=1))
            self.store.write_text("report.md", render_report_md(meta.query, final, rounds[-1], report))
        return final

    def _save(self, state: RunState, subtasks, pools, rounds, stop, notes: RunNotes) -> RunState:
        run = state.model_copy(update={
            "subtasks": tuple(subtasks), "pools": tuple(pools[k] for k in sorted(pools)), "rounds": tuple(rounds),
            "stop_reason": stop, "total_usage": self.gateway.spent,  # planning, drafting and revising included
        })
        self.store.save_run(run)
        self.store.write_json("notes.json", notes.__dict__)
        return run

