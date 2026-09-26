"""Final report: escalation labels on what is still unresolved (FR-11.2).

A claim still failing after the last round is not hidden or deleted; its
sentence is published with a label saying *why* it is unverified. When one
sentence has several failing claims, the most serious label wins.

A failed check (ERROR) gets no escalation label — none of the six labels
says "we could not run the check", and calling it "no supporting passage"
would be false. The rendered report marks it separately instead.
"""

from __future__ import annotations

from collections import Counter

from tcv.agents.synthesizer import render_markdown
from tcv.schemas import Escalation, EscalationKind, FinalReport, RoundState, RunState, VerdictKind

_ESCALATE = {
    VerdictKind.UNSUPPORTED: EscalationKind.NO_SUPPORT,
    VerdictKind.CONTRADICTED: EscalationKind.NO_SUPPORT,
    VerdictKind.UNCERTAIN: EscalationKind.NO_SUPPORT,
    VerdictKind.MISATTRIBUTED: EscalationKind.NO_SUPPORT,
    VerdictKind.PARTIALLY_SUPPORTED: EscalationKind.AGGREGATION,
    VerdictKind.COUNTEREXAMPLE_FOUND: EscalationKind.COUNTEREXAMPLE,
    VerdictKind.INTERNALLY_INCONSISTENT: EscalationKind.INCONSISTENT,
    VerdictKind.OVERCLAIM: EscalationKind.OVERCLAIM,
    VerdictKind.INFERENCE_RETAINED: EscalationKind.INFERENCE,
}

# Most serious first.
_SEVERITY = [EscalationKind.INCONSISTENT, EscalationKind.COUNTEREXAMPLE, EscalationKind.AGGREGATION,
             EscalationKind.NO_SUPPORT, EscalationKind.OVERCLAIM, EscalationKind.INFERENCE]

CHECK_FAILED = "not checked — the check itself failed"


def final_report(run: RunState, last: RoundState) -> FinalReport:
    section_of = {s.sentence_id: s.section for s in last.draft.sentences}
    labels: dict[str, Escalation] = {}
    for v in last.verdicts:
        kind = _ESCALATE.get(v.kind)
        if kind is None:
            continue
        section = None
        if kind is EscalationKind.INCONSISTENT and v.hint and v.hint.conflicts_with:
            section = section_of.get(v.hint.conflicts_with)
        cur = labels.get(v.sentence_id)
        if cur is None or _SEVERITY.index(kind) < _SEVERITY.index(cur.kind):
            labels[v.sentence_id] = Escalation(kind=kind, section=section)
    return FinalReport(run_id=run.run_id, draft=last.draft, labels=labels)


def render_report_md(query: str, run: RunState, last: RoundState, report: FinalReport) -> str:
    errored = {v.sentence_id for v in last.verdicts if v.kind is VerdictKind.ERROR}
    marks: dict[str, str] = {sid: esc.render() for sid, esc in report.labels.items()}
    for sid in errored - marks.keys():
        marks[sid] = CHECK_FAILED

    labelled = last.draft.model_copy(update={"sentences": tuple(
        s.model_copy(update={"text": f"{s.text} ⟨{marks[s.sentence_id]}⟩"}) if s.sentence_id in marks else s
        for s in last.draft.sentences)})

    kinds = Counter(v.kind.value for v in last.verdicts)
    u = run.total_usage
    header = [
        f"> **Run** `{run.run_id}` · query `{run.query_id}` · condition **{run.condition}** · "
        f"corpus `{run.corpus_version}` · config `{run.config_hash[:12]}`",
        f"> **Stopped:** {run.stop_reason or 'incomplete'} after {len(run.rounds)} round(s) · "
        f"{len(last.claims)} claims in {len(last.draft.sentences)} sentences · "
        + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())),
        f"> **Cost:** ${u.cost_usd:.4f} over {u.n_calls} model calls (list prices)",
        "",
        "> Sentences still unresolved after the last round carry a label in ⟨angle brackets⟩ saying why.",
        "",
    ]
    return "\n".join(header) + render_markdown(labelled, title=query)
