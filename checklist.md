# Phase 1 — Foundation and Pilot

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
- [ ] **D-8** — Gemini free tier allows **20 requests per model per day**. Either enable billing on the Google AI Studio project (pilot ≈ $0.23 at list price; the budget cap stays at $2 per run), or stay on the free tier and accept one small pilot per day — not enough for the evaluation phases, which need hundreds of calls per day — *blocks finishing the pilot today and all later phases*

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
