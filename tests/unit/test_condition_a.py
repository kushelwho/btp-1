"""Phase 2: the condition-A pipeline end to end, offline.

A scripted fake model answers each prompt the way the real one would. Any
claim containing "WRONG" is judged unsupported, so the tests control exactly
which sentences fail and whether a revision fixes them.
"""

import json

import pytest

from tcv.agents.planner import Planner
from tcv.agents.researcher import Researcher
from tcv.agents.synthesizer import Synthesizer, UntouchedViolation, assert_untouched, uncited_factual
from tcv.checker.pipeline import Checker, UnbuiltMechanism
from tcv.checker.verify_t1 import verify_t1
from tcv.config import CheckerConfig, LoopConfig, PlannerConfig, RetrievalConfig, load_run_config
from tcv.llm.cache import ResponseCache
from tcv.llm.gateway import Gateway, ModelsConfig, RoleConfig
from tcv.llm.ledger import Ledger
from tcv.llm.prompts import load_prompt
from tcv.llm.provider import FakeProvider, LLMResponse
from tcv.orchestrator.loop import Orchestrator, RunMeta
from tcv.orchestrator.state import StateStore
from tcv.retrieval.embed import HashingEmbedder
from tcv.retrieval.index import HybridIndex
from tcv.retrieval.search import HybridSearcher
from tcv.schemas import (
    Citation,
    Claim,
    Draft,
    RevisionItem,
    RevisionPayload,
    Sentence,
    VerdictKind,
)
from conftest import make_chunk, make_passage

A1, A2, B1 = "alpha-2024#p1c0", "alpha-2024#p2c0", "beta-2025#p1c0"
CHUNKS = [
    make_chunk("alpha-2024", 1, 0, "Alpha bounds its correction loop at three rounds of revision."),
    make_chunk("alpha-2024", 2, 0, "Alpha reports a catch rate on short claims but no false-positive rate."),
    make_chunk("beta-2025", 1, 0, "Beta trains its checker with reinforcement learning and a zero-tolerance reward."),
]

GOOD_DRAFT = f"""# Checking in multi-agent systems

## Loop design
Alpha bounds its correction loop [[{A1}]]. Alpha reports no false-positive rate [[{A2}]].

## Training
Beta trains its checker with reinforcement learning [[{B1}]]. Beta is WRONG about everything [[{B1}]].
"""


def _items(user: str) -> list[dict]:
    return json.loads(user[user.index("["): user.rindex("]") + 1])


class Script:
    """Routes each request by its prompt's opening line; records what was asked."""

    def __init__(self, draft=GOOD_DRAFT, fix="Beta uses a zero-tolerance reward [[beta-2025#p1c0]].", drafts=None):
        self.drafts = list(drafts or [draft])
        self.fix = fix
        self.calls: list[str] = []

    def __call__(self, req):
        s = req.system
        if s.startswith("You plan"):
            self.calls.append("plan")
            return {"subtasks": [{"heading": "Loop design", "question": "How do systems bound their loops?"},
                                 {"heading": "Training", "question": "How are checkers trained?"}]}
        if s.startswith("You write search queries"):
            self.calls.append("queries")
            return {"results": [{"index": it["index"], "queries": [f"{it['heading']} papers"]} for it in _items(req.user)]}
        if s.startswith("You write research survey reports"):
            self.calls.append("draft")
            return self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]
        if s.startswith("You revise"):
            self.calls.append("revise")
            flagged = [line.split("]")[0][1:] for line in req.user.split("Flagged sentences")[1].splitlines()
                       if line.startswith("[r")]
            return {"revisions": [{"sentence_id": sid, "replacement": self.fix} for sid in flagged]}
        if s.startswith("You split sentences"):
            self.calls.append("atomize")
            return {"results": [{"index": it["index"], "claims": [
                {"text": it["text"], "surface": it["text"], "modality": "none"}]} for it in _items(req.user)]}
        if s.startswith("You check claims"):
            self.calls.append("verify")
            return {"results": [{"index": it["index"], "label": "unsupported" if "WRONG" in it["claim"] else "supported",
                                 "confidence": 0.9, "evidence": [p["chunk_id"] for p in it["passages"]],
                                 "rationale": "scripted"} for it in _items(req.user)]}
        raise AssertionError(f"unscripted prompt: {s[:60]!r}")


MODELS = ModelsConfig(provider="gemini", roles={r: RoleConfig(model="fake") for r in ("synthesizer", "economy", "judge")})


def make_gateway(tmp_path, responder, budget=None, run="run_000000000001"):
    return Gateway(provider=FakeProvider(responder), models=MODELS, cache=ResponseCache(tmp_path / "cache"),
                   ledger=Ledger(tmp_path / "runs" / run / "calls.jsonl"), run_id=run, budget_usd=budget)


def make_orchestrator(tmp_path, gateway, max_rounds=3, run="run_000000000001"):
    emb = HashingEmbedder(dim=256)
    searcher = HybridSearcher(HybridIndex.build(CHUNKS, emb, corpus_version="vtest"), emb)
    return Orchestrator(
        planner=Planner(gateway, load_prompt("planner@1")),
        researcher=Researcher(searcher, gateway, load_prompt("researcher/queries@1"), RetrievalConfig()),
        synthesizer=Synthesizer(gateway, load_prompt("synthesizer/draft@1"), load_prompt("synthesizer/revise@1")),
        checker=Checker(gateway, CheckerConfig(), load_prompt("checker/atomize@1"), load_prompt("checker/verify_t1@1")),
        gateway=gateway, store=StateStore(tmp_path, run), config=LoopConfig(max_rounds=max_rounds))


META = RunMeta(run_id="run_000000000001", query_id="q99", query="How do checkers work?", condition="A",
               config_hash="0" * 64, corpus_version="vtest")


# ---------------------------------------------------------------- end to end


def test_condition_A_smoke_resolves_after_one_revision(tmp_path):
    script = Script()
    gw = make_gateway(tmp_path, script)
    run = make_orchestrator(tmp_path, gw).run(META)

    assert run.stop_reason == "resolved" and len(run.rounds) == 2
    r1, r2 = run.rounds
    assert [v.kind for v in r1.verdicts].count(VerdictKind.UNSUPPORTED) == 1
    assert all(v.kind is VerdictKind.SUPPORTED for v in r2.verdicts)
    assert r1.payload is not None and r2.payload is None  # no payload on the final round
    assert all(c.ctype.value == "T1" and c.route_source == "default" for c in r1.claims)  # condition A

    # only the flagged sentence changed; its replacement links back to it
    wrong = next(s for s in r1.draft.sentences if "WRONG" in s.text)
    new = [s for s in r2.draft.sentences if s.supersedes]
    assert len(new) == 1 and new[0].supersedes == wrong.sentence_id and new[0].sentence_id.startswith("r2s")
    assert [s for s in r2.draft.sentences if not s.supersedes] == [s for s in r1.draft.sentences if s is not wrong]

    # round 2 re-checked only the new sentence: one atomize + one verify call
    assert script.calls == ["plan", "queries", "draft", "atomize", "verify", "revise", "atomize", "verify"]

    # everything persisted and replayable
    store = StateStore(tmp_path, META.run_id)
    assert store.is_complete() and store.load_run() == run
    assert (store.root / "report.md").exists() and (store.root / "final.json").exists()
    assert all(p.cited for p in run.pools[0].entries if p.passage.chunk_id == A1)


def test_unfixable_claim_is_escalated_after_max_rounds(tmp_path):
    gw = make_gateway(tmp_path, Script(fix="Beta is still WRONG [[beta-2025#p1c0]]."))
    run = make_orchestrator(tmp_path, gw, max_rounds=3).run(META)
    assert run.stop_reason == "max_rounds" and len(run.rounds) == 3
    report = (StateStore(tmp_path, META.run_id).root / "report.md").read_text()
    assert "⟨unverified — no supporting passage⟩" in report
    final = json.loads((StateStore(tmp_path, META.run_id).root / "final.json").read_text())
    assert [e["kind"] for e in final["labels"].values()] == ["no_support"]


def test_budget_stops_the_loop_after_the_round_that_crossed_it(tmp_path):
    def priced(req):
        out = Script()(req)
        text = out if isinstance(out, str) else json.dumps(out)
        return LLMResponse(text=text, model="gemini-3.1-flash-lite", stop_reason="end_turn",
                           input_tokens=0, output_tokens=10_000)  # $0.015 per call

    gw = make_gateway(tmp_path, priced, budget=0.07)  # crossed by the 5th call (round-1 verify)
    run = make_orchestrator(tmp_path, gw).run(META)
    assert run.stop_reason == "budget" and len(run.rounds) == 1
    assert run.total_usage.cost_usd == pytest.approx(0.075)


def test_provider_failure_leaves_run_resumable_and_resume_replays_from_cache(tmp_path):
    from tcv.llm.gateway import GatewayError

    script = Script()

    # (a failed *check* only marks its claims ERROR — see the next test — so fail the draft instead)
    def failing_draft(req):
        if req.system.startswith("You write research survey reports"):
            raise RuntimeError("503 overloaded")
        return script(req)

    with pytest.raises(GatewayError):
        make_orchestrator(tmp_path, make_gateway(tmp_path, failing_draft)).run(META)
    assert not StateStore(tmp_path, META.run_id).is_complete()

    resumed = Script()
    run = make_orchestrator(tmp_path, make_gateway(tmp_path, resumed)).run(META)
    assert run.stop_reason == "resolved"
    assert resumed.calls[:2] == ["draft", "atomize"], "plan and queries must replay from the response cache"


def test_failed_checks_leave_the_run_incomplete_and_resume_resends_only_them(tmp_path):
    from tcv.orchestrator.loop import RunIncomplete

    script = Script()

    def broken_verify(req):
        if req.system.startswith("You check claims"):
            raise RuntimeError("503 overloaded")
        return script(req)

    with pytest.raises(RunIncomplete, match="check"):
        make_orchestrator(tmp_path, make_gateway(tmp_path, broken_verify)).run(META)
    store = StateStore(tmp_path, META.run_id)
    assert not store.is_complete(), "a run with failed checks must not count as finished"
    assert {v.kind for v in store.load_rounds()[0].verdicts} == {VerdictKind.ERROR}  # kept for inspection
    assert "revise" not in script.calls

    resumed = Script()
    run = make_orchestrator(tmp_path, make_gateway(tmp_path, resumed)).run(META)
    assert run.stop_reason == "resolved"
    assert resumed.calls[0] == "verify", "everything before the failed checks must replay from cache"


def test_report_marks_a_failed_check_without_inventing_a_label():
    from tcv.orchestrator.report import CHECK_FAILED, final_report, render_report_md
    from tcv.schemas import RoundState, RunState, Verdict

    d = Draft(round=1, sections=("S",), sentences=(
        Sentence(sentence_id="r1s0000", section="S", text="A.", citations=(Citation(chunk_id=A1),)),))
    c = Claim(claim_id="r1c0000", sentence_id="r1s0000", text="A", surface="A", citations=(A1,))
    v = Verdict(claim_id="r1c0000", sentence_id="r1s0000", kind=VerdictKind.ERROR, step="C.T1", rationale="503")
    rs = RoundState(round=1, draft=d, claims=(c,), verdicts=(v,))
    run = RunState(run_id="run_000000000001", query_id="q", condition="A", config_hash="0" * 64,
                   corpus_version="v", seed=0, subtasks=(), pools=(), rounds=(rs,), stop_reason="max_rounds")
    report = final_report(run, rs)
    assert report.labels == {}
    assert f"⟨{CHECK_FAILED}⟩" in render_report_md("q", run, rs, report)


# ---------------------------------------------------------------- components


def test_draft_is_regenerated_once_when_factual_sentences_are_uncited(tmp_path):
    uncited = GOOD_DRAFT.replace(f" [[{A2}]]", "")
    script = Script(drafts=[uncited, GOOD_DRAFT])
    gw = make_gateway(tmp_path, script)
    synth = Synthesizer(gw, load_prompt("synthesizer/draft@1"), load_prompt("synthesizer/revise@1"))
    from tcv.schemas import PoolEntry, RetrievalPool, SubTask

    pool = RetrievalPool(subtask_id="st01", entries=tuple(
        PoolEntry(passage=make_passage(0).model_copy(update={"chunk": c})) for c in CHUNKS))
    st = SubTask(subtask_id="st01", heading="Loop design", question="q", order=1)
    res = synth.draft("q", [st], {"st01": pool})
    assert script.calls == ["draft", "draft"] and res.uncited_factual == []


def test_uncited_detection_skips_signposting():
    d = Draft(round=1, sections=("S",), sentences=(
        Sentence(sentence_id="r1s0000", section="S", text="We now turn to training."),
        Sentence(sentence_id="r1s0001", section="S", text="Beta uses reinforcement learning."),
    ))
    assert uncited_factual(d) == ["r1s0001"]


def test_assert_untouched_catches_a_changed_unflagged_sentence():
    old = Draft(round=1, sections=("S",), sentences=(
        Sentence(sentence_id="r1s0000", section="S", text="A.", citations=(Citation(chunk_id=A1),)),
        Sentence(sentence_id="r1s0001", section="S", text="B.", citations=(Citation(chunk_id=A1),)),
    ))
    payload = RevisionPayload(round=1, items=(RevisionItem(
        sentence_ids=("r1s0000",), claim_text="A", ctype="T1", verdict=VerdictKind.UNSUPPORTED, passages=(),
        instruction="fix"),))
    changed = old.model_copy(update={"sentences": (old.sentences[0],
                                                   old.sentences[1].model_copy(update={"text": "B changed."}))})
    with pytest.raises(UntouchedViolation):
        assert_untouched(old, changed, payload)
    assert_untouched(old, old, payload)  # unchanged is fine


def test_checker_refuses_flags_whose_mechanism_is_not_built(tmp_path):
    gw = make_gateway(tmp_path, Script())
    with pytest.raises(UnbuiltMechanism, match="route"):
        Checker(gw, CheckerConfig(route=True), load_prompt("checker/atomize@1"), load_prompt("checker/verify_t1@1"))


def test_t1_abstains_below_threshold_and_skips_model_for_uncited_claims(tmp_path):
    def unsure(req):
        return {"results": [{"index": it["index"], "label": "supported", "confidence": 0.4, "evidence": [],
                             "rationale": "maybe"} for it in _items(req.user)]}

    fake = FakeProvider(unsure)
    gw = Gateway(provider=fake, models=MODELS, cache=ResponseCache(tmp_path / "c"), ledger=Ledger(tmp_path / "l"))
    passages = {A1: make_passage(0).model_copy(update={"chunk": CHUNKS[0]})}
    claims = [Claim(claim_id="r1c0000", sentence_id="r1s0000", text="x", surface="x", citations=(A1,)),
              Claim(claim_id="r1c0001", sentence_id="r1s0001", text="y", surface="y")]
    v = verify_t1(gw, load_prompt("checker/verify_t1@1"), claims, passages, uncertain_below=0.55)
    assert [x.kind for x in v] == [VerdictKind.UNCERTAIN, VerdictKind.UNSUPPORTED]
    assert v[1].rationale == "no citation" and len(fake.requests) == 1


def test_atomizer_falls_back_to_the_whole_sentence(tmp_path):
    from tcv.checker.atomize import atomize

    def empty(req):
        return {"results": [{"index": it["index"], "claims": []} for it in _items(req.user)]}

    gw = Gateway(provider=FakeProvider(empty), models=MODELS, cache=ResponseCache(tmp_path / "c"),
                 ledger=Ledger(tmp_path / "l"))
    s = Sentence(sentence_id="r1s0000", section="S", text="This may suggest a limit.", citations=(Citation(chunk_id=A1),))
    res = atomize(gw, load_prompt("checker/atomize@1"), [s], round_=1)
    assert res.fallback_sentences == ["r1s0000"]
    (c,) = res.claims
    assert c.text == s.text and c.citations == (A1,) and c.modality.value == "suggests"  # lexicon, hedge wins


def test_planner_bounds_and_deduplicates_subtasks(tmp_path):
    def many(req):
        return {"subtasks": [{"heading": "Same", "question": f"q{i}"} for i in range(10)]}

    gw = Gateway(provider=FakeProvider(many), models=MODELS, cache=ResponseCache(tmp_path / "c"),
                 ledger=Ledger(tmp_path / "l"))
    subtasks = Planner(gw, load_prompt("planner@1"), PlannerConfig(min_subtasks=2, max_subtasks=4)).plan("q")
    assert [s.subtask_id for s in subtasks] == ["st01", "st02", "st03", "st04"]
    assert len({s.heading for s in subtasks}) == 4


def test_repo_condition_A_config_turns_every_mechanism_off():
    cfg = load_run_config("configs/conditions/A_baseline.yaml")
    assert cfg.condition == "A" and cfg.checker.enabled_flags() == set()


def test_changed_sentence_with_the_same_id_is_rechecked_not_carried_over(tmp_path):
    """A planted error keeps its sentence ID; it must never inherit the clean verdict."""
    script = Script()
    gw = make_gateway(tmp_path, script)
    checker = Checker(gw, CheckerConfig(), load_prompt("checker/atomize@1"), load_prompt("checker/verify_t1@1"))
    from tcv.schemas import PoolEntry, RetrievalPool, RoundState

    pool = RetrievalPool(subtask_id="st01", entries=tuple(
        PoolEntry(passage=make_passage(0).model_copy(update={"chunk": c})) for c in CHUNKS))
    clean = Draft(round=1, sections=("S",), sentences=(
        Sentence(sentence_id="r1s0000", section="S", text="Alpha bounds its loop.", citations=(Citation(chunk_id=A1),)),
        Sentence(sentence_id="r1s0001", section="S", text="Beta uses RL.", citations=(Citation(chunk_id=B1),)),
    ))
    first = checker.check(clean, {"st01": pool})
    prior = RoundState(round=1, draft=clean, claims=first.claims, verdicts=first.verdicts)

    corrupted = clean.model_copy(update={"sentences": (
        clean.sentences[0], clean.sentences[1].model_copy(update={"text": "Beta is WRONG."}))})
    second = checker.check(corrupted, {"st01": pool}, prior)
    assert second.rechecked_sentences == ("r1s0001",)
    kinds = {v.sentence_id: v.kind for v in second.verdicts}
    assert kinds == {"r1s0000": VerdictKind.SUPPORTED, "r1s0001": VerdictKind.UNSUPPORTED}


# ---------------------------------------------------------------- loop dynamics


def test_dynamics_of_a_run_that_resolves_after_one_revision(tmp_path):
    from tcv.eval.dynamics import run_dynamics

    run = make_orchestrator(tmp_path, make_gateway(tmp_path, Script())).run(META)
    r1, r2 = run_dynamics(run)
    assert r1.payloaded == 0 and r1.failing_sentences == 1
    assert (r2.payloaded, r2.resolved, r2.persisting, r2.skipped, r2.deleted) == (1, 1, 0, 0, 0)
    assert r2.marginal_resolution == 1.0 and r2.displaced == 0


def test_dynamics_counts_persisting_and_deleted_fixes(tmp_path):
    from tcv.eval.dynamics import run_dynamics

    run = make_orchestrator(tmp_path, make_gateway(tmp_path, Script(fix="Beta is still WRONG [[beta-2025#p1c0]].")),
                            max_rounds=2).run(META)
    assert run_dynamics(run)[1].persisting == 1 and run_dynamics(run)[1].marginal_resolution == 0.0

    run2 = make_orchestrator(tmp_path / "b", make_gateway(tmp_path / "b", Script(fix=""))).run(META)
    assert run_dynamics(run2)[1].deleted == 1 and run2.stop_reason == "resolved"


# ---------------------------------------------------------------- oracle retrieval


def test_oracle_pools_hold_every_gold_passage_and_nothing_else(tmp_path):
    emb = HashingEmbedder(dim=256)
    searcher = HybridSearcher(HybridIndex.build(CHUNKS, emb, corpus_version="vtest"), emb)
    from tcv.schemas import SubTask

    sts = [SubTask(subtask_id="st01", heading="Loop", question="How do systems bound their loops?", order=1),
           SubTask(subtask_id="st02", heading="Training", question="How are checkers trained?", order=2)]
    r = Researcher(searcher, config=RetrievalConfig(oracle=True), gold=[A1, B1])
    pools = r.research(sts)
    for pool in pools.values():
        assert {p.chunk_id for p in pool.passages()} == {A1, B1}
        assert all(p.retrieved_by == "oracle" for p in pool.passages())
    assert pools["st02"].passages()[0].chunk_id == B1  # best match to "trained" first

    with pytest.raises(ValueError, match="gold"):
        Researcher(searcher, config=RetrievalConfig(oracle=True))
    with pytest.raises(ValueError, match="not in the corpus"):
        Researcher(searcher, config=RetrievalConfig(oracle=True), gold=["nope-2020#p1c0"]).research(sts)


def test_gold_propose_and_confirm_round_trip(tmp_path):
    import yaml

    from tcv.eval import gold as G

    text = G.propose("q99", "q?", [make_passage(0).model_copy(update={"chunk": CHUNKS[0]})], [])
    f = tmp_path / "c.yaml"
    data = yaml.safe_load(text)
    assert data["candidates"][0]["keep"] is False
    with pytest.raises(ValueError, match="keep"):
        f.write_text(text)
        G.confirm(f, by="KR")
    data["candidates"][0]["keep"] = True
    f.write_text(yaml.safe_dump(data))
    g = G.confirm(f, by="KR")
    assert g["chunks"] == [A1] and g["confirmed_by"] == "KR"


def test_oracle_condition_file_differs_from_A_only_in_retrieval():
    a, o = load_run_config("configs/conditions/A_baseline.yaml"), load_run_config("configs/conditions/A-oracle.yaml")
    assert o.retrieval.oracle and not a.retrieval.oracle
    assert o.checker == a.checker and o.loop == a.loop and o.planner == a.planner
