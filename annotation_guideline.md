# Annotation Guideline — Claim Types T1–T4

**Status: DRAFT v0.1 (2026-09-27), for team review.** Once approved, this guideline is **frozen** before any labelling starts (requirement AR-1). If it changes after labelling begins, the agreement score stops measuring anything.

---

## 1. What you are doing and why

The system sorts every claim in a report into one of four types. The type decides *which check* the claim gets. You will label **200 claims** so we can measure two things:
- whether two people agree on the types (Cohen's κ);
- how often the system's sorter gets them right.

If people can't agree on the types, the types are badly defined, and we'd rather find that out now.

You are **not** judging whether a claim is true. You are judging *what kind of check it could take*.

**Rules of the session:**
- Work **alone**. Don't discuss claims with the other annotator until both of you have finished.
- You see: the claim, the sentence it came from, and the section heading.
- You do **not** see: the cited passages, the system's own label, or the other annotator's labels.
- Don't look up the papers.
- Budget: about 4 hours for 200 claims, about 1 minute each. Take breaks.
- If you're unsure, pick the best label, tick **unsure**, and write one line in **notes**. Never skip a claim.

---

## 2. The four types

| Type | One-line test | Check it will get |
|---|---|---|
| **T1 Direct** | One passage from one paper could confirm or refute it. | Compare it with the cited passage. |
| **T2 Aggregative** | Its truth depends on **several** papers or systems together: a count, "several / most / each / all / none", a comparison or contrast between systems from different papers, a trend over time, or a generalisation about the frameworks under review. | Split it into one fact per paper, check each one, then compute the count or comparison in code. Sweeping claims also get a search for counterexamples. |
| **T3 Inferential** | The report's **own** reasoning beyond what any source says: an interpretation, an explanation of *why*, a recommendation, a speculation. | Checked only for conflict with the evidence, then labelled "inference". |
| **T4 Discourse** | Says nothing about the papers, systems or results. It only organises the report: signposts, transitions, pointers. | Not checked; logged as exempt. |

---

## 3. Decision procedure — apply in this order

1. **Does it say anything about the papers, systems, results, or the world?**
   If it only organises the report ("We now turn to…", "This section reviews…"), label **T4**.
   *A signpost that also asserts content is **not** T4:* "In summary, the frameworks differ along three axes" asserts a count, so it's T2.
2. **Is it the report's own reasoning, beyond what a source states, and not attributed to a source?**
   Interpretation, explanation, recommendation or speculation: label **T3**.
3. **Does its truth depend on more than one paper or system, or on a set of them?**
   Counts over papers or systems; quantifiers (several, most, each, all, none, many, few); comparisons or contrasts between systems from *different* papers; trends over time; generic statements about "frameworks" or "systems" under review: label **T2**.
4. **Otherwise**, label **T1**. That covers one system, one paper, one result or one mechanism.

---

## 4. Tie-breaking rules

- **R1. Hedged attribution is T1.** "MARCH suggests that blinding reduces bias" reports what *one source* says, even though hedged. Only hedging that is the *report's own* inference ("this may indicate…") points to T3.
- **R2. A comparison one paper reports about itself is T1.** "Tool-MAD outperforms MADKE by 5.5%" is a result stated in the Tool-MAD paper. It becomes T2 only when the report sets systems from different papers against each other.
- **R3. A count of parts inside one system is T1.** "MARCH uses three agents" is T1. "Three of the five frameworks bound their loop" is a count over papers, so T2.
- **R4. Similarity or contrast words across systems make it T2.** "GSAR similarly deploys…", "Unlike Du et al., …", "whereas", "in contrast", "both X and Y" all compare systems.
- **R5. General statement or generalisation?** If the claim restates a general point that one source makes about a *phenomenon* ("confirmation bias arises when a verifier sees the answer"), it's T1. If it generalises over *the frameworks being reviewed* ("recent frameworks incorporate abstention"), it's T2.
- **R6. Type doesn't depend on citations.** An uncited claim still gets a type from its form. A claim with three citations may still be T1.
- **R7. Mixed claims.** A claim should be one statement, but if it still mixes types, label its most demanding *checkable* part (T2 over T1 over T3) and write "mixed" in notes. These notes tell us where the claim splitter is failing.
- **R8. Don't judge truth.** A false count is still T2. A made-up result about one paper is still T1.

---

## 5. Worked examples

Examples marked ◆ are real sentences from system drafts (q02). Examples marked ◇ were **constructed** to illustrate a case the drafts rarely contain; real drafts almost never use pure signposting or clearly flagged inference, because the drafting prompt forbids adding anything the sources don't say.

### T1 — Direct

| # | Claim | Why |
|---|---|---|
| 1 ◆ | ClaimVerAgents filters retrieved snippets using a curated blacklist of 1,044 unreliable sources. | One system, one detail, one paper. |
| 2 ◆ | Tool-MAD achieves up to a 5.5% accuracy improvement over state-of-the-art debate frameworks across fact-verification benchmarks. | A comparison, but one the Tool-MAD paper reports itself (R2). |
| 3 ◆ | MARCH introduces an asymmetric verification architecture containing a Solver, a Proposer, and a Checker. | Three parts inside one system (R3). |
| 4 ◆ | MARCH's Checker receives only the extracted atomic questions and retrieved source documents, and is blinded to the Solver's response. | One mechanism of one system. |
| 5 ◆ | MARCH enforces an all-or-nothing binary Zero-Tolerance Reward during reinforcement learning. | One design choice of one paper. |
| 6 ◆ | A central challenge in evidence-based verification is confirmation bias, where exposing a verifier to generated text causes it to prioritise narrative coherence over grounding. | A general point about a phenomenon, which one source makes (R5). |
| 7 ◇ | Du et al. suggest that debate reduces hallucinated facts in arithmetic tasks. | A hedged view attributed to one paper (R1). |

### T2 — Aggregative

| # | Claim | Why |
|---|---|---|
| 1 ◆ | These systems structure verification through three primary architectural designs: peer-to-peer debate, modular multi-agent pipelines, and asymmetric auditing pipelines. | A count over the reviewed systems. |
| 2 ◆ | Frameworks differ substantially in how they source factual evidence. | A comparison across systems. |
| 3 ◆ | Each framework applies distinct evaluation logic to decide whether a claim is supported. | "Each": a universal over the reviewed frameworks. |
| 4 ◆ | Recent multi-agent frameworks mitigate LLM hallucinations by replacing monolithic generation with distributed verification workflows. | A generalisation over the frameworks under review (R5). |
| 5 ◆ | Several frameworks employ internal cross-checking and consistency-based verification. | "Several": a proportion over the set. |
| 6 ◆ | GSAR's design is similar to ClaimVerAgents' in deploying specialist agents to collect evidence. | A similarity between systems from two papers (R4). The draft's sentence "GSAR similarly deploys specialist agents…" splits into this claim (T2) and "GSAR deploys specialist agents to collect evidence" (T1). |
| 7 ◆ | Multi-agent verification frameworks demonstrate significant gains in factual accuracy over single-agent baselines. | A generalisation of results across the set. |

### T3 — Inferential

| # | Claim | Why |
|---|---|---|
| 1 ◇ | This suggests that retrieval quality, rather than the number of agents, is the binding constraint on accuracy. | The report's own interpretation, hedged by the report itself (R1). |
| 2 ◇ | One plausible reason debate plateaus after two rounds is that agents converge on the majority view rather than on the evidence. | An explanation of *why* that no source is said to give. |
| 3 ◇ | For practitioners, a modular pipeline is therefore the safer starting point. | A recommendation. |
| 4 ◇ | Taken together, these results imply that abstention should be treated as a first-class output rather than a failure. | A conclusion the report draws. |
| 5 ◇ | Blinding the checker is likely to matter more as reports grow longer. | A speculation beyond the evidence. |
| 6 ◇ | The popularity of self-consistency methods probably reflects their low implementation cost. | A speculative explanation. |

### T4 — Discourse

| # | Claim | Why |
|---|---|---|
| 1 ◇ | We now turn to how each framework decides whether a claim is supported. | A pure signpost. |
| 2 ◇ | This section reviews verification mechanisms in multi-agent systems. | Describes the report, not the papers. |
| 3 ◇ | The remainder of this section is organised by design family. | Organisation. |
| 4 ◇ | Table 1 summarises the frameworks discussed above. | A pointer. |
| 5 ◇ | The next paragraphs examine uncertainty handling. | A transition. |
| — ◇ | *Counter-example:* "In summary, the frameworks differ along three axes." | **Not T4**: it asserts a count, so T2 (step 1). |

### Hard cases (discuss in adjudication, not during labelling)

- ◆ "Operational and architectural constraints further complicate real-world deployment." A topic sentence, but it asserts that constraints exist and complicate deployment: T2 (a generalisation), not T4.
- ◆ "LLM-as-judge verifiers suffer from model drift over time, necessitating periodic re-calibration." With one citation, is it a phenomenon one source describes (T1, R5), or a generalisation over the reviewed verifiers (T2)? Label what the wording suggests and add a note.
- ◆ "Specific precision and recall figures across all models are not uniformly reported in the provided literature." A claim about the *literature as a whole*: T2.

---

## 6. After labelling (for the record)

1. κ is computed on your **independent** labels, before any discussion (AR-4).
2. Then the two of you go through the disagreements together and agree a gold label for each. Those gold labels become the reference set.
3. If κ < 0.6, the types are revised and re-labelled. That's planned for, not a failure (AR-6).

## 7. Label format

One row per claim in the labelling sheet: `claim_id`, `type` (T1–T4), `unsure` (yes/no), `notes`. Annotators are anonymised as A1 and A2.
