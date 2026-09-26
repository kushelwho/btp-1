# 1. Problem Statement

Large Language Models (LLMs) demonstrate remarkable capabilities in synthesizing complex information, generating cohesive narratives, and performing multi-step reasoning. However, when deployed to construct comprehensive research reports or long-form summaries from multi-document contexts, they exhibit a persistent, systemic failure mode: **context-conflicting hallucinations**. As the length of the generated output increases and the underlying corpus grows in volume and density, LLMs frequently produce statements that sound authoritative, fluent, and stylistically persuasive but are entirely unsupported by, or directly contradictory to, the retrieved source materials.

  

```
                                      Traditional Consensus Fallacy
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ LLM Instance 1 │─────┼─ Inter-Model   │─────┼─ Shared Blind  │ ──► Confident False Consensus
│  Draft / Claim │     │ Debate / Vote  │     │      Spot      │     (Factually Ungrounded)
└────────────────┘     └────────────────┘     └────────────────┘

                                  Our Evidence-Grounded Framework
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ Synthesizer    │─────┼─ Isolated      │─────┼─ Tagged Source │ ──► Factual Verification
│  Draft Claim   │     │ Critic Agent   │     │  Text Passage  │     (Verified or Escalated)
└────────────────┘     └────────────────┘     └────────────────┘
```

The standard architectural response to this challenge has been to introduce multi-agent systems where multiple model instances engage in natural language "debate" or multi-agent voting until inter-model consensus is achieved. This prevailing methodology suffers from a critical, under-addressed flaw: **inter-model agreement is not synonymous with factual correctness**. When multiple instances of similar foundation models debate a claim, they draw from shared training distributions and identical inductive biases. Consequently, multiple agents frequently converge with high confidence on the same hallucinated conclusion if they share a common blind spot.

  

Furthermore, existing multi-agent self-correction and debate frameworks exhibit several key operational deficiencies:

  

- **Unbounded Token Expenditure:** Most correction loops lack strict iteration bounds, causing agents to enter infinite verbal loops that quietly burn compute budgets and introduce severe latency spikes in production environments.
    
      
    
- **Unmeasured Verifier Errors:** Literature routinely assumes that the "judge" or "critic" agent is perfectly objective, reporting overall framework improvements while completely failing to measure the verifier's own error profile (false positives and false negatives).
    
      
    
- **Absence of Operational Systems Metrics:** Research in this domain predominantly focuses on single accuracy numbers on static benchmarks, ignoring the cost/latency-versus-accuracy tradeoff curves necessary to evaluate real-world production viability.
    
      
    

# 2. Current Research Work

The following section reviews the contemporary state-of-the-art (SOTA) research surrounding multi-agent verification, tool-augmented debate, and hallucination mitigation, ordered in reverse chronological order (latest research first):

  

```
                                  Chronological Evolution of SOTA
                                  
  Apr 2026: GSAR (Kamelhar)        ──► Typed Grounding, 3-Tier Recovery, Cost Bounds [source: 3]
  Mar 2026: MARCH (Li et al.)      ──► Asymmetric 3-Agent MARL, Response Atomizer [source: 5]
  Jan 2026: Tool-MAD (Jeong et al.)──► Dynamic Tool Retrieval, RAGAS Stability [source: 7]
  2025: ClaimVerAgents (Sallami)   ──► Task Decomposition, NEI Abstention [source: 2]
  2025: Yang et al. (MDPI)         ──► Error Logs, Weighted Voting, Entropy Control [source: 6]
  2023/2024: Du et al. (ICML)      ──► Multi-Agent Debate Consensus Baseline [source: 4]
```

## 1. GSAR: Typed Grounding for Hallucination Detection and Recovery in Multi-Agent LLMs

- **Authors & Date:** Federico A. Kamelhar (arXiv, April 2026)
    
      
    
- **Core Contribution:** Introduced a grounding-evaluation and replanning framework specifically for operational multi-agent diagnostic systems. It partitions claims into a four-way typology (_grounded_, _ungrounded_, _contradicted_, and _complementary_), assigns epistemic weights based on evidence provenance (e.g., tool-verified vs. model-inferred), and applies an asymmetric contradiction penalty. It couples this scoring mechanism to a three-tier recovery function (`proceed`, `regenerate`, `replan`) operating under a hard compute budget ($K_{max}$).
    
      
    

## 2. MARCH: Multi-Agent Reinforced Self-Check for LLM Hallucination

- **Authors & Date:** Zhuo Li et al., Alibaba Qwen Team (arXiv, March 2026)
    
      
    
- **Core Contribution:** Formulated an asymmetric, three-agent reinforcement learning pipeline comprising a _Solver_ (generates RAG responses), a _Proposer_ (acts as a "Response Atomizer" to extract discrete claim-level QA pairs), and a _Checker_ (blinded auditor that verifies claims against documents without seeing the Solver's output). It utilizes Multi-Agent Reinforcement Learning (MARL) with a zero-tolerance reward penalty to compel models to internalize evidence grounding.
    
      
    

## 3. Tool-MAD: A Multi-Agent Debate Framework for Fact Verification with Diverse Tool Augmentation and Adaptive Retrieval

- **Authors & Date:** Seyeon Jeong et al. (arXiv, January 2026)
    
      
    
- **Core Contribution:** Addressed the static evidence limitations of classic debate by equipping debating agents with heterogeneous external tools (RAG vector modules vs. live web Search APIs). It introduces an adaptive query formulation loop that refines retrieval queries across debate rounds and employs RAGAS-derived Faithfulness and Answer Relevance scores as stability indicators to guide final verdicts.
    
      
    

## 4. ClaimVerAgents: A Multi-Agent Retrieval-Augmented Claim Verification Framework

- **Authors & Date:** Dorsaf Sallami, Sabrine Amri, and Esma Aïmeur (IEEE/ACS AICCSA, 2025)
    
      
    
- **Core Contribution:** Proposed a modular, interpretable multi-agent architecture specifically for automated fake news detection. The framework decomposes claim verification into specialized sequential sub-tasks: _Claim Extraction_, _Query Generation_, _Web Search_, _Evidence Evaluation_, _Decision_, and _Explanation Generation_. It incorporates a confidence thresholding mechanism that allows the system to abstain via a "Not Enough Information" (NEI) decision label when evidence is insufficient.
    
      
    

## 5. Minimizing Hallucinations and Communication Costs: Adversarial Debate and Voting Mechanisms in LLM-Based Multi-Agents

- **Authors & Date:** Yi Yang et al. (MDPI Applied Sciences, March 2025)
    
      
    
- **Core Contribution:** Developed a framework combining single-model repetitive inquiries and internal error logs with multi-model adversarial debates and voting mechanisms. It dynamically adjusts model voting weights based on historical accuracy (boosting-inspired weight updates) and applies variance penalties and entropy compression to minimize total conversational tokens and turns.
    
      
    

## 6. Improving Factuality and Reasoning in Language Models through Multiagent Debate

- **Authors & Date:** Yilun Du, Shuang Li, Antonio Torralba, Igor Mordatch, and Joshua B. Tenenbaum (arXiv 2023 / ICML 2024)
    
      
    
- **Core Contribution:** Established the foundational paradigm of multi-agent debate. The paper demonstrated that taking multiple instances of an LLM, having them independently propose solutions, and iteratively feeding the responses of all agents back to each agent over multiple rounds significantly improves factual accuracy and mathematical reasoning compared to single-agent inference or self-reflection.
    
      
    

# 3. Scope of Current Research

## Advantages and Primary Use Cases

Current research frameworks in multi-agent factual verification offer substantial architectural advances over monolithic, single-shot LLM inference:

  

- **Task Specialization and Modularity:** Deconstructing complex reasoning into discrete pipeline stages (Extraction, Querying, Evidence Matching, Audit) prevents individual agents from experiencing context overload and improves process transparency.
    
      
    
- **Tool-Augmented Grounding:** Integrating dynamic retrieval modules (RAG and web search APIs) ensures that verification agents evaluate statements against external evidence rather than relying strictly on static, parametric memory.
    
      
    
- **Emergent Self-Correction:** Exposing models to opposing viewpoints or isolated cross-examination assists in identifying logical fallacies, math errors, and surface-level inaccuracies that single-agent chain-of-thought methods miss.
    
      
    
- **Targeted Domain Applications:** Current paradigms demonstrate strong efficacy in specialized classification domains, including real-time fake news detection (e.g., ClaimVerAgents), multi-hop question answering (e.g., MARCH), and operational IT incident diagnostic auditing (e.g., GSAR).
    
      
    

## Limitations and Disadvantages

Despite these advancements, current research exhibits severe theoretical and operational constraints:

  

|**Limitation Domain**|**Description & Structural Root Cause**|**Literature Impact**|
|---|---|---|
|**The Consensus Fallacy**|Agreement between model instances is treated as factual truth. Debating models with shared pre-training blind spots regularly converge on identical, incorrect hallucinations.|Du et al., Yang et al.|
|**Runaway Token Costs**|Multi-agent debate loops often lack hard stops or bounded recovery policies, leading to infinite verbal feedback loops that quietly burn token budgets.|Du et al., MARCH|
|**Verifier Infallibility Assumption**|Studies measure final output accuracy but assume the Critic/Verifier agent makes zero errors, ignoring false-positive and false-negative verifier rates.|ClaimVerAgents, Tool-MAD|
|**Training & Compute Heavy Bottlenecks**|Advanced self-check frameworks rely on multi-agent reinforcement learning (MARL), requiring massive compute clusters and complex RL infrastructure.|MARCH|
|**Rigid Task Constraints**|Frameworks are overwhelmingly engineered as binary/ternary _classifiers_ for short claims or QA pairs, making them unsuitable for generative long-form report drafting.|ClaimVerAgents, Tool-MAD|

# 4. Our Proposed Solution

## Conceptual Overview

Our proposed solution introduces a **Grounded Multi-Agent Framework for Hallucination-Resistant Research Synthesis**. Rather than attempting to classify isolated, external headlines or relying on open-ended inter-model debates, our system integrates claim-level evidence verification directly into an active, iterative drafting loop for long-form research synthesis.

  

The core architectural paradigm shifts the verification mechanism entirely: **we replace consensus-based verification with evidence-grounded verification**. The system operates as a cyclic state graph governed by four specialized functional agents, strict information isolation, and a mathematically bounded iteration policy.

  

```
                     ┌────────────────────────────────────────────────────────┐
                     │                      Planner Agent                     │
                     │           (Decomposes query into sub-tasks)            │
                     └───────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                     ┌────────────────────────────────────────────────────────┐
                     │                    Researcher Agent                    │
                     │       (Retrieves source passages & tags origins)       │
                     └───────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                     ┌────────────────────────────────────────────────────────┐
                     │                   Synthesizer Agent                    │
                     │          (Drafts report with tagged passages)          │
                     └───────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                     ┌────────────────────────────────────────────────────────┐
                     │                      Critic Agent                      │
                     │        (Extracts claims & checks origin passages)       │
                     └───────┬────────────────────────────────┬───────────────┘
                             │                                │
            [Unsupported / Contradicted]             [All Claims Grounded]
            [  & Iteration Round < N   ]             [ OR Round Limit N Met]
                             │                                │
                             ▼                                ▼
              ┌─────────────────────────────┐  ┌──────────────────────────────┐
              │ Targeted Revision Loop Back │  │ Output Final Synthesized     │
              │   to Synthesizer Agent      │  │ Report (Unresolved Claims    │
              └─────────────────────────────┘  │ Escalate as "Unverified")    │
                                               └──────────────────────────────┘
```

## Detailed Agent Architecture & Workflow

The system orchestrates work through four isolated functional roles operating across a state graph:

  

## 1. Planner Agent

The user's complex synthesis query is consumed by the Planner Agent. The Planner decomposes the high-level prompt into a sequence of discrete, logically structured sub-tasks and investigation goals, establishing a structured outline for the report.

  

## 2. Researcher Agent

The Researcher Agent is the **only component in the entire framework granted access to external knowledge retrieval tools**. For each sub-task generated by the Planner, the Researcher executes targeted retrieval queries against a curated document database. Crucially, every retrieved text passage is strictly tagged with an explicit origin identifier (`document_id`, `page_number`, `chunk_id`) before being passed downstream.

  

## 3. Synthesizer Agent

The Synthesizer Agent receives the tagged passages from the Researcher and drafts the research report. The Synthesizer is instructed to construct a comprehensive narrative while maintaining strict inline attribution, explicitly linking synthesized prose to the unique origin tags of the supporting passages.

  

## 4. Critic Agent (The Grounding Engine)

The Critic Agent represents the technical core of the framework. Rather than evaluating the overall "style" or "coherence" of the report, the Critic executes a programmatic two-step verification protocol:

  

- **Step A: Claim Extraction (Response Atomization):** The Critic programmatically deconstructs the Synthesizer’s draft into a set of discrete, standalone atomic claims.
    
      
    
- **Step B: Isolated Grounding Check:** For every extracted claim, the Critic isolates the exact tagged source passage referenced by the Synthesizer. It performs a strict entailment check (_Supported_, _Contradicted_, or _Unsupported_) evaluating whether the passage explicitly supports the claim.
    
      
    

## Bounded Feedback Loop & Explicit Escalation

If the Critic identifies claims that are unsupported or contradicted, it does not reject the entire report or trigger an open-ended debate. Instead, it generates a **targeted feedback payload** detailing the exact sentence index, the flagged claim, the associated source passage, and the specific reason for failure. This feedback is routed back to the Synthesizer for targeted re-drafting.

  

To prevent infinite execution loops and runaway compute costs, the feedback loop is governed by a strict engineering cap ($N=3$ rounds):

  

- **Iterative Loop Cap:** The Synthesizer-Critic loop executes for a maximum of $N$ iterations.
    
      
    
- **Explicit Uncertainty Escalation:** If a claim remains unresolved after $N$ rounds, the framework **stops attempting corrections**. It surfaces the final report to the user while explicitly tagging the unresolved statements as _"unverified - low confidence"_. Treating unverified claims as a legitimate output state ensures operational reliability and prevents uncontrolled token costs.
    
      
    

# 5. What Problems and Limitation It Solves and Its Comparison with SOTA

Our proposed solution directly resolves the fundamental architectural gaps present in existing literature:

  

```
                                      Key Architectural Improvements
                                      
  Consensus Fallacy Solved        ──► Replaces Inter-Model Agreement with Direct Passage Entailment [source: 1]
  Runaway Token Costs Solved      ──► Replaces Infinite Loops with Hard Cap (N=3) + Uncertainty Escalation [source: 1]
  Drafting Disconnect Solved      ──► Adapts Classification Logic into Active Generative Synthesis Loop [source: 1]
  Unmeasured Verifier Risk Solved ──► Evaluates Critic Reliability via Seeded-Error Benchmark (Catch/False Pos) [source: 1]
```

## 1. Elimination of the "Consensus Fallacy"

- **Problem Solved:** Traditional debate frameworks (Du et al., Yang et al.) assume that if multiple agents agree, the output is factually correct. Shared pre-training blind spots defeat this assumption.
    
      
    
- **Our Solution:** Our Critic verifies claims strictly against tagged text passages retrieved by the Researcher. Agreement between agents is completely removed as a metric of truth.
    
      
    

## 2. Elimination of Runaway Compute & Infinite Loops

- **Problem Solved:** Open-ended debates (Du et al., Tool-MAD) or reinforcement learning zero-tolerance penalties (MARCH) result in unbounded execution loops or massive offline training overhead.
    
      
    
- **Our Solution:** We implement a hard bound ($N=3$ rounds) paired with explicit uncertainty escalation (_"unverified - low confidence"_). This guarantees deterministic cost upper-bounds and predictable execution latency.
    
      
    

## 3. Transition from Short-Claim Classification to Generative Synthesis

- **Problem Solved:** SOTA frameworks like ClaimVerAgents and Tool-MAD act primarily as post-hoc classifiers for short headlines or QA pairs.
    
      
    
- **Our Solution:** We embed claim-level verification inside a generative drafting pipeline, enabling the automatic correction of long-form, multi-document research reports during drafting.
    
      
    

## 4. Direct Evaluation of Verifier Reliability

- **Problem Solved:** Existing literature assumes the verifier is infallible and fails to report verifier error rates.
    
      
    
- **Our Solution:** We explicitly measure our Critic’s performance using a **seeded-error test harness** (deliberately corrupting drafts with wrong numbers, swapped attributions, and unsupported statements) to report its exact _Catch Rate_ and _False Positive Rate_.
    
      
    

## Direct SOTA Comparison Matrix

|**Feature / Metric**|**Du et al. (2023/24) PDF**|**ClaimVerAgents (2025) PDF**|**Yang et al. (2025) PDF**|**Tool-MAD (2026) PDF**|**MARCH (2026) PDF**|**GSAR (2026) PDF**|**Our Proposed Framework PDF**|
|---|---|---|---|---|---|---|---|
|**Primary Verification Axis**|Inter-Model Consensus|Web Evidence Classification|Multi-Agent Voting|Tool-Augmented Debate|Asymmetric Blind Audit|Typed Evidence Grounding|**Claim-Level Source Grounding**|
|**Task Domain**|Math / QA / Chess|Fake News Detection|Math / MMLU QA|Fact Verification QA|Multi-Hop RAG QA|IT Incident Analysis|**Generative Research Synthesis**|
|**Loop Boundedness Policy**|Open-Ended|Max 3 Retrieval Rounds|Variance Threshold|Max $T$ Rounds|Unbounded / MARL Retries|Explicit $K_{max}$ Budget|**Hard Cap ($N=3$) + Escalation**|
|**Unresolved State Handling**|Forced Consensus|Abstain via NEI|Forced Consensus|Judge Decision|Penalty Trajectory|Degraded Output Banner|**Flagged "Unverified" Output**|
|**Verifier Reliability Measured?**|No|No|No|No|Indirectly (MARL Match)|Yes ($M_4$ Catch Rate)|**Yes (Seeded-Error Test Harness)**|
|**Empirical Baseline Setup**|Single Model vs Debate|Classical vs LLM Baselines|Single vs Multi-LLM|MAD vs MADKE Baselines|SFT vs MARL|Ablation vs Binary|**3-Way: Zero-Shot vs Debate vs Grounded**|

# 6. Limitations of Our Proposed Solution

While our proposed framework resolves major architectural weaknesses in multi-agent factual verification, it possesses specific inherent limitations that must be acknowledged:

  

## 1. Bottleneck Dependency on Retrieval Quality

The entire downstream verification pipeline depends on the Researcher Agent retrieving the correct source passages. If the retrieval module fails to surface the relevant context chunk, the Synthesizer will either lack necessary information or the Critic will correctly flag valid inferences as "unsupported," driving up the rate of escalated "unverified" claims.

  

## 2. Semantic Fuzziness in Claim Extraction and Entailment

Extracting atomic claims programmatically from complex prose prose without losing context is difficult. Furthermore, determining whether a source passage supports a nuanced textual claim remains a fuzzy judgment call. Edge cases involving high-level summaries, implicit logic, or paraphrased technical concepts can cause the Critic to emit false positives (flagging valid statements) or false negatives (missing subtle hallucinations).

  

## 3. Sensitivity to Corpus Boundaries

The system is designed around a chosen, structured document corpus. When applied to open-domain queries that require multi-hop reasoning across vast, unstructured, or highly noisy web data, retrieval noise increases significantly, which can degrade the precision of the Critic’s passage-matching checks.

  

## 4. Tradeoff Between Strictness and Output Completeness

Setting a high verification strictness threshold in the Critic Agent reduces hallucinations, but it increases the risk of over-flagging benign summaries or stylistic transitions. This can result in reports where safe, high-level introductory or concluding statements are needlessly escalated as "unverified - low confidence".