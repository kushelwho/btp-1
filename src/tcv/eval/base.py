"""Base drafts: the clean reports that planted errors are injected into.

A planted-error measurement is only valid on a draft with no *real* errors:
otherwise a flag on an untouched sentence might be a true catch, not a false
alarm. So a base draft starts unverified. A person reviews it (``review``
writes a checklist with each sentence beside its cited passages, suspects
first), drops any sentence they find wrong, and marks it verified. The
sweep runner warns loudly about unverified bases.

    data/base_drafts/<base_id>.json          BaseDraft
    data/base_drafts/<base_id>.review.md     review sheet for a person
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tcv.schemas import Draft, RetrievalPool, RoundState, RunState, Verdict

_BASE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class BaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_id: str
    query_id: str
    query: str
    source: str  # "run:<run_id>:r<round>" | "pilot:<query_id>"
    draft: Draft
    pools: tuple[RetrievalPool, ...]
    checker_verdicts: tuple[Verdict, ...] = ()  # condition-A verdicts at capture time — review aid only
    verified: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None
    dropped_sentences: tuple[str, ...] = ()
    notes: str = ""

    def pool_map(self) -> dict[str, RetrievalPool]:
        return {p.subtask_id: p for p in self.pools}


class BaseDraftStore:
    def __init__(self, data_root: str | Path):
        self.root = Path(data_root) / "base_drafts"

    def path(self, base_id: str) -> Path:
        return self.root / f"{base_id}.json"

    def save(self, base: BaseDraft) -> Path:
        if not _BASE_ID.match(base.base_id):
            raise ValueError(f"base id must be a lowercase slug, got {base.base_id!r}")
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path(base.base_id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(base.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(p)
        return p

    def load(self, base_id: str) -> BaseDraft:
        return BaseDraft.model_validate_json(self.path(base_id).read_text(encoding="utf-8"))

    def list(self) -> list[BaseDraft]:
        if not self.root.exists():
            return []
        return [BaseDraft.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("*.json"))]


def from_run(run: RunState, query: str, round_: int | None = None, base_id: str | None = None) -> BaseDraft:
    """Capture a run's draft at a given round (default: the last one)."""
    if not run.rounds:
        raise ValueError(f"run {run.run_id} has no rounds")
    rs: RoundState = run.rounds[-1] if round_ is None else next(r for r in run.rounds if r.round == round_)
    return BaseDraft(base_id=base_id or f"{run.query_id}-{run.run_id[4:10]}-r{rs.round}", query_id=run.query_id,
                     query=query, source=f"run:{run.run_id}:r{rs.round}", draft=rs.draft, pools=run.pools,
                     checker_verdicts=rs.verdicts)


def from_pilot(query_id: str, query: str, draft: Draft, pool: RetrievalPool, base_id: str | None = None) -> BaseDraft:
    return BaseDraft(base_id=base_id or f"{query_id}-pilot", query_id=query_id, query=query,
                     source=f"pilot:{query_id}", draft=draft, pools=(pool,))


def verify(base: BaseDraft, by: str, drop: list[str] | tuple[str, ...] = (), notes: str = "") -> BaseDraft:
    """Mark a base draft clean, removing the sentences the reviewer found wrong.

    Dropping (rather than rewriting) keeps every remaining sentence exactly as
    the model wrote it, so the base stays a realistic model draft.
    """
    known = {s.sentence_id for s in base.draft.sentences}
    unknown = sorted(set(drop) - known)
    if unknown:
        raise ValueError(f"not sentences of {base.base_id}: {unknown}")
    kept = tuple(s for s in base.draft.sentences if s.sentence_id not in set(drop))
    draft = base.draft.model_copy(update={"sentences": kept})
    return base.model_copy(update={
        "draft": draft, "verified": True, "verified_by": by, "verified_at": datetime.now(timezone.utc),
        "dropped_sentences": tuple(dict.fromkeys((*base.dropped_sentences, *drop))),
        "notes": "\n".join(x for x in (base.notes, notes) if x),
    })


def review_sheet(base: BaseDraft) -> str:
    """A checklist for a person: every sentence beside the passages it cites.

    Sentences the condition-A checker failed are listed first — they are the
    likeliest real errors — but *every* sentence needs a look: the checker
    misses things, which is the point of the project.
    """
    passages = {p.chunk_id: p for pool in base.pools for p in pool.passages()}
    failing = {}
    for v in base.checker_verdicts:
        if v.is_failure:
            failing.setdefault(v.sentence_id, []).append(f"{v.kind.value}: {v.rationale}")
    order = sorted(base.draft.sentences, key=lambda s: (s.sentence_id not in failing,
                                                       [x.sentence_id for x in base.draft.sentences].index(s.sentence_id)))
    out = [
        f"# Review: {base.base_id}",
        "",
        f"Question: {base.query}",
        f"Source: `{base.source}` · {len(base.draft.sentences)} sentences · "
        f"{len(failing)} flagged by the condition-A checker (listed first)",
        "",
        "For each sentence: does the cited passage really say this? Tick the box if yes. If a sentence is wrong,",
        "note its ID. Then run:",
        "",
        f"    uv run tcv base verify {base.base_id} --by <your-name> --drop <id>,<id>,...",
        "",
        "---",
        "",
    ]
    for s in order:
        flag = " ⚠ flagged" if s.sentence_id in failing else ""
        out.append(f"### [ ] `{s.sentence_id}` ({s.section}){flag}")
        out.append("")
        out.append(f"> {s.text}")
        out.append("")
        for reason in failing.get(s.sentence_id, []):
            out.append(f"- checker: {reason}")
        if not s.citations:
            out.append("- **no citation**")
        for c in s.citations:
            p = passages.get(c.chunk_id)
            text = p.chunk.text if p else "(passage not in the pool)"
            out.append(f"- `{c.chunk_id}`: {text}")
        out.append("")
    return "\n".join(out)
