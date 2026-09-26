# Requirements — Type-Routed Claim Verification for Long-Form Research Synthesis

**Companion to** `updated_proposal.md`. That document states *what* we are building and *why it is novel*; this one states *what must exist* for it to be built, run, and defended.

**Project context**
- **Team:** 2–3 people
- **Start:** 2026-09-16
- **Scope:** **Core** (Phases 1–7) is the committed target; **Full** (Phases 1–11) is conditional — see §10
- **Deliverables:** BTP report + viva, **plus** a workshop/conference paper submission
- **Corpus:** curated arXiv slice on hallucination mitigation / multi-agent verification (extension of `papers/`)
- **Budget:** undecided — §5 specifies two fully-designed paths and the decision point

**Phases.** This document schedules by **phase**, where one phase ≈ one week of calendar time at the team's sustainable pace. `roadmap.md` holds the phase-by-phase execution plan; §10 here defines only the scope tiers and the effort model that plan is built on.

**Requirement IDs:** `FR` functional · `DR` data · `MR` model/infra · `AR` annotation · `ER` evaluation · `RR` reproducibility · `NFR` non-functional · `PR` process. Priority: **[M]** must-have (project fails without it) · **[S]** should-have · **[C]** could-have (drop first under time pressure).

---

# 1. Scope

## 1.1 In scope

Building a training-free, four-agent synthesis pipeline (Planner → Researcher → Synthesizer → Critic) over a bounded academic corpus, with a type-routed Critic implementing novelties N1–N7, and an evaluation harness implementing N8–N11 sufficient to test falsifiable claims C1–C9.

## 1.2 Explicitly out of scope

| Excluded | Reason |
|---|---|
| Any model training or fine-tuning | Training-free is a stated contribution (G9) |
| Open-domain / web-scale retrieval | Scoped to bounded corpora (§8.8 of proposal) |
| Production deployment, multi-user serving, auth | Research prototype |
| Real-time / low-latency operation | All experiments are offline batch |
| Non-English corpora | Not needed for the claims under test |
| A polished end-user UI | See FR-9 — a minimal inspector only |

## 1.3 Success criteria

The project succeeds if **all** of the following hold, regardless of whether the falsifiable claims come out positive:

1. The full pipeline runs end-to-end on the corpus and produces attributed reports.
2. **Ablation conditions A–D** execute and produce per-error-class catch rates and false-positive rates.
3. Loop dynamics (marginal resolution, error displacement, cost per round) are measured.
4. Every falsifiable claim **whose mechanism was built** has a reported outcome — including negative ones.

Conditions **E and F** (N4 intra-report consistency, N5 assertiveness calibration) are **stretch**, not success criteria. They are the strongest additions to the contribution and the first things cut if the calendar bites — see §10.

A negative result on C2/C3 that is **measured and reported** is a successful project. An unmeasured claim is not.

---

# 2. Functional Requirements

## 2.1 Corpus and retrieval

| ID | Pri | Requirement |
|---|---|---|
| **FR-1.1** | M | Ingest PDFs; extract text with layout-aware segmentation; produce chunks with stable IDs |
| **FR-1.2** | M | Every chunk carries `(document_id, page_number, chunk_id, text, char_span)`. IDs stable across re-ingestion of the same corpus version |
| **FR-1.3** | M | Dense retrieval over chunks with a local embedding model; top-`k` configurable per sub-task |
| **FR-1.4** | M | **The retrieval pool `P` is persisted per sub-task, including passages never cited.** N3 (sweep) and N6 (misattribution) both read from it — dropping uncited passages breaks two novelties |
| **FR-1.5** | S | Hybrid retrieval (dense + BM25) with configurable weighting |
| **FR-1.6** | M | Corpus manifest: arXiv ID, title, version, SHA-256 of the source PDF, ingestion timestamp |

## 2.2 Planner

| ID | Pri | Requirement |
|---|---|---|
| **FR-2.1** | M | Decompose a synthesis query into an ordered list of sub-tasks with a target report outline |
| **FR-2.2** | M | Emit structured output (JSON schema-validated), not free prose |
| **FR-2.3** | S | Sub-task count bounded and configurable (default 5–8) to keep run cost predictable |

## 2.3 Researcher

| ID | Pri | Requirement |
|---|---|---|
| **FR-3.1** | M | **Sole holder of retrieval tools.** No other component may call the retriever — enforced by module boundary, not convention |
| **FR-3.2** | M | Per sub-task: formulate queries, retrieve, return tagged passages |
| **FR-3.3** | M | Persist the full pool `P` per sub-task (see FR-1.4) with a cited/uncited flag updated after synthesis |
| **FR-3.4** | C | Adaptive query refinement across rounds (Tool-MAD-style) |

## 2.4 Synthesizer

| ID | Pri | Requirement |
|---|---|---|
| **FR-4.1** | M | Draft a multi-section report from tagged passages with **mandatory inline attribution** in a parseable citation format |
| **FR-4.2** | M | Reject/regenerate drafts containing sentences with factual content and no citation (structural check, pre-Critic) |
| **FR-4.3** | M | On revision rounds, accept a targeted payload and revise **only flagged spans**; unflagged spans must be byte-identical |
| **FR-4.4** | M | Sentence indices stable across rounds so the Critic can reference spans reliably |

## 2.5 Critic — the core

### Step A — Atomization

| ID | Pri | Requirement |
|---|---|---|
| **FR-5.1** | M | Decompose the draft into atomic claims with preserved sentence index and citation set |
| **FR-5.2** | M | **Preserve epistemic modality as claim metadata.** Standard atomizers strip it; N5 is impossible without it |
| **FR-5.3** | M | Batched — many claims per LLM call, not one call per claim (see NFR-2.1) |

### Step B — Type router (N1)

| ID | Pri | Requirement |
|---|---|---|
| **FR-6.1** | M | Assign exactly one type T1–T4 per claim |
| **FR-6.2** | M | Lexical pre-pass: discourse markers → T4 candidate; quantifier/count/comparison keywords → T2 candidate. Reduces LLM volume and gives a rule-only baseline |
| **FR-6.3** | M | Emit per-claim type + confidence; log every assignment for the confusion matrix (ER-3) |
| **FR-6.4** | M | T4-typed claims bypass entailment entirely and are recorded as `Exempt` with reason |

### Step C — Path verification

| ID | Pri | Requirement |
|---|---|---|
| **FR-7.1** | M | **T1:** entailment of claim against its cited passage, blinded to the rest of the draft |
| **FR-7.2** | M | **Misattribution (N6):** on T1 failure, re-check against pool `P`; return `Misattributed` with the entailing chunk ID, distinct from `Unsupported` |
| **FR-7.3** | M | **T2 decomposition:** split an aggregative claim into constituent atoms, each with its own passage |
| **FR-7.4** | M | **T2 composition (N2):** evaluate the aggregation operator **in code** over verified atoms — counts by counting, comparisons by comparing, trends by monotonicity check. Not an LLM judgment |
| **FR-7.5** | M | Supported operators: `count`, `proportion`, `universal`, `existential`, `comparison`, `trend`, `contrast`. Unsupported operators → escalate as `unverified — unsupported aggregation` rather than silently passing |
| **FR-7.6** | M | **Disconfirming sweep (N3):** for universal-force claims, check uncited members of `P` for counterexamples |
| **FR-7.7** | M | `Partially-Supported` verdict carries a machine-readable repair hint (e.g. `{observed: 2, claimed: 3}`) |
| **FR-7.8** | M | **T3:** defeasibility check against pool; surviving claims labelled `inference`, not `fact` |
| **FR-7.9** | S | Verifier abstains (`Uncertain`) below a confidence threshold rather than guessing; abstentions counted separately in metrics |

### Step D — Assertiveness (N5) — *Full scope*

> FR-5.2 (modality preservation in the Atomizer) stays **[M]** even under Core scope. It costs almost nothing to retain modality, and stripping it now makes N5 unimplementable later without re-running every atomization.

| ID | Pri | Requirement |
|---|---|---|
| **FR-8.1** | S | Modality ladder as an explicit, versioned lexicon (`suggests < indicates < shows < demonstrates < proves`) — a lookup table, not an LLM call |
| **FR-8.2** | S | Assess evidence strength (single vs. converging sources; hedged vs. definitive source language) and flag `Overclaim` on mismatch |
| **FR-8.3** | S | Repair hint proposes a **downgrade**, never a deletion |
| **FR-8.4** | S | Under-claiming logged but never flagged |

### Step E — Intra-report consistency (N4) — *Full scope*

| ID | Pri | Requirement |
|---|---|---|
| **FR-9.1** | S | Gate candidate pairs by entity/topic overlap **in code** before any LLM call — the naive O(n²) sweep is not affordable |
| **FR-9.2** | S | Contradiction check on surviving pairs; verdict `Internally-Inconsistent` |
| **FR-9.3** | S | Payload carries **both** sentence indices and **both** supporting passages |
| **FR-9.4** | C | Scope-qualifier detection to reduce false contradictions (§8.3 of proposal) |

### Step F — Dependency graph (N7)

| ID | Pri | Requirement |
|---|---|---|
| **FR-10.1** | M | Maintain `claim → atoms → passages → documents` graph, built as a by-product of T2 decomposition |
| **FR-10.2** | M | Atom invalidation auto-re-flags every dependent aggregative claim |
| **FR-10.3** | S | Evidence concentration metric: fraction of verified claims resting on a single document |

## 2.6 Loop and escalation

| ID | Pri | Requirement |
|---|---|---|
| **FR-11.1** | M | Bounded Synthesizer↔Critic loop; `N` configurable (default 3) |
| **FR-11.2** | M | Six typed escalation labels emitted in the final report per §5.4 of the proposal |
| **FR-11.3** | M | Hard token-budget kill switch independent of `N` — a runaway run must not silently drain credits |
| **FR-11.4** | M | Full per-round state persisted (draft, claims, types, verdicts, payloads, token counts, wall-clock) so any run is replayable offline |

## 2.7 Stretch

| ID | Pri | Requirement |
|---|---|---|
| **FR-12.1** | C | Evidence-suppression audit (§5.5 of proposal); implement only if Full scope is reached and Phase 11 lands early. First item in the §10.1 cut order |

## 2.8 Inspection UI

| ID | Pri | Requirement |
|---|---|---|
| **FR-13.1** | S | Static HTML report viewer: draft with claims colour-coded by type and verdict, hover to see cited passage and Critic reasoning |
| **FR-13.2** | C | Side-by-side round diff (round *k* vs *k+1*) for error-displacement inspection |

> The viewer is **research instrumentation first** — you will be reading hundreds of verdicts by hand, and doing that in raw JSON will cost more hours than building it. It doubles as the viva demo.

---

# 3. Data Requirements

| ID | Pri | Requirement |
|---|---|---|
| **DR-1** | M | **40–60 arXiv papers** on hallucination mitigation, multi-agent verification, attributed generation, and faithfulness evaluation — a superset of `papers/` |
| **DR-2** | M | Corpus **frozen and versioned** before the seeded-error harness is built (Phase 3). Adding papers mid-experiment invalidates every prior run |
| **DR-3** | M | Papers must be text-extractable. Scanned/image-only PDFs are excluded (log exclusions in the manifest) |
| **DR-4** | M | **8–12 synthesis queries** spanning: single-topic survey, comparative survey (forces T2), temporal/trend query (forces T2 trend), and a query with a known contradiction in the corpus (forces N4) |
| **DR-5** | M | **Query design is load-bearing.** If the queries don't elicit aggregative claims, the experiment cannot test N2/N3 regardless of implementation quality. Validate on a pilot draft before freezing |
| **DR-6** | M | ~10 gold reference reports (human-checked) for oracle-retrieval ground truth and clean-draft FPR measurement |
| **DR-7** | S | Corpus includes at least one **genuine** cross-paper contradiction, verified by hand, so N4 is tested against a real case and not only a seeded one |

> **DR-5 is the single highest-risk requirement in this document.** Everything downstream assumes the drafts contain enough T2 claims to measure. Run a pilot in Phase 1.

---

# 4. Annotation Requirements

You answered "just me" for annotation but this is a 2–3 person team. Teammates *can* serve as second annotator; the requirements below assume they do, with AR-5 covering the independence caveat.

| ID | Pri | Requirement |
|---|---|---|
| **AR-1** | M | Written annotation guideline for T1–T4 with ≥5 worked examples per type and explicit tie-breaking rules, frozen before labelling starts |
| **AR-2** | M | **200 held-out claims** labelled independently by two annotators; Cohen's κ reported |
| **AR-3** | M | Annotators label **blind** to the router's output. Showing the model's guess destroys the measurement |
| **AR-4** | M | Disagreements adjudicated after κ is computed, producing the gold set; κ reported on the pre-adjudication labels |
| **AR-5** | S | For the **end-to-end hallucination-rate** evaluation (ER-6), annotators must be blind to which condition produced each report. Randomize and strip condition labels — teammates are invested in the outcome, and this is where that bias would actually distort a headline number |
| **AR-6** | S | κ < 0.6 triggers taxonomy revision and re-annotation, not a footnote. Budget one contingency phase |
| **AR-7** | M | Annotation budget: ~4 hours per annotator for AR-2; ~6 hours each for ER-6 |

---

# 5. Model and Infrastructure Requirements

## 5.1 The budget decision

**Claude Pro ($20/mo) does not include API access.** It covers claude.ai and Claude Code only. The experimental harness needs pay-as-you-go API credits or a non-API alternative.

| ID | Pri | Requirement |
|---|---|---|
| **MR-1** | M | **Decide the budget path by end of Phase 1.** Both paths below are designed; the choice affects model assignment (MR-8) and switching after Phase 3 wastes work |

## 5.2 Call volume and cost model

Estimated LLM calls per report-round *before* optimization:

```
  Planner + Researcher + Synthesizer + Atomizer + Router     ~5
  T1 entailment (~50 claims)                                ~50
  T2 constituent atoms (~10 claims × 4 atoms)               ~40
  Disconfirming sweep (~10 universals × 10 passages)       ~100
  T3 + assertiveness + gated consistency pairs              ~60
                                                          ─────
                                                           ~255 calls / report-round
```

Full ablation: 10 queries × 6 conditions × 3 rounds ≈ **~46,000 calls**, plus re-runs and the oracle ablation.

| ID | Pri | Requirement |
|---|---|---|
| **MR-2** | M | **Batch claims per request** — 10–20 claims with their passages per call, structured output returned. Cuts call count ~10×. Build this in from the start; retrofitting is painful |
| **MR-3** | M | **Prompt caching** on the passage prefix — passages repeat constantly; cache reads cost ~10% of input. Verify via `cache_read_input_tokens`, and treat a persistent zero as a bug, not noise |
| **MR-4** | M | **Batch API for all ablation runs** — 50% cost reduction, and the entire ablation is offline. There is no reason to run it synchronously |
| **MR-5** | S | **Local NLI pre-filter** (DeBERTa-MNLI or similar): confident entail/contradict resolve locally, uncertain cases escalate to the API. Halves API volume *and* supplies a free extra ablation condition (local NLI vs. LLM judge) |
| **MR-6** | M | On-disk response cache keyed by `(model, prompt_hash)` — a re-run of an unchanged condition must cost zero |

**Estimated cost with MR-2 through MR-5 applied: $20–40 for the full experimental programme.**

## 5.3 Path A — paid API (recommended)

| ID | Pri | Requirement |
|---|---|---|
| **MR-7** | M | Anthropic API credits, ~$40–50 |
| **MR-8** | M | Model assignment by role: **Synthesizer** `claude-opus-5` (quality matters, few calls) · **Atomizer + Router** `claude-haiku-4-5` (mechanical, high volume) · **Entailment** `claude-sonnet-5` (accuracy-critical, highest volume) |
| **MR-9** | S | Budget at standard rates: Opus 5 $5/$25, Sonnet 5 $3/$15, Haiku 4.5 $1/$5 per MTok. (Sonnet 5's introductory $2/$10 rate expired 2026-08-31 — do not plan against it) |
| **MR-10** | M | Pin exact model IDs in config. Never use a floating alias — a mid-project model update silently invalidates every prior result |

## 5.4 Path B — free / local fallback

| ID | Pri | Requirement |
|---|---|---|
| **MR-11** | M | Embeddings: `sentence-transformers` locally (free either way — this is not an LLM) |
| **MR-12** | M | Entailment: local NLI model (DeBERTa-MNLI class) |
| **MR-13** | M | Synthesizer + Atomizer: local instruction-tuned model via Ollama, or free-tier API within quota |
| **MR-14** | M | If Path B is taken, **state prominently in the report that entailment quality is the floor on every result.** A weak judge caps catch rate and inflates FPR independent of the mechanisms under test |

> Path B produces a defensible BTP. It weakens the paper, because a reviewer will attribute any low catch rate to the judge rather than the design. If ~$40 can be found, Path A is materially better.

## 5.5 Engineering infrastructure

| ID | Pri | Requirement |
|---|---|---|
| **MR-15** | M | Python 3.11+; dependencies pinned via lockfile |
| **MR-16** | M | Git from day one, on GitHub. **This repo is not currently a git repository — initialise it in Phase 1** |
| **MR-17** | M | All prompts in versioned template files, never inline string literals. A prompt change must show up in a diff |
| **MR-18** | M | Structured JSON logging of every LLM call: model ID, prompt hash, token counts, latency, cost, cache-hit status |
| **MR-19** | S | Config-driven experiments (YAML per condition) so an ablation is a config change, not a code edit |
| **MR-20** | S | Secrets via environment variables; `.env` git-ignored; no key ever committed |

---

# 6. Evaluation Requirements

| ID | Pri | Requirement |
|---|---|---|
| **ER-1** | M | **Seeded-error harness**, error classes E1–E10 (E11 stretch). Each injection records `(class, sentence_index, original_text, corrupted_text)` as ground truth |
| **ER-2** | M | **Catch rate per error class**, never aggregated into a single number — aggregation hides the exact effect under test |
| **ER-3** | M | **FPR on uncorrupted drafts**, overall and broken down by claim type. T4 over-flagging is the specific predicted pathology |
| **ER-4** | M | Verdict confusion matrix across all seven verdict values, including the E2-vs-E3 separation that tests N6 |
| **ER-5** | M | **Oracle-retrieval ablation** — full pipeline with real retrieval and with gold passages injected; the FPR gap is attributable to retrieval, not the Critic |
| **ER-6** | M | Three-way end-to-end baseline: zero-shot RAG · multi-agent debate (Du et al. adapted) · ours. Human-annotated hallucination rate on a sample, blind to condition (AR-5) |
| **ER-7** | M | **Loop dynamics**: marginal resolution per round, error displacement rate, token cost and wall-clock per round |
| **ER-8** | M | **Ablation conditions A–D** executable from config (**E–F** under Full scope), all sharing corpus, queries, seeds, and base models. The runner must accept new conditions without code changes, so E and F can be added late if Phase 6 finishes early |
| **ER-9** | M | Router confusion matrix vs. human gold labels, with T4→T1 and T2→T1 misroutes reported separately |
| **ER-10** | S | Cost and latency reported alongside accuracy in **every** results table. A bare accuracy number is the reporting practice §1.2 of the proposal criticises |
| **ER-11** | S | Statistical treatment: bootstrap CIs on catch rate and FPR. With ~10 queries per condition, differences will be noisy — say so honestly rather than over-reading them |

---

# 7. Reproducibility Requirements (paper track)

These exist because you are targeting a paper. They are cheap during the build and expensive to retrofit.

| ID | Pri | Requirement |
|---|---|---|
| **RR-1** | M | Every run seeded and recorded; a run is re-executable from its config + seed + response cache |
| **RR-2** | M | Exact model IDs and API parameters recorded per run (not just per project) |
| **RR-3** | M | Corpus manifest published: arXiv IDs, versions, SHA-256 hashes. Do not redistribute the PDFs — publish the manifest and the fetch script |
| **RR-4** | M | Prompt templates released verbatim as an appendix or repo directory |
| **RR-5** | M | Seeded-error generator released, so the harness is reusable by others — this is N8's path to being a contribution rather than internal tooling |
| **RR-6** | S | Annotation guidelines and the 200-claim gold label set released |
| **RR-7** | S | Raw per-claim verdict logs released (anonymized if needed) so the numbers are auditable |
| **RR-8** | C | One-command repro script for the headline table |

---

# 8. Non-Functional Requirements

| ID | Pri | Requirement |
|---|---|---|
| **NFR-1.1** | M | A full ablation sweep completes within one overnight run (~12h) so a bad result can be diagnosed and re-run within a day |
| **NFR-2.1** | M | Batched, cached, and resumable — a crashed sweep resumes from the response cache without re-billing |
| **NFR-3.1** | M | Critic components independently invocable and unit-testable without running the full pipeline |
| **NFR-3.2** | M | Composition operators (FR-7.4) have **deterministic unit tests** — they are pure functions and must be tested as such. This is also the cleanest evidence that N2 is code, not vibes |
| **NFR-4.1** | S | Graceful degradation: an API failure on one claim marks that claim `Error` and continues; one bad call must not kill a 4-hour sweep |
| **NFR-5.1** | M | Verdicts are auditable end-to-end: for any claim you can retrieve the exact prompt, model, passage set, and raw response that produced it |

---

# 9. Team Split

Three tracks, deliberately decoupled so they can proceed in parallel after Phase 1.

| Track | Owner | Owns | Requirements |
|---|---|---|---|
| **A — Pipeline** | Person 1 | Corpus ingestion, retrieval, Planner/Researcher/Synthesizer, orchestration, loop control, cost/logging infra | FR-1 to FR-4, FR-11, MR-15 to MR-20 |
| **B — Critic** | Person 2 | Atomizer, router, all verification paths, composition operators, sweep, consistency, assertiveness, dependency graph | FR-5 to FR-10 |
| **C — Evaluation** | Person 3 | Seeded-error harness, metrics, annotation protocol and study, ablation runner, analysis, inspection UI | ER-1 to ER-11, AR-1 to AR-7, FR-13 |

**Two-person variant:** merge A and C; Person 2 keeps the Critic. Track C's annotation study still needs both people (AR-2), and Track B's owner should not be the sole annotator for their own router.

**Interface contracts must be frozen in Phase 1** — the claim object, verdict object, and revision payload schemas. With three people building against each other, a schema change in Phase 5 costs more than the feature it enables. Write them as typed schemas with validation, not as a convention.

**The claim schema must carry the Full-scope fields from the start** — modality (FR-5.2) and the dependency-graph edges — even under Core scope. Adding a field to a schema three tracks already build against is the most expensive change available.

---

# 10. Scope Tiers and Effort Model

The phase-by-phase execution plan lives in **`roadmap.md`**. This section defines the scope tiers that plan targets and the effort model it is sized against.

## 10.1 Scope tiers

| Tier | Phases | Mechanisms | Ablation | Novelties tested |
|---|---|---|---|---|
| **Core** — committed | 1–7 | N1, N2, N3, N6, N7 + full evaluation harness | **A–D** | C1, C2, C3, C6, C7, C8 |
| **Full** — conditional | 1–11 | + N4, N5 | **A–F** | + C4, C5 |
| **Full + paper** | 1–13 | Above + submission-ready draft and artifact release | A–F | All |

**Core is a complete, defensible BTP.** N2 (composition verification) and N3 (disconfirming sweep) are the two strongest novelties and conditions A–D test both, alongside the measurement contributions N8–N11. N4 and N5 are the highest-value additions, but they are additions.

**Cut order under schedule pressure**, first to last:

1. FR-12.1 — evidence-suppression audit (already out of Core)
2. FR-9.4 — scope-qualifier detection
3. FR-13.2 — round-diff view
4. Condition **F** (N5 assertiveness)
5. Condition **E** (N4 consistency)
6. Query count per condition — from 10 to 6

**Never cut:** the ablation sweep, the oracle ablation, or analysis time. Those are what make the project defensible.

## 10.2 Effort model

| Track | Focused work |
|---|---|
| A — Pipeline (ingest, retrieval, three agents, loop, logging) | ~100 h |
| B — Critic (atomizer, router, all verification paths) | ~160 h |
| C — Evaluation (harness, metrics, annotation, runner, UI) | ~120 h |
| Integration, debugging, re-runs | ~60 h |
| Analysis, report, paper draft | ~60 h |
| **Full scope total** | **~500 person-hours** |
| **Core scope total** | **~360 person-hours** |

Calendar length as a function of sustained pace:

| Team | Hours/person/week | Core | Full |
|---|---|---|---|
| 3 people | 10 | 12 phases | 17 phases |
| 3 people | 15 | **8 phases** | **11 phases** |
| 3 people | 20 | 6 phases | 8 phases |
| 2 people | 15 | 12 phases | 17 phases |

`roadmap.md` is built on **3 people at ~15 h/week**. If the real pace is lower, extend the calendar rather than compressing the phases — the sequencing constraints below do not survive compression.

## 10.3 Known overrun risks

Four items reliably exceed estimates. They are priced into the table above; do not re-optimise them away:

1. **T2 decomposition (FR-7.3)** — splitting an aggregative claim into atoms *and* assigning each the correct passage is the hardest single component, harder than the composition arithmetic that follows. Budget a full phase.
2. **Corpus preparation (FR-1.1)** — PDF text extraction consistently runs 2–3× estimate.
3. **Seeded-error quality (ER-1)** — E9 (internal contradiction) is genuinely difficult to inject well. A weak seed set produces meaningless catch rates, and the problem surfaces only at sweep time.
4. **Writing** — a paper draft is one to two phases on its own, not an activity appended to the final phase.

## 10.4 Sequencing constraints — not negotiable

- **The seeded-error harness precedes the mechanisms it evaluates.** Build the test after the mechanism and you will fit the mechanism to the test without noticing.
- **The router IAA study precedes every mechanism built on the taxonomy.** If κ is unacceptable, that must surface before three more novelties depend on it.
- **The ablation sweep and analysis phases must not compress.** Every cut comes out of mechanism scope, never measurement time.
- **`FR-1.4` (retrieval pool retention) is a Phase 1 correctness requirement**, not an optimisation. Two novelties become unimplementable without it, and the failure surfaces in Phase 5.

---

# 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Queries don't elicit aggregative claims (DR-5)** | **Fatal** — N2/N3 untestable | Pilot in Phase 1; redesign queries; if needed, prompt the Synthesizer explicitly toward comparative framing and note it as a design choice |
| Budget undecided past Phase 1 | Blocks MR-8 model assignment; wasted rework | MR-1 gate; Path B is fully designed as a fallback |
| Router κ < 0.6 | C1 uninterpretable, N1 undermined | AR-6 contingency; a revised taxonomy with fewer, better-separated types is an acceptable outcome to report |
| Sweep FPR unacceptably high | N3 unusable as a revision trigger | Fall back to reporting it as a diagnostic signal, exactly as §8.5 pre-commits for N5 |
| Consistency check O(n²) blows up | Cost overrun | FR-9.1 gating is mandatory, not optional; cap pair count per report |
| Schedule slip mid-project | Ablation incomplete | Apply the §10.1 cut order; drop mechanism scope, never measurement time |
| Schema churn across three tracks | Integration hell mid-project | Phase 1 freeze, typed schemas with Full-scope fields present from the start, validation at boundaries |
| T2 decomposition overruns (§10.3) | Core scope at risk, not just Full | Timebox it; a partial operator set (count + comparison only, escalating the rest per FR-7.5) still tests C2 |
| Local model too weak (Path B) | Depressed catch rate confounds every result | MR-14 — state it as a limitation; report the local-NLI-vs-LLM gap as its own finding |

---

# 12. Open Decisions

| # | Decision | Owner | Deadline | Blocks |
|---|---|---|---|---|
| **D-1** | API budget: Path A or Path B | Team | End of Phase 1 | MR-7 to MR-14, model assignment |
| **D-2** | Target paper venue and deadline | Team + advisor | End of Phase 2 | Final-phase scope and formatting |
| **D-3** | Final corpus paper list | Team | End of Phase 1 | Everything downstream (DR-2) |
| **D-4** | Two-annotator vs. solo annotation protocol | Team | End of Phase 3 | AR-2, C7 |
| **D-5** | Whether to include the local-NLI condition as a reported ablation (free, and a genuine extra result) | Team | End of Phase 4 | ER-8 |
| **D-6** | **Commit to Core or attempt Full** | Team | End of Phase 6 | Phases 8–11; §10.1 cut order |
| **D-7** | Team's realistic hours/person/week | Team | Phase 1 | Calendar length in `roadmap.md` (§10.2) |

**On D-2:** realistic targets are workshops at major NLP/ML venues — factuality, trustworthy-generation, or agent-focused tracks. Check current CFP deadlines rather than assuming; a deadline landing mid-project changes the whole plan, and that is worth knowing in Phase 2 rather than Phase 8.

**On D-6:** this is the single most consequential scheduling decision. Make it at the end of Phase 6 with the Core mechanisms working and real per-phase velocity data in hand — not optimistically at the start, and not reactively once Phase 9 is already slipping.

**On D-7:** `roadmap.md` assumes 3 people at ~15 h/week. Correct that number in Phase 1 and re-anchor the calendar rather than discovering the gap in Phase 5.

---

# 13. Requirement → Novelty Traceability

Every novelty in `updated_proposal.md` §4.3 must be reachable from a requirement, or it is not getting built.

| Novelty | Scope | Requirements | Evaluated by |
|---|---|---|---|
| **N1** Claim-eligibility typing | Core | FR-6.1 – FR-6.4 | ER-9, AR-2 |
| **N2** Composition verification | Core | FR-7.3 – FR-7.5, NFR-3.2 | ER-1 (E6, E8), ER-2 |
| **N3** Disconfirming sweep | Core | FR-1.4, FR-3.3, FR-7.6 | ER-1 (E5, E7), ER-2 |
| **N4** Intra-report consistency | **Full** | FR-9.1 – FR-9.4 | ER-1 (E9), ER-2 |
| **N5** Assertiveness calibration | **Full** | FR-8.1 – FR-8.4 (+ FR-5.2, retained in Core) | ER-1 (E10), ER-3 |
| **N6** Misattribution verdict | Core | FR-7.2 | ER-1 (E2), ER-4 |
| **N7** Retraction propagation | Core | FR-10.1 – FR-10.3 | ER-7 |
| **N8** Seeded-error harness | Core | ER-1, RR-5 | — |
| **N9** Oracle ablation | Core | ER-5 | — |
| **N10** Router IAA validation | Core | AR-1 – AR-4 | ER-9 |
| **N11** Loop dynamics | Core | FR-11.4, ER-7 | — |

**Under Core scope, seeded-error classes E9 and E10 are still generated** (they cost almost nothing to produce) and reported as **undetected by every implemented condition**. That is a real result, not a gap: it is the measured confirmation that conditions A–D score zero on the failure modes N4 and N5 exist to catch — exactly the prediction §6.7 of the proposal states in advance.

**FR-1.4 is load-bearing for two novelties.** If the Researcher drops uncited passages to save space, N3 and N6 both become unimplementable and the failure will surface in Phase 5, not Phase 1. Treat it as a Phase 1 correctness requirement, not an optimisation.
