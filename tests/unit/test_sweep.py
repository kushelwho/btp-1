"""Planted-error sweep end to end with a fake model whose right answers are known."""

import json

import pytest
from conftest import make_chunk, make_passage

from tcv.checker.pipeline import Checker
from tcv.config import CheckerConfig
from tcv.eval.base import BaseDraft, BaseDraftStore
from tcv.eval.metrics import aggregate
from tcv.eval.runner import Sweep, SweepConfig
from tcv.llm.cache import ResponseCache
from tcv.llm.gateway import Gateway, ModelsConfig, RoleConfig
from tcv.llm.ledger import Ledger
from tcv.llm.prompts import load_prompt
from tcv.llm.provider import FakeProvider
from tcv.schemas import Citation, Draft, ErrorClass, PoolEntry, RetrievalPool, Sentence

CHUNKS = {cid: make_chunk(cid.split("#")[0], 1, 0, f"Passage of {cid.split('#')[0]}.")
          for cid in ("alpha-2024#p1c0", "beta-2025#p1c0", "gamma-2026#p1c0")}
TEXTS = [
    "Three of the five surveyed frameworks bound their loop.", "Debate often improves accuracy.",
    "GSAR uses a typed partition.", "ClaimVerAgents deploys specialist agents.",
    "GSAR similarly deploys specialist agents.", "Gamma reaches 81.8% accuracy.",
    "These results suggest that retrieval is the bottleneck.",
    "Since 2023, frameworks have increasingly relied on retrieval.", "MARCH trains with PPO.",
    "The checker is blinded to the answer.",
]
CIDS = list(CHUNKS)


def _items(user):
    return json.loads(user[user.index("["): user.rindex("]") + 1])


def make_base(verified=True) -> BaseDraft:
    sents = tuple(Sentence(sentence_id=f"r1s{i:04d}", section="S", text=t,
                           citations=(Citation(chunk_id=CIDS[i % 3]),)) for i, t in enumerate(TEXTS))
    pool = RetrievalPool(subtask_id="st01", entries=tuple(
        PoolEntry(passage=make_passage(0).model_copy(update={"chunk": c})) for c in CHUNKS.values()))
    return BaseDraft(base_id="q99-base", query_id="q99", query="q", source="test", verified=verified,
                     draft=Draft(round=1, sections=("S",), sentences=sents), pools=(pool,))


class Judge:
    """Supports a claim only if its text *and* citation are exactly the clean draft's."""

    def __init__(self, fail_verify=False):
        self.clean = {(t, CIDS[i % 3]) for i, t in enumerate(TEXTS)}
        self.fail_verify = fail_verify
        self.calls = []

    def __call__(self, req):
        if req.system.startswith("You split sentences"):
            self.calls.append("atomize")
            return {"results": [{"index": it["index"], "claims": [{"text": it["text"], "surface": it["text"],
                                                                    "modality": "none"}]} for it in _items(req.user)]}
        self.calls.append("verify")
        if self.fail_verify:
            raise RuntimeError("503 overloaded")
        out = []
        for it in _items(req.user):
            ok = (it["claim"], it["passages"][0]["chunk_id"]) in self.clean
            out.append({"index": it["index"], "label": "supported" if ok else "unsupported", "confidence": 0.9,
                        "evidence": [], "rationale": "scripted"})
        return {"results": out}


MODELS = ModelsConfig(provider="gemini", roles={r: RoleConfig(model="fake") for r in ("synthesizer", "economy", "judge")})


def setup(tmp_path, judge, verified=True, seeds=(0, 1)):
    BaseDraftStore(tmp_path).save(make_base(verified))
    cfg = SweepConfig(name="t", base_drafts=["q99-base"], seeds=list(seeds), conditions=["A"],
                      require_verified=True)
    gw = Gateway(provider=FakeProvider(judge), models=MODELS, cache=ResponseCache(tmp_path / "cache"),
                 ledger=Ledger(tmp_path / "calls.jsonl"))
    checker = Checker(gw, CheckerConfig(), load_prompt("checker/atomize@1"), load_prompt("checker/verify_t1@1"))
    return Sweep(cfg, tmp_path), (lambda cond: ("A", checker))


def test_sweep_scores_condition_A_as_designed(tmp_path):
    judge = Judge()
    sweep, checker_for = setup(tmp_path, judge)
    prog = sweep.run(checker_for, log=lambda s: None)
    assert prog.done == 3 and not prog.incomplete  # clean + 2 seeds

    # planted passes re-check only the planted sentences: 1 atomize + 1 verify each
    assert judge.calls == ["atomize", "verify"] * 3

    rep = aggregate(sweep.scores(), n_boot=200)["A"]
    assert rep.fpr["T1"].rate == 0.0  # the clean pass raises no false alarms
    for cls, r in rep.catch.items():
        if cls == ErrorClass.E10_HEDGE_STRIP.value:
            assert r.rate == 0.0 and rep.flag[cls].rate == 1.0  # flagged, but condition A has no overclaim verdict
        else:
            assert r.rate == 1.0, cls


def test_sweep_resumes_without_new_calls_and_writes_a_report(tmp_path):
    judge = Judge()
    sweep, checker_for = setup(tmp_path, judge)
    sweep.run(checker_for, log=lambda s: None)
    n = len(judge.calls)
    prog = sweep.run(checker_for, log=lambda s: None)
    assert prog.skipped == 3 and prog.done == 0 and len(judge.calls) == n
    metrics, report = sweep.report(n_boot=100)
    assert "Catch rate per error class" in report.read_text() and json.loads(metrics.read_text())["A"]


def test_unverified_base_is_skipped_when_verification_is_required(tmp_path):
    sweep, checker_for = setup(tmp_path, Judge(), verified=False)
    prog = sweep.run(checker_for, log=lambda s: None)
    assert prog.done == 0 and prog.unverified == ["q99-base"]


def test_pass_with_failed_checks_is_not_saved(tmp_path):
    sweep, checker_for = setup(tmp_path, Judge(fail_verify=True))
    prog = sweep.run(checker_for, log=lambda s: None)
    assert prog.done == 0 and prog.incomplete == ["A/q99-base/clean"]
    assert not (tmp_path / "results" / "t" / "A" / "q99-base" / "clean.json").exists()


def test_seeded_drafts_are_stored_and_reused(tmp_path):
    sweep, _ = setup(tmp_path, Judge())
    a = sweep.seeded("q99-base", 0)
    assert (tmp_path / "seeded").rglob("0.json")
    assert sweep.seeded("q99-base", 0) == a


@pytest.mark.parametrize("path", ["configs/sweeps/phase3-dev.yaml"])
def test_repo_sweep_configs_are_valid(path):
    from tcv.eval.runner import load_sweep

    assert load_sweep(path).conditions
