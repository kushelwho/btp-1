# Phase 3 — Evaluation Harness

**Started:** 2026-09-26 · **Goal:** build the measuring instrument *before* the mechanisms it measures. Building it after is how a mechanism gets unconsciously fitted to its test.

**Exit gate:** the harness generates every error class, the runner executes condition A, and metrics come out the far end.

**Working offline:** billing is being sorted out, so everything is built and tested without live model calls (scripted fake model and hand-built drafts). Live shakedowns wait for quota.

**State at last update (2026-09-27):** everything in Phase 3 that doesn't need a live model is built and tested (279 fast tests, import rules hold). What's left needs people or live calls: the team's reviews (base drafts, planted errors, guideline, gold passages) and a live sweep.

## Claude

### Base drafts
- [x] Base-draft store: take a finished run's (or the pilot's) draft plus its evidence pools; unverified until a person confirms it's clean
- [x] Checker carries a verdict over only when the sentence is *textually identical* (not just the same ID), so a corrupted sentence can never inherit its clean verdict

### Planted errors (ER-1)
- [x] Generator framework: reproducible by seed, ≤1 error per sentence, ~8 errors per draft, a ground-truth record for every injection
- [x] Rule-based generators: E1 numbers · E2 citation swap · E3 fabricated insertion · E4 negation/antonym · E5 over-generalisation · E6 miscount · E7 false contrast · E8 reversed trend · E10 hedge strengthening (≥2 steps up the strength ladder, checked by the lexicon)
- [x] E9 (two claims contradicting each other): human-written pairs from `configs/seeds/e9_pairs.yaml` (format documented; empty until written) — [ ] model-written generator later
- [x] Every generator tested on hand-built sentences, including where it must *not* fire

### Metrics (ER-2 to ER-4, ER-11)
- [x] Catch rate per error class (a catch = an expected verdict on the right sentence), never pooled into one number
- [x] "Flag rate" beside it: *any* failing verdict on the planted sentence, so an incidental catch by the baseline is visible rather than defined away
- [x] False-alarm rate on clean drafts, by claim type; abstentions counted separately
- [x] Verdict confusion matrix (error class × verdict), including the E2-vs-E3 split
- [x] 95% bootstrap confidence intervals over drafts

### Runner (ER-8)
- [x] Sweep config: base drafts × seeds × conditions × error classes, one YAML file
- [x] Single checking pass per planted draft (not the full loop); untouched claims reuse the clean pass, so only planted sentences cost calls
- [x] Resumable; results and metrics written under `data/results/<sweep>/`
- [x] `tcv sweep run` / `tcv sweep report`

### Oracle retrieval (ER-5)
- [x] Gold-passage file per query; oracle mode builds pools from gold passages instead of search
- [x] Helper that proposes candidate gold passages for the team to confirm

### Loop dynamics (ER-7)
- [x] Per round: claims resolved, failures persisting, new failures on sentences nobody touched (displacement), cost

### Inspector (FR-13.1)
- [x] `tcv inspect <run>` (or `--sweep … --base-id … --seed N` for a planted pass) → one self-contained HTML page: claims colour-coded by verdict; hover shows the passage and the checker's reason; planted errors marked

### Local models (budget path B — added 2026-09-27)
- [x] Ollama provider: explicit context window (refuses rather than silently truncates), thinking only for roles with an effort, schema-constrained JSON, seed fixed, model build (digest) recorded and pinnable
- [x] Batches too long for the local window split in half automatically, like batches cut off at the output limit
- [x] `configs/models.local.yaml` (qwen3:8b everywhere; thinking on for checking claims only)
- [x] `tcv judge-compare <run>` — re-checks a finished round's claims with another judge; Cohen's κ, disagreements, speed
- [ ] Team: Ollama running + `ollama pull qwen3:8b` (Ollama is installed via Homebrew; start it with `brew services start ollama`)
- [ ] Measure real speed and judge agreement: `uv run tcv judge-compare run_0af72cde707f` (75 claims Gemini checked without error), then pin the digest in `models.local.yaml`

### Annotation guideline (AR-1)
- [x] Draft guideline for T1–T4 with ≥5 worked examples per type and tie-breaking rules — `annotation_guideline.md` (real draft sentences where they exist; T3/T4 examples are marked as constructed, because real drafts almost never signpost or flag inference)

## Team (blocking)
- [ ] 🔴 Sanity-check the planted errors once generated: are the corruptions realistic? (E7 and E9 are the easiest to get wrong)
- [ ] 🔴 Verify base drafts are clean — review sheets are ready: `data/base_drafts/q02-dev.review.md`, `q02-pilot.review.md`
- [ ] 🔴 Approve the annotation guideline — frozen before any labelling, or κ measures nothing
- [ ] 🔴 **D-3** corpus keep/drop (carried over)

## Team (non-blocking)
- [ ] 🟡 **D-4** — confirm the two-annotator protocol and schedule Phase 4's session
- [ ] 🟡 Gold passages per query for the oracle runs (the helper proposes candidates; you confirm)
- [ ] 🔵 Heads-up: Phase 4 needs ~4 h from each of two annotators, labelling separately and blind to the model. Book it now

## Blocked / open
- **Phase 3's exit gate needs one live sweep:** `uv run tcv sweep run configs/sweeps/phase3-dev.yaml` (≈ 2 clean passes + 6 planted passes; judge calls ≈ 2×3 + 6×1). Waiting on the Gemini billing issue.
- Phase 2's exit gate (condition A on all 10 queries) still waits on live calls too.
- **E9 needs human-written pairs** in `configs/seeds/e9_pairs.yaml` before it can be measured (none yet).

## Ready for the team (no model needed)
- `data/base_drafts/q02-dev.review.md` and `q02-pilot.review.md` — review each sentence against its passages, then `uv run tcv base verify <id> --by <name> --drop <ids>`
- `uv run tcv seed preview q02-pilot --seed 0` — are the planted errors realistic?
- `annotation_guideline.md` — approve or change, then it's frozen
- `data/gold/candidates/q02.yaml` — mark `keep: true`, then `uv run tcv gold confirm --query q02 --by <name>`
- `data/runs/run_0af72cde707f/inspect-r1.html` — open in a browser to see the inspector on the live run

## Observations (Phase 3)
- **Previewed on the two real q02 drafts** (`tcv seed preview`): the pilot draft takes all 9 rule-based classes, the dev draft 8 (it has no count phrases, so E6 has nothing to change). Four rules were widened after reading real sentences: E1 now skips 0, rating scales and math, and prefers results over small integers; E7 also turns "frameworks like X do Y" into "Unlike X, frameworks do Y"; E8 also invents trends for "recent literature/work"; E10 adds an overclaiming lead-in to plain result sentences, because real drafts hedge rarely.
- **Real drafts hedge very little** — confirmed by reading them, so the atomizer's "98 of 99 claims are plain statements" was accurate, not a bug.
- A bug the new tests caught: when a re-checked draft had the same round number as its clean pass (always true for planted drafts), new claim IDs collided with carried-over ones and verdicts were mixed up. Fixed, with a uniqueness assertion.

## Deviations from `architecture.md` (Phase 3)
(numbering continues)

24. **False-alarm rate is per claim, not per sentence** — a sentence has no single type, its claims do.
25. **A "flag rate" is reported beside the catch rate**: any definite failing verdict on a planted sentence. Without it, a baseline's incidental flag (e.g. condition A calling an overclaim "unsupported") would be defined away by the expected-verdict set; with it, the prediction "A scores zero on E10" is tested rather than true by construction.
26. **Planted passes reuse the clean pass** for untouched sentences (carry-over by identical text), so each planted draft costs only its changed sentences. Valid for per-claim checks; conditions that compare claims with each other (E) will re-evaluate pairs involving changed sentences.
27. **Base drafts are cleaned by *dropping* sentences a reviewer finds wrong**, never by rewriting them, so a base stays a genuine model draft.
28. **Inserted sentences (E3, E9) get IDs `r<round>s9000` upward**, so they never collide with a real draft sentence.
29. **Gold passages live in `configs/gold/` (tracked in git)**, not `data/gold/`: they're human judgments, not regenerable data. Candidate lists stay in `data/`.
30. **An oracle pool holds all of a question's gold passages in every sub-task's pool**, ordered by match to that sub-task, rather than splitting the gold set between sub-tasks.
31. **Oracle retrieval is a condition file (`A-oracle`)**, not a runner flag, so oracle runs get their own config hash and run IDs.
32. **The inspector is a static HTML file per run or pass** (no server), openable anywhere.
33. **Displacement is 0 by construction under per-claim checks (A–D)**: untouched sentences are identical and their verdicts carry over. It becomes a real measurement with condition E. Errors a revision introduces into its own replacement are counted as "persisting".
34. **Budget path B (local models) added alongside path A**, not instead of it: a third provider behind the same interface, chosen per run by `--models configs/models.local.yaml`. Local model tags ("qwen3:8b") are priced at $0; unknown cloud models still raise.

---

# Phase 2 — Pipeline and Baseline Checker (code complete; exit gate waits on live runs)

**Started:** 2026-09-26 · **Goal:** the whole loop running end to end with the *standard* checker (every claim checked against its cited passage, nothing else). This is **ablation condition A**, the baseline every later mechanism must beat.

**Exit gate:** condition A runs end to end on all 10 queries and produces cited reports with a verdict for every claim.

**State at last update (2026-09-26):** the whole condition-A pipeline is built and tested (225 fast tests, import rules hold). The first live run completed round 1 on a real draft, then hit the free-tier quota. Billing stays off (D-8), so the pipeline now fits the free tier: condition A on all 10 queries takes ~3 days of daily runs.

## Claude

### Agents
- [x] Planner: question → 5–8 sub-tasks (structured output, count bounded by config)
- [x] Researcher: model-written search queries per sub-task, then hybrid search; full pools kept, citation flags updated after each draft
- [x] Synthesizer `draft`: report from the pools with mandatory `[[chunk_id]]` citations; one regeneration if factual sentences come back uncited
- [x] Synthesizer `revise`: rewrites **only** the sentences named in the fix-list; every other sentence stays byte-identical (checked after every round)

### Checker, condition A
- [x] Atomizer: sentences → claims, **wording strength (modality) kept**, batched; every sentence yields a claim (condition A must not quietly skip signposting)
- [x] T1 check: each claim against its cited passages only, blind to the rest of the draft; batched; abstains below a confidence threshold
- [x] Fix-list (revision payload) built from failing verdicts
- [x] Checker config flags for conditions B–F exist; turning on an unbuilt one fails loudly instead of doing nothing

### Loop and runs
- [x] Orchestrator: plan → research → draft → (check → revise) × N, stopping on resolved / max rounds / budget
- [x] Every round persisted (draft, claims, verdicts, fix-list, cost) so a run replays offline
- [x] Escalation labels on whatever is still unresolved; `report.md` rendered per run
- [x] Run config (base + condition overlay) with a hash recorded in every run; runs resumable
- [x] `tcv run --query <id|all> --condition A`
- [x] End-to-end tests with a scripted fake model (`tests/unit/test_condition_a.py`, 13 tests: resolve after revision, escalation at max rounds, budget stop, resume from cache, failed checks, uncited retry, untouched check, …)
- [~] Live run of condition A on one query — **round 1 complete** on the dev models (q02: 50 sentences → 99 claims → 56 supported, 18 unsupported, 1 contradicted, 24 check failures from Google overload/quota). The revision step stopped on the daily quota; rerunning the same command resumes from cache
- [x] Free-tier fit: roles spread over three models, larger batches (40 checks / 50 sentences per call), one widely spaced retry on "busy", quota errors stop a run cleanly, failed checks leave it resumable
- [ ] Condition A on all 10 queries — **exit gate**; at ~4 runs per day on the free tier, about 3 days of `uv run tcv run --query all --condition A`

## Team (blocking)
- [x] **D-8** — billing stays **off** (2026-09-26). The project runs on the free tier; see Decisions for how it fits
- [ ] 🟡 Check the Gemma 4 31B daily limit at aistudio.google.com/rate-limit (Google doesn't publish free limits; the plan assumes it is well above 20/day)
- [ ] 🔴 **D-3** — corpus keep/drop (carried over from Phase 1)

## Team (non-blocking)
- [ ] 🟡 Read two full generated reports: do they read like real surveys? Is retrieval surfacing sensible passages?
- [ ] 🟡 **D-2** — target paper venue and deadline
- [ ] 🔵 Heads-up: Phase 3 will ask you to sanity-check the planted errors. Realistic corruptions matter; a weak set makes every catch rate meaningless

## Blocked / open
- **Daily routine (free tier):** after 12:30 IST each day, run `uv run tcv run --query all --condition A`. Finished runs are skipped; a run stopped by quota or a failed check resumes from cache, re-sending only what didn't finish. Expect ~4 runs per day.
- **Free-tier budget per run (estimate from the first live run):** drafter ~2–3 requests (draft + revisions), judge ~4–5 (99 claims at 40 per call, plus re-checks), Gemma the rest. The judge's 20/day is the bottleneck.
- **Risk for later phases:** Phases 3–6 check many seeded drafts under six conditions, which is judge-heavy. At 20 judge requests a day this is days of quota per sweep. Revisit before Phase 3: bigger check batches, a second judge-eligible model, or billing.

## Observations (Phase 2)
- **First live signal — the gap the project targets is visible in run one.** Of the 19 claims the baseline failed, about 12 are cross-paper framing or aggregation that no single passage states: "Recent literature identifies several architectural paradigms…", "A third category encompasses … Tool-MAD", "Multi-agent frameworks demonstrate significant gains over … baselines". The standard check can't confirm these whether they're right or wrong, which is exactly failure mode F1. One more is the report's honest "precision and recall are not uniformly reported" sentence, flagged because no passage says it.
- **The baseline caught a real hallucination:** the draft said MARCH gives a *positive* reward when all claims match; MARCH's equation 7 gives **0** on success and −1 otherwise. (Checked against `march-2026#p4c2`.)
- **Checking is token-heavy at high thinking:** a batch of 15 checks uses 6–10k output tokens (~$0.03–0.04 at list price); q02's round 1 had 7 batches. Worth trying medium thinking for the judge once billing is on, measured against the same claims.
- **Modality:** 98 of 99 claims came back "none". Either the draft hedges very little, or the atomizer under-reports strength words — check by hand before Phase 3 relies on it (FR-5.2).

## Decisions (Phase 2)
- **The baseline check judges content, not wording strength.** "X may improve Y" and "X improves Y" are judged alike in condition A. Checking strength against evidence is condition F's mechanism, and building it into the baseline would hide what F adds.
- **The atomizer never drops a sentence.** Signposting like "We now turn to…" still becomes a claim in condition A, as it would under standard checking. Exempting it is condition B's job.
- **Free-tier model roles** (D-8, billing off): drafter `gemini-3.8-flash`, judge `gemini-3.7-flash`, mechanical steps `gemma-4-31b-it`. Each model has its own daily quota, and a judge different from the drafter never grades its own writing. Gemma 4 31B passed a test of the claim-splitting prompt, and caught a hedge ("may suggest" → `suggests`). Gemma 4 26B returned a block and is not used.
- **`configs/models.dev.yaml`** exists for plumbing checks when the pinned models' daily quota is spent. It changes the config hash, so its runs never mix with real ones, and its results are not reported.

## Deviations from `architecture.md` (Phase 2)
(numbering continues from Phase 1)

17. **The Researcher writes queries for all sub-tasks in one batched call** (`research(subtasks)`), not one call per sub-task. Fewer calls, same pools.
18. **Unchanged sentences are not re-checked in later rounds**; their claims and verdicts carry over. They are byte-identical (enforced), so a re-check could differ only by model randomness, at the cost of calls. Error displacement is measured on the rewritten sentences.
19. **FR-4.2 is softened:** if a draft still has uncited factual sentences after one regeneration, the run continues and the checker fails those sentences (`unsupported`, "no citation") instead of aborting the run.
20. **Synthesizer interfaces:** `draft` returns a `DraftResult` (draft plus citation diagnostics); `revise` also takes the question and sub-tasks. The model returns replacement text for flagged sentences only, and the new draft is assembled in code, so untouched sentences are identical by construction (and still checked).
21. **Run configuration** lives in `tcv/config.py`, `configs/run/base.yaml` and `configs/conditions/`. Model roles stay in `configs/models.yaml`, referenced from the run config and hashed with it.
22. **A round with any failed check (`error`: the model call broke, not the claim) leaves the run incomplete** instead of finishing it. The run is resumed later and re-sends only the failed checks. A daily-quota error inside a batch stops the run rather than failing claims one by one. Failed checks are never sent for revision, and if one ever reaches a final report it's marked "not checked — the check itself failed", not given one of the six escalation labels, none of which would be true.
23. **`CheckResult` has no dependency-graph field yet**; it arrives with the graph in Phase 5.

---

# Phase 1 — Foundation and Pilot (closed except the carry-overs above)

**Started:** 2026-09-25 · **Goal:** working repo, frozen data structures, ingested corpus, working search, and evidence the thesis is testable.

**Exit gate:** a pilot draft contains enough aggregative (T2) claims to measure. *D-1 resolved: Gemini API.*

**State at last update (2026-09-26):** all Claude work is done. 210 fast tests + 4 slow integration tests pass, and all 4 import contracts hold. The data structures are frozen and pinned by a test. **One of 10 pilot drafts exists and passes the screen.** The other 9 wait on Gemini's free-tier daily quota (see D-8). The corpus freeze waits on D-3.

## Claude

### Repo foundation
- [x] `git init`, `.gitignore`, `.env.example`, `README.md` — *nothing committed yet; commit when the team asks*
- [x] `pyproject.toml` + `uv.lock`, pinned Python 3.12 venv
- [x] Import-rule contracts (only Researcher touches retrieval; operators never touch the model; only the gateway touches the SDK; schemas depend on nothing) + test
  - the test plants a real violation for each rule in a temp copy and confirms it's caught

### Data structures (frozen at end of phase)
- [x] `schemas/`: ids, corpus, retrieval, draft, claims, verdicts, payload, run, eval
- [x] Schema tests: validation, immutability, JSON round-trip, ID patterns (47 tests)

### Corpus
- [x] PDF → page-mapped normalised text
- [x] Sentence-aware chunking within pages, stable chunk IDs, exact char spans
- [x] Corpus manifest with SHA-256, freeze + verify
- [x] `configs/corpus.yaml` source list for the 6 seed papers — arXiv IDs / DOI read from the PDFs themselves
- [x] Ingestion tests (span round-trip, ID stability across re-ingest, hash verify, 4 real-bug regressions)

### Retrieval
- [x] Local embedding model wrapper (bge-small-en-v1.5, CPU for determinism)
- [x] Dense (exact cosine) + BM25 hybrid, weighted reciprocal-rank fusion, save/load with staleness check
- [x] `RetrievalPool` persistence keeping uncited passages (`orchestrator/state.py`)
- [x] Retrieval tests (fast, hashing embedder) + slow real-model probes

### Model gateway
- [x] Provider interface + Anthropic provider + fake provider for tests
- [x] Versioned prompt loading
- [x] Disk response cache keyed by prompt hash
- [x] Call ledger (JSONL) + budget kill-switch
- [x] Batched calls with per-item failure isolation
- [x] Gateway tests (cache hit costs zero, budget stops calls, refusals/invalid output never cached, batch isolation, exact SDK request shape) — 26 tests

### CLI and pilot material
- [x] `tcv ingest`, `tcv search`, `tcv verify-corpus`, `tcv freeze`, `tcv pilot [--dry-run]`
- [x] 10 synthesis queries in `configs/queries.yaml` (single-topic, comparative, temporal, tension)
- [x] Candidate corpus list: 48 papers in `configs/corpus_candidates.yaml` (41 core, 7 optional; 4 flagged "verify ID")
- [x] Pilot drafter (`tcv pilot`) — written and dry-run tested
- [x] Gemini provider behind the same interface (D-1 → Gemini API), pricing, model config, tests (15 new)
  - `configs/models.yaml` → Gemini; the Claude setup is kept as `configs/models.anthropic.yaml`
  - model IDs may not contain "preview" or "latest"; `pilot` now continues past a failed query
- [x] Live smoke test: free text, structured output (our real `Verdict` schema), cache hit at $0
- [x] Screen widened to `lex-v2` after reading the first draft: lex-v1 flagged 1 cross-paper claim, a human reading found ~8; lex-v2 flags 9, each checked by hand. It also reports sentences citing 2+ papers, a second signal that doesn't depend on wording
- [x] Provider stops at once on a daily-quota error and retries overloads only a few times, widely spaced; `pilot` stops cleanly when the quota is gone
- [~] Pilot run + aggregative-claim screen — **1/10 drafts** (q02: 39 sentences, 9 candidates, 6 citing 2+ papers, 6/6 papers cited, 0 bad citations → **PASS**). The other 9 are blocked by the free-tier quota (D-8)

### Phase-close work
- [x] Data structures frozen: `tests/unit/test_schema_freeze.py` pins a fingerprint of every exported schema; any change fails until SCHEMA_VERSION is bumped (checked: changing one default fails it)
- [x] Fetch step: `tcv fetch --check` confirmed all 48 candidate arXiv IDs against arXiv, including the 4 flagged "verify" (FacTool's title was truncated in our list; fixed). `tcv fetch` refuses until every candidate has a decision, pins arXiv versions, downloads, and writes `configs/corpus.v1.yaml` (11 tests)
- [ ] Corpus v1 ingested and frozen — **blocked on D-3**

## Team (blocking)
- [x] **D-1** — hosted API via **Google Gemini** (2026-09-26). agentrouter.org was ruled out: it accepts only requests that look like Claude Code.
- [ ] **D-3** — add `decision: keep` / `decision: drop` to every entry in `configs/corpus_candidates.yaml` (all 48 IDs are confirmed), then tell me or run `uv run tcv fetch` — *blocks corpus freeze*
- [x] `GEMINI_API_KEY` in `.env`
- [x] **D-8** — billing off; the project runs on the free tier (decided 2026-09-26, see Phase 2)

## Team (non-blocking)
- [ ] **D-7** — realistic weekly hours for review/annotation
- [ ] Review the pilot drafts once they exist — do the "aggregative candidates" really count or compare across papers?

## Blocked / open
- **Corpus freeze** waits on D-3. The seed corpus is `v0-seed` (6 papers, 382 chunks); the approved corpus becomes `v1`.
- **After D-3:** `uv run tcv fetch` → `uv run tcv --config configs/corpus.v1.yaml ingest` → `… freeze`, then make v1 the default corpus.
- **After D-8 (or the daily reset at 12:30 IST):** `uv run tcv pilot` runs the 10 drafts on the pinned gemini-3.8-flash (10 of the 20 daily requests). Then the team reviews the drafts.
- **Observation:** on the seed corpus, q08 (retrieval and tools) draws evidence from only 2 papers — expected to improve with the full corpus; re-check then.
- **Observation:** a judge call on gemini-3.8-flash at high thinking is ~700 output tokens (~$0.003). One early call used 7,800, mostly thinking, so revisit the judge's thinking level in Phase 3 once real volumes are known.
- **Observation:** gemini-3.8-flash returned "503: high demand" for a while on 2026-09-26 while 3.7-flash answered. The provider retries with backoff for ~1 minute; after that the query is skipped and a rerun fills it.
- **Observation:** the free-tier quota is 20 requests/model/day (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). On 2026-09-26 it was used up by retries against "503 high demand" before most drafts ran.
- **Observation:** arXiv's API returns 406 to Python's HTTP stack (urllib, http.client, httpx) whatever the headers, but serves curl normally. The fetch step uses curl with an honest User-Agent and arXiv's 3-second pace.
- **Observation:** the q02 draft is from gemini-3.7-flash (a one-off `--model` override because 3.8 was overloaded); rerun on 3.8 with the rest for a consistent set.
- **Observation:** retrieval probe MRR 0.84 at dense weight 0.6 (8 known-answer probes). Too few probes to tune the weight; keep 0.6 until a proper probe set exists.

## Deviations from `architecture.md`
Recorded here rather than editing `architecture.md`, which the team is revising on another device. Fold these in on the next sync.

1. **Document IDs are readable slugs** (`du-2023`, `gsar-2026`), not `arxiv:NNNN.NNNNNvN`. Two seed papers aren't on arXiv. The arXiv ID / DOI moved to `Document.source` (`arxiv:2305.14325v1`, `doi:10.3390/…`, or `local`). Chunk IDs are `<doc>#p<page>c<idx>`.
2. **`Document`** has `source`, `year`, `filename` in place of `arxiv_version`; **`CorpusManifest`** gained `n_chunks`.
3. **Dense search is an exact numpy dot product, not FAISS.** At ~50 papers it's instant, fully deterministic, and one fewer native dependency. The index interface allows a swap later.
4. **Hybrid fusion is weighted reciprocal-rank fusion** (dense weight 0.6), not score addition — cosine and BM25 scores aren't on comparable scales.
5. **PDF extraction** (normaliser `norm-v2`): the reference list is dropped entry by entry and extraction resumes at appendix headings, because appendices often follow the references; running headers are matched by shape (digits ignored); publisher metadata sidebars on page 1 are dropped.
6. **Escalation labels** are `EscalationKind` + `Escalation(kind, section).render()` rather than a string enum, since "inconsistent with §k" needs the section filled in.
7. **`Atom` gained `unit`** — the comparison check must return undecidable for mismatched units (architecture §7.2), which needs the unit recorded.
8. **`RetrievalPool`** gained `passages()`, `cited()`, and `with_citations()` — the last sets flags on a copy and never removes an entry.
9. **"Only the gateway touches the SDK" checks direct imports only.** Every component reaches the SDK *through* the gateway, which is the design. The pure-operators rule stays strict about indirect imports.
10. **Planning docs stay at the repo root** instead of `docs/`, so the cross-device sync isn't disturbed.
11. **Claude Opus 5 calls use server-side fallback** (`fallbacks="default"`; Anthropic config only), so a request declined by a safety classifier is re-run on the recommended fallback model rather than returned as a refusal.
12. **A minimal Researcher exists already** (`search_pool`, retrieval only), so the pilot needed no exception to the "only the Researcher searches" rule. Phase 2 adds model-written queries.
13. **The lexical pre-pass (`checker/lexicon.py`) arrived early** (it's Phase 4 in the plan) because the pilot's exit gate needs it to count aggregative candidates.
14. **The models in use are Gemini, not Claude** (D-1, 2026-09-26): gemini-3.8-flash drafts and judges, gemini-3.1-flash-lite does the mechanical steps. A Gemini provider sits beside the Anthropic one; `effort` maps to Gemini's thinking level; safety and recitation blocks count as refusals, so they're never cached. Prices are list prices (3.6–3.8 Flash double on 2027-01-01).
15. **New corpus documents are named `<first-author-surname>-<year>`** (e.g. `liang-2023`, `du-2023b` on a clash) from arXiv metadata, and their `source` pins the arXiv version current at fetch time (`arxiv:2305.19118v4`).
16. **Schema freeze is enforced by a fingerprint test**, not only by convention.
