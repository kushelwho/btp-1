"""The single path from the rest of the system to a model.

Every model call goes through ``Gateway``, which is why caching, logging,
batching, and the budget kill-switch exist exactly once:

    render prompt → cache key → cache hit? ──yes──► return, cost 0, logged
                                    │ no
                                    ▼
                          budget exceeded? ──yes──► BudgetExceeded
                                    │ no
                                    ▼
                  provider call → validate output → cost → cache → ledger
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, create_model, field_validator

from tcv.schemas import Usage

from .cache import ResponseCache, cache_key
from .ledger import Ledger, LedgerEntry
from .pricing import cost_usd
from .prompts import Prompt
from .provider import LLMRequest, LLMResponse, Provider
from .schema_compat import to_structured_output_schema

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- configuration


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    max_tokens: int = 8000
    effort: str | None = None

    @field_validator("model")
    @classmethod
    def _pinned(cls, v: str) -> str:
        if "latest" in v or "preview" in v or v.endswith("-"):
            raise ValueError(f"model id must be pinned, got {v!r}")
        return v

    @field_validator("effort")
    @classmethod
    def _effort(cls, v: str | None) -> str | None:
        if v is not None and v not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unknown effort level {v!r}")
        return v


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = "anthropic"
    roles: dict[str, RoleConfig]
    budget_usd_per_run: float | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in {"anthropic", "gemini"}:
            raise ValueError(f"unknown provider {v!r}")
        return v


def load_models_config(path: str | Path) -> ModelsConfig:
    with open(path, encoding="utf-8") as f:
        return ModelsConfig.model_validate(yaml.safe_load(f))


# ---------------------------------------------------------------- results and errors


class GatewayError(RuntimeError):
    def __init__(self, message: str, call_id: str | None = None):
        super().__init__(message)
        self.call_id = call_id


class BudgetExceeded(GatewayError):
    pass


class RefusalError(GatewayError):
    pass


class OutputValidationError(GatewayError):
    pass


@dataclass
class CallResult(Generic[T]):
    value: T | None  # validated structured output, or None for free text
    text: str
    call_id: str
    usage: Usage
    cached: bool
    model: str


@dataclass
class ItemResult(Generic[T]):
    """Outcome for one item of a batched call. Exactly one of value/error is set."""

    value: T | None
    error: str | None
    call_id: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------- gateway


@dataclass
class Gateway:
    provider: Provider
    models: ModelsConfig
    cache: ResponseCache
    ledger: Ledger
    run_id: str | None = None
    budget_usd: float | None = None
    spent: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        if self.budget_usd is None:
            self.budget_usd = self.models.budget_usd_per_run

    # -- budget

    @property
    def budget_exceeded(self) -> bool:
        return self.budget_usd is not None and self.spent.cost_usd >= self.budget_usd

    # -- single call

    def call(self, role: str, prompt: Prompt, variables: dict[str, Any], out: type[T] | None = None,
             n_items: int = 1) -> CallResult[T]:
        rc = self.models.roles[role]
        system, user = prompt.render({k: _as_text(v) for k, v in variables.items()})
        schema = to_structured_output_schema(out.model_json_schema()) if out is not None else None
        key = cache_key(model=rc.model, effort=rc.effort, max_tokens=rc.max_tokens, prompt=prompt.ref,
                        prompt_sha256=prompt.sha256, system=system, user=user, schema=schema)
        call_id = self.ledger.next_call_id()
        base = dict(call_id=call_id, run_id=self.run_id, role=role, requested_model=rc.model, prompt=prompt.ref,
                    prompt_sha256=prompt.sha256, cache_key=key, n_items=n_items)

        hit = self.cache.get(key)
        if hit is not None:
            value = _validate(out, hit["text"]) if out is not None else None
            self.ledger.append(LedgerEntry(ts=Ledger.now(), model=hit["model"], local_cache_hit=True,
                                           status="ok", **base))
            self.spent = self.spent + Usage(n_calls=1)
            return CallResult(value=value, text=hit["text"], call_id=call_id, usage=Usage(n_calls=1),
                              cached=True, model=hit["model"])

        if self.budget_exceeded:
            self.ledger.append(LedgerEntry(ts=Ledger.now(), model=rc.model, status="budget",
                                           error=f"budget ${self.budget_usd:.2f} reached", **base))
            raise BudgetExceeded(f"run budget ${self.budget_usd:.2f} reached "
                                 f"(spent ${self.spent.cost_usd:.4f})", call_id)

        t0 = time.monotonic()
        try:
            resp = self.provider.complete(LLMRequest(model=rc.model, system=system, user=user,
                                                     max_tokens=rc.max_tokens, output_schema=schema,
                                                     effort=rc.effort))
        except Exception as e:  # network, auth, rate limit after SDK retries, ...
            self.ledger.append(LedgerEntry(ts=Ledger.now(), model=rc.model, status="error",
                                           latency_s=time.monotonic() - t0, error=repr(e)[:500], **base))
            raise GatewayError(f"{prompt.ref}: provider call failed: {e}", call_id) from e
        latency = time.monotonic() - t0
        usage = _usage(resp, latency)
        self.spent = self.spent + usage
        tokens = dict(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                      cache_read_tokens=resp.cache_read_tokens, cache_write_tokens=resp.cache_write_tokens,
                      cost_usd=usage.cost_usd, latency_s=latency)

        if resp.stop_reason == "refusal":
            self.ledger.append(LedgerEntry(ts=Ledger.now(), model=resp.model, status="refusal", **tokens, **base))
            raise RefusalError(f"{prompt.ref}: model declined the request", call_id)

        value = None
        if out is not None:
            try:
                value = _validate(out, resp.text)
            except OutputValidationError as e:
                self.ledger.append(LedgerEntry(ts=Ledger.now(), model=resp.model, status="invalid_output",
                                               error=str(e)[:500], **tokens, **base))
                e.call_id = call_id
                raise

        self.cache.put(key, {"text": resp.text, "model": resp.model, "stop_reason": resp.stop_reason,
                             "prompt": prompt.ref, **{k: v for k, v in tokens.items() if k != "latency_s"}})
        self.ledger.append(LedgerEntry(ts=Ledger.now(), model=resp.model, status="ok", **tokens, **base))
        return CallResult(value=value, text=resp.text, call_id=call_id, usage=usage, cached=False, model=resp.model)

    # -- batched call

    def call_batch(self, role: str, prompt: Prompt, items: list[dict[str, Any]], out_item: type[T],
                   shared: dict[str, Any] | None = None, per_request: int = 15) -> list[ItemResult[T]]:
        """Send many items per request; return one result per item, in input order.

        The prompt must contain ``${items}``; it receives a JSON array of the
        items, each tagged with an ``index``. The model returns one result per
        index. A failed request fails only its own items, and an item the
        model skipped or duplicated fails alone — never the whole batch.
        """
        if per_request < 1:
            raise ValueError("per_request must be >= 1")
        wrapper = _batch_model(out_item)
        results: list[ItemResult[T] | None] = [None] * len(items)

        for start in range(0, len(items), per_request):
            idxs = list(range(start, min(start + per_request, len(items))))
            payload = json.dumps([{"index": i, **items[i]} for i in idxs], ensure_ascii=False, indent=1)
            try:
                res = self.call(role, prompt, {**(shared or {}), "items": payload}, out=wrapper, n_items=len(idxs))
            except BudgetExceeded:
                raise  # the whole run must stop, not just this batch
            except GatewayError as e:
                for i in idxs:
                    results[i] = ItemResult(value=None, error=str(e), call_id=e.call_id)
                continue

            seen: dict[int, list[Any]] = {}
            for r in res.value.results:
                seen.setdefault(r.index, []).append(r)
            for i in idxs:
                got = seen.get(i, [])
                if len(got) == 1:
                    fields = {k: getattr(got[0], k) for k in out_item.model_fields}
                    results[i] = ItemResult(value=out_item(**fields), error=None, call_id=res.call_id)
                else:
                    why = "missing from model output" if not got else f"returned {len(got)} times"
                    results[i] = ItemResult(value=None, error=f"item {i} {why}", call_id=res.call_id)
        return results  # type: ignore[return-value]


# ---------------------------------------------------------------- helpers


def _as_text(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, BaseModel):
        return v.model_dump_json(indent=1)
    return json.dumps(v, ensure_ascii=False, indent=1, default=str)


def _validate(out: type[T], text: str) -> T:
    try:
        return out.model_validate_json(text)
    except ValidationError as e:
        raise OutputValidationError(f"output did not match {out.__name__}: {e.error_count()} error(s); "
                                    f"first: {e.errors()[0]['msg']}") from e


def _usage(resp: LLMResponse, latency: float) -> Usage:
    return Usage(
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cache_read_tokens=resp.cache_read_tokens,
        cache_write_tokens=resp.cache_write_tokens,
        cost_usd=cost_usd(resp.model, resp.input_tokens, resp.output_tokens,
                          resp.cache_read_tokens, resp.cache_write_tokens),
        wall_seconds=latency,
        n_calls=1,
    )


_BATCH_MODELS: dict[type, type] = {}


def _batch_model(out_item: type[T]) -> type[BaseModel]:
    """{"results": [ {index: int, ...out_item fields} ]} — built once per item type."""
    if out_item not in _BATCH_MODELS:
        indexed = create_model(f"{out_item.__name__}Indexed", __base__=out_item, index=(int, ...))
        _BATCH_MODELS[out_item] = create_model(f"{out_item.__name__}Batch",
                                               __config__=ConfigDict(extra="forbid"),
                                               results=(list[indexed], ...))
    return _BATCH_MODELS[out_item]
