"""Run-state persistence tests."""

import pytest

from conftest import DOC, make_draft, make_pool
from tcv.orchestrator.state import StateStore
from tcv.schemas import RoundState, RunState, SubTask, Usage
from tcv.schemas.ids import chunk_id


def _run(run_id="run_0123456789ab", stop=None, rounds=2):
    pool = make_pool(4).with_citations({chunk_id(DOC, 1, 1): ["r1s0001"]})
    return RunState(
        run_id=run_id, query_id="q01", condition="A", config_hash="h", corpus_version="v0-seed", seed=0,
        subtasks=(SubTask(subtask_id="st01", heading="Intro", question="q", order=0),),
        pools=(pool,),
        rounds=tuple(RoundState(round=r, draft=make_draft(round_=r), claims=(), verdicts=(),
                                usage=Usage(n_calls=r)) for r in range(1, rounds + 1)),
        stop_reason=stop,
    )


def test_pool_round_trip_keeps_uncited_passages(tmp_path):
    store = StateStore(tmp_path, "run_0123456789ab")
    pool = _run().pools[0]
    store.save_pool(pool)
    (loaded,) = store.load_pools()
    assert loaded == pool
    assert len(loaded.uncited()) == 3 and len(loaded.cited()) == 1


def test_run_reassembles_from_separate_files(tmp_path):
    store = StateStore(tmp_path, "run_0123456789ab")
    run = _run(rounds=3)
    store.save_run(run)
    assert store.load_run() == run
    assert sorted(p.name for p in (store.root / "rounds").iterdir()) == ["1.json", "2.json", "3.json"]
    assert '"rounds": []' in (store.root / "run.json").read_text()  # header stays small


def test_rounds_load_in_numeric_order(tmp_path):
    store = StateStore(tmp_path, "run_0123456789ab")
    for r in (10, 2, 1):
        store.save_round(RoundState(round=r, draft=make_draft(round_=r), claims=(), verdicts=()))
    assert [r.round for r in store.load_rounds()] == [1, 2, 10]  # not "1, 10, 2"


def test_completion_marker(tmp_path):
    store = StateStore(tmp_path, "run_0123456789ab")
    assert not store.is_complete()
    store.save_run(_run(stop=None))
    assert not store.is_complete()
    store.save_run(_run(stop="max_rounds"))
    assert store.is_complete()


def test_store_rejects_foreign_run(tmp_path):
    with pytest.raises(ValueError):
        StateStore(tmp_path, "run_aaaaaaaaaaaa").save_run(_run())
