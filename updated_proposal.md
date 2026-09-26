# Type-Routed Claim Verification for Hallucination-Resistant Long-Form Research Synthesis

**Summary.** Claim-level verification — decompose generated text into atomic claims, check each against retrieved evidence — is now the dominant response to LLM hallucination. It was developed for short-form question answering, and it transfers badly to long-form research synthesis. Three failure modes appear once outputs are long enough to be reports rather than answers, and none is detectable by per-claim entailment against cited evidence: claims whose truth conditions range over a *set* of sources, claims that contradict *each other* while each remains individually grounded, and claims that overstate *what their evidence licenses*. We propose a type-routed Critic that checks all three, operating training-free inside a bounded generative drafting loop, and we evaluate it with a seeded-error harness in which six of eleven error classes are undetectable by the standard method by construction.

> **Novelty claims are consolidated in §4.** That section states what is new, what is adopted, and where each claim is specified, implemented, and tested.

---

# 1. Problem Statement

Large Language Models (LLMs) synthesize complex information, generate cohesive narratives, and perform multi-step reasoning at a level that makes them attractive for automated research synthesis. When deployed to construct long-form reports from multi-document corpora, however, they exhibit a persistent failure mode: **context-conflicting hallucination**. As output length and corpus density grow, models produce statements that are fluent, authoritative, and stylistically persuasive but unsupported by — or directly contradictory to — the retrieved sources.

The field has converged on claim-level verification as the response, and that convergence is well-founded (§2.2). Our problem is narrower:

> **Claim-level verification was developed for short-form question answering, and it does not transfer cleanly to long-form synthesis.**

The reason is structural. In short-form QA, a response is a handful of atomic facts, each traceable to a passage. In a research report, the sentences carrying the most value are precisely the ones no single passage entails:

```
  "Three of the five surveyed frameworks bound their correction loop."      → aggregation over sources
  "This approach consistently outperforms debate baselines."                → universal quantifier
  "Unlike earlier work, X does not measure verifier error."                 → cross-source contrast
  "The trend from 2023 to 2026 is toward bounded recovery."                 → temporal synthesis
  "This demonstrates that retrieval quality is the binding constraint."     → assertiveness beyond evidence
  "We now turn to the question of retrieval quality."                       → discourse scaffolding
```

## 1.1 Three Failure Modes Unique to Long-Form Output

**F1 — Set-valued truth conditions.** A claim like *"three of five frameworks bound their loop"* is not an atom and is not reducible to a set of independently-scored atoms. Its truth condition is an *operator over* a set of atoms. Single-passage entailment mishandles it in both directions: it is flagged `Unsupported` when correct (no one passage entails it), and it passes when incorrect (the cited passage supports the fragment that was checked). Miscounts, false contrasts, and invented trends are invisible to per-passage checking by construction.

**F2 — Internal inconsistency.** A long report can assert in §2 that *"GSAR bounds its recovery loop"* and in §5 that *"no reviewed framework bounds its loop."* Both claims may be individually grounded, against different passages, and jointly contradictory. This failure **cannot occur in short-form QA** — an output must be long enough to contradict itself. No verifier that checks claims independently against evidence can detect it, regardless of entailment quality.

**F3 — Assertiveness drift.** Verification asks *whether* a claim is supported, never whether its **linguistic strength matches the strength of its support**. *"This demonstrates X"* backed by one preliminary result is an overclaim, but it passes entailment because the underlying fact is present. Standard atomization pipelines discard epistemic modality as noise before checking, so overclaiming — the characteristic failure of research writing specifically — is invisible to them.

## 1.2 The Unexamined Verifier

A second, compounding gap concerns the verifier itself. The literature reports the accuracy of systems that *contain* verifiers, but rarely the error profile *of* the verifier. Where a catch rate is reported (GSAR's $M_4$), it is measured on short isolated claims with gold evidence, with no corresponding false-positive rate.

For long-form synthesis, false-positive rate is the metric that determines usability. A Critic that flags every topic sentence produces a report drowned in "unverified" banners, regardless of how many real hallucinations it catches. Strictness and completeness trade off directly, and no reviewed work measures where that tradeoff sits.

---

# 2. Related Work

Prior work relevant to this proposal falls along two axes. Both are load-bearing: Axis A supplies the multi-agent architecture and bounded-recovery framing, Axis B supplies the verification primitives.

```
                        Axis A — Multi-Agent Verification & Debate
  Apr 2026: GSAR (Kamelhar)          ──► Typed grounding, 3-tier recovery, K_max budget
  Mar 2026: MARCH (Li et al.)        ──► Asymmetric 3-agent MARL, blinded Checker
  Jan 2026: Tool-MAD (Jeong et al.)  ──► Heterogeneous tools, adaptive retrieval, RAGAS stability
  2025:     ClaimVerAgents (Sallami) ──► Modular sub-task decomposition, NEI abstention
  Mar 2025: Yang et al. (MDPI)       ──► Error logs, weighted voting, entropy compression
  2023/24:  Du et al. (ICML)         ──► Multi-agent debate consensus baseline

                        Axis B — Attributed Generation & Faithfulness Evaluation
  Atomic decomposition   ──► FActScore; RAGAS faithfulness
  Faithfulness scoring   ──► Vectara HHEM / HHEM-2.1; FaithJudge; TruLens RAG Triad
  Claim verification     ──► FEVER benchmark lineage; MedRAGChecker; FIRE
  Cited generation       ──► ALCE / citation-attributed generation; RARR; Self-RAG
  Long-form factuality   ──► SAFE / LongFact
```

## 2.1 Axis A — Multi-Agent Verification and Debate

### GSAR: Typed Grounding for Hallucination Detection and Recovery in Multi-Agent LLMs
**Federico A. Kamelhar, Oracle Corporation (arXiv, April 2026)**

A grounding-evaluation and replanning framework for operational multi-agent diagnostic systems. Partitions claims into a four-way typology — *grounded*, *ungrounded*, *contradicted*, *complementary* — giving first-class standing to non-redundant alternative perspectives. Assigns evidence-type-specific weights $w : T \to [0,1]$ reflecting epistemic strength (tool-observed > signal-observed > model-inferred), computes an asymmetric contradiction-penalised score

$$S = \frac{W(G) + W(K)}{W(G) + W(U) + \gamma W(X) + W(K)}$$

and couples $S$ to a three-tier decision function $\delta \in \{\text{proceed}, \text{regenerate}, \text{replan}\}$ under an explicit compute budget $K_{max}$. Evaluated on FEVER with gold Wikipedia evidence under four independent LLM judges.

*Relation to this work.* GSAR is the closest prior work on **bounded recovery** and the only reviewed paper reporting a verifier catch rate ($M_4$). We adopt its bounded-budget framing. Two properties limit its applicability here: it evaluates on FEVER short claims rather than generated long-form text, and it reports catch rate without a corresponding false-positive rate. Its four-way typology also types *evidence status*, not *claim checkability* — a distinction developed in §4.1 (N1). It is a single-author industry preprint evaluated on a proprietary stack (Locus SDK, Oracle Database 26ai, Cohere embed-v3.0), which should temper its weight as a baseline.

### MARCH: Multi-Agent Reinforced Self-Check for LLM Hallucination
**Zhuo Li et al., Alibaba Qwen Team (arXiv, March 2026)**

An asymmetric three-agent RL pipeline: a *Solver* generates a RAG response, a *Proposer* acts as a "Response Atomizer" decomposing the response into claim-level verifiable propositions and QA pairs, and a *Checker* validates those propositions against retrieved evidence **in isolation, deprived of the Solver's original output**. The paper argues that concurrent exposure to query, documents, and response induces *confirmation bias*, and that deliberate information asymmetry breaks the cycle of self-confirmation. Trained via multi-agent RL with a zero-tolerance reward: any discrepancy between Proposer claims and Checker validation penalises the entire trajectory.

*Relation to this work.* **MARCH is our nearest neighbour and is addressed directly in §7.1.** Its Solver → Proposer → Checker decomposition maps closely onto our Synthesizer → Atomization → Grounding Check, including the isolation rationale. We treat MARCH's information-asymmetry argument as **settled and adopted**, not as a position we contest (§4.4). Our departure is that MARCH — like all reviewed work — assumes every extracted proposition is verifiable by single-passage entailment, which §1.1 shows is false for long-form synthesis.

### Tool-MAD: Multi-Agent Debate with Diverse Tool Augmentation and Adaptive Retrieval
**Seyeon Jeong, Yeonjun Choi, Jong Wook Kim, Beakcheol Jang — Yonsei / Sangmyung University (arXiv, January 2026)**

Addresses the static-evidence limitation of classic debate by assigning each debating agent a distinct external tool (search API vs. RAG module), introducing an adaptive query-formulation loop that refines retrieval across debate rounds, and folding RAGAS Faithfulness and Answer Relevance into a "stability score" used by a Judge agent. Reports up to 5.5% accuracy improvement over MADKE across four fact-verification benchmarks.

*Relation to this work.* Establishes that iterative, debate-driven retrieval refinement beats one-shot retrieval. Verification remains debate-adjudicated and the task remains short-claim fact verification.

### ClaimVerAgents: A Multi-Agent Retrieval-Augmented Claim Verification Framework
**Dorsaf Sallami, Sabrine Amri, Esma Aïmeur — University of Montreal (IEEE/ACS AICCSA, 2025)**

A modular, interpretable multi-agent architecture for real-time fake-news detection, decomposing verification into claim extraction, query generation, web search, evidence evaluation, verdict decision, and explanation generation within a confidence-aware pipeline. Evaluated on PolitiFact. Includes a "Not Enough Information" (NEI) abstention label.

*Relation to this work.* The NEI mechanism is the closest precedent for our escalation state — evidence-insufficiency as a legitimate verdict rather than a forced decision. Task is single-claim classification, not generation.

### Minimizing Hallucinations and Communication Costs
**Yi Yang, Yitong Ma, Hao Feng, Yiming Cheng, Zhu Han (MDPI Applied Sciences, March 2025)**

Combines repetitive inquiry and internal error logs for single-model hallucination mitigation with adversarial debate and voting across models. Dynamically adjusts voting weights by historical accuracy, and applies entropy compression to reduce token usage and task completion time.

*Relation to this work.* One of the few papers treating token cost as a first-class objective rather than an afterthought. Truth remains defined by weighted agreement.

### Improving Factuality and Reasoning in Language Models through Multiagent Debate
**Yilun Du, Shuang Li, Antonio Torralba, Igor Mordatch, Joshua B. Tenenbaum (arXiv 2023 / ICML 2024)**

The foundational multi-agent debate paradigm: multiple model instances independently propose answers, then iteratively condition on each other's responses across rounds. Improves factual accuracy and reasoning over single-agent inference and self-reflection across six benchmarks. Requires only black-box model access.

*Relation to this work.* Our debate baseline in the three-way comparison (§6.8).

## 2.2 Axis B — Attributed Generation and Faithfulness Evaluation

This axis, not multi-agent debate, is the methodological ancestor of our Critic, and both of our nearest neighbours cite it explicitly. GSAR states that "FActScore establishes the atomic-claim decomposition protocol we rely on"; MARCH's Proposer is a FActScore-lineage atomizer.

- **Atomic-claim decomposition.** FActScore established the protocol of breaking generated text into atomic facts scored independently against a knowledge source. RAGAS operationalizes this as a *faithfulness* metric: decompose an answer into statements, compute the fraction supported by retrieved context.
- **Faithfulness classifiers and judges.** Vectara's HHEM / HHEM-2.1 emits a binary hallucinated/non-hallucinated label against a source context. FaithJudge improves judge consistency by anchoring against human-annotated hallucination pools. TruLens's RAG Triad scores context relevance, groundedness, and answer relevance as separate LLM-judge scalars.
- **Claim verification pipelines.** The FEVER benchmark established the three-way NLI partition (SUPPORTS / REFUTES / NOT ENOUGH INFO) that nearly all downstream work inherits. MedRAGChecker performs atomic-claim support estimation with class-specific reliability weighting. FIRE iterates retrieval and verification in an agentic loop.
- **Citation-attributed generation.** A parallel line trains or prompts models to emit inline citations and evaluates citation precision/recall directly (ALCE-style attributed generation; RARR's post-hoc research-and-revise; Self-RAG's retrieve-critique-generate loop).
- **Long-form factuality.** SAFE / LongFact extend atomic-fact scoring to long-form generation with search-based verification of each atom.

**Adopted from this axis, and not claimed as contribution:** atomic decomposition, per-claim entailment against cited evidence, inline attribution, and the three-way verdict lattice (§4.4).

**Not addressed by this axis:** every method above scores atoms *independently* and aggregates by counting. A claim whose truth condition is itself an aggregation has no defined treatment (F1). No method compares claims to one another (F2). All discard epistemic modality during atomization (F3). None distinguishes claims *ineligible* for entailment checking from claims that fail it.

> *Citation hygiene note: exact venues, years, and author lists for Axis B entries must be verified against primary sources before submission. Axis A entries are verified against the PDFs in `papers/`.*

---

# 3. Gap Analysis

| Gap | Description | Status in reviewed literature |
|---|---|---|
| **G1 — Aggregative claims** | Claims whose truth conditions range over a *set* of passages (counts, quantifiers, comparisons, trends) cannot be verified by single-passage entailment, yet are the highest-value sentences in a synthesis report. | **Unaddressed.** All reviewed methods score atoms independently. |
| **G2 — Claim eligibility** | Long-form prose contains discourse scaffolding, hedged framing, and interpretive commentary that are not factual claims. Forcing them through binary entailment guarantees over-flagging. | **Unaddressed.** GSAR's four-way partition types *evidence status*, not *claim checkability*. |
| **G3 — Disconfirming evidence** | Universal claims ("consistently", "never", "unlike X") are falsified by evidence the Synthesizer did *not* cite. Verifying only against cited passages cannot detect over-generalization. | **Unaddressed.** All reviewed verifiers check claim-against-cited-evidence. |
| **G4 — Internal consistency** | Two individually-grounded claims within one report may contradict each other. Only possible in long-form output. | **Unaddressed.** No reviewed method compares claims to one another. |
| **G5 — Assertiveness calibration** | Claim modality ("suggests" vs. "demonstrates") is discarded during atomization, so overclaiming on thin evidence passes verification. | **Unaddressed.** Modality is treated as noise across both axes. |
| **G6 — Citation vs. factual error** | A claim that is true but cited to the wrong passage is indistinguishable from a fabrication, forcing expensive regeneration where a citation swap would do. | **Unaddressed as an in-loop signal.** ALCE-style work measures citation precision at evaluation time only. |
| **G7 — Verifier false-positive rate** | Catch rate is reported (GSAR $M_4$); false-positive rate is not. For long-form output, FPR determines usability. | **Partially addressed.** GSAR reports catch rate on FEVER short claims only. |
| **G8 — Loop dynamics** | Whether iterative correction converges, and whether revision displaces errors rather than removing them, is unmeasured. Iteration caps are asserted, not derived. | **Unaddressed.** GSAR and ClaimVerAgents impose bounds without reporting marginal return per round. |
| **G9 — Training cost** | The strongest self-check result (MARCH) requires multi-agent RL. | **Open by design.** We target the training-free regime. |

---

# 4. Novelty Claims

This section consolidates every novelty claim so it can be assessed without reading the full system description. Each entry states the claim, why it is new against the reviewed literature, its nearest prior work, and where in this document it is specified, seeded, ablated, and falsified.

**Strength ratings** are our own honest assessment of how well each claim survives adversarial questioning: *Strong* = no reviewed method does this and the setting forces it; *Moderate* = adjacent work exists on a different axis; *Supporting* = sound and useful, but insufficient to carry the contribution alone.

## 4.1 Mechanism Novelties

### N1 — Claim-eligibility typing (T1–T4) · *Moderate*

**Claim.** Claims in a long-form draft are routed by *what kind of check they admit* — direct-attribution, aggregative, inferential, or non-checkable discourse — before any verification is attempted. Discourse scaffolding is exempted rather than failed.

**Why it is new.** Every reviewed verifier applies one operator uniformly to every extracted proposition. The implicit assumption — that all output text is checkable factual content — holds for QA answers and fails for reports, where transitions, framing, and structural sentences are a large fraction of the text.

**Nearest prior work.** GSAR's four-way partition (*grounded / ungrounded / contradicted / complementary*). The distinction is the axis: GSAR types **evidence status** (what did we find in support of this claim?); N1 types **claim checkability** (does entailment even apply to this sentence?). A GSAR-typed claim has already been checked; an N1-typed claim has not yet been routed.

**Anticipated objection.** *"This is prompt engineering, not a contribution."* Answer: the router is a component with a measured error profile and a validated taxonomy (N10), not a heuristic. Its misroute costs are asymmetric and reported separately.

→ Specified §5.3 Step B · Gap G2 · Ablation condition B · Claim C1

### N2 — Composition verification for aggregative claims · *Strong*

**Claim.** For claims whose truth condition is an operator over a set of sources — counts, comparisons, trends — the operator is evaluated **by the system over independently verified constituent atoms**, rather than accepted as the model asserted it.

**Why it is new.** FActScore, RAGAS, MARCH's Checker, GSAR, and every method on Axis B score atoms independently and then aggregate by *counting how many passed*. None defines the case where a claim's truth condition **is itself an aggregation**. "Three of five frameworks bound their loop" is not an atom, is not a set of atoms, and has no treatment in any reviewed method.

**Nearest prior work.** None on this operation. FActScore is the nearest ancestor in that it supplies the atom decomposition N2 builds on.

**Anticipated objection.** *"Couldn't a stronger entailment model handle this?"* No — the failure is structural, not capacity-limited. The cited passage genuinely does not contain the aggregation, so no entailment judgment over that passage can return the right answer.

→ Specified §5.3 Step C (T2) · Gap G1 · Errors E6, E8 · Ablation condition C · Claim C2

### N3 — Disconfirming-evidence sweep · *Strong*

**Claim.** For claims with universal force (`all`, `none`, `consistently`, `never`, `unlike X`), the Critic searches the **uncited remainder of the retrieval pool** for counterexamples, inverting the verification direction from confirmation to falsification.

**Why it is new.** Every verifier in both axes checks *claim against cited evidence*. Under that procedure a universal claim **cannot fail**: the cited passage supports it, and the counterexample lives in a passage the Synthesizer chose not to cite. Over-generalization is therefore undetectable by the field's standard operation, in principle rather than in practice.

**Nearest prior work.** None. Tool-MAD retrieves adaptively across debate rounds, but retrieves to *support* argument, not to falsify a claim under test.

**Anticipated objection.** *"Is this not just better retrieval?"* No — retrieval quality determines what is in the pool; N3 changes what is *done* with the pool. It runs against passages already retrieved and deliberately not cited.

→ Specified §5.3 Step C (T2) · Gap G3 · Errors E5, E7 · Ablation condition D · Claim C3

### N4 — Intra-report consistency checking · *Strong*

**Claim.** After per-claim verification, surviving claims are checked **against each other** for contradiction, gated by entity and topic overlap. Detected pairs return both sentence indices and both supporting passages.

**Why it is new.** No reviewed method compares claims to one another; all compare claims to evidence. Two claims can each be perfectly grounded against different passages and still contradict, and no amount of entailment accuracy will surface that.

**Why this one is the sharpest instance of "forced by the setting."** The failure requires an output long enough to contradict itself. It cannot occur in short-form QA, which is precisely why the QA-derived literature has no mechanism for it.

**Nearest prior work.** None. Du et al. surface disagreement *between agents*; N4 surfaces disagreement *within one document produced by one agent*.

→ Specified §5.3 Step E · Gap G4 · Error E9 · Ablation condition E · Claim C4

### N5 — Assertiveness calibration · *Strong*

**Claim.** Epistemic modality is **retained through atomization** and compared against evidence strength. A claim whose linguistic force exceeds what its evidence licenses is flagged `Overclaim`, with a downgrade hint rather than a deletion.

**Why it is new.** Every atomizer in Axis B normalizes "may suggest that X" to the proposition X before checking — modality is treated as noise to be stripped. As a direct consequence, overclaiming is invisible to all of them: the underlying fact is present, so entailment passes. This matters disproportionately in research synthesis, where overclaiming is the characteristic failure mode of the genre.

**Nearest prior work.** None. This required a change upstream in Step A, which is why no method that inherits the standard atomization protocol can add it without modification.

**Anticipated objection.** *"The acceptable/excessive boundary is subjective."* Conceded, and scoped: an explicit modality ladder rather than open-ended judgment, with the highest expected FPR of any check, and an honest fallback (§8.5) of reporting it as a diagnostic rather than a revision trigger.

→ Specified §5.3 Step D (+ Step A modification) · Gap G5 · Error E10 · Ablation condition F · Claim C5

### N6 — Misattribution as a distinct verdict · *Supporting*

**Claim.** A claim failing against its cited passage is re-checked against the wider pool before verdict. `Misattributed` (entailed by $Q$, cited to $P$) is returned distinctly from `Unsupported` (entailed by nothing), with a repair hint naming $Q$.

**Why it is new.** Reviewed verifiers collapse both cases into a single failure, forcing the Synthesizer toward regeneration when a citation swap would suffice — cheaper, and less likely to delete correct content. ALCE-style work measures citation precision, but as an *evaluation metric*, not an in-loop repair signal.

→ Specified §5.3 Step C (T1) · Gap G6 · Error E2 · Ablation condition C · Claim C6

### N7 — Retraction propagation over a claim dependency graph · *Supporting*

**Claim.** A `claim → atoms → passages → documents` graph, built as a by-product of N2's decomposition, propagates invalidation: when an atom fails in any round, every aggregative claim depending on it is automatically re-flagged. Evidence concentration falls out as a reportable risk metric.

**Why it is new.** Without it, a constituent fact can be corrected in round $k$ while the aggregative claim resting on it silently retains its stale value — a failure created by the combination of iterative revision and composition checking, and therefore not present in any reviewed system.

→ Specified §5.3 Step F · Ablation condition C

## 4.2 Measurement Novelties

### N8 — Adversarially-designed seeded-error harness · *Strong*

**Claim.** An eleven-class error taxonomy in which **six classes (E5–E10) are undetectable by single-passage entailment by construction**, with catch rate reported per class and false-positive rate reported by claim type.

**Why it is new.** Seeded-error evaluation is itself a known technique; the design is the contribution. Because the undetectable classes are specified in advance, the harness is a direct test of N2–N5 rather than a general NLI benchmark, and conditions A–D are *predicted to score exactly zero* on E9 and E10. GSAR reports a catch rate but no false-positive rate; no reviewed work reports either broken down by error class or claim type.

→ Specified §6.2, §6.3 · Gap G7

### N9 — Oracle-retrieval ablation · *Supporting*

**Claim.** The pipeline is run twice — real retrieval and gold-passage injection — attributing any performance gap to retrieval rather than to the Critic.

**Why it is new.** Retrieval failure and verifier failure are confounded in every reviewed evaluation and reported as one number. Separating them is cheap and no one does it.

→ Specified §6.4

### N10 — Router validation by inter-annotator agreement · *Supporting*

**Claim.** Two annotators label 200 held-out claims T1–T4; Cohen's $\kappa$ is reported, and the study is scheduled *before* the mechanisms that depend on the taxonomy are built.

**Why it is new.** Taxonomies in this literature are asserted, not validated. Treating our own as falsifiable — and sequencing the check before it becomes load-bearing — is what separates N1 from an untested heuristic.

→ Specified §6.5 · Phase P5 · Claim C7

### N11 — Loop dynamics and error displacement · *Moderate*

**Claim.** Marginal claim resolution per round, token cost per round, and **error displacement rate** — new unsupported claims *introduced* by a revision, measured by re-verifying previously-clean spans.

**Why it is new.** Iteration caps are asserted throughout the literature (GSAR's $K_{max}$, ClaimVerAgents' three rounds, Tool-MAD's $T$) but the marginal return that would justify a particular value is never reported. Error displacement is unmeasured across the entire self-correction line — Self-Refine, Reflexion, GSAR, MARCH — and a non-zero result would be an uncomfortable finding for all of it. Our iteration bound $N$ is derived from this curve rather than asserted.

→ Specified §6.6 · Gap G8 · Claim C8

## 4.3 Novelty Index

| ID | Novelty | Strength | Gap | Error class | Ablation | Falsifies via |
|---|---|---|---|---|---|---|
| **N1** | Claim-eligibility typing (T1–T4) | Moderate | G2 | — | B | C1 |
| **N2** | Composition verification | **Strong** | G1 | E6, E8 | C | C2 |
| **N3** | Disconfirming-evidence sweep | **Strong** | G3 | E5, E7 | D | C3 |
| **N4** | Intra-report consistency | **Strong** | G4 | E9 | E | C4 |
| **N5** | Assertiveness calibration | **Strong** | G5 | E10 | F | C5 |
| **N6** | Misattribution verdict | Supporting | G6 | E2 | C | C6 |
| **N7** | Retraction propagation | Supporting | — | — | C | — |
| **N8** | Adversarial seeded-error harness | **Strong** | G7 | E1–E11 | — | C1–C6 |
| **N9** | Oracle-retrieval ablation | Supporting | — | — | — | — |
| **N10** | Router validation (IAA) | Supporting | — | — | — | C7 |
| **N11** | Loop dynamics + error displacement | Moderate | G8 | — | — | C8 |

**Novel only in combination:** training-free operation (G9) + long-form generative target + bounded compute + typed escalation. Each ingredient exists somewhere in the reviewed literature; the assembly does not. This is legitimate to state but weak standing alone, and should never lead.

**Stretch component (designed, conditionally scheduled):** evidence-suppression audit — §5.5, error E11, phase P8. Shares machinery with N3 and is deliberately excluded from the index above so it is not double-counted.

## 4.4 Explicitly Not Claimed

Stating the boundary precisely is what makes the claims above credible. The following are adopted from prior work and are **not** presented as contributions:

| Adopted | Source |
|---|---|
| Atomic-claim decomposition | FActScore; MARCH's Proposer |
| Blinded / isolated verification, and the confirmation-bias argument for it | **MARCH** — settled, adopted, not contested |
| Per-claim entailment against cited evidence | Axis B generally |
| The three-way verdict lattice (supported / contradicted / insufficient) | FEVER lineage |
| Bounded compute budget for a correction loop | GSAR ($K_{max}$) |
| Abstention as a legitimate output state | ClaimVerAgents (NEI) |
| Inline citation-attributed generation | ALCE lineage |
| Retrieval-tool monopoly and provenance tagging | Standard practice |

In particular, we do not claim to have discovered that evidence-grounded verification outperforms inter-model consensus, nor that blinding the verifier defeats self-confirmation. Du et al. established the former as a question and MARCH answered the latter in March 2026. We build on both.

## 4.5 Novelty in One Paragraph

> Existing claim verifiers check a claim against the evidence it cites. That is sufficient for short-form QA and insufficient for research synthesis, because synthesis prose is dominated by claims whose truth conditions range over a *set* of sources, claims that can contradict *each other* while each remains individually grounded, and claims that overstate *what their evidence licenses* — none of which the standard operation can detect, in principle rather than in practice. We type claims by what kind of check they admit, evaluate aggregation operators over verified atoms rather than trusting them, search uncited evidence for counterexamples, check claims against one another, and calibrate claim strength against evidence strength. We then measure the verifier itself with a seeded-error harness in which six of eleven error classes are invisible to the standard method by construction.

---

# 5. Proposed Solution

## 5.1 Conceptual Overview

We propose a **type-routed, evidence-grounded multi-agent framework for long-form research synthesis**. Four isolated functional agents operate over a cyclic state graph under a hard compute bound. The distinguishing mechanism is a Critic that does not treat verification as a uniform operation: it determines *what kind of claim* it is looking at, dispatches to a verification path matching that claim's truth conditions, and then performs checks that no per-claim verifier can perform — comparing claims to each other, and comparing claim strength to evidence strength.

```
        ┌──────────────────────────────────────────────────────────────┐
        │                        Planner Agent                         │
        │              Decomposes query into sub-tasks                 │
        └───────────────────────────┬──────────────────────────────────┘
                                    ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                      Researcher Agent                         │
        │   SOLE holder of retrieval tools. Emits tagged passages:      │
        │        (document_id, page_number, chunk_id, text)             │
        │   Maintains full retrieval pool P, including uncited passages │
        └───────────────────────────┬───────────────────────────────────┘
                                    ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                     Synthesizer Agent                        │
        │        Drafts report with mandatory inline attribution       │
        └───────────────────────────┬──────────────────────────────────┘
                                    ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                CRITIC AGENT — Grounding Engine                │
        │                                                               │
        │  A. Atomization           → claims, modality preserved   [N5] │
        │  B. Type router           → assign T1..T4                [N1] │
        │  C. Path verification     → per-type check + pool matching    │
        │       T1 Direct      ─► entailment + misattribution      [N6] │
        │       T2 Aggregative ─► atom-set + composition + sweep [N2,N3]│
        │       T3 Inferential ─► defeasibility, labelled inference     │
        │       T4 Discourse   ─► exempt, logged                        │
        │  D. Assertiveness check   → modality vs. evidence        [N5] │
        │  E. Report-level checks   → intra-report consistency     [N4] │
        │  F. Retraction propagation over dependency graph         [N7] │
        └───────┬──────────────────────────────────────┬────────────────┘
                │                                      │
       [Failures & round < N]                 [All resolved OR round = N]
                ▼                                      ▼
   ┌────────────────────────────┐    ┌──────────────────────────────────┐
   │ Targeted Revision Payload  │    │ Final Report. Unresolved claims  │
   │ → back to Synthesizer      │    │ tagged per-type:                 │
   │ (sentence idx, claim, type,│    │  "unverified — no support"       │
   │  passage, verdict, hint)   │    │  "unverified — aggregation"      │
   └────────────────────────────┘    │  "unverified — counterexample"   │
                                     │  "inconsistent with §k"          │
                                     │  "overclaim — evidence weaker"   │
                                     │  "inference — not evidence"      │
                                     └──────────────────────────────────┘
```

## 5.2 Agent Roles

**Planner.** Decomposes the user's synthesis query into an ordered set of discrete sub-tasks and investigation goals, producing a structured report outline.

**Researcher.** *The only component with access to retrieval tools.* This monopoly is a structural invariant, not a convenience: it guarantees no downstream agent can introduce parametric memory into the evidence pool. Every retrieved passage is tagged with an explicit origin identifier (`document_id`, `page_number`, `chunk_id`). The Researcher maintains the full **retrieval pool** $P$ per sub-task — including passages the Synthesizer never cites, which N3 and N6 both require.

**Synthesizer.** Receives tagged passages and drafts the report with strict inline attribution linking prose to origin tags. On subsequent rounds it receives targeted revision payloads and is instructed to revise *only* flagged spans.

**Critic.** The technical core, detailed below.

## 5.3 The Critic

### Step A — Atomization (adopted, with one modification)

The draft is decomposed into discrete, standalone claims with sentence indices preserved. This follows the FActScore / MARCH-Proposer protocol and is not claimed as novel, with one change: **epistemic modality is preserved rather than stripped** [N5]. Standard atomizers normalize "may suggest that X" to the proposition X; we retain the modal operator as claim metadata, because Step D requires it.

### Step B — The Type Router [N1]

Each atomized claim is assigned exactly one type.

| Type | Definition | Examples | Verification path |
|---|---|---|---|
| **T1 — Direct attribution** | Truth conditions satisfied by a single passage. | "Tool-MAD reports up to 5.5% improvement over MADKE." | Single-passage entailment |
| **T2 — Aggregative** | Truth conditions range over a *set* of passages: counts, quantifiers, cross-source comparisons, temporal trends. | "Three of five frameworks bound their loop." "X consistently outperforms Y." | Atom-set verification + composition check + disconfirming sweep |
| **T3 — Inferential** | Reasoned extension beyond what evidence states; plausible but not entailed. | "This suggests retrieval quality is the binding constraint." | Defeasibility check; labelled inference, never fact |
| **T4 — Discourse** | Structural scaffolding carrying no verifiable factual content. | "We now turn to evaluation." | **Exempt.** Logged, not entailment-checked. |

Router error costs are asymmetric: misrouting T4 → T1 produces false positives (the over-flagging pathology of §8.4), while misrouting T2 → T1 produces false negatives (undetected aggregation errors). Router accuracy is therefore itself a reported metric (§6.5), validated against human annotation with inter-annotator agreement [N10] — a taxonomy on which two annotators cannot agree is not a taxonomy.

### Step C — Type-Specific Verification

**T1 — Single-passage entailment.** The Critic isolates the exact tagged passage cited by the Synthesizer and performs a strict entailment check, blinded to the rest of the draft (adopting MARCH's information-asymmetry protocol).

**Misattribution detection [N6].** When a T1 claim fails against its cited passage, the Critic re-checks it against the wider retrieval pool $P$ before returning a verdict:

- `Unsupported` — no passage in $P$ entails the claim
- `Misattributed` — entailed by $Q \neq P_{cited}$; repair hint names $Q$

This separates "this fact is wrong" from "this fact is right, cited to the wrong chunk." The repair becomes a citation swap rather than a rewrite — materially cheaper, and it avoids the Synthesizer deleting correct content.

**T2 — Composition verification [N2, N3].** Three sub-steps:

1. **Decomposition into constituent atoms.** *"Three of the five surveyed frameworks bound their correction loop"* decomposes into five per-framework atoms, each with its own passage.
2. **Per-atom verification.** Each constituent atom is verified as a T1 claim, including misattribution handling.
3. **Composition check.** The aggregation operator is evaluated *by the system over the verified atom set*, not asserted by the model. A count claim is checked by counting verified-true atoms. A comparison claim is evaluated over verified values. A trend claim is checked for monotonicity over verified time-indexed atoms.

   **Disconfirming-evidence sweep [N3].** For claims with universal force (`all`, `none`, `consistently`, `never`, `unlike X`, `in every case`), the Critic sweeps the *uncited* remainder of $P$ for counterexamples. This inverts the standard verification direction: the Critic actively searches for evidence that would falsify the claim rather than evidence that would confirm it. It is the only way over-generalization becomes detectable — a universal claim checked against its own cited passage cannot fail.

   Verdicts: `Supported`, `Contradicted`, `Partially-Supported` (atoms hold, aggregation fails), `Unsupported`. `Partially-Supported` carries a precise repair hint — *"two of five verified, not three"* — enabling surgical revision rather than regeneration.

**T3 — Defeasibility check.** The claim is not required to be entailed; it is checked for *consistency* with the evidence pool. Does any retrieved passage contradict it? A surviving T3 claim is retained and marked in the final output as inference rather than evidence. This resolves the tension in which legitimate analytical commentary is either falsely flagged or silently passed off as fact.

**T4 — Exempt.** Recorded in the verification log with its type assignment and passed through unverified. Exemption is auditable: the log states exactly which sentences were never checked and why.

### Step D — Assertiveness Calibration [N5]

A cross-cutting check applied to surviving T1, T2, and T3 claims. Using the modality retained in Step A, the Critic compares **claim strength** against **evidence strength**:

```
  claim modality ladder:     suggests < indicates < shows < demonstrates < proves
  evidence strength signals: single vs. converging sources; hedged vs. definitive
                             source language; sample/scope qualifiers in the passage
```

A mismatch — claim modality exceeding what the evidence licenses — is flagged `Overclaim`, with a repair hint proposing a downgrade rather than a deletion. The inverse case (evidence stronger than claim) is logged but not flagged; under-claiming is not a hallucination.

Scoped deliberately to an explicit modality ladder rather than open-ended judgment, since the acceptable/excessive boundary is fuzzier than for entailment (§8.5).

### Step E — Intra-Report Consistency [N4]

A **report-level** check with no per-claim analogue. After per-claim verification, the Critic performs pairwise contradiction detection over the surviving claim set, gated by entity and topic overlap to avoid quadratic blowup on unrelated pairs.

A detected pair receives verdict `Internally-Inconsistent`, and the revision payload carries **both** sentence indices plus each claim's supporting passage — the Synthesizer must be told which two statements conflict, not merely that one is suspect. Where the two claims cite passages that genuinely differ, the correct repair is often to reconcile them explicitly in the text rather than to delete either.

### Step F — Claim Dependency Graph and Retraction Propagation [N7]

The Critic maintains a graph linking `claim → constituent atoms → passages → documents`, constructed as a by-product of T2 decomposition. It serves two purposes:

- **Retraction propagation.** When an atom is invalidated in any round, every aggregative claim depending on it is automatically re-flagged, preventing the case where a constituent fact is corrected but the aggregative claim resting on it silently retains its old value.
- **Evidence concentration reporting.** The graph exposes what fraction of a report's verified claims rest on a single document. A report 80% grounded in one source is a different risk object from one drawing evenly across the corpus, and no reviewed work reports this.

## 5.4 Bounded Feedback Loop and Typed Escalation

Critic failures generate a **targeted revision payload** — sentence index (or index pair, for inconsistency), extracted claim, assigned type, associated passage(s), verdict, and repair hint. This is routed to the Synthesizer for span-local re-drafting. The report is never wholesale rejected and no open-ended debate is triggered.

The loop is governed by a hard cap $N$:

- **Iteration bound.** The Synthesizer–Critic loop executes at most $N$ rounds, giving a deterministic upper bound on token cost and wall-clock latency.
- **Typed escalation.** Claims unresolved after $N$ rounds are surfaced with a **type-specific** label rather than one generic banner:
  - `unverified — no supporting passage` (T1 failure)
  - `unverified — aggregation not confirmed` (T2 composition failure)
  - `unverified — counterexample found` (disconfirming sweep hit)
  - `inconsistent with §k` (Step E)
  - `overclaim — evidence weaker than stated` (Step D)
  - `inference — not directly evidenced` (T3 retained)

  Typed escalation is strictly more useful than a flat confidence flag: a reader acts differently on *"we found no support for this number"* than on *"this contradicts §3"* than on *"this is the author's inference."*
- **Escalation is a success state.** Surfacing an honest uncertainty label is a correct outcome, not a failure. This bounds token expenditure while avoiding the forced-consensus pathology of debate frameworks.

**On the value of $N$.** Rather than asserting $N = 3$, we derive it [N11]: §6.6 measures marginal claim resolution per round against cumulative token cost, and $N$ is set at the observed knee. If the data does not support 3, we report the value it does support.

## 5.5 Stretch Component — Evidence-Suppression Audit

*Designed but scheduled conditionally (§9, P8); implemented only if the core pipeline lands on schedule.*

All verification above asks whether what is *in* the report is wrong. It does not ask **what the report left out**. If the Researcher retrieves a passage materially contradicting the report's thesis and the Synthesizer silently drops it, every claim can be perfectly grounded and the report still misleads. In research synthesis this selective-reporting failure is arguably more damaging than a wrong figure — a wrong figure is falsifiable, a suppressed counter-finding is not.

The mechanism extends the disconfirming sweep from universal claims to the report level: scan retrieved-but-uncited passages for content contradicting or materially qualifying cited claims, and flag `Unreported-Contradicting-Evidence` with the passage attached so the Synthesizer can incorporate rather than delete. It is listed separately and excluded from the §4.3 novelty index because it shares machinery with N3 and should not be double-counted.

---

# 6. Evaluation Protocol

Evaluation is a contribution in its own right [N8–N11]. Every claim below is falsifiable.

## 6.1 Corpus and Task

A curated, bounded multi-document corpus with known contents (candidate: a 30–60 paper topical slice of arXiv). Task: generate a structured multi-section survey report from a high-level synthesis query. Bounding the corpus is deliberate — it establishes retrieval ground truth, prerequisite to the oracle ablation in §6.4.

## 6.2 Seeded-Error Harness [N8]

We deliberately corrupt otherwise-clean drafts with known errors at known indices, giving exact ground truth for verifier evaluation. The taxonomy is designed so that **six of eleven classes are invisible to single-passage entailment by construction** — this makes the harness a test of our contribution rather than a general NLI benchmark.

| ID | Error class | Detectable by T1-only Critic? | Targets |
|---|---|---|---|
| **E1** | Numeric corruption (altered figures, percentages, dates) | Yes | baseline |
| **E2** | Attribution swap (correct fact, wrong source) | Partially | N6 |
| **E3** | Unsupported insertion (fluent claim, no passage support) | Yes | baseline |
| **E4** | Contradiction (claim negating its cited passage) | Yes | baseline |
| **E5** | Quantifier over-generalization ("some" → "consistently") | **No** | N3 |
| **E6** | Count/aggregation error (off-by-one over source set) | **No** | N2 |
| **E7** | False cross-source contrast ("unlike X" where X does) | **No** | N3 |
| **E8** | Fabricated trend (invented temporal direction) | **No** | N2 |
| **E9** | Internal contradiction (two grounded claims that conflict) | **No** | N4 |
| **E10** | Hedge stripping ("may suggest" → "demonstrates", fact intact) | **No** | N5 |
| **E11** | Omission (contradicting retrieved passage silently dropped) | **No** | §5.5 *(stretch)* |

E2 is marked *partially*: a T1-only Critic detects it as `Unsupported` but cannot distinguish it from E3 — which is exactly what N6 is tested on.

## 6.3 Verifier Reliability Metrics

- **Catch Rate**, reported **per error class** E1–E11. A single aggregate catch rate hides precisely the effect under test.
- **False Positive Rate**, measured on **uncorrupted** drafts — the fraction of correct claims flagged — reported overall and **broken down by claim type**, since T4 over-flagging is the specific pathology predicted in §8.4.
- **Verdict confusion matrix** across `Supported` / `Contradicted` / `Unsupported` / `Misattributed` / `Partially-Supported` / `Internally-Inconsistent` / `Overclaim`. Distinguishing E2 from E3 is a measurable claim, not an assumed capability.

## 6.4 Oracle-Retrieval Ablation [N9]

The pipeline is run twice: once with real retrieval, once with gold passages injected. This **disentangles Critic error from retrieval error** — a confound acknowledged but unresolved across the reviewed literature, where retrieval failures and verifier failures are reported as a single number. Any FPR gap between conditions is attributable to retrieval, not to the Critic.

## 6.5 Router Validation [N10]

- **Inter-annotator agreement.** Two human annotators label 200 held-out claims T1–T4; Cohen's $\kappa$ reported. Low agreement falsifies the taxonomy as specified, and we would rather discover that before building on it.
- **Router confusion matrix** against the human labels, with T4→T1 and T2→T1 misroutes called out separately given their asymmetric cost.

## 6.6 Loop Dynamics [N11]

- **Marginal resolution per round**: claims resolved in round $k$ as a fraction of those outstanding entering round $k$. Yields the curve from which $N$ is derived.
- **Error displacement rate**: new unsupported claims *introduced* by a revision, measured by re-verifying previously-clean spans after each round. If correction is whack-a-mole, this is non-zero and worth reporting — an uncomfortable result for the self-correction literature generally, and unmeasured by any reviewed work.
- **Token cost and wall-clock latency per round**, giving the cost/accuracy curve.

## 6.7 Ablation: The Novelty Test

The single most important experiment. Everything held constant; only the Critic varies.

| Condition | Critic configuration | Tests |
|---|---|---|
| **A** | Naive single-passage entailment on all claims (≈ MARCH Checker, training-free) | baseline |
| **B** | + Type router with T4 exemption | N1 |
| **C** | + Composition check, misattribution verdict, retraction propagation | N2, N6, N7 |
| **D** | + Disconfirming-evidence sweep | N3 |
| **E** | + Intra-report consistency | N4 |
| **F** | + Assertiveness calibration | N5 |

**Predictions stated in advance.** A→B reduces false-positive rate with no loss of catch rate on E1–E4. C raises catch rate on E6, E8 and separates E2 from E3. D raises catch rate on E5, E7. E raises catch rate on E9 from zero. F raises catch rate on E10 from zero. Conditions A–D are expected to score **exactly zero** on E9 and E10, since neither compares claims to one another nor inspects modality.

## 6.8 End-to-End Baselines

Three-way comparison on identical corpus, queries, and base model:

1. **Zero-shot RAG synthesis** — retrieve, then generate, no verification.
2. **Multi-agent debate** — Du et al. protocol adapted to long-form synthesis.
3. **Ours** — type-routed grounded verification.

Reported on: hallucination rate (human-annotated on a sample), citation precision, unverified-claim rate, evidence concentration, total token cost, and end-to-end latency. Cost accompanies accuracy in every table; a bare accuracy number without its cost is the reporting practice §1.2 criticises.

---

# 7. Comparison with State of the Art

## 7.1 Direct Comparison with MARCH

Because MARCH's Solver → Proposer → Checker pipeline is structurally close to ours, the deltas are stated explicitly rather than left implicit:

| Dimension | MARCH | Ours |
|---|---|---|
| Information asymmetry | Introduced and validated | **Adopted as settled prior art** |
| Training requirement | Multi-agent RL, zero-tolerance reward | **Training-free, inference-time only** |
| Task | Multi-hop RAG QA | **Long-form generative synthesis** |
| Claim treatment | All propositions verified uniformly | **Type-routed: four paths, one exempt** [N1] |
| Aggregative claims | Undefined | **Composition check + sweep** [N2, N3] |
| Claim-vs-claim checking | None | **Intra-report consistency** [N4] |
| Claim modality | Discarded at atomization | **Retained; assertiveness calibrated** [N5] |
| Wrong-citation handling | Collapses into unsupported | **Distinct `Misattributed` verdict** [N6] |
| Unresolved state | Reward penalty on trajectory | **Typed escalation as output state** |
| Verifier error profile | Indirect (MARL reward match) | **Catch rate per error class + FPR** [N8] |

We do not claim to have discovered that blinded verification beats self-confirmation; MARCH showed that. We claim that blinded verification, as currently formulated, is *undefined* on the claim types dominating long-form synthesis, and we define it.

## 7.2 Full Comparison Matrix

| Feature | Du et al. | ClaimVerAgents | Yang et al. | Tool-MAD | MARCH | GSAR | **Ours** |
|---|---|---|---|---|---|---|---|
| **Verification axis** | Inter-model consensus | Web evidence classification | Weighted voting | Tool-augmented debate | Blinded atom audit | Typed evidence grounding | **Type-routed claim grounding** |
| **Task domain** | Math / QA / Chess | Fake news detection | Math / MMLU | Fact verification QA | Multi-hop RAG QA | IT incident analysis | **Generative research synthesis** |
| **Aggregative claims** [N2] | — | — | — | — | Undefined | Undefined | **Composition check** |
| **Claim-eligibility typing** [N1] | — | — | — | — | — | Evidence-status only | **Checkability typing (T1–T4)** |
| **Disconfirming search** [N3] | — | — | — | — | — | — | **Yes (universal claims)** |
| **Intra-report consistency** [N4] | — | — | — | — | — | — | **Yes** |
| **Assertiveness calibration** [N5] | — | — | — | — | — | — | **Yes** |
| **Misattribution verdict** [N6] | — | — | — | — | — | — | **Yes** |
| **Retraction propagation** [N7] | — | — | — | — | — | — | **Yes (dependency graph)** |
| **Loop bound** | Open-ended | Max 3 retrieval rounds | Variance threshold | Max $T$ rounds | MARL retries | Explicit $K_{max}$ | **Hard cap, empirically derived** |
| **Unresolved handling** | Forced consensus | NEI abstention | Forced consensus | Judge decision | Reward penalty | Degraded-output banner | **Typed escalation labels** |
| **Catch rate reported** [N8] | No | No | No | No | Indirect | Yes ($M_4$) | **Yes, per error class** |
| **False-positive rate reported** [N8] | No | No | No | No | No | No | **Yes, by claim type** |
| **Retrieval/Critic error separated** [N9] | No | No | No | No | No | No | **Yes (oracle ablation)** |
| **Verifier taxonomy validated** [N10] | No | No | No | No | No | No | **Yes (IAA)** |
| **Loop dynamics reported** [N11] | No | No | No | No | No | No | **Yes (incl. displacement)** |
| **Training cost** | None | None | None | None | **MARL cluster** | None | **None** |

## 7.3 Nearest Prior Work per Novelty

| Novelty | Closest existing work | Distance |
|---|---|---|
| **N1** Claim-eligibility typing | GSAR four-way partition | Different axis: evidence status vs. claim checkability |
| **N2** Composition verification | FActScore atom decomposition | FActScore supplies the atoms; the operator over them is undefined there |
| **N3** Disconfirming sweep | Tool-MAD adaptive retrieval | Tool-MAD retrieves to support argument, not to falsify a claim under test |
| **N4** Intra-report consistency | Du et al. inter-agent disagreement | Between agents vs. within one document by one agent |
| **N5** Assertiveness calibration | — | No analogue; all atomizers discard modality |
| **N6** Misattribution verdict | ALCE citation precision | Evaluation metric vs. in-loop repair signal |
| **N7** Retraction propagation | — | Failure mode arises only from iteration + composition |
| **N8** Seeded-error harness | GSAR $M_4$ catch rate | Catch rate only, short claims, no FPR, no per-class breakdown |
| **N9** Oracle ablation | — | Confound present but unseparated everywhere |
| **N10** Router IAA validation | — | Taxonomies asserted, not validated |
| **N11** Loop dynamics | GSAR $K_{max}$ | Bound imposed vs. bound derived; displacement unmeasured |

---

# 8. Limitations

## 8.1 Router Error Propagates
The type router is load-bearing and constitutes a new failure surface. A T2 claim misrouted to T1 is checked by the wrong operator; a T4 misroute reintroduces the over-flagging problem the router exists to solve. We measure router accuracy directly (§6.5) rather than assuming it, but router error bounds overall system performance and cannot be designed away.

## 8.2 Disconfirming Sweep Is Bounded by the Retrieval Pool
The counterexample search covers the retrieval pool $P$, not the corpus. A counterexample in a document the Researcher never retrieved is undetectable. N3 reduces over-generalization error; it cannot eliminate it, and we do not claim soundness. The same bound applies to the evidence-suppression audit (§5.5).

## 8.3 Consistency Checking Is Incomplete and Quadratic
Pairwise contradiction detection is gated by entity/topic overlap for tractability, so contradictions between claims sharing no surface features will be missed. The check is also vulnerable to *false* contradiction detection where two claims are scope-qualified in ways the Critic does not resolve ("X bounds its loop in the diagnostic setting" vs. "X does not bound its loop in general"). Both directions of error are measured, not assumed away.

## 8.4 Retrieval Remains the Upstream Bottleneck
If retrieval misses a relevant chunk, the Synthesizer lacks context and the Critic correctly flags valid inferences as unsupported. The oracle ablation *measures* this rather than removing it. Quantifying a bottleneck is progress, not a solution.

## 8.5 Assertiveness Calibration Has the Fuzziest Boundary
Where acceptable confidence ends and overclaim begins is less crisp than entailment, and we expect the highest false-positive rate of any check here. Scoping to an explicit modality ladder bounds the judgment but does not make it objective. If measured FPR on E10 is unacceptable, the honest outcome is to report N5 as a diagnostic signal rather than a revision trigger.

## 8.6 Entailment Remains Semantically Fuzzy
Whether a passage supports a nuanced claim is a judgment call, particularly for paraphrase, implicit logic, and high-level summary. Type routing narrows where fuzziness applies — T4 exemption and T3 labelling remove two large classes from binary entailment — but T1 and the per-atom step of T2 still rest on an LLM entailment judgment with its own error rate. This is the honest floor of the approach.

## 8.7 Verification Cost Scales with Claim Complexity
A T2 claim decomposing into five atoms costs roughly five entailment calls plus a sweep, versus one call under a naive Critic; consistency checking adds gated pairwise comparisons. If T2 claims are common, per-report cost rises materially. §6.6's cost curves must report this, including the case where it renders the approach uneconomical.

## 8.8 Corpus Boundedness
The design assumes a curated, bounded corpus. Open-domain queries over noisy web-scale data would degrade retrieval precision and, through it, composition checking, the disconfirming sweep, and the suppression audit. We scope to bounded corpora and state this as a scope condition, not a solved problem.

---

# 9. Implementation Plan

| Phase | Deliverable | Novelties | Purpose |
|---|---|---|---|
| **P1** | Corpus ingestion, chunking, tagged retrieval; retrieval pool $P$ retained | — | Foundation; tags and pool retention are prerequisites for N3 and N6 |
| **P2** | Planner / Researcher / Synthesizer with enforced inline attribution | — | Produces draft reports to verify |
| **P3** | Naive T1-only Critic + bounded loop | — | **Ablation condition A** — the baseline the contribution must beat |
| **P4** | Seeded-error harness, classes E1–E10; annotation protocol | N8 | Measurement infrastructure, built *before* the mechanisms it evaluates |
| **P5** | Type router (T1–T4); IAA study on 200 held-out claims | N1, N10 | Condition B; validates the taxonomy before anything is built on it |
| **P6** | Composition check, misattribution verdict, dependency graph, disconfirming sweep | N2, N3, N6, N7 | Conditions C, D |
| **P7** | Intra-report consistency; assertiveness calibration | N4, N5 | Conditions E, F |
| **P8** | *Stretch:* evidence-suppression audit; error class E11 | — | §5.5 — only if P1–P7 complete on schedule |
| **P9** | Full ablation, loop dynamics, oracle ablation, three-way baselines | N9, N11 | §6 results |

Building P4 before P5–P7 is deliberate: the evaluation harness must exist before the mechanisms it evaluates, or the mechanisms will be unconsciously fitted to the test. P5's IAA study precedes P6–P7 for the same reason — if the taxonomy is unreliable, that must surface before it becomes load-bearing.

---

# 10. Falsifiable Claims

Stated in advance so the project can fail honestly.

- **C1** [N1]. Type routing with T4 exemption reduces Critic false-positive rate relative to uniform entailment, without reducing catch rate on E1–E4.
- **C2** [N2]. Composition checking raises catch rate on E6 (count errors) and E8 (fabricated trends) substantially above the T1-only baseline, expected near zero.
- **C3** [N3]. The disconfirming-evidence sweep raises catch rate on E5 (over-generalization) and E7 (false contrast) above the T1-only baseline.
- **C4** [N4]. Intra-report consistency checking raises catch rate on E9 above zero, at a false-contradiction rate low enough to be usable.
- **C5** [N5]. Assertiveness calibration raises catch rate on E10 above zero, at a false-positive rate low enough to be usable as a revision trigger rather than only a diagnostic.
- **C6** [N6]. Misattribution verdicts separate E2 from E3 at above-chance accuracy, and reduce mean revision cost for E2 relative to full regeneration.
- **C7** [N10]. The type taxonomy achieves inter-annotator agreement sufficient to be treated as well-specified.
- **C8** [N11]. Marginal claim resolution per round decays sharply, admitting a defensible iteration bound; and error displacement is non-trivial, i.e. revision introduces new errors at a measurable rate.
- **C9**. The end-to-end system reduces hallucination rate relative to both zero-shot RAG and multi-agent debate at a reportable and bounded token cost.

**Failure conditions.** If C2 and C3 fail, the core contribution is falsified. If C4 and C5 fail, the long-form-specific extensions are falsified while the core may survive. If C7 fails, the taxonomy requires redesign before C1 can be interpreted. We commit to reporting each outcome as measured.
