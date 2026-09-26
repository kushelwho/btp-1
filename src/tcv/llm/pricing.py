"""List prices, USD per million tokens (checked 2026-09-26).

Used for the budget kill-switch and for the cost columns in every results
table. On a free tier the real charge is zero, but the ledger still records
the list price so cost columns stay comparable. An unknown model raises rather than pricing at zero — a silent zero
would let an unpriced model bypass the budget entirely.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float  # per MTok, uncached input
    output: float  # per MTok

    @property
    def cache_read(self) -> float:
        return self.input * 0.1

    @property
    def cache_write(self) -> float:  # 5-minute TTL
        return self.input * 1.25


PRICES: dict[str, Price] = {
    "claude-opus-5": Price(5.00, 25.00),
    "claude-opus-4-8": Price(5.00, 25.00),  # default server-side fallback target
    "claude-sonnet-5": Price(3.00, 15.00),
    "claude-haiku-4-5": Price(1.00, 5.00),
    # Gemini: output price includes thinking tokens; cached input is 0.1x as above.
    # 3.6–3.8 Flash are on introductory pricing until 2026-12-31 and double on
    # 2027-01-01 ($1.50 / $7.50) — update here if runs continue past that date.
    "gemini-3.8-flash": Price(0.75, 3.75),
    "gemini-3.7-flash": Price(0.75, 3.75),
    "gemini-3.6-flash": Price(0.75, 3.75),
    "gemini-3.5-flash": Price(1.50, 9.00),
    "gemini-3.5-flash-lite": Price(0.30, 2.50),
    "gemini-3.1-flash-lite": Price(0.25, 1.50),
    "gemini-2.5-pro": Price(1.25, 10.00),  # prompts <= 200k tokens
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-2.5-flash-lite": Price(0.10, 0.40),
    "gemma-4-31b-it": Price(0.0, 0.0),  # open weights; no paid price on the Gemini API
    "fake": Price(0.0, 0.0),  # test provider
}


class UnknownModelPrice(KeyError):
    pass


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0,
             batch: bool = False) -> float:
    if model not in PRICES and ":" in model and "/" not in model:
        return 0.0  # an Ollama tag ("qwen3:8b"): a local model, no per-call charge
    try:
        p = PRICES[model]
    except KeyError:
        raise UnknownModelPrice(f"no list price for {model!r}; add it to tcv/llm/pricing.py") from None
    total = (input_tokens * p.input + output_tokens * p.output
             + cache_read * p.cache_read + cache_write * p.cache_write) / 1_000_000
    return total * (0.5 if batch else 1.0)
