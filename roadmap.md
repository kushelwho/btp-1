# Roadmap — Type-Routed Claim Verification for Long-Form Research Synthesis

**Companion to** `requirements.md` (what must exist) and `updated_proposal.md` (what is novel and why). This document is the **execution plan and the session handoff record**.

**Start:** 2026-09-16 · **Team:** 2–3 people + Claude building · **Scope:** Core = Phases 1–7 (committed) · Full = Phases 8–11 (conditional)

> **This file is the memory.** Claude's context does not persist across sessions. When a new session starts mid-project, this document plus `checklist.md` is what says where we are, what is decided, and what is next. Keep both current — a stale roadmap costs a re-derivation of decisions already made.

---

# Standing Protocol

## P-1. The checklist ritual — every phase, without exception

**At the start of each phase, before any other work:** write `checklist.md` with that phase's work items as unchecked boxes. Tick each item the moment it is genuinely done — not when it is started, not when it "should work."

```markdown
# Phase N — <name>

## Claude
- [ ] Item
- [x] Completed item

## Team (blocking)
- [ ] Item — owner, est. time

## Team (non-blocking)
- [ ] Item — owner

## Blocked / open
- Anything waiting on a decision, with what it's waiting for
```

Rules:

- **One phase at a time.** `checklist.md` holds the *current* phase only. Archive the finished one to `checklists/phase-N.md` before overwriting.
- **Claude writes it at phase start and ticks items as it goes.** The team ticks their own items.
- **The "Blocked / open" section is the handoff.** A new session reads it first. If it is empty and boxes are unticked, work continues from the first unticked box.
- **A phase is not complete until every box is ticked or explicitly struck with a reason.**

## P-2. Input conventions

Each phase marks what is needed from the team:

| Marker | Meaning |
|---|---|
| 🔴 **BLOCKING** | Work stops until this is answered. Claude will say so and wait rather than guess. |
| 🟡 **NON-BLOCKING** | Needed this phase, but Claude keeps working meanwhile. Fine to do at your convenience. |
| 🔵 **HEADS-UP** | Nothing needed now — a flag that the *next* phase will need something that takes scheduling. |

Anything requiring coordination (annotation sessions, advisor meetings) is flagged one phase early, never sprung on the day.

## P-3. What Claude cannot do for you

Stated once, so it is not a surprise later:

- **Annotation (AR-2, ER-6).** If Claude labels the claims, the inter-annotator agreement is one model agreeing with itself. That is a circularity a reviewer will catch, and it invalidates N10. This is genuinely yours.
- **Judging output quality.** Whether a draft reads like a real survey, whether a flagged claim is truly a false positive, whether retrieval surfaced sensible passages — Claude will flag uncertainty, but some of this needs your eyes even unasked. You know this literature; Claude does not know it the way you do.
- **Understanding the code well enough to defend it.** Your examiner will ask how the composition checker decides a count claim is wrong. Budget real review time — that is the thing being graded.

## P-4. When a phase slips

Apply the cut order from `requirements.md` §10.1 — drop mechanism scope, never measurement time. Record the cut in `checklist.md` with a one-line reason, so the report can state honestly what was descoped and why.

---

# Core — Phases 1 to 7

## Phase 1 — Foundation and Pilot

**Goal.** A working repo, frozen contracts, an ingested corpus, and — critically — evidence that the whole thesis is testable.

**Exit gate.** 🚩 **A pilot draft contains enough T2 (aggregative) claims to measure.** If it does not, N2 and N3 cannot be tested and the queries must be redesigned before anything else is built. This gate outranks everything else in the phase.

**Claude builds**
- `git init`, repo scaffold, lockfile, `.gitignore`, `.env` handling (MR-15 to MR-20)
- **Frozen schemas** — claim, verdict, revision payload — as typed, validated objects, carrying Full-scope fields (modality, dependency edges) from day one
- PDF ingestion, chunking, `(document_id, page_number, chunk_id, char_span)` tagging (FR-1.1, FR-1.2)
- Local embedding retrieval + **retrieval pool `P` persistence including uncited passages** (FR-1.3, FR-1.4 — load-bearing for N3 and N6)
- Corpus manifest with SHA-256 hashes (FR-1.6)
- A throwaway single-pass drafter, purely to generate the pilot for the exit gate
- Draft 8–12 synthesis queries (DR-4) spanning single-topic, comparative, temporal, and known-contradiction shapes

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **D-3** — final corpus paper list (40–60 arXiv papers). Claude can propose a candidate list from `papers/` + citation chasing; you approve | Team | 2 h |
| 🔴 | **D-1** — budget path A or B. Blocks model assignment; switching after Phase 3 wastes work | Team | 30 min |
| 🔴 | API credentials if Path A | One person | 15 min |
| 🟡 | **Review the pilot draft against the exit gate** — do the aggregative claims actually appear? | Team | 1 h |
| 🟡 | **D-7** — realistic weekly availability for review and annotation | Team | — |
| 🔵 | **HEADS-UP:** Phase 3 drafts the annotation guideline; Phase 4 needs ~4 h from each of two annotators. Start thinking about who and when. | — | — |

---

## Phase 2 — Pipeline and Baseline Critic

**Goal.** The full agent loop running end-to-end with a naive Critic. This is **ablation condition A** — the baseline everything else must beat.

**Exit gate.** Condition A runs end-to-end on all queries and produces attributed reports with per-claim verdicts.

**Claude builds**
- Planner (FR-2), Researcher (FR-3) with enforced tool monopoly at the module boundary
- Synthesizer with mandatory inline attribution and stable sentence indices (FR-4)
- Atomizer **with modality preserved** (FR-5.2 — cheap now, unimplementable later if skipped)
- Naive T1-only entailment Critic (FR-7.1)
- Bounded Synthesizer↔Critic loop, typed escalation, token kill-switch (FR-11)
- Batched calls, prompt caching, on-disk response cache (MR-2, MR-3, MR-6)
- Structured per-call logging: model, prompt hash, tokens, cost, cache-hit (MR-18)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🟡 | **Read two full generated reports.** Do they read like real surveys? Is retrieval surfacing sensible passages? This is the judgment Claude cannot make | Team | 2 h |
| 🟡 | **D-2** — target paper venue and CFP deadline. A deadline landing mid-project changes everything downstream | Team + advisor | 1 h |
| 🔵 | **HEADS-UP:** Phase 3 will ask you to sanity-check the seeded errors. Realistic corruptions matter — a weak seed set makes every catch rate meaningless. | — | — |

---

## Phase 3 — Evaluation Harness

**Goal.** Build the measuring instrument **before** the mechanisms it measures. Building it after is how you unconsciously fit the mechanism to the test.

**Exit gate.** Harness generates all error classes, the runner executes condition A, and metrics come out the far end.

**Claude builds**
- Seeded-error generator, classes E1–E10, with ground-truth records (ER-1)
- Metrics: catch rate per class, FPR on clean drafts by claim type, verdict confusion matrix (ER-2 to ER-4)
- Config-driven ablation runner — new conditions addable without code changes (ER-8, MR-19)
- Oracle-retrieval harness (ER-5)
- Loop-dynamics instrumentation: marginal resolution, error displacement, cost per round (ER-7)
- **Inspector UI** (FR-13.1) — colour-coded claims, hover for passage and reasoning
- **Annotation guideline draft** with ≥5 worked examples per type (AR-1)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **Sanity-check the seeded errors.** Are the corruptions realistic? E9 (internal contradiction) is the hard one to inject well and the easiest to get wrong | Team | 2 h |
| 🔴 | **Approve the annotation guideline.** It must be frozen before labelling, or κ measures nothing | Team | 1 h |
| 🟡 | **D-4** — confirm two-annotator protocol and schedule the Phase 4 session | Team | 30 min |
| 🔵 | **HEADS-UP:** Phase 4 needs **4 h from each of two annotators**, labelling independently and blind. Book it now. | — | — |

---

## Phase 4 — Type Router and Annotation Study

**Goal.** N1 built and its taxonomy validated. This is **condition B**.

**Exit gate.** Condition B runs; Cohen's κ reported. 🚩 **κ ≥ 0.6, or the taxonomy is revised before Phase 5 builds on it.**

**Claude builds**
- Lexical pre-pass: discourse markers → T4, quantifier/count keywords → T2 (FR-6.2)
- LLM router for the remainder, per-claim type + confidence (FR-6.1, FR-6.3)
- T4 exemption path — logged, auditable, never entailment-checked (FR-6.4)
- Router confusion matrix vs. gold labels, T4→T1 and T2→T1 misroutes reported separately (ER-9)
- Cohen's κ computation on pre-adjudication labels (AR-2, AR-4)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **Annotate 200 claims, independently and blind to the router's output.** Two people. Showing the model's guess destroys the measurement | 2 annotators | 4 h each |
| 🔴 | **Adjudicate disagreements** — after κ is computed, not before | Team | 1 h |
| 🟡 | **D-5** — include the local-NLI condition as a reported ablation? Free, and a genuine extra result | Team | 15 min |

> If κ lands below 0.6, that is a **finding, not a failure** — it means the taxonomy needs fewer, better-separated types. Revising and re-annotating costs a phase; building three novelties on an unreliable taxonomy costs the contribution.

---

## Phase 5 — Composition, Misattribution, Dependency Graph

**Goal.** N2, N6, N7 — the strongest novelty in the set. This is **condition C**.

**Exit gate.** Condition C runs; catch rate on E6 and E8 measurably above condition A.

**Claude builds**
- **T2 decomposition** (FR-7.3) — splitting an aggregative claim into atoms with correct passage assignment. The hardest single component; see `requirements.md` §10.3
- **Composition operators in code** (FR-7.4, FR-7.5): `count`, `proportion`, `universal`, `existential`, `comparison`, `trend`, `contrast`, with unsupported operators escalated rather than silently passed
- **Deterministic unit tests on every operator** (NFR-3.2) — these are pure functions, and the tests are the cleanest evidence that N2 is code rather than vibes
- Misattribution verdict: re-check against pool `P`, return `Misattributed` with the entailing chunk (FR-7.2)
- `Partially-Supported` with machine-readable repair hints (FR-7.7)
- Claim dependency graph + retraction propagation + evidence concentration (FR-10)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🟡 | **Spot-check 20 T2 decompositions.** Did it split the claim correctly and attach the right passages? Decomposition errors silently corrupt every downstream verdict | Team | 2 h |
| 🟡 | Review the operator unit tests — this is high-value viva preparation, not busywork | Team | 1 h |

> **Timebox this phase.** If decomposition overruns, ship a partial operator set (`count` and `comparison` only, escalating the rest per FR-7.5). That still tests C2.

---

## Phase 6 — Disconfirming Sweep and Core Ablation

**Goal.** N3 built (**condition D**), then the full Core sweep and all measurements.

**Exit gate.** Conditions A–D all measured; catch rate per error class, FPR by claim type, oracle ablation, and loop dynamics all in hand.

**Claude builds**
- Universal-force detection and the **disconfirming-evidence sweep** over uncited members of `P` (FR-7.6)
- T3 defeasibility path (FR-7.8)
- Full ablation sweep A–D across all queries, via Batch API
- Oracle-retrieval run (ER-5) — separates Critic error from retrieval error
- Loop dynamics: marginal resolution, **error displacement**, cost and latency per round (ER-7)
- Bootstrap CIs on catch rate and FPR (ER-11)
- E9/E10 reported as **undetected by every implemented condition** — the measured confirmation of §6.7's advance prediction

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **Blind hallucination-rate evaluation** (ER-6). Reports randomised, condition labels stripped. You are invested in the outcome; blinding is what keeps this number credible | 2 people | 6 h each |
| 🔴 | **D-6 — commit to Core or attempt Full.** Decide here, with real velocity data in hand | Team | 30 min |
| 🟡 | Review the results tables before analysis is written | Team | 2 h |

> **This phase must not compress.** A bug found at hour six of an overnight sweep costs the night. Budget re-run time.

---

## Phase 7 — Analysis and BTP Report

**Goal.** Core scope complete and defensible.

**Exit gate.** Report drafted, every falsifiable claim has a reported outcome, artifacts prepared.

**Claude builds**
- Results tables with **cost and latency alongside accuracy in every one** (ER-10)
- Analysis of each falsifiable claim, including negative outcomes
- Reproducibility artifacts: corpus manifest, prompt templates, seeded-error generator, gold label set (RR-1 to RR-7)
- Report scaffolding, figures, and prose drafts

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **Own the report.** Claude drafts; you revise into your own voice and verify every claim. This is what gets graded | Team | 15 h |
| 🔴 | Advisor review checkpoint | Team + advisor | 2 h |
| 🟡 | Viva preparation — walk the code with the operator tests open | Team | 5 h |

**🎯 Core scope is complete here.** A finished 4-condition ablation with real numbers, a validated taxonomy, and measured verifier reliability. Stop here and it is a solid BTP.

---

# Full — Phases 8 to 11 (conditional on D-6)

## Phase 8 — Intra-Report Consistency

**Goal.** N4 — the failure mode that cannot occur in short-form QA. **Condition E.**

**Exit gate.** Condition E runs; catch rate on E9 above zero, at a usable false-contradiction rate.

**Claude builds**
- Entity/topic overlap **gating in code** before any LLM call (FR-9.1 — mandatory; the naive O(n²) sweep is not affordable)
- Pairwise contradiction check on surviving pairs (FR-9.2)
- Payload carrying **both** sentence indices and **both** passages (FR-9.3)
- Scope-qualifier detection if time allows (FR-9.4)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🟡 | Review flagged contradiction pairs — are they real conflicts or scope-qualification artifacts? | Team | 2 h |

---

## Phase 9 — Assertiveness Calibration

**Goal.** N5 — overclaiming, the characteristic failure of research writing. **Condition F.**

**Exit gate.** Condition F runs; catch rate on E10 above zero.

**Claude builds**
- Versioned modality ladder as a lexicon, not an LLM call (FR-8.1)
- Evidence-strength assessment and `Overclaim` flagging (FR-8.2)
- Downgrade repair hints, never deletions (FR-8.3); under-claiming logged, never flagged (FR-8.4)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🟡 | Judge 20 `Overclaim` flags — is the boundary calibrated? This is the fuzziest check in the system | Team | 2 h |

> If FPR is unusable, report N5 as a **diagnostic signal rather than a revision trigger** — exactly as §8.5 of the proposal pre-commits. That is a planned outcome, not a failure.

---

## Phase 10 — Full Ablation

**Goal.** All six conditions measured together.

**Exit gate.** A–F complete; the §6.7 prediction tested — do A–D score exactly zero on E9 and E10?

**Claude builds**
- Full A–F sweep, re-run from a clean cache for consistency
- Re-analysis with E and F included
- Updated tables, CIs, cost curves

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🟡 | Extend the blind evaluation to conditions E and F | 2 people | 2 h each |

---

## Phase 11 — Paper and Artifact Release

**Goal.** Submission-ready.

**Claude builds**
- Paper draft in venue format
- Public artifact bundle: code, prompts, manifest, error generator, gold labels (RR-3 to RR-8)
- One-command repro script for the headline table (RR-8)

**Team input**

| | What | Owner | Time |
|---|---|---|---|
| 🔴 | **Own the paper.** Same as the report — Claude drafts, you revise and verify | Team | 15 h |
| 🔴 | Advisor sign-off and submission | Team + advisor | 2 h |
| 🟡 | FR-12.1 (evidence-suppression audit) only if this phase lands early | — | — |

---

# Decision Gates Summary

| # | Decision | Phase | Blocking |
|---|---|---|---|
| **D-1** | API budget: Path A or B | 1 | 🔴 |
| **D-3** | Final corpus list | 1 | 🔴 |
| **D-7** | Team weekly availability | 1 | 🟡 |
| **D-2** | Paper venue and deadline | 2 | 🟡 |
| **D-4** | Annotation protocol | 3 | 🟡 |
| **D-5** | Local-NLI condition | 4 | 🟡 |
| **D-6** | **Core or Full** | 6 | 🔴 |

---

# Total Team Time

| Phase | Blocking | Non-blocking |
|---|---|---|
| 1 | 2.75 h | 1 h |
| 2 | — | 3 h |
| 3 | 3 h | 0.5 h |
| 4 | 9 h (2 annotators) | 0.25 h |
| 5 | — | 3 h |
| 6 | 12.5 h (2 people) | 2 h |
| 7 | 17 h | 5 h |
| **Core total** | **~44 h** | **~15 h** |
| 8–11 (Full) | ~17 h | ~8 h |

Roughly **60 hours across the team for Core**, concentrated in Phases 4, 6, and 7 — annotation, blind evaluation, and owning the writeup.

> Note: `requirements.md` §10.2 still carries the older effort model, which priced implementation as human coding hours. The phase structure here supersedes it. Worth syncing before the advisor reads both.

---

# Phase Status

Update as phases complete. This is the first thing a new session should read.

| Phase | Status | Completed | Notes |
|---|---|---|---|
| 1 — Foundation and Pilot | ⬜ Not started | — | |
| 2 — Pipeline and Baseline Critic | ⬜ Not started | — | |
| 3 — Evaluation Harness | ⬜ Not started | — | |
| 4 — Type Router and Annotation | ⬜ Not started | — | |
| 5 — Composition and Misattribution | ⬜ Not started | — | |
| 6 — Sweep and Core Ablation | ⬜ Not started | — | |
| 7 — Analysis and BTP Report | ⬜ Not started | — | |
| 8 — Intra-Report Consistency | ⬜ Conditional | — | Requires D-6 = Full |
| 9 — Assertiveness Calibration | ⬜ Conditional | — | Requires D-6 = Full |
| 10 — Full Ablation | ⬜ Conditional | — | Requires D-6 = Full |
| 11 — Paper and Artifact Release | ⬜ Conditional | — | Requires D-6 = Full |
