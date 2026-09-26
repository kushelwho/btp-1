"""Planted errors (ER-1): corrupt a clean draft in known ways, at known places.

Each generator takes one sentence and returns a corruption, or ``None`` when
the sentence offers nothing to corrupt in that way. ``inject`` walks the
error classes, tries sentences in a seeded random order, and records a
``SeededError`` (ground truth) for every change:

  * reproducible — the same (base draft, seed) always gives the same errors;
  * at most one error per sentence, ~8 per draft;
  * which verdicts count as a *catch* is fixed here, per class, before any
    checker exists to be measured against it.

Rule-based generators cover E1–E8 and E10. E9 (two claims contradicting each
other) needs fluent new text: pairs written by a person are read from a
file now; a model-written generator can be added later. E11 (omission) is
a stretch goal and not built.

The generators aim for *realistic* corruptions, but rules can misfire —
E7 especially. The team sanity-checks a sample before results count.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tcv.checker.lexicon import modality
from tcv.eval.base import BaseDraft
from tcv.schemas import (Citation, Draft, ErrorClass, Modality, Passage, SeededDraft, SeededError, Sentence,
                         VerdictKind)

GENERATOR_VERSION = "seed-v1"

V = VerdictKind
# Which verdicts count as catching each class. Fixed before any mechanism is built.
EXPECTED: dict[ErrorClass, tuple[VerdictKind, ...]] = {
    ErrorClass.E1_NUMERIC: (V.CONTRADICTED, V.UNSUPPORTED),
    ErrorClass.E2_ATTRIBUTION: (V.MISATTRIBUTED, V.UNSUPPORTED),
    ErrorClass.E3_INSERTION: (V.UNSUPPORTED, V.CONTRADICTED),
    ErrorClass.E4_CONTRADICTION: (V.CONTRADICTED, V.UNSUPPORTED),
    ErrorClass.E5_OVERGENERALIZE: (V.COUNTEREXAMPLE_FOUND, V.PARTIALLY_SUPPORTED, V.UNSUPPORTED, V.CONTRADICTED),
    ErrorClass.E6_COUNT: (V.PARTIALLY_SUPPORTED, V.CONTRADICTED, V.UNSUPPORTED),
    ErrorClass.E7_FALSE_CONTRAST: (V.COUNTEREXAMPLE_FOUND, V.CONTRADICTED, V.UNSUPPORTED),
    ErrorClass.E8_TREND: (V.PARTIALLY_SUPPORTED, V.CONTRADICTED, V.UNSUPPORTED),
    ErrorClass.E9_INTERNAL: (V.INTERNALLY_INCONSISTENT,),
    ErrorClass.E10_HEDGE_STRIP: (V.OVERCLAIM,),
}

RULE_BASED = (ErrorClass.E1_NUMERIC, ErrorClass.E2_ATTRIBUTION, ErrorClass.E3_INSERTION,
              ErrorClass.E4_CONTRADICTION, ErrorClass.E5_OVERGENERALIZE, ErrorClass.E6_COUNT,
              ErrorClass.E7_FALSE_CONTRAST, ErrorClass.E8_TREND, ErrorClass.E10_HEDGE_STRIP)

INSERTED_ID_BASE = 9000  # inserted sentences get ids r<round>s9000, s9001, … — never a real draft id


# ---------------------------------------------------------------- shared helpers


@dataclass
class Corruption:
    """What a generator proposes for one sentence."""

    text: str | None = None  # new text for the sentence (same id); None = unchanged
    citations: tuple[str, ...] | None = None  # new citations (E2); None = unchanged
    insert: Sentence | None = None  # a new sentence placed after this one (E3, E9)
    note: str = ""


@dataclass
class Context:
    draft: Draft
    passages: dict[str, Passage]
    rng: random.Random
    entities: list[str]
    _next_insert: int = INSERTED_ID_BASE
    e9_pairs: list[dict] = field(default_factory=list)

    def new_sentence_id(self) -> str:
        sid = f"r{self.draft.round}s{self._next_insert:04d}"
        self._next_insert += 1
        return sid

    def previous(self, s: Sentence) -> Sentence | None:
        same = [x for x in self.draft.sentences if x.section == s.section]
        i = same.index(s)
        return same[i - 1] if i > 0 else None


_ENTITY_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b")
_NOT_ENTITIES = {
    "LLM", "LLMs", "RAG", "API", "APIs", "NLI", "CoT", "RL", "PPO", "QA", "AI", "MAD", "NLP", "GPT", "JSON", "F1",
    "ID", "IDs", "URL", "PDF", "NEI", "SOTA", "RAGAS", "SFT", "RLHF", "LM", "LMs", "MoE",
}


def entities_in(text: str) -> list[str]:
    """System and paper names: tokens with two or more capitals (MARCH, GSAR, Tool-MAD, ClaimVerAgents)."""
    out = []
    for m in _ENTITY_TOKEN.finditer(text):
        tok = m.group()
        if sum(ch.isupper() for ch in tok) >= 2 and tok not in _NOT_ENTITIES and tok not in out:
            out.append(tok)
    return out


def _replace_first(pattern: re.Pattern, text: str, repl: Callable[[re.Match], str]) -> str | None:
    m = pattern.search(text)
    if not m:
        return None
    return text[:m.start()] + repl(m) + text[m.end():]


def _keep_case(original: str, new: str) -> str:
    return new[:1].upper() + new[1:] if original[:1].isupper() else new


# ---------------------------------------------------------------- E1 numbers


_NUMBER = re.compile(r"(?<![\w.\-])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\-]|\.\d)")
_REFERENCE_WORD = re.compile(r"(?:section|table|figure|fig\.|equation|eq\.|appendix|step|round|stage|phase|"
                             r"version|v)\s*$", re.I)


def _perturb(num: str, rng: random.Random) -> str:
    if "," in num:
        n = int(num.replace(",", ""))
        return f"{n * rng.choice([2, 10]):,}"
    if "." in num:
        whole, dec = num.split(".")
        value = float(num) * rng.choice([0.7, 0.8, 1.2, 1.3])
        return f"{value:.{len(dec)}f}"
    n = int(num)
    if 1900 <= n <= 2099:  # a year
        return str(n + rng.choice([-2, -1, 1, 2]))
    if n <= 10:
        return str(n + 1 if n <= 1 or rng.random() < 0.5 else n - 1)
    return str(rng.choice([n + max(1, round(n * 0.2)), max(1, n - max(1, round(n * 0.2))), n * 10]))


_SCALE = re.compile(r"\b(?:0|1)\s*[–-]\s*(?:5|7|10|100)\b|\[\s*0\s*,\s*1\s*\]")  # rating scales, [0, 1]
_MATH = re.compile(r"\$[^$]+\$")


def _tier(num: str) -> int:
    """Prefer substantive figures: 0 = results (decimals, multi-digit), 1 = years, 2 = small integers."""
    if "." in num or "," in num:
        return 0
    n = int(num)
    if 1900 <= n <= 2099:
        return 1
    return 0 if n >= 10 else 2


def gen_numeric(s: Sentence, ctx: Context) -> Corruption | None:
    candidates = [m for m in _NUMBER.finditer(s.text)
                  if not _REFERENCE_WORD.search(s.text[:m.start()])
                  and m.group(1) != "0"
                  and not any(sc.start() <= m.start() < sc.end()
                              for sc in (*_SCALE.finditer(s.text), *_MATH.finditer(s.text)))]
    if not candidates:
        return None
    best = min(_tier(m.group(1)) for m in candidates)
    m = ctx.rng.choice([m for m in candidates if _tier(m.group(1)) == best])
    new = _perturb(m.group(1), ctx.rng)
    if new == m.group(1):
        return None
    return Corruption(text=s.text[:m.start(1)] + new + s.text[m.end(1):], note=f"{m.group(1)} → {new}")


# ---------------------------------------------------------------- E2 citation swap


def gen_attribution(s: Sentence, ctx: Context) -> Corruption | None:
    if not s.citations:
        return None
    cited_docs = {c.chunk_id.split("#")[0] for c in s.citations}
    foreign = sorted(cid for cid, p in ctx.passages.items() if p.chunk.doc_id not in cited_docs)
    if not foreign:
        return None
    new = ctx.rng.choice(foreign)
    return Corruption(citations=(new,), note=f"citations → {new} (a different paper)")


# ---------------------------------------------------------------- E3 fabricated insertion


_BENCHMARKS = ["FEVER", "TruthfulQA", "HotpotQA", "StrategyQA", "HaluEval", "SciFact", "GSM8K", "MMLU"]
_INSERT_TEMPLATES = [
    "{E} additionally reports a {p}% reduction in hallucination rate on the {B} benchmark.",
    "{E} was also evaluated on {B}, where it outperformed every baseline by {p} points.",
    "In a follow-up ablation, {E} found that removing its verifier lowered accuracy on {B} by {p}%.",
    "{E} further reports that its approach cuts inference cost by {p}% relative to single-agent prompting on {B}.",
]


def gen_insertion(s: Sentence, ctx: Context) -> Corruption | None:
    if not s.citations:
        return None
    names = entities_in(s.text) or []
    if not names:
        return None
    cited_text = " ".join(ctx.passages[c.chunk_id].chunk.text for c in s.citations if c.chunk_id in ctx.passages)
    all_text = " ".join(p.chunk.text for p in ctx.passages.values())
    unused = [b for b in _BENCHMARKS if b not in all_text] or [b for b in _BENCHMARKS if b not in cited_text]
    if not unused:
        return None
    text = ctx.rng.choice(_INSERT_TEMPLATES).format(E=ctx.rng.choice(names), B=ctx.rng.choice(unused),
                                                      p=ctx.rng.randint(7, 29))
    new = Sentence(sentence_id=ctx.new_sentence_id(), section=s.section, text=text, citations=s.citations[:1])
    return Corruption(insert=new, note="fabricated sentence citing a real passage")


# ---------------------------------------------------------------- E4 contradiction


_ANTONYMS = [
    ("increases", "decreases"), ("increase", "decrease"), ("increased", "decreased"), ("increasing", "decreasing"),
    ("higher", "lower"), ("improves", "degrades"), ("improved", "degraded"), ("improve", "degrade"),
    ("outperforms", "underperforms"), ("outperformed", "underperformed"), ("reduces", "increases"),
    ("reduced", "increased"), ("better", "worse"), ("succeeds", "fails"), ("supports", "contradicts"),
    ("enables", "prevents"), ("strengthens", "weakens"), ("maximizes", "minimizes"), ("maximize", "minimize"),
    ("includes", "excludes"), ("before", "after"), ("independently", "jointly"), ("explicitly", "implicitly"),
]
_ANTONYM_MAP = {**{a: b for a, b in _ANTONYMS}, **{b: a for a, b in _ANTONYMS if b not in {x for x, _ in _ANTONYMS}}}
_ANTONYM_RE = re.compile(r"\b(" + "|".join(sorted(_ANTONYM_MAP, key=len, reverse=True)) + r")\b", re.I)
_DROP_NEGATION = [(re.compile(r"\b(does|do|did|is|are|was|were|can|will|should) not\b", re.I), r"\1"),
                  (re.compile(r"\bcannot\b", re.I), "can"), (re.compile(r"\bnever\b", re.I), "always")]
_AUX = re.compile(r"\b(is|are|was|were|can|will|should)\b(?! not)")
_VERB_S = re.compile(r"\b(uses|relies|employs|requires|trains|achieves|reports|introduces|assigns|computes|"
                     r"decomposes|verifies|retrieves|generates|evaluates|produces|applies|combines|incorporates|"
                     r"treats|checks|measures|detects|relies)\b")


def _base_form(verb: str) -> str:
    if verb.endswith("ies"):
        return verb[:-3] + "y"
    if verb.endswith(("sses", "shes", "ches", "xes")):
        return verb[:-2]
    return verb[:-1]


def gen_contradiction(s: Sentence, ctx: Context) -> Corruption | None:
    t = s.text
    for pat, repl in _DROP_NEGATION:
        if pat.search(t):
            return Corruption(text=pat.sub(repl, t, count=1), note="negation removed")
    new = _replace_first(_ANTONYM_RE, t, lambda m: _keep_case(m.group(), _ANTONYM_MAP[m.group().lower()]))
    if new:
        return Corruption(text=new, note="antonym swap")
    new = _replace_first(_AUX, t, lambda m: f"{m.group()} not")
    if new:
        return Corruption(text=new, note="negated auxiliary")
    new = _replace_first(_VERB_S, t, lambda m: f"does not {_base_form(m.group())}")
    if new:
        return Corruption(text=new, note="negated verb")
    return None


# ---------------------------------------------------------------- E5 over-generalisation


_UNIVERSAL_ALREADY = re.compile(r"\b(all|every|each|always|consistently|never|none|invariably|universally)\b", re.I)
_QUANTIFIER = re.compile(r"\b(some|several|many|a few|certain|most)\b(?= (?:of the |[a-z-]+))", re.I)
_FREQUENCY = {"often": "always", "sometimes": "always", "frequently": "always", "typically": "invariably",
              "generally": "universally", "usually": "always", "occasionally": "always", "commonly": "always"}
_FREQUENCY_RE = re.compile(r"\b(" + "|".join(_FREQUENCY) + r")\b", re.I)
_GAIN_VERB = re.compile(r"\b(improves|outperforms|reduces|increases|enhances|mitigates|achieves|yields|surpasses|"
                        r"lowers|boosts)\b")


def gen_overgeneralize(s: Sentence, ctx: Context) -> Corruption | None:
    t = s.text
    if _UNIVERSAL_ALREADY.search(t):
        return None
    new = _replace_first(_QUANTIFIER, t, lambda m: _keep_case(m.group(), "all"))
    if new:
        return Corruption(text=new, note="quantifier → all")
    new = _replace_first(_FREQUENCY_RE, t, lambda m: _keep_case(m.group(), _FREQUENCY[m.group().lower()]))
    if new:
        return Corruption(text=new, note="frequency → always")
    new = _replace_first(_GAIN_VERB, t, lambda m: f"consistently {m.group()}")
    if new:
        return Corruption(text=new, note="'consistently' inserted")
    return None


# ---------------------------------------------------------------- E6 miscount


_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
_WORD_NUM = {w: i for i, w in enumerate(_WORDS)}
_NUMTOK = r"(?:" + "|".join(_WORDS) + r"|\d+)"
_K_OF_N = re.compile(rf"\b({_NUMTOK}) (?:out )?of (?:the )?(?:[\w-]+ ){{0,2}}?({_NUMTOK})\b", re.I)
_KINDS = (r"(?:approaches|frameworks|designs|architectures|families|categories|types|strategies|paradigms|"
          r"mechanisms|methods|systems|papers|studies|works|pipelines|benchmarks|datasets)")
_N_KINDS = re.compile(rf"\b({_NUMTOK}) (?:[\w-]+ ){{0,2}}{_KINDS}\b", re.I)


def _to_int(tok: str) -> int:
    return _WORD_NUM[tok.lower()] if tok.lower() in _WORD_NUM else int(tok)


def _like(tok: str, n: int) -> str:
    if tok.isdigit():
        return str(n)
    word = _WORDS[n] if n < len(_WORDS) else str(n)
    return _keep_case(tok, word)


def gen_count(s: Sentence, ctx: Context) -> Corruption | None:
    m = _K_OF_N.search(s.text)
    if m:
        k, n = _to_int(m.group(1)), _to_int(m.group(2))
        options = [x for x in (k - 1, k + 1) if 0 <= x <= n and x != k]
        if options:
            new = ctx.rng.choice(options)
            return Corruption(text=s.text[:m.start(1)] + _like(m.group(1), new) + s.text[m.end(1):],
                              note=f"{k} of {n} → {new} of {n}")
    m = _N_KINDS.search(s.text)
    if m:
        k = _to_int(m.group(1))
        if k >= 2:
            new = ctx.rng.choice([k - 1, k + 1]) if k > 2 else k + 1
            return Corruption(text=s.text[:m.start(1)] + _like(m.group(1), new) + s.text[m.end(1):],
                              note=f"{k} → {new}")
    return None


# ---------------------------------------------------------------- E7 false contrast


_LIKE_EXAMPLE = re.compile(rf"^((?:[\w-]+ ){{0,3}}{_KINDS}) like ([A-Z][\w-]*),? ")
_SIMILAR_CUE = re.compile(r"(?:,\s*)?\b(similarly|likewise|in the same way)\b,?\s*", re.I)
_BOTH = re.compile(r"^Both ([A-Z][\w-]*) and ([A-Z][\w-]*) (\w+)\b")
_IRREGULAR_3P = {"are": "is", "have": "has", "do": "does", "were": "was"}


def _third_person(verb: str) -> str:
    """'use' → 'uses', 'rely' → 'relies', 'are' → 'is' — for "Both A and B <verb>" → "A <verb>s"."""
    if verb in _IRREGULAR_3P:
        return _IRREGULAR_3P[verb]
    if verb.endswith("y") and len(verb) > 1 and verb[-2] not in "aeiou":
        return verb[:-1] + "ies"
    if verb.endswith(("s", "sh", "ch", "x", "z")):
        return verb + "es"
    return verb + "s"


def gen_false_contrast(s: Sentence, ctx: Context) -> Corruption | None:
    """A sentence that asserts similarity becomes a contrast: "Unlike B, A …".

    Only sentences that *state* a similarity are used, so the contrast is
    false by the draft's own account; the previous sentence supplies B.
    """
    m = _BOTH.match(s.text)
    if m and entities_in(m.group(1)) and entities_in(m.group(2)):
        a, b, verb = m.group(1), m.group(2), m.group(3)
        return Corruption(text=f"Unlike {b}, {a} {_third_person(verb)}{s.text[m.end():]}",
                          note=f"'both {a} and {b}' → 'unlike {b}'")
    m = _LIKE_EXAMPLE.search(s.text)
    if m and entities_in(m.group(2)) and not _SIMILAR_CUE.search(s.text):
        # "Dynamic debate frameworks like Tool-MAD integrate X" names Tool-MAD as one of them,
        # so "Unlike Tool-MAD, dynamic debate frameworks integrate X" is false by the draft's own account.
        group = s.text[:m.start()] + m.group(1)
        rest = s.text[m.end():]
        return Corruption(text=f"Unlike {m.group(2)}, {group[:1].lower() + group[1:]} {rest}",
                          note=f"'{m.group(1).split()[-1]} like {m.group(2)}' → 'unlike {m.group(2)}'")
    if not _SIMILAR_CUE.search(s.text):
        return None
    prev = ctx.previous(s)
    here = set(entities_in(s.text))
    others = [e for e in (entities_in(prev.text) if prev else []) if e not in here]
    if not here or not others:
        return None
    b = others[0]
    stripped = _SIMILAR_CUE.sub(" ", s.text, count=1).strip()
    stripped = re.sub(r"\s{2,}", " ", stripped)
    first = stripped.split()[0] if stripped.split() else ""
    body = stripped if entities_in(first) else stripped[:1].lower() + stripped[1:]
    return Corruption(text=f"Unlike {b}, {body}", note=f"similarity to {b} → contrast")


# ---------------------------------------------------------------- E8 reversed / invented trend


_TEMPORAL = re.compile(r"\b(?:19|20)\d\d\b|\b(recent(?:ly)?|over time|evolv\w*|trend\w*|shift\w*|increasingly|"
                       r"earlier|newer|since|historically|progressively|over the (?:past|last))\b", re.I)
_TREND_FLIP = [
    ("increasingly", "decreasingly"), ("more and more", "fewer and fewer"), ("toward", "away from"),
    ("towards", "away from"), ("has grown", "has declined"), ("have grown", "have declined"), ("rising", "falling"),
    ("growing", "declining"), ("increased", "decreased"), ("increases", "decreases"), ("increase", "decrease"),
    ("gained", "lost"), ("more", "less"),
]
_TREND_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a, _ in _TREND_FLIP) + r")\b", re.I)
_TREND_MAP = dict(_TREND_FLIP)
_INVENT = re.compile(rf"\b((?:[Rr]ecent|[Nn]ewer|[Ll]ater|[Mm]odern) (?:[\w-]+ ){{0,3}}"
                     rf"(?:{_KINDS}|literature|work|research)) (?!increasingly)([a-z]+)\b")


def gen_trend(s: Sentence, ctx: Context) -> Corruption | None:
    if not _TEMPORAL.search(s.text):
        return None  # without a temporal frame this is just E4 again
    new = _replace_first(_TREND_RE, s.text, lambda m: _keep_case(m.group(), _TREND_MAP[m.group().lower()]))
    if new:
        return Corruption(text=new, note="trend direction reversed")
    m = _INVENT.search(s.text)
    if m:
        return Corruption(text=s.text[:m.start(2)] + "increasingly " + s.text[m.start(2):], note="trend invented")
    return None


# ---------------------------------------------------------------- E10 strengthened wording


_STRENGTHEN = [
    (re.compile(r"\b(may|might|could) (\w+)", re.I), lambda m: f"will definitively {m.group(2)}"),
    (re.compile(r"\b(suggests|indicates|reports|shows|finds|observes) that\b", re.I), lambda m: "proves that"),
    (re.compile(r"\b(suggest|indicate|report|show|find|observe) that\b", re.I), lambda m: "prove that"),
    (re.compile(r"\b(suggested|indicated|reported|showed|found|observed) that\b", re.I), lambda m: "proved that"),
    (re.compile(r"\bappears to\b", re.I), lambda m: "is proven to"),
    (re.compile(r"\bappear to\b", re.I), lambda m: "are proven to"),
    (re.compile(r"\bseems to\b", re.I), lambda m: "is proven to"),
    (re.compile(r"\b(possibly|perhaps|likely)\b", re.I), lambda m: "conclusively"),
    (re.compile(r"\b(shows|shown|showed)\b", re.I),
     lambda m: {"shows": "proves", "shown": "proven", "showed": "proved"}[m.group().lower()]),
]


_RESULT_CUE = re.compile(r"\b(improv\w*|outperform\w*|reduc\w*|increas\w*|achiev\w*|accuracy|gains?|"
                         r"effective\w*|mitigat\w*|prevent\w*|eliminat\w*|enhanc\w*|superior|better)\b", re.I)
_OVERCLAIM_LEAD = "It is conclusively established that "


def gen_hedge_strip(s: Sentence, ctx: Context) -> Corruption | None:
    """Raise wording strength by ≥2 steps on the ladder, fact left intact.

    Real drafts hedge rarely, so besides stripping hedges ("may improve" →
    "will definitively improve"), a plain statement of a *result* gets an
    overclaiming lead-in — "none" (rank 3) → "proves" (rank 5).
    """
    before = modality(s.text)
    for pat, repl in _STRENGTHEN:
        new = _replace_first(pat, s.text, lambda m: _keep_case(m.group(), repl(m)))
        if new and modality(new).rank >= before.rank + 2:
            return Corruption(text=new, note=f"strength {before.value} → {modality(new).value}")
    if before is Modality.NONE and s.citations and _RESULT_CUE.search(s.text):
        body = s.text if entities_in(s.text.split()[0]) else s.text[:1].lower() + s.text[1:]
        new = _OVERCLAIM_LEAD + body
        if modality(new).rank >= before.rank + 2:
            return Corruption(text=new, note=f"strength none → {modality(new).value} (overclaiming lead-in)")
    return None


# ---------------------------------------------------------------- E9 from a file


def load_e9_pairs(path: str | Path) -> dict[str, list[dict]]:
    """``{base_id: [{target, contradicting, cite, after?}, ...]}`` — written by a person."""
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def gen_internal(s: Sentence, ctx: Context) -> Corruption | None:
    for pair in ctx.e9_pairs:
        if pair["target"] != s.sentence_id or pair.get("_used"):
            continue
        pair["_used"] = True
        after_id = pair.get("after") or ctx.draft.sentences[-1].sentence_id
        section = ctx.draft.by_id(after_id).section
        new = Sentence(sentence_id=ctx.new_sentence_id(), section=section, text=pair["contradicting"].strip(),
                       citations=(Citation(chunk_id=pair["cite"]),))
        return Corruption(insert=new, note=f"contradicts {s.sentence_id}; placed after {after_id}")
    return None


GENERATORS: dict[ErrorClass, Callable[[Sentence, Context], Corruption | None]] = {
    ErrorClass.E1_NUMERIC: gen_numeric,
    ErrorClass.E2_ATTRIBUTION: gen_attribution,
    ErrorClass.E3_INSERTION: gen_insertion,
    ErrorClass.E4_CONTRADICTION: gen_contradiction,
    ErrorClass.E5_OVERGENERALIZE: gen_overgeneralize,
    ErrorClass.E6_COUNT: gen_count,
    ErrorClass.E7_FALSE_CONTRAST: gen_false_contrast,
    ErrorClass.E8_TREND: gen_trend,
    ErrorClass.E9_INTERNAL: gen_internal,
    ErrorClass.E10_HEDGE_STRIP: gen_hedge_strip,
}


# ---------------------------------------------------------------- injection


def _render(s: Sentence) -> str:
    return s.text + "".join(f" [[{c.chunk_id}]]" for c in s.citations)


@dataclass
class InjectReport:
    seeded: SeededDraft
    not_applicable: list[ErrorClass]  # classes no sentence of this draft could take
    notes: dict[str, str]  # error_id → what the generator did


def inject(base: BaseDraft, seed: int, classes: Sequence[ErrorClass] = RULE_BASED, max_errors: int = 8,
           e9_pairs: dict[str, list[dict]] | None = None) -> InjectReport:
    """Plant up to ``max_errors`` errors, at most one per sentence and one per class.

    Classes are tried in a seeded random order so that, when a draft offers
    more classes than ``max_errors``, which ones are dropped varies by seed
    rather than always being the last few.
    """
    rng = random.Random(f"{base.base_id}|{seed}|{GENERATOR_VERSION}")
    passages = {p.chunk_id: p for pool in base.pools for p in pool.passages()}
    ctx = Context(draft=base.draft, passages=passages, rng=rng,
                  entities=entities_in(" ".join(s.text for s in base.draft.sentences)),
                  e9_pairs=[dict(p) for p in (e9_pairs or {}).get(base.base_id, [])])
    order = list(classes)
    rng.shuffle(order)

    used: set[str] = set()
    changed: dict[str, Sentence] = {}
    inserts: dict[str, list[Sentence]] = {}
    errors: list[SeededError] = []
    notes: dict[str, str] = {}
    not_applicable: list[ErrorClass] = []
    for cls in order:
        if len(errors) >= max_errors:
            break
        candidates = [s for s in base.draft.sentences if s.sentence_id not in used]
        rng.shuffle(candidates)
        for s in candidates:
            c = GENERATORS[cls](s, ctx)
            if c is None:
                continue
            eid = f"{base.base_id}-s{seed}-e{len(errors):02d}"
            if c.insert is not None:
                anchor = s.sentence_id if cls is not ErrorClass.E9_INTERNAL else next(
                    (p["after"] for p in ctx.e9_pairs if p["target"] == s.sentence_id and p.get("after")),
                    base.draft.sentences[-1].sentence_id)
                inserts.setdefault(anchor, []).append(c.insert)
                named = (s.sentence_id, c.insert.sentence_id) if cls is ErrorClass.E9_INTERNAL else (c.insert.sentence_id,)
                original, corrupted = ("" if cls is not ErrorClass.E9_INTERNAL else _render(s)), _render(c.insert)
            else:
                new = s.model_copy(update={
                    "text": c.text if c.text is not None else s.text,
                    "citations": tuple(Citation(chunk_id=x) for x in c.citations) if c.citations is not None
                    else s.citations})
                changed[s.sentence_id] = new
                named = (s.sentence_id,)
                original, corrupted = _render(s), _render(new)
            used.add(s.sentence_id)
            errors.append(SeededError(error_id=eid, error_class=cls, sentence_ids=named, original=original,
                                      corrupted=corrupted, expected_verdicts=EXPECTED[cls]))
            notes[eid] = c.note
            break
        else:
            not_applicable.append(cls)

    sentences: list[Sentence] = []
    for s in base.draft.sentences:
        sentences.append(changed.get(s.sentence_id, s))
        sentences.extend(inserts.get(s.sentence_id, []))
    draft = base.draft.model_copy(update={"sentences": tuple(sentences)})
    seeded = SeededDraft(base_draft_id=base.base_id, draft=draft, errors=tuple(errors),
                         generator_version=GENERATOR_VERSION, seed=seed)
    return InjectReport(seeded=seeded, not_applicable=not_applicable, notes=notes)
