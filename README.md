# tcv — Type-Routed Claim Verification

**Fact-checking for AI-written research reports.**

B.Tech project, Netaji Subhas University of Technology (NSUT), New Delhi.
**Team:** Krish Garg (2023UCS1685), Kanishka Yadav (2023UCS1696), Kushel Rohilla (2023UCS1712)
**Supervisor:** Dr. Vivek Mehta

> **In one sentence:** we build a system that writes a research report from a fixed set of papers and then checks every claim in it. Before checking a claim, it first works out *what kind of check that claim needs*, because the sentences that matter most in a report can't be verified the way today's fact-checkers verify them.

**Status:** Phase 1 of 7 (foundation) is complete apart from two steps waiting on team decisions. See [Current status](#7-current-status).

---

## Contents

1. [The problem](#1-the-problem)
2. [Why today's fact-checkers miss it](#2-why-todays-fact-checkers-miss-it)
3. [Our idea: sort claims before checking them](#3-our-idea-sort-claims-before-checking-them)
4. [How the system works](#4-how-the-system-works)
5. [A worked example](#5-a-worked-example)
6. [What is new here](#6-what-is-new-here)
7. [Current status](#7-current-status)
8. [How we will know it works](#8-how-we-will-know-it-works)
9. [Plan](#9-plan)
10. [Limitations](#10-limitations)
11. [Glossary](#11-glossary)
12. [For developers](#12-for-developers)

---

## 1. The problem

Large language models (**LLMs**) such as Gemini, Claude and GPT can read dozens of papers and write a fluent survey of them. The catch is **hallucination**: the model writes sentences that sound authoritative but that the sources don't support, or even contradict.

The standard fix is **claim-level verification**:
1. split the text into small factual statements (**atomic claims**);
2. for each one, look at the passage it cites;
3. ask whether that passage supports it (**entailment**).

This works well for short answers ("When was X published?"). **It works badly for long reports**, and that's the gap this project addresses.

## 2. Why today's fact-checkers miss it

In a research report, the most valuable sentences are the ones **no single passage can confirm**. We identified three kinds of failure that only show up in long-form writing:

| Failure | Example sentence | Why a per-passage checker misses it |
|---|---|---|
| **Claims about a *set* of papers** | "Three of the five frameworks limit their correction loop." | No single passage says "three of five". The checker either wrongly flags a correct count or wrongly passes a wrong one. |
| **The report contradicting itself** | Section 2: "GSAR limits its loop." Section 5: "No framework limits its loop." | Each sentence may match its own source perfectly. Only comparing the sentences *with each other* reveals the conflict, and an answer to a short question is never long enough to contradict itself. |
| **Saying it more strongly than the evidence allows** | "This **demonstrates** that retrieval is the bottleneck," backed by one early result | The underlying fact is present, so the check passes. Current checkers throw away words like "suggests" and "demonstrates" before checking. |

A second problem is that **fact-checkers are rarely checked themselves**. Papers report how many errors a checker catches, but almost never how often it raises **false alarms**. In a long report, a checker that flags every second sentence is useless, however many real errors it catches.

## 3. Our idea: sort claims before checking them

Before verifying anything, our checker sorts each claim into one of four **types** according to *what kind of check it can take*, and sends each type down its own verification path.

| Type | What it is | Example | How it's checked |
|---|---|---|---|
| **T1 Direct** | A fact one passage can confirm | "Tool-MAD reports up to 5.5% improvement over MADKE." | Compare against the cited passage. If that fails, search the other retrieved passages. It may be true but **cited to the wrong source** (*misattributed*), which is fixed by a citation swap rather than a rewrite. |
| **T2 Aggregative** | A claim about a *set* of papers: counts, comparisons, contrasts, trends, "all/none/consistently" | "Three of the five frameworks limit their loop." | Split it into one small claim per paper, check each, then **do the counting or comparing in ordinary code**, never by asking the model. Claims like "all", "never" or "unlike X" also get a **search for counterexamples** among passages the report *didn't* cite. |
| **T3 Inferential** | The author's reasoning beyond the evidence | "This suggests retrieval quality is the binding constraint." | Checked only for *conflict* with the evidence. If it survives, it stays in the report, clearly labelled as inference rather than fact. |
| **T4 Discourse** | Signposting with no factual content | "We now turn to evaluation." | Not checked, but logged, so it's always clear what was skipped. |

On top of the per-claim checks, the checker also:
- compares claims **with each other** to find contradictions inside the report (**intra-report consistency**);
- compares **how strongly** a claim is worded with **how strong** its evidence is, and flags overclaims with a suggested softer wording (**assertiveness calibration**).

## 4. How the system works

Four components, each with a single job, run in a loop with a fixed maximum number of rounds. (The proposal calls the last component the *Critic*; in the code it's the *Checker*.)

```
  User's question  ("Compare the verification mechanisms used by multi-agent frameworks")
        │
        ▼
  ┌─────────────┐   breaks the question into sub-topics and an outline
  │  Planner    │
  └──────┬──────┘
         ▼
  ┌─────────────┐   the ONLY component allowed to search the papers; keeps every
  │ Researcher  │   passage it found, including ones the report never cites
  └──────┬──────┘
         ▼
  ┌─────────────┐   writes the report; every factual sentence must carry a citation
  │ Synthesizer │   such as [[du-2023#p4c1]] (paper, page, chunk)
  └──────┬──────┘
         ▼
  ┌─────────────┐   1. split the report into claims (keeping "may"/"shows"/"proves")
  │  Checker    │   2. sort each claim into T1–T4
  │             │   3. verify each claim along its type's path
  │             │   4. check claim strength against evidence strength
  │             │   5. check the claims against each other
  └──────┬──────┘
         │
    problems found and rounds left?
      ├── yes ──► targeted fix-list back to the Synthesizer
      │           ("sentence 14: two of five, not three; see passage X")
      │           It rewrites only those sentences, then the Checker runs again.
      │
      └── no ───► FINAL REPORT. Anything still unresolved is labelled honestly:
                    "unverified: no supporting passage"
                    "unverified: counterexample found"
                    "inconsistent with §3"
                    "overclaim: evidence weaker than stated"
                    "inference, not directly evidenced"
```

Design rules the code enforces (tests fail if they're broken):
- **Only the Researcher searches the papers.** No other component can slip in "facts" from the model's memory.
- **The counting and comparing code never calls a model.** Arithmetic is done by code, so a model can't be fooled into miscounting.
- **Every model call goes through one gateway.** It caches responses, logs each call's cost, and stops the run once the budget is spent.
- **The loop has a hard cap on rounds**, so cost and running time are bounded. A clearly labelled "we couldn't verify this" counts as a valid outcome, not a failure.

The system is **training-free**: it uses existing models as they are, with no fine-tuning.

## 5. A worked example

Suppose the Synthesizer writes:

> "Three of the five surveyed frameworks bound their correction loop [[gsar-2026#p7c2]]."

| | Standard checker | Our checker |
|---|---|---|
| **What it looks at** | The one cited passage, which is about GSAR only | Recognises a **count over five frameworks** (type T2, operator COUNT) |
| **What it does** | Asks "does this passage support the sentence?" | Splits it into five small claims ("GSAR bounds its loop", "MARCH bounds its loop", …), checks each against that paper's own passages, then **counts the true ones in code** |
| **Result** | Either "unsupported" (a false alarm if the count is right) or "supported" (a missed error if it's wrong) | "Partially supported: **2 of 5** verified, not 3." The Synthesizer gets that exact fix |

The same machinery catches "consistently outperforms" when an uncited passage shows a case where it didn't, and "unlike X, Y does not…" when X actually does.

## 6. What is new here

Compared with the papers we build on (GSAR, MARCH, Tool-MAD, ClaimVerAgents, Du et al.'s multi-agent debate, Yang et al.), these are, as far as we know, **not done by any of them**:

1. **Sorting claims by the check they can take** (T1–T4) before verifying anything, with signposting sentences exempted rather than failed.
2. **Checking claims about sets of papers** by verifying the parts and computing the count or comparison in code.
3. **Searching for counterexamples** among passages the report didn't cite, to catch over-generalisations like "all", "never" and "consistently".
4. **Checking the report against itself** for contradictions between claims.
5. **Checking wording strength against evidence strength** ("suggests" versus "demonstrates").
6. **Telling "wrong fact" apart from "right fact, wrong citation"**, so a wrong citation is fixed by swapping it.
7. **Measuring the checker itself**, not only the system around it. We report false alarms per claim type and catch rate per error type, on a test set built so that 6 of the 11 error types are invisible to the standard method.

**What we do *not* claim** (adopted from earlier work and credited):
- splitting text into atomic claims (FActScore, MARCH);
- checking claims "blind", without seeing the rest of the draft (MARCH);
- the supported / contradicted / not-enough-information verdicts (FEVER);
- limiting the number of correction rounds (GSAR);
- allowing "not enough information" as an answer (ClaimVerAgents).

## 7. Current status

**Phase 1 (foundation) — built and tested**

| Piece | What exists |
|---|---|
| Paper ingestion | PDFs are turned into clean page text: headers, page numbers, reference lists and publisher sidebars are removed, and appendices are kept. The text is split into ~180-word **chunks** with exact character positions, so every citation traces back to the source text. |
| Search | **Hybrid retrieval**: keyword search (**BM25**) plus meaning-based search (**embeddings**, `bge-small-en-v1.5`), merged by **reciprocal rank fusion**. Runs locally on CPU, so results are reproducible. |
| Model gateway | One entry point for all model calls, with a response cache, a per-call cost log, a budget kill-switch, batching, and quota handling. Models in use: **Gemini 3.8 Flash** (writing and judging) and **Gemini 3.1 Flash Lite** (mechanical steps). A Claude setup is kept as an alternative. |
| Data structures | Every object passed between components (claims, verdicts, fix-lists, …) is defined once, validated, and **frozen**: a test fails if one changes without a version bump. |
| Corpus | 6 seed papers (382 chunks) ingested. 48 more candidate papers, **all 48 arXiv IDs confirmed**, are waiting on the team's keep/drop decision. |
| Tests | 210 fast tests plus 4 integration tests over the real papers, and 4 enforced architecture rules. |

**First evidence that the idea is testable.** The whole approach depends on real AI-written reports actually containing claims about *sets* of papers. In the first pilot report (39 sentences), **9 sentences made cross-paper claims**, for example:
- "These systems structure verification through **three** primary architectural designs…"
- "Frameworks **differ substantially** in how they source factual evidence…"
- "**Each framework** applies distinct evaluation logic…"

The same report cited all 6 papers and had no broken citations. This is one report, so it's encouraging but not yet a result. The remaining 9 pilot reports are waiting on API quota.

## 8. How we will know it works

**Seeded errors.** We take clean reports and plant known mistakes at known places, so we know exactly what a perfect checker should catch:

| | Error type | Can the standard method catch it? |
|---|---|---|
| E1 | Changed number or date | Yes |
| E2 | Right fact, wrong citation | Partly (can't tell it apart from E3) |
| E3 | Made-up claim | Yes |
| E4 | Claim contradicting its own source | Yes |
| E5 | Over-generalisation ("some" → "consistently") | **No** |
| E6 | Wrong count across papers | **No** |
| E7 | False contrast ("unlike X…" when X does too) | **No** |
| E8 | Invented trend over time | **No** |
| E9 | Two claims in the report contradicting each other | **No** |
| E10 | Hedge removed ("may suggest" → "demonstrates") | **No** |
| E11 | Contradicting evidence silently left out *(stretch goal)* | **No** |

**What we measure:**
- **Catch rate for each error type**, not one overall number that hides the differences.
- **False-alarm rate** on clean reports, broken down by claim type.
- **Ablation study:** we add one mechanism at a time (conditions A→F) and measure what each one adds. The predictions are written down *before* running, so the project can fail honestly. For example, we predict the standard method scores **exactly zero** on E9 and E10.
- **Is the sorting reliable?** Two people label 200 claims T1–T4 independently, and we measure how often they agree (**Cohen's κ**). If humans can't agree on the types, the types need redesigning.
- **Retrieval versus checker errors:** the system is also run with the correct passages handed to it (**oracle retrieval**), so search mistakes aren't blamed on the checker.
- **Does fixing introduce new errors?** We re-check previously clean sentences after each revision round.
- **Cost:** every result is reported alongside its token cost.

## 9. Plan

One phase is about one week.

| Phase | Work | Status |
|---|---|---|
| 1 | Foundation: ingestion, search, model gateway, data structures, pilot | ✅ Built (pilot and corpus freeze pending team input) |
| 2 | Planner / Researcher / Synthesizer pipeline + baseline checker (the standard method) | Next |
| 3 | Seeded-error test set, built *before* the mechanisms it tests | |
| 4 | Claim-type sorter + human agreement study | |
| 5 | Set-claim checking, misattribution, claim dependency tracking | |
| 6 | Counterexample search + core ablation | |
| 7 | Analysis and BTP report | |
| 8–11 | *If time allows:* self-contradiction check, wording-strength check, full ablation, paper | |

Full plan: [`roadmap.md`](roadmap.md). Week-by-week progress: [`checklist.md`](checklist.md).

## 10. Limitations

We state these up front:
- **The sorter can be wrong.** A misrouted claim gets the wrong check. We measure how often this happens rather than assume it doesn't.
- **The counterexample search only sees retrieved passages.** A counterexample in a paper the Researcher never retrieved stays invisible.
- **Contradiction checking is incomplete.** Only claim pairs that share entities or topics are compared (checking all pairs is too expensive), so some contradictions will be missed.
- **"Too strongly worded" is partly a judgment call.** We expect this check to have the most false alarms. If it has too many, we'll report it as a diagnostic signal rather than use it to trigger rewrites.
- **The model's own judgment is the floor.** Whether a passage supports a nuanced claim is still decided by a model, which has its own error rate.
- **The corpus is fixed.** The design assumes a curated set of 40–60 papers, not the open web.

## 11. Glossary

| Term | Meaning |
|---|---|
| **LLM** | Large language model: the AI that writes text (Gemini, Claude, GPT). |
| **Hallucination** | Fluent text that its sources don't support, or that contradicts them. |
| **Corpus** | The fixed collection of papers the system is allowed to use. |
| **Chunk** | A ~180-word piece of a paper's page, the unit that search returns and citations point to. Written `paper#p<page>c<index>`, e.g. `du-2023#p4c1`. |
| **RAG** | Retrieval-augmented generation: search the documents first, then let the model write using what was found. |
| **BM25** | A classic keyword-matching search score. |
| **Embedding** | A list of numbers representing a text's meaning; similar meanings give similar numbers, which enables meaning-based search. |
| **Hybrid retrieval / RRF** | Combining keyword and meaning-based search; reciprocal rank fusion merges the two ranked lists. |
| **Retrieval pool** | Every passage found for a question, *including the ones the report didn't cite*. The counterexample search and misattribution check need these. |
| **Atomic claim** | A single, self-contained factual statement extracted from a sentence. |
| **Entailment** | Whether a passage logically supports a claim. |
| **Aggregative claim** | A claim whose truth depends on several sources together: counts, comparisons, contrasts, trends, "all/none". |
| **Composition operator** | The operation an aggregative claim performs (COUNT, COMPARISON, CONTRAST, TREND, UNIVERSAL, PROPORTION, EXISTENTIAL), computed in code. |
| **Disconfirming sweep** | Searching uncited passages for counterexamples to a sweeping claim. |
| **Misattribution** | A true claim cited to the wrong passage. |
| **Modality / assertiveness** | How strongly a claim is worded: suggests < indicates < shows < demonstrates < proves. |
| **Intra-report consistency** | Whether the report's claims agree with each other. |
| **Escalation label** | The honest tag given to a claim still unresolved after the last round. |
| **Seeded error** | A mistake planted on purpose to test whether the checker catches it. |
| **Catch rate / false-positive rate** | The share of planted errors caught / the share of correct claims wrongly flagged. |
| **Ablation** | Turning mechanisms on one at a time to measure what each contributes. |
| **Oracle retrieval** | Giving the system the correct passages directly, to separate search errors from checking errors. |
| **Cohen's κ (kappa)** | A score for how much two human labellers agree beyond chance (1 = perfect, 0 = chance). |
| **Training-free** | Uses existing models as they are, with no fine-tuning. |
| **Structured output** | Asking the model to answer in a fixed JSON format, which the code then validates. |
| **Import contract** | An automated rule about which parts of the code may use which others, e.g. only the Researcher may call search. |

## 12. For developers

### Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned and installed by uv).

```sh
uv sync                      # create .venv and install locked dependencies
cp .env.example .env         # then add GEMINI_API_KEY (needed only for model calls)
```

Source PDFs live in `papers/` (git-ignored). Everything under `data/` is regenerated from them.

### Commands

```sh
uv run tcv ingest                 # extract, chunk and index the corpus in configs/corpus.yaml
uv run tcv search "your query"    # hybrid search over the corpus
uv run tcv pilot --dry-run        # build pilot prompts and estimate cost; calls no model
uv run tcv pilot                  # draft the pilot reports and screen them (needs an API key)
uv run tcv pilot --models configs/models.anthropic.yaml   # same, on Claude (needs ANTHROPIC_API_KEY)
uv run tcv verify-corpus          # check source PDFs against the manifest hashes
uv run tcv freeze                 # freeze the corpus version (after team approval)
uv run tcv fetch --check          # confirm candidate papers' arXiv IDs and titles
uv run tcv fetch                  # download approved candidates, write configs/corpus.v1.yaml
```

### Tests and checks

```sh
uv run pytest                     # fast suite (offline, no model download)
uv run pytest -m slow             # integration over the real seed papers + embedding model
uv run lint-imports               # the architecture rules
```

### Layout

```
src/tcv/
  schemas/      data structures exchanged between components (frozen)
  corpus/       PDF → page text → chunks with exact character spans; manifest; arXiv fetch
  retrieval/    local embeddings + BM25, fused by reciprocal rank (Researcher-only)
  llm/          model gateway: providers (Gemini, Anthropic), prompts, cache, cost log, budget, batching
  agents/       Researcher, draft parser (Planner and Synthesizer arrive in Phase 2)
  checker/      claim-type word patterns (the full Checker arrives in Phases 2–6)
  orchestrator/ run-state persistence (the loop arrives in Phase 2)
  eval/         query set, pilot screen
configs/        corpus, models, queries, candidate papers
prompts/        versioned prompt templates
tests/          unit, contract (architecture rules), integration (slow)
```

### Project documents

| File | Contents |
|---|---|
| [`updated_proposal.md`](updated_proposal.md) | Full proposal: problem, related work, what's new, evaluation design |
| [`requirements.md`](requirements.md) | What must exist, with priorities |
| [`architecture.md`](architecture.md) | How it's built: components, data structures, contracts |
| [`roadmap.md`](roadmap.md) | Phase-by-phase plan and where team input is needed |
| [`checklist.md`](checklist.md) | Current phase, ticked off as work completes |
| [`report/mse-report.md`](report/mse-report.md) | Mid-semester evaluation report |
