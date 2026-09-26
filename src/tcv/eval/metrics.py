"""Metrics for planted-error runs (ER-2 to ER-4, ER-11).

Two passes per (base draft, condition) feed these:

  * the **clean pass** over the verified base draft → false-alarm rate (FPR)
    by claim type, abstention rate;
  * one **planted pass** per seed → per-error outcomes.

Definitions (architecture §11.2, with the choices below made explicit):

  catch      an *expected* verdict (``SeededError.expected_verdicts``) on any
             claim of any sentence the error names.
  flag       any definite failing verdict there — reported beside the catch
             rate so an incidental flag by a weaker condition is visible
             instead of being defined away.
  abstain    ``uncertain``: neither a catch nor a false alarm, counted apart
             (FR-7.9).
  unscored   an error whose sentences got an ``error`` verdict (the check
             itself failed) is left out of every denominator and counted.
  FPR(T)     failing claims of type T / claims of type T, on the clean pass.
             Measured per *claim*: a sentence has no single type, its claims do.

Rates are never pooled across error classes (ER-2). Confidence intervals are
95% percentile bootstraps over drafts, the unit that varies (ER-11).
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from tcv.schemas import Claim, ClaimType, SeededDraft, Verdict, VerdictKind

CLEAN = "clean"
_NOT_A_FLAG = {VerdictKind.ERROR, VerdictKind.UNCERTAIN}


@dataclass
class ErrorOutcome:
    error_id: str
    error_class: str
    caught: bool
    flagged: bool
    abstained: bool
    unscored: bool
    verdicts: list[str]


@dataclass
class PassScore:
    """One checking pass: a planted draft (seed set) or the clean draft (seed None)."""

    condition: str
    base_id: str
    seed: int | None
    outcomes: list[ErrorOutcome] = field(default_factory=list)
    claims_by_type: dict[str, int] = field(default_factory=dict)  # clean pass only
    failing_by_type: dict[str, int] = field(default_factory=dict)
    abstained_by_type: dict[str, int] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)  # row (class | clean) → verdict → count
    cost_usd: float = 0.0
    n_calls: int = 0


def _by_sentence(verdicts: Sequence[Verdict]) -> dict[str, list[Verdict]]:
    out: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        out[v.sentence_id].append(v)
    return out


def score_planted(condition: str, seeded: SeededDraft, verdicts: Sequence[Verdict],
                  cost_usd: float = 0.0, n_calls: int = 0) -> PassScore:
    by_s = _by_sentence(verdicts)
    score = PassScore(condition=condition, base_id=seeded.base_draft_id, seed=seeded.seed,
                      cost_usd=cost_usd, n_calls=n_calls)
    confusion: dict[str, Counter] = defaultdict(Counter)
    for e in seeded.errors:
        vs = [v for sid in e.sentence_ids for v in by_s.get(sid, [])]
        kinds = [v.kind for v in vs]
        expected = set(e.expected_verdicts)
        unscored = VerdictKind.ERROR in kinds or not kinds
        score.outcomes.append(ErrorOutcome(
            error_id=e.error_id, error_class=e.error_class.value,
            caught=not unscored and any(k in expected for k in kinds),
            flagged=not unscored and any(v.is_failure and v.kind not in _NOT_A_FLAG for v in vs),
            abstained=not unscored and VerdictKind.UNCERTAIN in kinds,
            unscored=unscored, verdicts=[k.value for k in kinds]))
        for k in kinds:
            confusion[e.error_class.value][k.value] += 1
    score.confusion = {row: dict(c) for row, c in confusion.items()}
    return score


def score_clean(condition: str, base_id: str, claims: Sequence[Claim], verdicts: Sequence[Verdict],
                type_of: Mapping[str, ClaimType] | None = None, cost_usd: float = 0.0, n_calls: int = 0) -> PassScore:
    """False alarms on a verified-clean draft, by claim type.

    ``type_of`` maps claim_id → type from a better source (human gold labels,
    or a routing condition's labels for the same claims); by default each
    claim's own type is used (all T1 in condition A).
    """
    verdict_of = {v.claim_id: v for v in verdicts}
    score = PassScore(condition=condition, base_id=base_id, seed=None, cost_usd=cost_usd, n_calls=n_calls)
    total, failing, abst = Counter(), Counter(), Counter()
    confusion = Counter()
    for c in claims:
        v = verdict_of.get(c.claim_id)
        if v is None or v.kind is VerdictKind.ERROR:
            continue
        t = ((type_of or {}).get(c.claim_id) or c.ctype or ClaimType.T1_DIRECT).value
        total[t] += 1
        confusion[v.kind.value] += 1
        if v.kind is VerdictKind.UNCERTAIN:
            abst[t] += 1
        elif v.is_failure:
            failing[t] += 1
    score.claims_by_type, score.failing_by_type, score.abstained_by_type = dict(total), dict(failing), dict(abst)
    score.confusion = {CLEAN: dict(confusion)}
    return score


# ---------------------------------------------------------------- aggregation


@dataclass
class Rate:
    n: int
    k: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None


def _rate(pairs: Sequence[tuple[int, int]], n_boot: int, rng: random.Random) -> Rate:
    """Pooled k/n with a percentile bootstrap over the units that produced each (k, n)."""
    n = sum(p[1] for p in pairs)
    k = sum(p[0] for p in pairs)
    if n == 0:
        return Rate(0, 0, None, None, None)
    boots = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        sn = sum(p[1] for p in sample)
        if sn:
            boots.append(sum(p[0] for p in sample) / sn)
    boots.sort()
    lo = boots[int(0.025 * (len(boots) - 1))] if boots else None
    hi = boots[int(0.975 * (len(boots) - 1))] if boots else None
    return Rate(n=n, k=k, rate=k / n, ci_low=lo, ci_high=hi)


@dataclass
class ConditionReport:
    condition: str
    catch: dict[str, Rate]
    flag: dict[str, Rate]
    abstain_on_errors: dict[str, Rate]
    unscored: dict[str, int]
    fpr: dict[str, Rate]
    abstain_clean: dict[str, Rate]
    confusion: dict[str, dict[str, int]]
    cost_usd: float
    n_calls: int
    n_planted_passes: int
    n_clean_passes: int


def aggregate(scores: Sequence[PassScore], n_boot: int = 2000, seed: int = 0) -> dict[str, ConditionReport]:
    rng = random.Random(seed)
    by_cond: dict[str, list[PassScore]] = defaultdict(list)
    for s in scores:
        by_cond[s.condition].append(s)
    reports = {}
    for cond, passes in sorted(by_cond.items()):
        planted = [p for p in passes if p.seed is not None]
        clean = [p for p in passes if p.seed is None]
        classes = sorted({o.error_class for p in planted for o in p.outcomes}, key=lambda c: int(c[1:]))

        def per_pass(cls: str, attr: str) -> list[tuple[int, int]]:
            out = []
            for p in planted:
                os_ = [o for o in p.outcomes if o.error_class == cls and not o.unscored]
                if os_:
                    out.append((sum(getattr(o, attr) for o in os_), len(os_)))
            return out

        types = sorted({t for p in clean for t in p.claims_by_type})
        confusion: dict[str, Counter] = defaultdict(Counter)
        for p in passes:
            for row, cols in p.confusion.items():
                confusion[row].update(cols)
        reports[cond] = ConditionReport(
            condition=cond,
            catch={c: _rate(per_pass(c, "caught"), n_boot, rng) for c in classes},
            flag={c: _rate(per_pass(c, "flagged"), n_boot, rng) for c in classes},
            abstain_on_errors={c: _rate(per_pass(c, "abstained"), n_boot, rng) for c in classes},
            unscored={c: sum(o.unscored for p in planted for o in p.outcomes if o.error_class == c) for c in classes},
            fpr={t: _rate([(p.failing_by_type.get(t, 0), p.claims_by_type.get(t, 0)) for p in clean
                           if p.claims_by_type.get(t)], n_boot, rng) for t in types},
            abstain_clean={t: _rate([(p.abstained_by_type.get(t, 0), p.claims_by_type.get(t, 0)) for p in clean
                                     if p.claims_by_type.get(t)], n_boot, rng) for t in types},
            confusion={row: dict(c) for row, c in confusion.items()},
            cost_usd=sum(p.cost_usd for p in passes), n_calls=sum(p.n_calls for p in passes),
            n_planted_passes=len(planted), n_clean_passes=len(clean),
        )
    return reports


# ---------------------------------------------------------------- rendering


def _fmt(r: Rate) -> str:
    if r.rate is None:
        return "—"
    return f"{r.rate:.2f} [{r.ci_low:.2f}, {r.ci_high:.2f}] ({r.k}/{r.n})"


def render_markdown(reports: Mapping[str, ConditionReport]) -> str:
    conds = list(reports)
    out = ["## Catch rate per error class", "",
           "An *expected* verdict on the planted sentence. 95% bootstrap CI over drafts; (caught/total).", "",
           "| Class | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    classes = sorted({c for r in reports.values() for c in r.catch}, key=lambda c: int(c[1:]))
    for c in classes:
        out.append(f"| {c} | " + " | ".join(_fmt(reports[k].catch[c]) if c in reports[k].catch else "—"
                                            for k in conds) + " |")
    out += ["", "## Flag rate per error class", "",
            "*Any* definite failing verdict on the planted sentence, whether or not it is the expected one.", "",
            "| Class | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    for c in classes:
        out.append(f"| {c} | " + " | ".join(_fmt(reports[k].flag[c]) if c in reports[k].flag else "—"
                                            for k in conds) + " |")
    types = sorted({t for r in reports.values() for t in r.fpr})
    out += ["", "## False-alarm rate on clean drafts, by claim type", "",
            "| Type | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    for t in types:
        out.append(f"| {t} | " + " | ".join(_fmt(reports[k].fpr[t]) if t in reports[k].fpr else "—"
                                            for k in conds) + " |")
    out += ["", "## Cost and coverage", "", "| | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds),
            "| cost (list price) | " + " | ".join(f"${reports[k].cost_usd:.4f}" for k in conds) + " |",
            "| model calls | " + " | ".join(str(reports[k].n_calls) for k in conds) + " |",
            "| planted / clean passes | " + " | ".join(f"{reports[k].n_planted_passes} / {reports[k].n_clean_passes}"
                                                     for k in conds) + " |",
            "| unscored errors (check failed) | " + " | ".join(str(sum(reports[k].unscored.values()))
                                                             for k in conds) + " |"]
    for k in conds:
        rows = reports[k].confusion
        cols = sorted({v for r in rows.values() for v in r})
        out += ["", f"## Verdict confusion — condition {k}", "", "Claims on planted sentences (by class) and on clean drafts.",
                "", "| | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        order = sorted((r for r in rows if r != CLEAN), key=lambda c: int(c[1:])) + ([CLEAN] if CLEAN in rows else [])
        for r in order:
            out.append(f"| {r} | " + " | ".join(str(rows[r].get(c, 0)) for c in cols) + " |")
    return "\n".join(out) + "\n"


def to_json(reports: Mapping[str, ConditionReport]) -> dict:
    return {k: asdict(v) for k, v in reports.items()}
