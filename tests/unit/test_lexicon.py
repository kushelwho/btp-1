"""Lexical pre-pass tests. These are candidate detectors — the cases below pin
the obvious hits and, just as importantly, the obvious non-hits."""

import pytest

from tcv.checker.lexicon import aggregative_operator, is_discourse, modality
from tcv.schemas import Modality, Operator


@pytest.mark.parametrize("text, op", [
    ("Three of the five surveyed frameworks bound their correction loop.", Operator.COUNT),
    ("Two out of six papers report a false-positive rate.", Operator.COUNT),
    ("Unlike Du et al., MARCH blinds the checker to the original answer.", Operator.CONTRAST),
    ("The trend from 2023 to 2026 is toward bounded recovery.", Operator.TREND),
    ("Tool-MAD outperforms MADKE on all four benchmarks.", Operator.COMPARISON),
    ("None of the reviewed systems measures verifier error.", Operator.UNIVERSAL),
    ("This approach consistently improves factual accuracy.", Operator.UNIVERSAL),
    ("Most of the frameworks rely on an LLM judge.", Operator.PROPORTION),
    ("At least one framework trains its checker with reinforcement learning.", Operator.EXISTENTIAL),
    # lex-v2: cues the first pilot draft used and lex-v1 missed
    ("These systems structure verification through three primary architectural designs.", Operator.COUNT),
    ("The literature splits into two broad families of methods.", Operator.COUNT),
    ("In contrast, modular pipelines decompose claim validation into sequential roles.", Operator.CONTRAST),
    ("Frameworks differ substantially in how they source factual evidence.", Operator.CONTRAST),
    ("By contrast, GSAR keeps a refusal channel.", Operator.CONTRAST),
    ("GSAR similarly deploys specialist agents to collect evidence.", Operator.COMPARISON),
    ("Compared with debate, pipelines need fewer calls.", Operator.COMPARISON),
    ("Each framework applies distinct evaluation logic.", Operator.UNIVERSAL),
    ("Early debate frameworks rely on the internal knowledge of the model.", Operator.UNIVERSAL),
    ("To handle ambiguity, recent multi-agent frameworks incorporate explicit abstention.", Operator.UNIVERSAL),
    ("Many verification systems rely on a single judge.", Operator.PROPORTION),
])
def test_aggregative_markers(text, op):
    assert aggregative_operator(text) is op


@pytest.mark.parametrize("text", [
    "MARCH trains the checker with reinforcement learning.",
    "One of the most cited results comes from Du et al.",  # "one of the most" is not a count
    "GSAR reports a catch rate on FEVER.",
    "The checker sees only the cited passage.",
    # single-paper sentences from the first pilot draft — counts of parts, not of works
    "MARCH uses three agents.",
    "Tool-MAD structures debate between two heterogeneous debaters overseen by a Judge agent.",
    "Tool-MAD evaluates debater responses at each round using two quantitative metrics from RAGAS.",
    "ClaimVerAgents filters retrieved snippets using a curated blacklist of 1,044 unreliable sources.",
    "ClaimVerAgents divides verification across a Web Search Agent, a Decision Agent, and an Explanation Agent.",
    "MARCH resolves this through deliberate information asymmetry.",
])
def test_plain_single_source_claims_are_not_aggregative(text):
    assert aggregative_operator(text) is None


@pytest.mark.parametrize("text, expected", [
    ("We now turn to the question of retrieval quality.", True),
    ("This section reviews prior work.", True),
    ("In summary, bounded loops are common.", True),
    ("Debate improves factual accuracy on six benchmarks.", False),
])
def test_discourse_detection(text, expected):
    assert is_discourse(text) is expected


@pytest.mark.parametrize("text, m", [
    ("These results may suggest that retrieval is the bottleneck.", Modality.SUGGESTS),
    ("This may demonstrate a general effect.", Modality.SUGGESTS),  # hedge dominates
    ("The authors demonstrate a 5.5% improvement.", Modality.DEMONSTRATES),
    ("This proves that consensus is unreliable.", Modality.PROVES),
    ("GSAR reports a catch rate.", Modality.SHOWS),
    ("The pattern indicates a shift toward budgets.", Modality.INDICATES),
    ("MARCH uses three agents.", Modality.NONE),
])
def test_modality(text, m):
    assert modality(text) is m
