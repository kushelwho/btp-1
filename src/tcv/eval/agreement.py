"""Agreement between two labellers: Cohen's κ and a confusion table.

Used twice: in Phase 4 for the two human annotators' claim types (AR-2), and
before switching checker models, to compare a new judge's verdicts with an
existing judge's on the *same* claims.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class Agreement:
    n: int
    observed: float  # raw agreement
    kappa: float | None  # None when chance agreement is 1 (a single label everywhere)
    table: dict[str, dict[str, int]]  # a-label → b-label → count


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> Agreement:
    if len(a) != len(b):
        raise ValueError("label lists differ in length")
    n = len(a)
    if n == 0:
        return Agreement(0, 0.0, None, {})
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / (n * n)
    kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    table: dict[str, dict[str, int]] = {}
    for x, y in zip(a, b):
        table.setdefault(x, {}).setdefault(y, 0)
        table[x][y] += 1
    return Agreement(n=n, observed=observed, kappa=kappa, table=table)


def render(agr: Agreement, a_name: str, b_name: str) -> str:
    labels = sorted({*agr.table, *(y for row in agr.table.values() for y in row)})
    k = "—" if agr.kappa is None else f"{agr.kappa:.2f}"
    lines = [f"{agr.n} items · raw agreement {agr.observed:.2f} · Cohen's κ {k}", "",
             f"{a_name} ↓ / {b_name} →  " + "  ".join(f"{x:>14}" for x in labels)]
    for x in labels:
        lines.append(f"{x:>22}  " + "  ".join(f"{agr.table.get(x, {}).get(y, 0):>14}" for y in labels))
    return "\n".join(lines)
