"""Command-line entry point.

    tcv ingest          extract, chunk, and index the corpus in configs/corpus.yaml
    tcv search QUERY    hybrid search over the ingested corpus
    tcv pilot           Phase 1 exit gate: draft reports, count aggregative claims
    tcv verify-corpus   recompute source hashes against the manifest
    tcv freeze          freeze the current corpus version
    tcv fetch --check   look up candidate papers on arXiv and confirm their titles
    tcv fetch           download the approved (keep) candidates, write the new corpus config
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
from pathlib import Path

from tcv.corpus.manifest import freeze, verify
from tcv.corpus.pipeline import ingest_corpus
from tcv.corpus.sources import load_corpus_config
from tcv.corpus.store import CorpusStore

DEFAULT_CORPUS = "configs/corpus.yaml"
DEFAULT_DATA = "data"


def _store(args) -> tuple:
    cfg = load_corpus_config(args.config)
    return cfg, CorpusStore(args.data, cfg.version)


def cmd_ingest(args) -> int:
    from tcv.retrieval.embed import SentenceTransformerEmbedder
    from tcv.retrieval.store import build_and_save

    cfg, store = _store(args)
    t0 = time.time()
    manifest = ingest_corpus(cfg, args.data)
    print(f"corpus {cfg.version}: {len(manifest.documents)} documents, {manifest.n_chunks} chunks "
          f"({time.time() - t0:.1f}s)")
    if args.no_index:
        return 0
    t0 = time.time()
    embedder = SentenceTransformerEmbedder(cfg.embed_model, device=args.device)
    index = build_and_save(store.read_chunks(), embedder, args.data, cfg.version)
    print(f"index: {index.meta.n_chunks} × {index.meta.dim} with {cfg.embed_model} ({time.time() - t0:.1f}s)")
    return 0


def cmd_search(args) -> int:
    from tcv.retrieval.store import load_searcher

    cfg, store = _store(args)
    searcher = load_searcher(store.read_chunks(), args.data, cfg.version, cfg.embed_model,
                             device=args.device, dense_weight=args.dense_weight)
    for rank, p in enumerate(searcher.search(args.query, k=args.k), start=1):
        print(f"\n[{rank}] {p.chunk.chunk_id}   score={p.score:.5f}")
        print(textwrap.indent(textwrap.fill(p.chunk.text[: args.chars], width=100), "    "))
    return 0


def cmd_verify(args) -> int:
    cfg, store = _store(args)
    problems = verify(store.read_manifest(), Path(cfg.papers_dir))
    for p in problems:
        print("✗", p)
    print("corpus OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_freeze(args) -> int:
    cfg, store = _store(args)
    m = store.read_manifest()
    problems = verify(m, Path(cfg.papers_dir))
    if problems:
        print("refusing to freeze — sources do not match the manifest:", *problems, sep="\n  ")
        return 1
    store.write_manifest(freeze(m))
    print(f"corpus {cfg.version} frozen ({len(m.documents)} documents, {m.n_chunks} chunks)")
    return 0


def cmd_pilot(args) -> int:
    from tcv.agents.researcher import Researcher
    from tcv.eval.pilot import MIN_AGGREGATIVE_PER_REPORT, prompt_variables, run_pilot
    from tcv.eval.queries import load_queries
    from tcv.llm.gateway import ModelsConfig, load_models_config
    from tcv.llm.pricing import cost_usd
    from tcv.llm.prompts import load_prompt
    from tcv.retrieval.store import load_searcher

    cfg, store = _store(args)
    manifest = store.read_manifest()
    qs = load_queries(args.queries)
    queries = qs.queries if args.query == "all" else (qs.get(args.query),)
    prompt = load_prompt(args.prompt)
    models = load_models_config(args.models)
    if args.model:  # one-off override for this run; the pinned config is untouched
        pinned = models.model_dump()
        pinned["roles"]["synthesizer"]["model"] = args.model
        models = ModelsConfig.model_validate(pinned)  # re-validated: no preview/floating ids
        print(f"note: synthesizer overridden to {args.model} for this run (config pins "
              f"{load_models_config(args.models).roles['synthesizer'].model})")
    role = models.roles["synthesizer"]
    researcher = Researcher(load_searcher(store.read_chunks(), args.data, cfg.version, cfg.embed_model))

    pools = {q.id: researcher.search_pool("st00", [q.text, *q.probes], k_per_query=12, k_total=args.k)
             for q in queries}

    if args.dry_run:
        total = 0.0
        for q in queries:
            system, user = prompt.render(prompt_variables(q.text, pools[q.id], manifest))
            in_tok = (len(system) + len(user)) // 4
            est = cost_usd(role.model, in_tok, args.est_output_tokens)
            total += est
            docs = {p.chunk.doc_id for p in pools[q.id].passages()}
            out = Path(args.data) / "pilot" / q.id
            out.mkdir(parents=True, exist_ok=True)
            (out / "prompt.txt").write_text(f"{system}\n\n=====\n\n{user}", encoding="utf-8")
            print(f"{q.id} [{q.shape:12}] {len(pools[q.id].entries):2} passages from {len(docs)} papers, "
                  f"~{in_tok:,} input tokens, est. ${est:.3f}")
        print(f"\ndry run — no API calls. {len(queries)} report(s) with {role.model}: est. ${total:.2f} "
              f"(assumes ~{args.est_output_tokens:,} output tokens each, incl. thinking). "
              f"Prompts written to {args.data}/pilot/<query>/prompt.txt")
        return 0

    from tcv.llm.cache import ResponseCache
    from tcv.llm.gateway import BudgetExceeded, Gateway, GatewayError
    from tcv.llm.ledger import Ledger
    from tcv.llm.provider import QuotaExhausted, make_provider

    gateway = Gateway(provider=make_provider(models.provider), models=models,
                      cache=ResponseCache(Path(args.data) / "cache" / "responses"),
                      ledger=Ledger(Path(args.data) / "pilot" / "calls.jsonl"))
    passed, failed = 0, []
    for q in queries:
        try:
            a = run_pilot(q.id, q.text, pools[q.id], manifest, gateway, prompt, Path(args.data) / "pilot" / q.id)
        except BudgetExceeded:
            raise
        except GatewayError as e:  # e.g. provider overloaded: keep going, a rerun fills the gap from cache
            failed.append(q.id)
            if isinstance(e.__cause__, QuotaExhausted):
                print(f"{q.id}: stopping — {e.__cause__}")
                failed.extend(x.id for x in queries[queries.index(q) + 1:])
                break
            print(f"{q.id}: FAILED ({e.call_id}) {str(e)[:160]}")
            continue
        passed += a.screen_passed
        print(a.summary())
    done = len(queries) - len(failed)
    print(f"\n{passed}/{done} reports have ≥{MIN_AGGREGATIVE_PER_REPORT} aggregative candidates "
          f"(provisional screen — review the drafts). Spent ${gateway.spent.cost_usd:.3f}. "
          f"Outputs in {args.data}/pilot/<query>/")
    if failed:
        print(f"{len(failed)} failed ({', '.join(failed)}): rerun `tcv pilot` — finished drafts come from cache")
        return 1
    return 0


def cmd_fetch(args) -> int:
    from tcv.corpus import fetch as F

    seed = load_corpus_config(args.config)
    cands = F.load_candidates(args.candidates)
    print(f"looking up {len(cands)} candidates on arXiv …")
    results = F.check(cands, F.lookup(c.arxiv for c in cands))
    for r in results:
        c = r.candidate
        mark = {"ok": "ok  ", "title_mismatch": "DIFF", "not_found": "MISS"}[r.status]
        flag = " (was flagged verify)" if c.verify else ""
        print(f"{mark} {c.arxiv:<11} {c.decision or '—':<5} {c.title[:70]}{flag}")
        if r.status == "title_mismatch":
            print(f"     arXiv title: {r.record.title[:90]}  (similarity {r.similarity:.2f})")
    n_bad = sum(r.status != "ok" for r in results)
    print(f"\n{len(results) - n_bad}/{len(results)} candidates confirmed; {n_bad} need a corrected id or a drop.")
    if args.check:
        return 0 if n_bad == 0 else 1

    try:
        plan = F.plan_fetch(cands, results, seed)
    except F.FetchRefused as e:
        print(f"\nnot fetching: {e}")
        return 1
    entries = [e for _, _, e in plan]
    print(f"\nfetching {len(entries)} kept paper(s) into {seed.papers_dir}/ (pinned versions) …")
    F.download(entries, seed.papers_dir)
    cfg = F.write_corpus_config(seed, entries, args.version, args.out)
    print(f"\nwrote {args.out} ({len(cfg.documents)} documents, version {cfg.version}). Next:\n"
          f"  uv run tcv --config {args.out} ingest\n  uv run tcv --config {args.out} freeze")
    return 0


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="tcv", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CORPUS, help="corpus config (default: %(default)s)")
    ap.add_argument("--data", default=DEFAULT_DATA, help="data root (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="extract, chunk and index the corpus")
    p.add_argument("--no-index", action="store_true", help="skip building the search index")
    p.add_argument("--device", default="cpu", help="embedding device; cpu is deterministic")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("search", help="hybrid search over the corpus")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=8)
    p.add_argument("--dense-weight", type=float, default=0.6)
    p.add_argument("--device", default="cpu")
    p.add_argument("--chars", type=int, default=400, help="characters of each hit to print")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("pilot", help="Phase 1 exit gate: draft reports and count aggregative claims")
    p.add_argument("--query", default="all", help="query id from the query set, or 'all'")
    p.add_argument("--queries", default="configs/queries.yaml")
    p.add_argument("--models", default="configs/models.yaml")
    p.add_argument("--model", help="override the synthesizer model for this run only")
    p.add_argument("--prompt", default="pilot/draft@1")
    p.add_argument("-k", type=int, default=30, help="passages per report")
    p.add_argument("--dry-run", action="store_true", help="build pools and prompts, estimate cost, call nothing")
    p.add_argument("--est-output-tokens", type=int, default=4000, help="output estimate for --dry-run")
    p.set_defaults(fn=cmd_pilot)

    sub.add_parser("verify-corpus", help="check source files against manifest hashes").set_defaults(fn=cmd_verify)
    sub.add_parser("freeze", help="freeze the current corpus version").set_defaults(fn=cmd_freeze)

    p = sub.add_parser("fetch", help="check/download approved candidate papers from arXiv (D-3)")
    p.add_argument("--check", action="store_true", help="only look up ids and confirm titles; download nothing")
    p.add_argument("--candidates", default="configs/corpus_candidates.yaml")
    p.add_argument("--version", default="v1", help="version of the corpus config to write")
    p.add_argument("--out", default="configs/corpus.v1.yaml")
    p.set_defaults(fn=cmd_fetch)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
