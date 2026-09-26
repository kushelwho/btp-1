"""Command-line entry point.

    tcv ingest          extract, chunk, and index the corpus in configs/corpus.yaml
    tcv search QUERY    hybrid search over the ingested corpus
    tcv pilot           Phase 1 exit gate: draft reports, count aggregative claims
    tcv verify-corpus   recompute source hashes against the manifest
    tcv freeze          freeze the current corpus version
    tcv fetch --check   look up candidate papers on arXiv and confirm their titles
    tcv fetch           download the approved (keep) candidates, write the new corpus config
    tcv run             full pipeline for one condition: plan, research, draft, check, revise
    tcv base ...        base drafts for planted-error tests: add, list, review, verify
    tcv seed preview    show the errors planted into a base draft, original beside corrupted
    tcv sweep run|report   planted-error sweep from a YAML config; metrics and report
    tcv dynamics        what each revision round achieved, for finished runs
    tcv gold propose|confirm   gold passages per query, for oracle retrieval
    tcv inspect         HTML page per run (or sweep pass): claims coloured by verdict, passages on hover
    tcv judge-compare   re-check a finished round's claims with another judge model; agreement + speed
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

    gateway = Gateway(provider=make_provider(models.provider, models), models=models,
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


def _condition_path(cond: str) -> Path:
    p = Path(cond)
    if p.suffix in {".yaml", ".yml"}:
        return p
    exact = Path("configs/conditions") / f"{cond}.yaml"  # e.g. A-oracle.yaml
    if exact.exists():
        return exact
    matches = sorted(Path("configs/conditions").glob(f"{cond}_*.yaml"))
    if len(matches) != 1:
        raise SystemExit(f"no unique condition file for {cond!r} in configs/conditions/")
    return matches[0]


def run_id_for(query_id: str, condition: str, chash: str, corpus_version: str, seed: int) -> str:
    import hashlib

    return "run_" + hashlib.sha256(f"{query_id}|{condition}|{chash}|{corpus_version}|{seed}".encode()).hexdigest()[:12]


def _summarise(run) -> str:
    from collections import Counter

    last = run.rounds[-1] if run.rounds else None
    per_round = " → ".join(
        f"r{r.round}: {sum(v.is_failure for v in r.verdicts)}/{len(r.verdicts)} failing" for r in run.rounds)
    kinds = Counter(v.kind.value for v in last.verdicts) if last else {}
    return (f"{run.query_id} [{run.run_id}] stop={run.stop_reason or 'incomplete'} · {per_round or 'no rounds'}"
            f"{' · final: ' + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) if kinds else ''}"
            f" · ${run.total_usage.cost_usd:.4f}, {run.total_usage.n_calls} calls")


def cmd_run(args) -> int:
    import yaml

    from tcv.agents.planner import Planner
    from tcv.agents.researcher import Researcher
    from tcv.agents.synthesizer import Synthesizer
    from tcv.checker.pipeline import Checker
    from tcv.config import config_hash, load_run_config, resolved
    from tcv.eval.queries import load_queries
    from tcv.llm.cache import ResponseCache
    from tcv.llm.gateway import Gateway, GatewayError, load_models_config
    from tcv.llm.ledger import Ledger
    from tcv.llm.prompts import load_prompt
    from tcv.llm.provider import QuotaExhausted, make_provider
    from tcv.orchestrator.loop import Orchestrator, RunIncomplete, RunMeta
    from tcv.orchestrator.state import StateStore
    from tcv.eval.gold import load_gold
    from tcv.retrieval.store import load_searcher

    run_cfg = load_run_config(_condition_path(args.condition), args.base)
    if args.models:
        run_cfg = run_cfg.model_copy(update={"models": args.models})
    models_text = Path(run_cfg.models).read_text(encoding="utf-8")
    models = load_models_config(run_cfg.models)
    chash = config_hash(run_cfg, models_text)

    corpus_cfg, corpus_store = _store(args)
    manifest = corpus_store.read_manifest()
    if not manifest.frozen:
        print(f"note: corpus {corpus_cfg.version} is not frozen — development run, not a reportable result")
    qs = load_queries(args.queries)
    queries = qs.queries if args.query == "all" else tuple(qs.get(q) for q in args.query.split(","))

    prompts = {name: load_prompt(ref) for name, ref in {
        "plan": "planner@1", "queries": "researcher/queries@1", "draft": "synthesizer/draft@1",
        "revise": "synthesizer/revise@1", "atomize": "checker/atomize@1", "t1": "checker/verify_t1@1"}.items()}
    searcher = load_searcher(corpus_store.read_chunks(), args.data, corpus_cfg.version, corpus_cfg.embed_model)
    provider = make_provider(models.provider, models)
    cache = ResponseCache(Path(args.data) / "cache" / "responses")

    failed = 0
    for q in queries:
        run_id = run_id_for(q.id, run_cfg.condition, chash, corpus_cfg.version, args.seed)
        store = StateStore(args.data, run_id)
        if store.is_complete() and not args.force:
            print(_summarise(store.load_run()) + "  (already complete)")
            continue
        store.write_text("config.resolved.yaml", yaml.safe_dump(
            {**resolved(run_cfg), "config_hash": chash, "corpus_version": corpus_cfg.version,
             "models_file": models_text}, sort_keys=False))
        gateway = Gateway(provider=provider, models=models, cache=cache, ledger=Ledger(store.ledger_path),
                          run_id=run_id)
        orch = Orchestrator(
            planner=Planner(gateway, prompts["plan"], run_cfg.planner),
            researcher=Researcher(searcher, gateway, prompts["queries"], run_cfg.retrieval,
                                  gold=load_gold(q.id) if run_cfg.retrieval.oracle else None),
            synthesizer=Synthesizer(gateway, prompts["draft"], prompts["revise"], manifest, run_cfg.synthesizer),
            checker=Checker(gateway, run_cfg.checker, prompts["atomize"], prompts["t1"]),
            gateway=gateway, store=store, config=run_cfg.loop)
        try:
            run = orch.run(RunMeta(run_id=run_id, query_id=q.id, query=q.text, condition=run_cfg.condition,
                                   config_hash=chash, corpus_version=corpus_cfg.version, seed=args.seed))
        except (GatewayError, RunIncomplete) as e:
            failed += 1
            print(f"{q.id} [{run_id}] INCOMPLETE — {str(e)[:200]}\n  rerun the same command to resume from cache")
            if isinstance(e.__cause__, QuotaExhausted):
                print("stopping: daily quota exhausted")
                break
            continue
        print(_summarise(run) + f"\n  report: {store.root / 'report.md'}")
    return 1 if failed else 0


def cmd_base(args) -> int:
    from tcv.eval import base as B
    from tcv.eval.queries import load_queries
    from tcv.orchestrator.state import StateStore
    from tcv.schemas import Draft, RetrievalPool

    store = B.BaseDraftStore(args.data)
    if args.action == "add":
        qs = load_queries(args.queries)
        if args.run:
            run = StateStore(args.data, args.run).load_run()
            base = B.from_run(run, qs.get(run.query_id).text, round_=args.round, base_id=args.id)
        elif args.pilot:
            d = Path(args.data) / "pilot" / args.pilot
            base = B.from_pilot(args.pilot, qs.get(args.pilot).text,
                                Draft.model_validate_json((d / "draft.json").read_text()),
                                RetrievalPool.model_validate_json((d / "pool.json").read_text()), base_id=args.id)
        else:
            raise SystemExit("give --run <run_id> or --pilot <query_id>")
        if store.path(base.base_id).exists() and not args.force:
            raise SystemExit(f"{base.base_id} exists (use --force to replace it)")
        print(f"saved {store.save(base)} — {len(base.draft.sentences)} sentences, unverified")
        (store.root / f"{base.base_id}.review.md").write_text(B.review_sheet(base), encoding="utf-8")
        print(f"review sheet: {store.root / (base.base_id + '.review.md')}")
    elif args.action == "list":
        for b in store.list():
            state = f"verified by {b.verified_by}" if b.verified else "UNVERIFIED"
            print(f"{b.base_id:24} {len(b.draft.sentences):3} sentences  {state:22} {b.source}")
    elif args.action == "review":
        b = store.load(args.base_id)
        out = store.root / f"{b.base_id}.review.md"
        out.write_text(B.review_sheet(b), encoding="utf-8")
        print(out)
    elif args.action == "verify":
        b = B.verify(store.load(args.base_id), by=args.by, drop=[x for x in (args.drop or "").split(",") if x],
                     notes=args.notes or "")
        store.save(b)
        print(f"{b.base_id}: verified by {b.verified_by}, {len(b.draft.sentences)} sentences kept, "
              f"dropped {list(b.dropped_sentences) or 'none'}")
    return 0


def cmd_seed(args) -> int:
    from tcv.eval import base as B
    from tcv.eval import seed as S
    from tcv.schemas import ErrorClass

    base = B.BaseDraftStore(args.data).load(args.base_id)
    classes = [ErrorClass(c) for c in args.classes.split(",")] if args.classes else list(S.RULE_BASED)
    if args.e9 and ErrorClass.E9_INTERNAL not in classes:
        classes.append(ErrorClass.E9_INTERNAL)
    rep = S.inject(base, seed=args.seed, classes=classes, max_errors=args.max_errors,
                   e9_pairs=S.load_e9_pairs(args.e9) if args.e9 else None)
    if not base.verified:
        print(f"note: {base.base_id} is UNVERIFIED — fine for a preview, not for results\n")
    for e in rep.seeded.errors:
        print(f"{e.error_class.value:>3} {'/'.join(e.sentence_ids)}  ({rep.notes[e.error_id]})")
        if e.original:
            print(f"    before: {e.original}")
        print(f"    after:  {e.corrupted}\n")
    if rep.not_applicable:
        print("no sentence could take: " + ", ".join(c.value for c in rep.not_applicable))
    return 0


def cmd_sweep(args) -> int:
    from tcv.eval.runner import Sweep, load_sweep

    cfg = load_sweep(args.config)
    sweep = Sweep(cfg, args.data)
    if args.action == "report":
        metrics, report = sweep.report()
        print(f"{metrics}\n{report}")
        return 0

    from tcv.checker.pipeline import Checker
    from tcv.config import load_run_config
    from tcv.llm.cache import ResponseCache
    from tcv.llm.gateway import Gateway, load_models_config
    from tcv.llm.ledger import Ledger
    from tcv.llm.prompts import load_prompt
    from tcv.llm.provider import make_provider

    models = load_models_config(args.models)
    gateway = Gateway(provider=make_provider(models.provider, models), models=models,
                      cache=ResponseCache(Path(args.data) / "cache" / "responses"),
                      ledger=Ledger(sweep.root / "calls.jsonl"), run_id=None, budget_usd=args.budget)
    atomize, t1 = load_prompt("checker/atomize@1"), load_prompt("checker/verify_t1@1")

    def checker_for(cond: str):
        run_cfg = load_run_config(_condition_path(cond), args.base)
        return run_cfg.condition, Checker(gateway, run_cfg.checker, atomize, t1)

    prog = sweep.run(checker_for)
    print(f"\n{prog.done} passes done, {prog.skipped} already done, {len(prog.incomplete)} to re-run"
          + (f", stopped: {prog.stopped}" if prog.stopped else "")
          + (f"\nunverified base drafts: {', '.join(sorted(set(prog.unverified)))}" if prog.unverified else ""))
    if prog.done or prog.skipped:
        metrics, report = sweep.report()
        print(f"report: {report}")
    return 1 if prog.incomplete or prog.stopped else 0


def cmd_dynamics(args) -> int:
    import json

    from tcv.eval.dynamics import render_table, run_dynamics
    from tcv.orchestrator.state import StateStore

    runs_dir = Path(args.data) / "runs"
    ids = args.run or sorted(p.parent.name for p in runs_dir.glob("*/run.json"))
    shown = 0
    for rid in ids:
        store = StateStore(args.data, rid)
        run = store.load_run()
        if run.stop_reason is None and not args.run:
            continue  # unfinished runs only when asked for by id
        rows = run_dynamics(run)
        print(render_table(run, rows) + "\n")
        store.write_json("dynamics.json", [r.__dict__ for r in rows])
        shown += 1
    if not shown:
        print("no finished runs yet")
    return 0


def cmd_gold(args) -> int:
    import yaml

    from tcv.eval import gold as G
    from tcv.eval.queries import load_queries

    q = load_queries(args.queries).get(args.query)
    if args.action == "propose":
        from tcv.retrieval.store import load_searcher

        cfg, store = _store(args)
        searcher = load_searcher(store.read_chunks(), args.data, cfg.version, cfg.embed_model)
        hits: dict = {}
        for text in (q.text, *q.probes):
            for p in searcher.search(text, k=args.k):
                if p.chunk_id not in hits or p.score > hits[p.chunk_id].score:
                    hits[p.chunk_id] = p
        ranked = sorted(hits.values(), key=lambda p: (-p.score, p.chunk_id))
        out = G.candidates_path(args.data, q.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(G.propose(q.id, q.text, ranked, G.pools_from_runs(args.data, q.id)), encoding="utf-8")
        print(f"{out} — mark keep: true on the passages a good report needs, then `tcv gold confirm`")
    else:
        gold = G.confirm(G.candidates_path(args.data, q.id), by=args.by)
        path = G.gold_path(q.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Gold passages for {q.id} (oracle retrieval). Confirmed by a person; tracked in git.\n"
                        + yaml.safe_dump(gold, sort_keys=False), encoding="utf-8")
        print(f"{path}: {len(gold['chunks'])} gold passages")
    return 0


def cmd_inspect(args) -> int:
    from tcv.inspect.html import render

    if args.sweep:
        from tcv.checker.pipeline import CheckResult
        from tcv.eval.base import BaseDraftStore
        from tcv.eval.runner import Sweep, load_sweep

        sweep = Sweep(load_sweep(args.sweep), args.data)
        base = BaseDraftStore(args.data).load(args.base_id)
        name = "clean" if args.seed is None else f"seed{args.seed}"
        path = sweep.root / args.condition / base.base_id / f"{name}.json"
        r = CheckResult.model_validate_json(path.read_text(encoding="utf-8"))
        planted = sweep.seeded(base.base_id, args.seed) if args.seed is not None else None
        draft = planted.draft if planted else base.draft
        passages = {p.chunk_id: p for pool in base.pools for p in pool.passages()}
        page = render(f"{base.base_id} · {name} · condition {args.condition}", draft, r.claims, r.verdicts, passages,
                      subtitle=base.query, planted=planted)
        out = path.with_suffix(".html")
    else:
        from tcv.eval.queries import load_queries
        from tcv.orchestrator.state import StateStore

        store = StateStore(args.data, args.run)
        run = store.load_run()
        rs = run.rounds[-1] if args.round is None else next(x for x in run.rounds if x.round == args.round)
        passages = {p.chunk_id: p for pool in run.pools for p in pool.passages()}
        query = load_queries(args.queries).get(run.query_id).text
        page = render(query, rs.draft, rs.claims, rs.verdicts, passages,
                      subtitle=f"{run.query_id} · {run.run_id} · condition {run.condition} · round {rs.round} of "
                               f"{len(run.rounds)} · stop: {run.stop_reason or 'incomplete'}")
        out = store.root / (f"inspect-r{rs.round}.html" if args.round else "inspect.html")
    out.write_text(page, encoding="utf-8")
    print(out)
    return 0


def cmd_judge_compare(args) -> int:
    """Same claims, same passages, a different judge: how far do the verdicts agree?"""
    import time

    from tcv.checker.verify_t1 import verify_t1
    from tcv.config import load_run_config
    from tcv.eval.agreement import cohen_kappa, render
    from tcv.llm.cache import ResponseCache
    from tcv.llm.gateway import Gateway, load_models_config
    from tcv.llm.ledger import Ledger
    from tcv.llm.prompts import load_prompt
    from tcv.llm.provider import make_provider
    from tcv.orchestrator.state import StateStore
    from tcv.schemas import VerdictKind

    store = StateStore(args.data, args.run)
    rs = next(r for r in store.load_rounds() if r.round == args.round)
    passages = {p.chunk_id: p for pool in store.load_pools() for p in pool.passages()}
    old = {v.claim_id: v for v in rs.verdicts}
    claims = [c for c in rs.claims if old[c.claim_id].kind is not VerdictKind.ERROR][: args.limit]
    models = load_models_config(args.models)
    ledger_path = store.root / f"judge-compare-{Path(args.models).stem}.jsonl"
    gw = Gateway(provider=make_provider(models.provider, models), models=models,
                 cache=ResponseCache(Path(args.data) / "cache" / "responses"), ledger=Ledger(ledger_path))
    ck = load_run_config(_condition_path("A"), args.base).checker
    batch = args.batch or ck.batch_size
    t0 = time.monotonic()
    new = verify_t1(gw, load_prompt("checker/verify_t1@1"), claims, passages, batch_size=batch,
                    uncertain_below=ck.uncertain_below)
    wall = time.monotonic() - t0
    pairs = [(old[c.claim_id].kind.value, v.kind.value) for c, v in zip(claims, new) if v.kind is not VerdictKind.ERROR]
    agr = cohen_kappa([a for a, _ in pairs], [b for _, b in pairs])
    print(render(agr, "reference", models.roles["judge"].model))
    errored = sum(v.kind is VerdictKind.ERROR for v in new)
    out_tokens = gw.spent.output_tokens
    print(f"\n{len(claims)} claims in batches of {batch}: {wall / 60:.1f} min wall, {gw.spent.n_calls} calls, "
          f"{out_tokens:,} output tokens ({out_tokens / wall:.1f} tok/s incl. prompt reading), {errored} failed checks")
    flipped = [(c, old[c.claim_id], v) for c, v in zip(claims, new)
               if v.kind is not VerdictKind.ERROR and v.kind != old[c.claim_id].kind]
    if flipped:
        print(f"\n{len(flipped)} disagreements (reference → new):")
        for c, a, b in flipped[: args.show]:
            print(f"- {a.kind.value} → {b.kind.value}: {c.text[:140]}")
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

    p = sub.add_parser("run", help="run the full pipeline for one condition on one or more queries")
    p.add_argument("--query", default="all", help="query id(s), comma-separated, or 'all'")
    p.add_argument("--condition", default="A", help="condition letter (configs/conditions/<X>_*.yaml) or a path")
    p.add_argument("--base", default="configs/run/base.yaml")
    p.add_argument("--models", help="override the model config (changes the config hash, so a new run)")
    p.add_argument("--queries", default="configs/queries.yaml")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--force", action="store_true", help="re-run even if the run is complete (replays from cache)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("base", help="base drafts for planted-error tests")
    bsub = p.add_subparsers(dest="action", required=True)
    b = bsub.add_parser("add", help="capture a run's (or the pilot's) draft as an unverified base draft")
    b.add_argument("--run")
    b.add_argument("--round", type=int)
    b.add_argument("--pilot", help="query id of a pilot draft")
    b.add_argument("--id", help="base id (default derived from the source)")
    b.add_argument("--queries", default="configs/queries.yaml")
    b.add_argument("--force", action="store_true")
    bsub.add_parser("list", help="list base drafts")
    b = bsub.add_parser("review", help="write the review sheet for a base draft")
    b.add_argument("base_id")
    b = bsub.add_parser("verify", help="mark a base draft clean, dropping sentences found wrong")
    b.add_argument("base_id")
    b.add_argument("--by", required=True)
    b.add_argument("--drop", help="comma-separated sentence ids to remove")
    b.add_argument("--notes")
    p.set_defaults(fn=cmd_base)

    p = sub.add_parser("seed", help="planted errors")
    ssub = p.add_subparsers(dest="action", required=True)
    b = ssub.add_parser("preview", help="show the errors planted into a base draft")
    b.add_argument("base_id")
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--classes", help="comma-separated, e.g. E1,E5,E6 (default: all rule-based)")
    b.add_argument("--max-errors", type=int, default=8)
    b.add_argument("--e9", help="YAML file of human-written E9 pairs")
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser("sweep", help="planted-error sweeps")
    wsub = p.add_subparsers(dest="action", required=True)
    for action, text in (("run", "run (or resume) a sweep, then write its report"), ("report", "rewrite the report")):
        b = wsub.add_parser(action, help=text)
        b.add_argument("config", help="configs/sweeps/<name>.yaml")
        b.add_argument("--models", default="configs/models.yaml")
        b.add_argument("--base", default="configs/run/base.yaml")
        b.add_argument("--budget", type=float, default=5.0, help="spending cap for this invocation (list prices)")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("dynamics", help="per-round loop dynamics of finished runs")
    p.add_argument("run", nargs="*", help="run ids (default: every finished run)")
    p.set_defaults(fn=cmd_dynamics)

    p = sub.add_parser("gold", help="gold passages for oracle retrieval")
    gsub = p.add_subparsers(dest="action", required=True)
    b = gsub.add_parser("propose", help="write candidate passages for a person to mark")
    b.add_argument("--query", required=True)
    b.add_argument("-k", type=int, default=15, help="search hits per query text")
    b.add_argument("--queries", default="configs/queries.yaml")
    b = gsub.add_parser("confirm", help="turn the marked candidates into configs/gold/<query>.yaml")
    b.add_argument("--query", required=True)
    b.add_argument("--by", required=True)
    b.add_argument("--queries", default="configs/queries.yaml")
    p.set_defaults(fn=cmd_gold)

    p = sub.add_parser("inspect", help="HTML inspector for a run, or for one pass of a sweep")
    p.add_argument("run", nargs="?", help="run id")
    p.add_argument("--round", type=int, help="round to show (default: the last)")
    p.add_argument("--queries", default="configs/queries.yaml")
    p.add_argument("--sweep", help="sweep config, to inspect one of its passes instead of a run")
    p.add_argument("--condition", default="A")
    p.add_argument("--base-id")
    p.add_argument("--seed", type=int, help="planted pass to show (omit for the clean pass)")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("judge-compare", help="re-check a round's claims with another judge; agreement and speed")
    p.add_argument("run", help="run id whose round to re-check")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--models", default="configs/models.local.yaml")
    p.add_argument("--base", default="configs/run/base.yaml")
    p.add_argument("--batch", type=int, help="claims per call (default: the run config's batch size)")
    p.add_argument("--limit", type=int, help="only the first N claims (a quick speed test)")
    p.add_argument("--show", type=int, default=15, help="disagreements to print")
    p.set_defaults(fn=cmd_judge_compare)

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
