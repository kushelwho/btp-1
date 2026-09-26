"""Loop dynamics (ER-7, N11): what each revision round actually achieved.

For each transition from round r-1 to round r of a finished run:

  payloaded     sentences the fix-list named in round r-1
  resolved      … whose replacement passes every check in round r
  deleted       … the Synthesizer removed (an allowed fix for an unsupportable claim)
  persisting    … whose replacement still fails
  skipped       … the Synthesizer returned nothing for (still present, still failing)
  displaced     sentences that passed in r-1, were NOT named, and fail in r
  marginal_resolution = (resolved + deleted) / payloaded
  displacement        = displaced / sentences passing in r-1

A note on displacement. Unnamed sentences come back byte-identical (enforced),
and under per-claim checks (conditions A–D) their verdicts carry over, so
displacement there is 0 by construction: a rewrite cannot change how an
untouched claim reads against its own passage. It becomes a real
measurement once claims are compared with *each other* (condition E), where
a rewritten sentence can newly contradict an untouched one. Errors a
revision introduces into its own replacement show up as ``persisting``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from tcv.schemas import RunState, VerdictKind


@dataclass
class RoundDynamics:
    round: int
    sentences: int
    claims: int
    failing_sentences: int
    payloaded: int
    resolved: int
    deleted: int
    persisting: int
    skipped: int
    displaced: int
    marginal_resolution: float | None
    displacement: float | None
    check_cost_usd: float
    check_calls: int


def _failing_sentences(round_state) -> set[str]:
    return {v.sentence_id for v in round_state.verdicts if v.is_failure and v.kind is not VerdictKind.ERROR}


def run_dynamics(run: RunState) -> list[RoundDynamics]:
    out: list[RoundDynamics] = []
    prev = None
    for rs in run.rounds:
        failing = _failing_sentences(rs)
        row = RoundDynamics(round=rs.round, sentences=len(rs.draft.sentences), claims=len(rs.claims),
                            failing_sentences=len(failing), payloaded=0, resolved=0, deleted=0, persisting=0,
                            skipped=0, displaced=0, marginal_resolution=None, displacement=None,
                            check_cost_usd=rs.usage.cost_usd, check_calls=rs.usage.n_calls)
        if prev is not None and prev.payload is not None:
            named = prev.payload.named_sentences()
            current_ids = {s.sentence_id for s in rs.draft.sentences}
            replacements: dict[str, list[str]] = {}
            for s in rs.draft.sentences:
                if s.supersedes:
                    replacements.setdefault(s.supersedes, []).append(s.sentence_id)
            for sid in named:
                if sid in current_ids:
                    row.skipped += 1
                elif sid not in replacements:
                    row.deleted += 1
                elif any(r in failing for r in replacements[sid]):
                    row.persisting += 1
                else:
                    row.resolved += 1
            row.payloaded = len(named)
            prev_failing = _failing_sentences(prev)
            prev_passing = {s.sentence_id for s in prev.draft.sentences} - prev_failing
            row.displaced = len({sid for sid in prev_passing - named if sid in failing})
            row.marginal_resolution = (row.resolved + row.deleted) / row.payloaded if row.payloaded else None
            row.displacement = row.displaced / len(prev_passing) if prev_passing else None
        out.append(row)
        prev = rs
    return out


def render_table(run: RunState, rows: list[RoundDynamics]) -> str:
    head = (f"{run.query_id} [{run.run_id}] condition {run.condition}, stop={run.stop_reason}, "
            f"total ${run.total_usage.cost_usd:.4f} / {run.total_usage.n_calls} calls")
    lines = [head, "round  sent  claims  failing  named  resolved  deleted  persist  skipped  displaced  "
                   "marginal  check$"]
    for r in rows:
        mr = f"{r.marginal_resolution:.2f}" if r.marginal_resolution is not None else "   —"
        lines.append(f"{r.round:>5}  {r.sentences:>4}  {r.claims:>6}  {r.failing_sentences:>7}  {r.payloaded:>5}  "
                     f"{r.resolved:>8}  {r.deleted:>7}  {r.persisting:>7}  {r.skipped:>7}  {r.displaced:>9}  "
                     f"{mr:>8}  {r.check_cost_usd:.4f}")
    return "\n".join(lines)


def to_dict(rows: list[RoundDynamics]) -> list[dict]:
    return [asdict(r) for r in rows]
