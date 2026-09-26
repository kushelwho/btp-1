<div align="center">

# NETAJI SUBHAS UNIVERSITY OF TECHNOLOGY

```
┌─────────────────────────────┐
│                             │
│   [ INSERT NSUT LOGO HERE ] │
│                             │
└─────────────────────────────┘
```

**Department of Computer Science and Engineering**

*B.Tech Project — Mid-Semester Evaluation Report*

<br>

# Checking Whether AI-Written Research Reports Are Actually True

### A Fact-Checking System That Sorts Claims by Type Before Verifying Them

<br>

**Submitted by**

| Name | Roll Number |
|:---|:---|
| Krish Garg | 2023UCS1685 |
| Kanishka Yadav | 2023UCS1696 |
| Kushel Rohilla | 2023UCS1712 |

<br>

**Under the supervision of**

### Dr. Vivek Mehta

Department of Computer Science and Engineering

<br>

Academic Year 2026–27

</div>

---

# Table of Contents

**1. Introduction**

**2. Motivation**
  2.1 Why Long Reports Are Different From Short Answers
  2.2 The Three Problems
  2.3 Nobody Checks the Fact-Checker

**3. Literature Survey**
  3.1 Systems That Use Multiple AI Agents
  3.2 Systems That Check Claims Against Sources
  3.3 What Is Missing

**4. Problem Statement**
  4.1 What We Are Trying to Solve
  4.2 The Nine Gaps

**5. Objective and Methodology**
  5.1 Our Objectives
  5.2 How the System Works
  5.3 The Checker in Detail
  5.4 Stopping Rules
  5.5 How We Will Test It

**6. Simulation Platform and Requirements**
  6.1 Software and Hardware
  6.2 What Needs an AI Model and What Does Not
  6.3 Cost
  6.4 Documents and Human Labelling

**7. Conclusion**
  7.1 What We Are Contributing
  7.2 Work Plan
  7.3 Known Weaknesses

**8. References**

---

# 1. Introduction

Large Language Models (LLMs) such as GPT and Claude can read long documents and write fluent summaries of them. This makes them attractive for a task that is otherwise slow and expensive: **research synthesis** — reading a pile of technical papers and writing a structured report about what they collectively say. Literature surveys, technical reviews, and market reports all work this way, and all of them are limited by how much one person can read.

There is a well-known problem. When an LLM writes a long report, it produces sentences that sound confident, well-written, and authoritative but are simply **not true** — not supported by the source documents, or directly contradicted by them. This is called **hallucination**.

It is especially damaging here, because the output *reads* like a proper survey. Someone reading it cannot tell a well-supported sentence from an invented one without going back and reading all the source papers themselves. At that point the automation has saved nobody any time.

The research community has settled on a standard fix, which works like this:

1. Break the generated report into individual factual claims.
2. For each claim, find the source passage the AI said it came from.
3. Check whether that passage actually supports the claim.
4. Flag or rewrite anything that fails.

This approach works well and we are not disputing it. Our project is about a specific place where it stops working.

**Our central argument:** this fact-checking method was designed for short question-answering, where an answer is a few simple facts. It does not transfer cleanly to long reports. We identify three kinds of sentence that appear only in long reports and that this method cannot check — not because the AI doing the checking is weak, but because checking one sentence against one passage is simply the wrong operation for those sentences.

Our solution is a checker that **first decides what kind of claim it is looking at**, and only then picks a way to verify it. We also build a test set where most of the planted errors are ones the standard method cannot possibly catch, so that any improvement we measure is real and not an artifact.

One more design choice worth stating early: our system needs **no model training**. It runs entirely by prompting existing models. The strongest comparable system in the literature (MARCH, Section 3.1) gets its results through reinforcement learning on a GPU cluster. We are deliberately avoiding that.

---

# 2. Motivation

## 2.1 Why Long Reports Are Different From Short Answers

If you ask an AI "what year was this paper published?", the answer is one fact and it came from one place. Checking it is easy: find the passage, see if it says 2024.

A research report is different. The sentences that make a report *valuable* — the ones that actually synthesise rather than just quote — are usually the ones that **no single passage can confirm**. Here are six ordinary sentences from a competent literature survey:

```
"Three of the five frameworks we surveyed limit how many times they retry."
        → counts across several papers

"This approach consistently beats the debate-based methods."
        → a claim about every case, not one case

"Unlike the earlier work, this system does measure its own error rate."
        → compares two different papers

"The trend from 2023 to 2026 has been toward tighter cost limits."
        → describes a pattern over time

"This shows that retrieval quality is the real bottleneck."
        → an interpretation, stated more strongly than the evidence allows

"We now turn to the question of retrieval quality."
        → not a factual claim at all
```

**Figure 1:** Six sentence types that standard fact-checking handles badly.

Not one of these can be checked by pulling up its cited passage and asking "does this passage say that?" The next section explains why, and groups the failures into three problems.

## 2.2 The Three Problems

### Problem 1 — Some claims are about a *group* of sources, not one source

Take *"three of the five frameworks limit how many times they retry."* This is not a simple fact. It is really a **count** performed over five separate facts, each of which lives in a different paper.

Standard checking gets this wrong in **both** directions:

- **It rejects correct sentences.** No single passage says "three of five." So the checker marks the sentence unsupported, even though it is perfectly true. In other words, the checker punishes exactly the sentences that make a report a synthesis instead of a list of quotations.
- **It accepts wrong sentences.** Suppose the real number is two, not three. The checker looks at whichever passage was cited, sees that *that* framework does limit retries, and passes the sentence. The miscount is never noticed.

This is worth being precise about, because it is the heart of our project: **a better AI model would not fix this.** The cited passage genuinely does not contain the count. No amount of careful reading of that passage can produce the right answer, because the information is not in there.

### Problem 2 — A long report can contradict itself

A report might say in Section 2 that *"System X limits its retries"* and in Section 5 that *"none of the reviewed systems limit their retries."* Both sentences might be individually well-supported, each pointing at a different passage. Together they are nonsense.

This **cannot happen in short question-answering** — an answer has to be long enough to contradict itself, and a one-line answer is not. That is precisely why existing methods have no mechanism for it: the problem never came up in the setting they were designed for.

And no amount of improving the checker helps, because the contradiction is not between a claim and a passage. It is between two claims. A checker that examines claims one at a time, however accurate, will never see it.

### Problem 3 — Claims can be technically true but overstated

Fact-checking asks *whether* a claim is supported. It never asks whether the sentence is **worded more strongly than the evidence justifies**.

"This **proves** that X" backed by a single preliminary experiment is an overclaim. But it passes the check, because the underlying fact is sitting right there in the passage.

The reason existing systems miss this is mechanical. When they break a report into claims, they normalise the wording first — "may suggest that X" becomes simply "X" — because the hedging words are treated as noise. Once the hedge is gone, there is nothing left to compare against.

This matters more here than elsewhere. Overstating your evidence is the characteristic mistake of academic writing specifically.

## 2.3 Nobody Checks the Fact-Checker

There is a second gap, and it is about the checker rather than the writer.

Papers report how accurate their *overall system* is. They rarely report how accurate the *checking component* is on its own. And where a catch rate is reported, it is almost always measured on short isolated claims with perfect evidence supplied — not on real generated text.

Crucially, almost nobody reports the opposite error: **how often the checker flags a sentence that was actually fine.** For long reports this is the number that decides whether the system is usable at all. A checker that flags every introductory sentence gives you a report covered in warning labels, and users will ignore all of them — including the real ones.

There is a direct trade-off here. Make the checker stricter and it catches more real errors but also flags more good sentences. No existing work measures where that trade-off sits, so nobody knows how to tune it.

---

# 3. Literature Survey

Work relevant to this project falls into two groups. The first gave us the overall multi-agent structure; the second gave us the actual checking technique.

## 3.1 Systems That Use Multiple AI Agents

| Work | What it does | How it relates to us |
|:---|:---|:---|
| **GSAR**<br>Kamelhar, 2026 | Sorts claims into four buckets — supported, unsupported, contradicted, and "adds a useful alternative view" — weights them by how trustworthy the evidence source is, and uses the resulting score to decide whether to continue, rewrite, or start over. Runs under a fixed budget so it cannot loop forever. | The closest existing work on **stopping rules**, and the only one we reviewed that reports how often its checker catches errors. We borrow the budget idea. Its limits: it is tested on short isolated claims rather than generated reports, it never reports how often it flags correct claims, and its four buckets describe *what the evidence showed* rather than *what kind of claim it is* — a difference explained in Section 5.3. |
| **MARCH**<br>Li et al., 2026 | Three agents: one writes an answer, one breaks it into checkable claims, and one verifies those claims against the sources **without being allowed to see the original answer**. The argument is that a checker who can see the answer tends to rubber-stamp it. Trained with reinforcement learning. | **The closest work to ours.** Its three-agent split maps almost directly onto our design, including the idea of hiding the draft from the checker — which we **adopt as established and do not claim as our own**. Where we differ: MARCH assumes every claim can be checked against a single passage, which Section 2 argues is false for long reports. We also avoid its training requirement entirely. |
| **Tool-MAD**<br>Jeong et al., 2026 | Gives each debating agent a different tool — one uses web search, another uses a document database — and lets them refine their searches as the debate goes on. Reports up to 5.5% improvement over the previous best debate method. | Shows that searching repeatedly beats searching once. But the final decision still comes from agents arguing with each other, and the task is still short claims. |
| **ClaimVerAgents**<br>Sallami et al., 2025 | A fake-news checker built as a pipeline of small specialised steps: pull out the claim, write a search query, search, judge the evidence, decide, explain. Can answer "not enough information" instead of being forced to guess. | That "not enough information" option is the closest existing version of our idea that **admitting uncertainty is a valid answer**. But it classifies single claims; it does not write anything. |
| **Yang et al.**<br>2025 | Combines repeated questioning and error logs with debate and voting between models, weighting each model's vote by how often it has been right before. Also compresses the conversation to save cost. | One of the few papers that treats running cost as a real constraint rather than an afterthought. But truth is still decided by models agreeing with each other. |
| **Du et al.**<br>2023 / 2024 | The original debate method: several copies of a model answer independently, then read each other's answers and revise, for several rounds. Improves accuracy on reasoning and factual tasks. | We use this as one of our comparison baselines in Section 5.5. |

**Table 1:** Multi-agent verification and debate systems.

## 3.2 Systems That Check Claims Against Sources

This second group, not the debate systems, is where our checker actually comes from. Both of our closest competitors say so themselves — GSAR states that it relies on FActScore's method for breaking text into claims, and MARCH's claim-extraction agent is built on the same lineage.

| Area | Representative work | What it established |
|:---|:---|:---|
| Breaking text into claims | FActScore, RAGAS | The method of splitting generated text into individual facts and scoring each one separately |
| Scoring faithfulness | Vectara HHEM, TruLens | Models that give a hallucination score for a response against its source |
| Claim verification | FEVER and its successors | The three-way verdict — supported, refuted, not enough information — that nearly everything since has inherited |
| Writing with citations | ALCE, RARR, Self-RAG | Models that produce inline citations, measured on whether those citations are correct |
| Long-form fact checking | SAFE / LongFact | Extends per-claim scoring to long generated text using web search |

**Table 2:** Claim-checking and attribution research.

**We use all of this and do not claim it as our contribution:** splitting text into claims, checking each against its cited source, inline citations, and the three-way verdict.

## 3.3 What Is Missing

Across both groups, every method we reviewed scores claims **one at a time and independently**, then adds up the results. The consequences are:

- A claim that is itself a count or comparison over several sources has no defined treatment.
- No method ever compares two claims against each other.
- All of them throw away hedging words before checking.
- None distinguishes a sentence that *cannot* be fact-checked from one that *failed* fact-checking.
- None reports how often the checker wrongly flags a correct sentence in generated text.

Our system is the only one of the seven that addresses any of these, and it does so without any model training, whereas the strongest competitor needs a GPU cluster.

---

# 4. Problem Statement

## 4.1 What We Are Trying to Solve

Given a fixed collection of technical documents and a broad research question, produce a long structured report in which every factual statement is either:

**(a)** genuinely backed by the documents, or
**(b)** clearly and usefully marked as unverified.

The research problem is that the standard tool for part (a) — check one claim against one cited passage — **does not work** for three kinds of statement that are common in long reports:

1. Statements that are true or false depending on a **group** of sources, not any one of them.
2. Statements that **contradict each other** while each one looks fine on its own.
3. Statements that are **worded more strongly** than the evidence supports, while still being technically true.

A related problem is that the checker itself has never been properly measured, so nobody knows how strict to make it.

## 4.2 The Nine Gaps

| # | Gap | Explanation | Status in existing work |
|:---|:---|:---|:---|
| 1 | Claims about groups of sources | Counts, comparisons and trends across several papers cannot be checked one passage at a time, yet they are the most valuable sentences in a report. | Not addressed |
| 2 | Not everything is checkable | Section headings, transitions and commentary are not factual claims. Forcing them through a fact check guarantees false alarms. | Not addressed |
| 3 | Evidence that was not cited | A sweeping claim is disproved by evidence the writer chose *not* to cite. Checking only cited passages can never catch this. | Not addressed |
| 4 | Self-contradiction | Two individually supported claims can contradict each other. Only possible in long output. | Not addressed |
| 5 | Overstated wording | Hedging words are discarded before checking, so overclaiming passes. | Not addressed |
| 6 | Wrong citation vs. wrong fact | A true claim with the wrong citation looks identical to an invented one, forcing an expensive rewrite when a citation swap would do. | Not addressed during generation |
| 7 | False alarm rate | Catch rate is sometimes reported; the false alarm rate almost never is. For long reports this decides usability. | Partly addressed |
| 8 | What happens across rounds | Nobody measures whether repeated correction actually converges, or whether fixing one sentence breaks another. Retry limits are picked arbitrarily. | Not addressed |
| 9 | Training cost | The best existing result requires reinforcement learning infrastructure. | Open by choice |

**Table 3:** Gaps in existing work.

---

# 5. Objective and Methodology

## 5.1 Our Objectives

Seven things to build, and four things to measure. The numbers in brackets refer to the gaps in Table 3.

**To build:**

1. **Sort claims by type** before checking them, so each gets an appropriate test. *(Gap 2)*
2. **Verify group claims properly** — check each part separately, then do the counting or comparing in ordinary program code. *(Gap 1)*
3. **Search the uncited evidence** for anything that disproves a sweeping claim. *(Gap 3)*
4. **Compare claims against each other** to catch self-contradiction. *(Gap 4)*
5. **Compare how strongly a claim is worded** against how strong its evidence actually is. *(Gap 5)*
6. **Tell a wrong citation apart from a wrong fact**, and repair each differently. *(Gap 6)*
7. **Track which claims depend on which facts**, so correcting a fact automatically re-checks everything built on it.

**To measure:**

8. **Plant known errors** in otherwise-clean reports, and report catch rate and false alarm rate separately for each error type. *(Gap 7)*
9. **Separate checker mistakes from search mistakes** by re-running with perfect passages supplied.
10. **Verify our claim taxonomy is real** by having two people label claims independently and measuring whether they agree.
11. **Measure what happens across correction rounds**, including whether fixing one sentence breaks another. *(Gap 8)*

## 5.2 How the System Works

Four components, each with one job, running in a loop with a hard limit on how many times it can repeat.

```
  ┌──────────────────────────────────────────────────────────┐
  │  PLANNER                                                 │
  │  Breaks the research question into sub-topics            │
  └────────────────────────┬─────────────────────────────────┘
                           ▼
  ┌──────────────────────────────────────────────────────────┐
  │  RESEARCHER                                              │
  │  The ONLY part allowed to search the documents           │
  │  Labels every passage it finds with where it came from   │
  │  Keeps everything it found, including unused passages    │
  └────────────────────────┬─────────────────────────────────┘
                           ▼
  ┌──────────────────────────────────────────────────────────┐
  │  WRITER                                                  │
  │  Drafts the report, citing a passage for every claim     │
  └────────────────────────┬─────────────────────────────────┘
                           ▼
  ┌──────────────────────────────────────────────────────────┐
  │  CHECKER                                                 │
  │   Step 1  Split the draft into individual claims         │
  │   Step 2  Sort each claim into one of four types         │
  │   Step 3  Check each claim the way its type requires     │
  │   Step 4  Compare wording strength against evidence      │
  │   Step 5  Compare claims against each other              │
  │   Step 6  Re-check anything that depended on a fix       │
  └───────┬──────────────────────────────┬───────────────────┘
          │                              │
   [problems found,              [all clear, or
    retries remaining]            retry limit reached]
          ▼                              ▼
  ┌──────────────────┐        ┌─────────────────────────────┐
  │ Send specific    │        │ Final report; anything       │
  │ fixes to Writer  │        │ unresolved is clearly        │
  └──────────────────┘        │ labelled as unverified       │
                              └─────────────────────────────┘
```

**Figure 2:** How the four components fit together.

The **Planner** turns a broad question into an ordered list of sub-topics and a report outline.

The **Researcher** is the only component allowed to search the documents. This is deliberate and strictly enforced: if any other component could search, it could also quietly substitute something it "remembers" from training instead of something it actually found. Every passage it returns is labelled with its document, page, and location. It also keeps **every passage it found, including the ones the Writer never used** — objectives 3 and 6 both depend on having those.

The **Writer** drafts the report, citing a source for every factual sentence. On later rounds it revises only the specific sentences that were flagged, leaving everything else untouched.

The **Checker** is the technical core, described next.

## 5.3 The Checker in Detail

### Step 1 — Split the draft into claims

The report is broken into individual standalone claims, keeping track of which sentence each came from. This follows the established method and is not something we claim as new — with one change. **We keep the hedging words** ("may suggest", "clearly demonstrates") attached to each claim, where standard methods delete them. Step 4 cannot work without them.

### Step 2 — Sort each claim into a type

Before any checking happens, every claim is put in exactly one of four boxes.

| Type | What it is | Example | How it gets checked |
|:---|:---|:---|:---|
| **Type 1**<br>Direct | One passage can settle it | "Tool-MAD reports a 5.5% improvement" | Check that passage |
| **Type 2**<br>Group | Depends on several sources: counts, comparisons, trends, sweeping statements | "Three of the five systems limit retries" | Check each part, then do the counting in code, then search for counterexamples |
| **Type 3**<br>Interpretation | Goes beyond what any source says | "This suggests search quality is the bottleneck" | Check nothing contradicts it; label it as interpretation |
| **Type 4**<br>Structural | Not a factual claim at all | "We now turn to evaluation" | **Skip it**; record that it was skipped |

**Table 4:** The four claim types.

Getting this wrong is costly in two different ways, and they are not symmetric. Putting a Type 4 sentence in the Type 1 box means flagging a perfectly good transition sentence as a factual error. Putting a Type 2 claim in the Type 1 box means a miscount slips through unnoticed.

Because sorting is this important, we measure how well it works rather than assuming it works. Two people will label the same claims by hand and we will check whether they agree with each other and with the system. A category scheme that two humans cannot apply consistently is not a real category scheme, and we would rather find that out early.

Simple word-matching handles the obvious cases — phrases like "we now turn to" mean Type 4, words like "three of", "all", "unlike" mean Type 2 — which saves cost and gives us a rules-only baseline to compare against.

### Step 3 — Check each claim according to its type

**Type 1** claims are checked against the exact passage cited, with the checker deliberately not shown the rest of the report. This is MARCH's idea and we adopt it: a checker that can see the surrounding draft tends to be swayed by it.

When a Type 1 claim fails, we do not immediately call it wrong. We first search the **other** passages. If some different passage does support it, then the fact is right and only the citation is wrong — a completely different problem with a completely different fix. We report it separately as a **misattribution**, and the repair is just swapping the citation rather than rewriting the sentence. This is cheaper and it stops the Writer from deleting content that was correct.

**Type 2** claims — the group claims — go through three steps:

1. **Split it up.** "Three of the five systems limit retries" becomes five separate small claims, one per system, each with its own passage.
2. **Check each part** exactly as if it were a Type 1 claim.
3. **Do the arithmetic in code.** Count how many parts came back true. Compare that to what the sentence claimed. If the sentence said three and only two checked out, the sentence is wrong — and we know it by *counting*, not by asking a model.

This third step is the centre of the whole project, so it is worth stating plainly: **the counting is done by an ordinary program, not by an AI model.** Counting is arithmetic. A comparison is a comparison. A trend is checking whether numbers go up or down. Writing these as normal code makes them exact, repeatable, and testable with ordinary unit tests — none of which is ever true of an AI making a judgement call.

For sweeping claims — anything containing "all", "none", "always", "never", "unlike X" — we add one more step. We go back through the passages the Writer **did not cite** and look for a counterexample.

This is backwards from how fact-checking normally works, and deliberately so. Normally you look for evidence that the claim is right. Here we look for evidence that it is wrong. It has to work this way: a sweeping claim checked against its own cited passage can never fail, because the writer picked the one passage that agreed with it. The counterexample, if it exists, is always somewhere the writer did not point.

**Type 3** claims are interpretations, so we do not demand that a source states them outright. We only check that nothing in the evidence contradicts them, and then label them clearly as interpretation rather than fact.

**Type 4** claims are skipped entirely, but the skip is recorded. Anyone can look at the log and see exactly which sentences were never checked, and why.

### Step 4 — Compare wording strength against evidence strength

Using the hedging words kept in Step 1, the system compares how confidently a sentence is worded against how much evidence actually backs it. Wording runs on a scale:

```
   suggests  <  indicates  <  shows  <  demonstrates  <  proves
      weak                                              strong
```

Evidence strength is judged on whether several sources agree or only one, and whether the source itself was hedged or definite. If the wording is stronger than the evidence justifies, the sentence is flagged as an **overclaim**, and the suggested fix is to soften the wording — not to delete the sentence.

The reverse case, where a sentence is more cautious than it needs to be, is recorded but never flagged. Being too careful is not a hallucination.

### Step 5 — Compare claims against each other

This check has no per-claim equivalent; it only makes sense across a whole report.

After everything else is done, the system compares claims against each other looking for contradictions. Comparing every pair would be far too slow, so an ordinary code filter first narrows it down to pairs that talk about the same things.

When a contradiction is found, the message sent back names **both** sentences and **both** supporting passages. Telling the Writer "sentence 40 is suspicious" is useless; telling it "sentence 40 and sentence 112 cannot both be true, here is the evidence for each" is actionable.

### Step 6 — Re-check anything that depended on a fix

The system keeps a map of which claims were built from which facts. If a fact gets corrected in round two, every group claim that counted on it is automatically re-checked.

Without this, a specific and silent failure occurs: the individual fact gets fixed, but the sentence saying "three of five systems..." still says three, because nobody went back and re-counted.

## 5.4 Stopping Rules

When the Checker finds a problem, it sends the Writer a precise message: which sentence, what the claim was, what type it is, which passages are involved, what went wrong, and a suggested fix. The Writer changes only that sentence. The report is never thrown out and rewritten, and the components never argue with each other.

The loop has a **hard limit** on rounds, which puts a firm ceiling on both cost and running time.

Anything still unresolved when the limit is hit is not silently dropped and not silently kept. It is published with a specific label saying what went wrong:

- *no supporting passage found*
- *the count or comparison could not be confirmed*
- *a counterexample was found in the sources*
- *contradicts the statement in section 4*
- *worded more strongly than the evidence supports*
- *this is interpretation, not a directly evidenced fact*

We treat these labels as a **successful outcome**, not a failure. An honest "we could not verify this, and here is exactly why" is more useful than a confident guess. And unlike existing work, which picks a retry limit arbitrarily, we will measure how much each additional round actually fixes and set the limit from that data.

## 5.5 How We Will Test It

### Planting known errors

We take clean reports and deliberately introduce errors at known positions, so we know exactly what the right answer is. The error list is designed so that **six of the eleven types cannot possibly be caught by the standard method** — which is what makes this a real test of our contribution rather than a general test of AI reading comprehension.

| # | Error planted | Can standard checking catch it? | Which objective it tests |
|:---|:---|:---|:---|
| 1 | Change a number, percentage or date | Yes | — |
| 2 | Keep the fact, cite the wrong source | Partly | Objective 6 |
| 3 | Insert a fluent sentence with no support at all | Yes | — |
| 4 | State the opposite of what the passage says | Yes | — |
| 5 | Turn "some" into "consistently" | **No** | Objective 3 |
| 6 | Change a count from two to three | **No** | Objective 2 |
| 7 | Claim "unlike X" when X actually does the same thing | **No** | Objective 3 |
| 8 | Invent a trend that is not in the data | **No** | Objective 2 |
| 9 | Add a claim that contradicts another supported claim | **No** | Objective 4 |
| 10 | Change "may suggest" to "demonstrates" | **No** | Objective 5 |
| 11 | Silently drop a passage that disagrees | **No** | Stretch goal |

**Table 5:** The eleven planted error types.

### What we measure

**Catch rate, reported separately for each of the eleven error types.** A single combined number would hide exactly the effect we are trying to demonstrate.

**False alarm rate** — how often a correct sentence gets flagged — measured on clean reports, and broken down by claim type, because flagging Type 4 headings is the specific failure we predict.

**A breakdown of which verdict was given when**, including whether the system can really tell error 2 (wrong citation) from error 3 (invented claim).

**Cost and running time**, reported next to accuracy in every result table. An accuracy number with no cost attached is exactly the reporting habit criticised in Section 2.3.

### Turning features on one at a time

The main experiment. Everything else stays fixed; we only change what the Checker is allowed to do.

| Version | What the Checker does | Tests objective |
|:---|:---|:---|
| 1 | Plain checking — every claim against its cited passage | baseline |
| 2 | Adds claim sorting, skipping Type 4 | 1 |
| 3 | Adds group-claim counting, misattribution, dependency tracking | 2, 6, 7 |
| 4 | Adds the counterexample search | 3 |
| 5 | Adds contradiction checking | 4 |
| 6 | Adds wording-strength checking | 5 |

**Table 6:** The six versions we compare.

**What we predict, stated before running anything.** Version 2 should reduce false alarms without catching fewer real errors. Version 3 should catch errors 6 and 8 and separate error 2 from error 3. Version 4 should catch errors 5 and 7. Version 5 should catch error 9; version 6 should catch error 10.

Most importantly: **versions 1 through 4 should score exactly zero on errors 9 and 10**, because none of them compares claims to each other or looks at wording. Predicting a zero in advance and then observing it is a stronger result than any improvement number.

### Three more experiments

**Separating our mistakes from search mistakes.** We run everything twice — once with real document search, once with the correct passages handed to the system directly. Any difference is the search's fault, not the Checker's. Existing work mixes these two together and reports one combined number.

**Checking the claim types are real.** Two of us label 200 claims independently, without seeing what the system decided, and we measure agreement.

**Watching what happens across rounds.** How much does each extra round actually fix? What does each round cost? And most interestingly: **does fixing one sentence break another?** We check this by re-verifying sentences that were already clean. Nobody in the self-correction literature has measured this.

**Comparing against alternatives.** Three-way comparison against (a) plain AI writing with document search and no checking, and (b) the debate method of Du et al. Hallucination rate is judged by people who are not told which system produced which report.

### What would prove us wrong

We are stating our predictions in advance so the project can fail honestly.

The **core claims** are that group-claim counting catches errors 6 and 8 which plain checking cannot, and that the counterexample search catches errors 5 and 7. **If both fail, our main contribution is wrong** and we will report that.

Secondary claims: claim sorting reduces false alarms without losing catch rate; contradiction and wording checks catch errors 9 and 10 at a tolerable false alarm rate; misattribution really can be told apart from invention; two people can agree on the claim types; extra rounds give sharply diminishing returns; and the whole system beats both baselines at a bounded cost.

---

# 6. Simulation Platform and Requirements

## 6.1 Software and Hardware

The system is written in Python. Documents are read from PDF and split into labelled chunks. Searching combines two methods: meaning-based search using a local model, and keyword search. The components talk to each other through strictly defined message formats that are validated automatically, so a mismatch between two parts fails loudly instead of silently.

The counting and comparison functions are plain Python with ordinary unit tests. Experiments are driven by configuration files, so adding a new version to compare needs no code changes. Every AI call is logged with which model, how many tokens, how long it took, and what it cost. All prompts live in version-controlled files rather than being buried in the code, so a change to a prompt shows up in the project history like any other change.

We also build a simple HTML viewer that shows a report with each claim colour-coded by its type and verdict. This is mainly for us — we will be reading hundreds of verdicts by hand, and doing that in raw log files would waste more time than the viewer costs to build.

**No GPU cluster is needed.** The search model and an optional local checking model run on a normal laptop; the heavier AI work happens through a paid API. This follows directly from our decision not to train anything.

## 6.2 What Needs an AI Model and What Does Not

A useful way to understand the design is to see how little of it actually requires an AI.

| Part of the system | How often it runs | How much accuracy matters | What it needs |
|:---|:---|:---|:---|
| Writer | Once per round | Very high | Strongest available model |
| Claim splitting, claim sorting | Moderate | Low — mechanical work | Cheapest model |
| Checking a claim against a passage | **Very often — about 80% of all calls** | **Critical** | Mid-range model |
| Counting, comparing, trend checking | — | — | **No AI — plain code** |
| Narrowing down claim pairs to compare | — | — | **No AI — plain code** |
| Reading hedging words | — | — | **No AI — word list** |
| Tracking claim dependencies | — | — | **No AI — plain code** |
| All metrics and statistics | — | — | **No AI — arithmetic** |

**Table 7:** What needs a model and what does not.

Exact model versions are pinned in the configuration. We never point at a "latest" label, because if the provider updates the model halfway through our experiments, every earlier result silently becomes incomparable and we would have no way to tell.

**Fallback plan.** If paid access turns out not to be possible, we have designed a fully local version: local search, a small local checking model, and a local writing model. This removes the cost entirely, but the checking quality then becomes the limit on every result we report — which we would state clearly rather than quietly.

## 6.3 Cost

One round of report generation needs roughly 255 AI calls: about fifty for checking individual claims, forty for the parts of group claims, a hundred for the counterexample search, and the rest for planning, writing, splitting, sorting and the remaining checks. Running all six versions across ten questions and three rounds comes to roughly 46,000 calls.

Four things bring this down to a manageable number:

1. **Sending many claims per call** instead of one at a time, which cuts the number of calls by roughly ten times.
2. **Reusing cached passages**, since the same passage text is sent repeatedly — cached text costs about a tenth as much.
3. **Using the discounted batch service**, which is half price and perfectly suited to us because none of our experiments need instant answers.
4. **Filtering with a small local model first**, so only the genuinely uncertain cases go to the paid service.

With all four applied, the expected cost of the whole project is in the range of tens of dollars rather than hundreds.

## 6.4 Documents and Human Labelling

We will use **40 to 60 research papers** on hallucination, fact-checking, and multi-agent systems. The collection is **frozen before testing begins** — adding a paper halfway through would invalidate every result collected before it. We record the exact version and a checksum of every file so the collection can be reconstructed exactly.

We will write **8 to 12 research questions**, covering four shapes deliberately: single-topic surveys, comparisons between systems, questions about change over time, and at least one question where we know two papers in the collection disagree.

**This is the single biggest risk in the project.** If our questions do not make the Writer produce group claims, then objectives 2 and 3 cannot be tested at all, no matter how well they are built. We will therefore generate a sample report and inspect it *before* freezing anything.

Two rounds of human labelling are needed. Sorting validation takes two people about four hours each, labelling 200 claims independently without seeing the system's answer. Judging hallucination rate at the end takes about six hours each, on reports shuffled with the version labels removed — removing the labels matters, because we obviously want our own system to win and that bias would otherwise leak into the numbers. With three of us, two can label and the third settles disagreements.

Because we also intend to submit this as a paper, we treat reproducibility as a requirement rather than a nice-to-have: every run recorded with its settings, exact model versions logged, the document list published with checksums instead of the copyrighted PDFs, all prompts published as written, and the error-planting tool released so others can reuse it.

---

# 7. Conclusion

## 7.1 What We Are Contributing

Checking each claim against its cited source is an effective, well-tested technique for short question-answering. Our argument is that it is not enough for long research reports — not because the AI doing the checking is inadequate, but because three common kinds of sentence have truth conditions that this check does not address at all.

What we propose to contribute:

1. **A way of sorting claims by what kind of check they can take**, separating sentences that can be fact-checked from ones that cannot — a distinction existing systems do not make.
2. **Proper verification of group claims**, where the counting and comparing is done by ordinary program code over separately verified facts, instead of being taken on trust from the model.
3. **A search for disproof** rather than proof, looking through uncited evidence for counterexamples to sweeping claims.
4. **Contradiction checking within a single report**, catching a failure that cannot even occur in short answers.
5. **Wording-strength checking**, keeping hedging words through the pipeline instead of discarding them.
6. **Telling a wrong citation apart from a wrong fact**, which allows a much cheaper repair.
7. **A test set built so that most planted errors are invisible to the standard method**, plus a way to separate our mistakes from search mistakes, plus the first measurement of whether repeated correction breaks previously correct sentences.

The whole system runs without training anything.

## 7.2 Work Plan

So far we have completed the literature review, the problem formulation, the system design, the testing plan, and the requirements specification. Implementation is planned in eleven phases, with phases 1 to 7 being what we commit to and 8 to 11 conditional on schedule.

| Phase | What gets built | When it is done |
|:---|:---|:---|
| 1 | Repository, message formats, document loading, search, sample report | Sample reports actually contain group claims |
| 2 | Planner, Researcher, Writer, plus the basic Checker and loop | Version 1 runs end to end |
| 3 | Error-planting tool, metrics, experiment runner, viewer | Test tools ready before the features they test |
| 4 | Claim sorting, plus the human labelling study | Version 2; humans agree with each other |
| 5 | Group-claim counting, misattribution, dependency tracking | Version 3 |
| 6 | Counterexample search, then the full comparison run | Versions 1–4 measured |
| 7 | Analysis and report | **Core project complete** |
| 8–11 | Contradiction checking, wording checking, full comparison, paper | Conditional on schedule |

**Table 8:** Implementation phases.

Two rules about ordering are not negotiable. **The test tools get built before the features they test** — build the test afterwards and you will unconsciously shape the feature to pass it. And **the human labelling study comes before anything that depends on the claim types**, so that if the categories turn out to be unreliable we find out before three more features are built on top of them.

## 7.3 Known Weaknesses

We would rather state these upfront than have them discovered later.

**Claim sorting is now a single point of failure.** It is a new thing that can go wrong, and how well it works puts a ceiling on how well anything after it works.

**The counterexample search can only look at what was retrieved.** If the contradicting evidence sits in a paper the Researcher never found, we cannot catch it. The search reduces the problem; it does not eliminate it, and we do not claim otherwise.

**Search quality limits everything.** If the right passage is never found, the Writer has nothing to work with and the Checker correctly flags a reasonable sentence as unsupported. Our second run with perfect passages measures how big this effect is, but it does not remove it.

**Wording-strength checking is the fuzziest judgement in the system.** Where reasonable confidence ends and overclaiming begins is genuinely debatable, and we expect this check to produce the most false alarms of any. If it turns out too noisy to drive rewrites, we will report it as a warning signal instead and say so.

**Checking whether a passage supports a claim is still a judgement call.** Sorting claims by type reduces how often that judgement is needed but does not make it exact. This is the honest floor of the approach.

**Group claims cost more to check.** A claim that splits into five parts needs roughly five checks plus a search, against one for the simple method.

**We only work on a fixed document collection.** Pointing this at the open web would degrade search quality and, through it, everything that depends on it.

---

# 8. References

[1] F. A. Kamelhar, "GSAR: Typed Grounding for Hallucination Detection and Recovery in Multi-Agent LLMs," arXiv preprint, April 2026.

[2] Z. Li, Y. Zhang, P. Cheng, J. Song, M. Zhou, H. Li, S. Hu, Y. Qin, E. Zhao, X. Jiang, and G. Jiang, "MARCH: Multi-Agent Reinforced Self-Check for LLM Hallucination," Qwen Large Model Application Team, Alibaba, arXiv preprint, March 2026.

[3] S. Jeong, Y. Choi, J. W. Kim, and B. Jang, "Tool-MAD: A Multi-Agent Debate Framework for Fact Verification with Diverse Tool Augmentation and Adaptive Retrieval," arXiv preprint, January 2026.

[4] D. Sallami, S. Amri, and E. Aïmeur, "ClaimVerAgents: A Multi-Agent Retrieval-Augmented Claim Verification Framework," in Proc. IEEE/ACS Int. Conf. on Computer Systems and Applications (AICCSA), 2025.

[5] Y. Yang, Y. Ma, H. Feng, Y. Cheng, and Z. Han, "Minimizing Hallucinations and Communication Costs: Adversarial Debate and Voting Mechanisms in LLM-Based Multi-Agents," Applied Sciences, vol. 15, no. 7, art. 3676, March 2025.

[6] Y. Du, S. Li, A. Torralba, I. Mordatch, and J. B. Tenenbaum, "Improving Factuality and Reasoning in Language Models through Multiagent Debate," arXiv preprint, 2023; in Proc. Int. Conf. on Machine Learning (ICML), 2024.

[7] S. Min, K. Krishna, X. Lyu, M. Lewis, W. Yih, P. W. Koh, M. Iyyer, L. Zettlemoyer, and H. Hajishirzi, "FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation," in Proc. EMNLP, 2023.

[8] S. Es, J. James, L. Espinosa-Anke, and S. Schockaert, "RAGAS: Automated Evaluation of Retrieval Augmented Generation," in Proc. EACL, System Demonstrations, 2024.

[9] J. Thorne, A. Vlachos, C. Christodoulopoulos, and A. Mittal, "FEVER: a Large-scale Dataset for Fact Extraction and VERification," in Proc. NAACL-HLT, 2018.

[10] T. Gao, H. Yen, J. Yu, and D. Chen, "Enabling Large Language Models to Generate Text with Citations," in Proc. EMNLP, 2023.

[11] L. Gao, Z. Dai, P. Pasupat, A. Chen, A. T. Chaganty, Y. Fan, V. Zhao, N. Lao, H. Lee, D.-C. Juan, and K. Guu, "RARR: Researching and Revising What Language Models Say, Using Language Models," in Proc. ACL, 2023.

[12] A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection," in Proc. ICLR, 2024.

[13] J. Wei, C. Yang, X. Song, Y. Lu, N. Hu, D. Tran, D. Peng, R. Liu, D. Huang, C. Du, and Q. V. Le, "Long-form Factuality in Large Language Models," arXiv preprint, 2024.

[14] Vectara, "HHEM: Hughes Hallucination Evaluation Model," model release and technical documentation, 2023–2024.

[15] TruLens, "The RAG Triad: Context Relevance, Groundedness, and Answer Relevance," TruEra technical documentation, 2023.
