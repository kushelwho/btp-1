"""Synthesizer — drafts the report, then revises only what the Checker flags.

Drafting (FR-4.1, FR-4.2): the model writes markdown with ``[[chunk_id]]``
citations; the draft parser turns it into sentences with stable IDs. If
factual sentences come back without a citation, the draft is regenerated
(up to a configured number of times) with the offending sentences quoted.

Revision (FR-4.3, FR-4.4): the model never rewrites the report. It returns
replacement text for the flagged sentence IDs only, and the new draft is
assembled in code: every other sentence is carried over as the same object,
so it keeps its ID and text byte-for-byte. A replacement gets fresh IDs for
the new round, linked back through ``supersedes``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from tcv.agents.draft_parser import parse_draft
from tcv.checker.lexicon import is_discourse
from tcv.config import SynthesizerConfig
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import CorpusManifest, Draft, RetrievalPool, RevisionPayload, Sentence, SubTask
from tcv.schemas.ids import sentence_id


@dataclass
class DraftResult:
    draft: Draft
    markdown: str
    call_ids: list[str] = field(default_factory=list)
    malformed_citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    uncited_factual: list[str] = field(default_factory=list)  # sentence IDs still uncited after retries


@dataclass
class RevisionResult:
    draft: Draft
    call_id: str
    replaced: dict[str, tuple[str, ...]]  # old sentence id → new sentence ids ("" deletion → ())
    ignored: list[str] = field(default_factory=list)  # ids the model revised but was not asked to
    skipped: list[str] = field(default_factory=list)  # flagged ids the model returned nothing for
    malformed_citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)


class Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence_id: str
    replacement: str


class Revisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revisions: list[Replacement]


def uncited_factual(draft: Draft) -> list[str]:
    """Sentences with no citation that are not obvious signposting (FR-4.2)."""
    return [s.sentence_id for s in draft.sentences if not s.citations and not is_discourse(s.text)]


def _doc_label(manifest: CorpusManifest | None, doc_id: str) -> str:
    if manifest is None:
        return doc_id
    doc = manifest.doc(doc_id)
    return f"{doc.title} ({doc.year})" if doc.year else doc.title


def render_passages(subtasks: Sequence[SubTask], pools: Mapping[str, RetrievalPool],
                    manifest: CorpusManifest | None) -> tuple[str, int, int]:
    """Passages grouped by the sub-task that retrieved them, each chunk shown once.

    Returns ``(text, n_passages, n_documents)``.
    """
    seen: set[str] = set()
    blocks = []
    for st in subtasks:
        pool = pools.get(st.subtask_id)
        if pool is None:
            continue
        shown = []
        for p in pool.passages():
            if p.chunk_id in seen:
                continue
            seen.add(p.chunk_id)
            shown.append(f"[[{p.chunk_id}]] — {_doc_label(manifest, p.chunk.doc_id)}, page {p.chunk.page}\n"
                         f"{p.chunk.text}")
        if shown:
            blocks.append(f"### Passages retrieved for: {st.heading}\n\n" + "\n\n---\n\n".join(shown))
    docs = {cid.split("#")[0] for cid in seen}
    return "\n\n".join(blocks), len(seen), len(docs)


def render_report(draft: Draft) -> str:
    """The draft one sentence per line, with IDs and citations — what the reviser sees."""
    lines = []
    for sec in draft.sections:
        sents = [s for s in draft.sentences if s.section == sec]
        if not sents:
            continue
        lines.append(f"## {sec}")
        for s in sents:
            cites = "".join(f"[[{c.chunk_id}]]" for c in s.citations)
            lines.append(f"[{s.sentence_id}] {s.text}{(' ' + cites) if cites else ''}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_markdown(draft: Draft, title: str | None = None) -> str:
    """The draft as ordinary markdown with inline citations."""
    out = [f"# {title}", ""] if title else []
    for sec in draft.sections:
        sents = [s for s in draft.sentences if s.section == sec]
        if not sents:
            continue
        out.append(f"## {sec}")
        out.append("")
        out.append(" ".join(f"{s.text}{''.join(f'[[{c.chunk_id}]]' for c in s.citations)}" for s in sents))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _render_fixes(payload: RevisionPayload, draft: Draft) -> str:
    by_sentence: dict[str, list[str]] = {}
    for item in payload.items:
        for sid in item.sentence_ids:
            by_sentence.setdefault(sid, []).append(
                f"  - problem ({item.verdict.value}) with the claim \"{item.claim_text}\": {item.instruction}")
    lines = []
    for sid, problems in by_sentence.items():
        try:
            text = draft.by_id(sid).text
        except KeyError:
            continue
        lines.append(f"[{sid}] {text}")
        lines.extend(problems)
    return "\n".join(lines)


class Synthesizer:
    def __init__(self, gateway: Gateway, draft_prompt: Prompt, revise_prompt: Prompt,
                 manifest: CorpusManifest | None = None, config: SynthesizerConfig = SynthesizerConfig()):
        self._gateway = gateway
        self._draft_prompt = draft_prompt
        self._revise_prompt = revise_prompt
        self._manifest = manifest
        self._config = config

    # -- first draft

    def draft(self, query: str, subtasks: Sequence[SubTask], pools: Mapping[str, RetrievalPool]) -> DraftResult:
        passages, n_passages, n_docs = render_passages(subtasks, pools, self._manifest)
        known = {p.chunk_id for pool in pools.values() for p in pool.passages()}
        outline = "\n".join(f"{st.order}. {st.heading} — {st.question}" for st in sorted(subtasks, key=lambda s: s.order))
        variables = {"query": query, "outline": outline, "passages": passages,
                     "n_passages": str(n_passages), "n_documents": str(n_docs), "feedback": ""}

        best: DraftResult | None = None
        call_ids: list[str] = []
        for attempt in range(self._config.uncited_retries + 1):
            res = self._gateway.call("synthesizer", self._draft_prompt, variables)
            call_ids.append(res.call_id)
            parsed = parse_draft(res.text, round_=1, known_chunks=known)
            result = DraftResult(draft=parsed.draft, markdown=res.text, malformed_citations=parsed.malformed_citations,
                                 unknown_citations=parsed.unknown_citations,
                                 uncited_factual=uncited_factual(parsed.draft))
            if best is None or len(result.uncited_factual) < len(best.uncited_factual):
                best = result
            if not result.uncited_factual:
                break
            quoted = "\n".join(f"- {parsed.draft.by_id(sid).text}" for sid in result.uncited_factual[:20])
            variables["feedback"] = (
                "\nA previous version of this report had factual sentences without citation markers, "
                f"for example:\n{quoted}\nEvery factual sentence must end with [[chunk_id]] markers. "
                "Rewrite the whole report following all the rules.\n")
        assert best is not None
        best.call_ids = call_ids
        return best

    # -- targeted revision

    def revise(self, query: str, prior: Draft, payload: RevisionPayload,
               pools: Mapping[str, RetrievalPool], subtasks: Sequence[SubTask]) -> RevisionResult:
        named = payload.named_sentences()
        known = {p.chunk_id for pool in pools.values() for p in pool.passages()}
        passages, _, _ = render_passages(subtasks, pools, self._manifest)
        res = self._gateway.call("synthesizer", self._revise_prompt, {
            "query": query, "report": render_report(prior), "fixes": _render_fixes(payload, prior),
            "passages": passages,
        }, out=Revisions)

        new_round = prior.round + 1
        wanted: dict[str, str] = {}
        ignored = []
        for r in res.value.revisions:
            if r.sentence_id in named:
                wanted.setdefault(r.sentence_id, r.replacement)
            else:
                ignored.append(r.sentence_id)

        counter = 0
        sentences: list[Sentence] = []
        replaced: dict[str, tuple[str, ...]] = {}
        malformed: list[str] = []
        unknown: list[str] = []
        for s in prior.sentences:
            if s.sentence_id not in wanted:
                sentences.append(s)  # the same object: byte-identical by construction
                continue
            text = "\n".join(line for line in wanted[s.sentence_id].splitlines() if not line.lstrip().startswith("#"))
            parsed = parse_draft(text, round_=new_round, known_chunks=known)
            malformed += parsed.malformed_citations
            unknown += parsed.unknown_citations
            new_ids = []
            for p in parsed.draft.sentences:
                sid = sentence_id(new_round, counter)
                counter += 1
                sentences.append(Sentence(sentence_id=sid, section=s.section, text=p.text, citations=p.citations,
                                          supersedes=s.sentence_id))
                new_ids.append(sid)
            replaced[s.sentence_id] = tuple(new_ids)

        draft = Draft(round=new_round, sections=prior.sections, sentences=tuple(sentences))
        return RevisionResult(draft=draft, call_id=res.call_id, replaced=replaced, ignored=ignored,
                              skipped=sorted(named - wanted.keys()), malformed_citations=malformed,
                              unknown_citations=unknown)


class UntouchedViolation(AssertionError):
    pass


def assert_untouched(old: Draft, new: Draft, payload: RevisionPayload) -> None:
    """Every sentence the payload did not name must come back identical (FR-4.3).

    Without this, error displacement (N11) is unmeasurable: a new failure could
    come from an unrelated rewrite instead of from the revision itself.
    """
    named = payload.named_sentences()
    new_by_id = {s.sentence_id: s for s in new.sentences}
    for s in old.sentences:
        if s.sentence_id in named:
            continue
        if new_by_id.get(s.sentence_id) != s:
            raise UntouchedViolation(f"sentence {s.sentence_id} changed although it was not flagged")
