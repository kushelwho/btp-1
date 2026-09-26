"""Fetch step (D-3) tests — offline: arXiv responses are canned Atom XML."""

import pytest
import yaml

from tcv.corpus import fetch as F
from tcv.corpus.sources import CorpusConfig, load_corpus_config

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2305.19118v4</id>
    <published>2023-05-30T17:59:59Z</published>
    <title>Encouraging Divergent Thinking in Large Language Models
      through Multi-Agent Debate</title>
    <author><name>Tian Liang</name></author><author><name>Zhiwei He</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2308.07201v1</id>
    <published>2023-08-14T00:00:00Z</published>
    <title>ChatEval: Towards Better LLM-based Evaluators through Multi-Agent Debate</title>
    <author><name>Chi-Min Chan</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_9999.99999</id>
    <title>Error</title>
  </entry>
</feed>"""


def cand(arxiv, title, decision=None, **kw):
    return F.Candidate(arxiv=arxiv, title=title, priority="core", decision=decision, **kw)


SEED = CorpusConfig.model_validate({
    "version": "v0-seed", "embed_model": "m",
    "documents": [{"doc_id": "du-2023", "title": "Improving Factuality", "filename": "du.pdf",
                   "source": "arxiv:2305.14325v1", "year": 2023}],
})


def test_parse_atom_pins_version_normalises_title_and_skips_errors():
    recs = F.parse_atom(ATOM)
    assert set(recs) == {"2305.19118", "2308.07201"}
    r = recs["2305.19118"]
    assert r.versioned_id == "2305.19118v4" and r.year == 2023 and r.first_author_surname == "Liang"
    assert r.title == "Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate"


def test_lookup_batches_and_pauses_between_requests():
    urls, sleeps = [], []

    def get(url):
        urls.append(url)
        return ATOM

    F.lookup([f"id{i}" for i in range(5)], get=get, batch=2, sleep=sleeps.append)
    assert len(urls) == 3 and sleeps == [F.POLITE_DELAY_S] * 2
    assert "id_list=id0%2Cid1" in urls[0]


def test_check_flags_wrong_id_and_missing_id():
    recs = F.parse_atom(ATOM)
    results = F.check([
        cand("2305.19118", "Encouraging divergent thinking in large language models through multi agent debate."),
        cand("2308.07201", "Lost in the Middle: How Language Models Use Long Contexts"),  # id points elsewhere
        cand("9999.99999", "Anything"),
    ], recs)
    assert [r.status for r in results] == ["ok", "title_mismatch", "not_found"]


def test_fetch_refuses_until_every_candidate_is_decided():
    recs = F.parse_atom(ATOM)
    cands = [cand("2305.19118", recs["2305.19118"].title, "keep"), cand("2308.07201", recs["2308.07201"].title)]
    with pytest.raises(F.FetchRefused, match="no decision"):
        F.plan_fetch(cands, F.check(cands, recs), SEED)


def test_fetch_refuses_a_kept_candidate_that_failed_the_check():
    recs = F.parse_atom(ATOM)
    cands = [cand("2308.07201", "Lost in the Middle", "keep")]
    with pytest.raises(F.FetchRefused, match="failed the arXiv check"):
        F.plan_fetch(cands, F.check(cands, recs), SEED)


def test_a_dropped_candidate_may_fail_the_check():
    recs = F.parse_atom(ATOM)
    cands = [cand("2305.19118", recs["2305.19118"].title, "keep"), cand("9999.99999", "Gone", "drop")]
    plan = F.plan_fetch(cands, F.check(cands, recs), SEED)
    assert [e.doc_id for _, _, e in plan] == ["liang-2023"]


def test_plan_gives_readable_unique_ids_and_pinned_sources():
    recs = F.parse_atom(ATOM)
    recs["2308.07201"] = F.ArxivRecord("2308.07201", "v1", recs["2308.07201"].title, 2023, "Du")  # collides
    cands = [cand(i, r.title, "keep") for i, r in recs.items()]
    entries = [e for _, _, e in F.plan_fetch(cands, F.check(cands, recs), SEED)]
    assert [(e.doc_id, e.source, e.filename) for e in entries] == [
        ("liang-2023", "arxiv:2305.19118v4", "liang-2023.pdf"),
        ("du-2023b", "arxiv:2308.07201v1", "du-2023b.pdf"),  # du-2023 is a seed paper
    ]


def test_seed_papers_are_not_fetched_twice():
    rec = F.ArxivRecord("2305.14325", "v1", "Improving Factuality", 2023, "Du")
    cands = [cand("2305.14325", "Improving Factuality", "keep")]
    assert F.plan_fetch(cands, F.check(cands, {"2305.14325": rec}), SEED) == []


def test_download_rejects_non_pdf_and_skips_existing(tmp_path):
    rec = F.parse_atom(ATOM)["2305.19118"]
    cands = [cand("2305.19118", rec.title, "keep")]
    (entry,) = [e for _, _, e in F.plan_fetch(cands, F.check(cands, {"2305.19118": rec}), SEED)]

    with pytest.raises(F.FetchRefused, match="did not return a PDF"):
        F.download([entry], tmp_path, get=lambda url: b"<html>captcha</html>", log=lambda s: None)
    assert not list(tmp_path.iterdir()), "a failed download must not leave a file behind"

    urls = []
    F.download([entry], tmp_path, get=lambda url: urls.append(url) or b"%PDF-1.7 ...", log=lambda s: None)
    assert urls == ["https://arxiv.org/pdf/2305.19118v4"] and (tmp_path / "liang-2023.pdf").exists()
    F.download([entry], tmp_path, get=lambda url: pytest.fail("re-downloaded"), log=lambda s: None)


def test_written_corpus_config_is_valid_and_keeps_the_seeds(tmp_path):
    rec = F.parse_atom(ATOM)["2305.19118"]
    cands = [cand("2305.19118", rec.title, "keep")]
    entries = [e for _, _, e in F.plan_fetch(cands, F.check(cands, {"2305.19118": rec}), SEED)]
    out = tmp_path / "corpus.v1.yaml"
    F.write_corpus_config(SEED, entries, "v1", out)
    cfg = load_corpus_config(out)
    assert cfg.version == "v1" and [d.doc_id for d in cfg.documents] == ["du-2023", "liang-2023"]
    assert out.read_text().startswith("# Corpus v1")


def test_repo_candidate_list_is_valid():
    cands = F.load_candidates("configs/corpus_candidates.yaml")
    assert len(cands) >= 40
    raw = yaml.safe_load(open("configs/corpus_candidates.yaml"))
    assert len(raw["candidates"]) == len(cands)
