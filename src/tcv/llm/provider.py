"""Model providers behind a single interface.

The gateway talks only to ``Provider``. This module is the one place a
provider SDK (Anthropic, Google Gen AI) is imported; the fake provider makes
the whole pipeline testable offline and deterministically. A local-model
provider (the fully-local budget path) would slot in here without any
caller changing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# Requests above this many output tokens are streamed, which avoids SDK HTTP
# timeouts on long generations (the SDK refuses long non-streaming requests).
STREAM_ABOVE_MAX_TOKENS = 16_000

# Models on which server-side refusal fallbacks are enabled by default.
FALLBACK_MODELS = frozenset({"claude-opus-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: str
    user: str
    max_tokens: int
    output_schema: dict | None = None  # JSON schema for structured output
    effort: str | None = None  # low | medium | high | xhigh | max — omit for models without effort


@dataclass
class LLMResponse:
    text: str
    model: str  # model that served the response
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    raw: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def complete(self, req: LLMRequest) -> LLMResponse: ...


class ProviderError(RuntimeError):
    pass


class QuotaExhausted(ProviderError):
    """A quota that will not refill within the run (e.g. a free-tier daily cap).

    Retrying cannot help, so callers should stop the run rather than fail
    item after item.
    """


class AnthropicProvider:
    """Claude via the Anthropic SDK.

    * The system prompt is marked for prompt caching: it carries the stable
      instructions (and, for checks, the shared passages), so repeated calls
      over the same passages read from cache at ~10% of input cost.
    * Structured output uses ``output_config.format``; the response is still
      validated client-side by the gateway.
    * On Claude Opus 5, server-side fallback is enabled (``fallbacks="default"``):
      a request declined by a safety classifier is re-run on the recommended
      fallback model instead of returning a refusal. Opus 5 thinks by default,
      which is left on.
    """

    name = "anthropic"

    def __init__(self, api_key: str | None = None, max_retries: int = 3, timeout: float = 600.0):
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set (copy .env.example to .env and fill it in)")
        self._client = anthropic.Anthropic(api_key=key, max_retries=max_retries, timeout=timeout)

    def _kwargs(self, req: LLMRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": req.user}],
        }
        if req.system:
            kwargs["system"] = [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}]
        output_config: dict[str, Any] = {}
        if req.output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": req.output_schema}
        if req.effort is not None:
            output_config["effort"] = req.effort
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    def complete(self, req: LLMRequest) -> LLMResponse:
        kwargs = self._kwargs(req)
        messages = self._client.messages
        if req.model in FALLBACK_MODELS:
            messages = self._client.beta.messages
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")

        if req.max_tokens > STREAM_ABOVE_MAX_TOKENS:
            with messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        else:
            msg = messages.create(**kwargs)

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        return LLMResponse(
            text=text,
            model=msg.model,
            stop_reason=msg.stop_reason,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            raw={"id": msg.id},
        )


class GeminiProvider:
    """Gemini via the Google Gen AI SDK (Gemini Developer API, API-key auth).

    * The system prompt goes in ``system_instruction``. Gemini caches repeated
      prompt prefixes implicitly (no write cost), so shared passages placed
      first are billed at the cached rate on repeat calls.
    * Structured output uses ``response_json_schema``; the response is still
      validated client-side by the gateway.
    * ``effort`` maps onto Gemini 3's ``thinking_level``. Gemini 2.x models
      take a token budget instead, so effort is rejected for them rather
      than silently ignored.
    * Safety, recitation and prompt blocks are reported as ``refusal`` so the
      gateway never caches them.
    * Retries are handled here rather than by the SDK, because the two 429s
      need opposite treatment: a per-minute quota is waited out, a daily
      quota raises ``QuotaExhausted`` at once. On the free tier every
      attempt counts against the daily cap, so "503 high demand" gets only
      a few, widely spaced retries.
    """

    name = "gemini"

    _EFFORT_TO_LEVEL = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
    _STOP = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}
    _REFUSAL = frozenset({"SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"})
    _TRANSIENT = frozenset({408, 500, 502, 503, 504})

    def __init__(self, api_key: str | None = None, max_retries: int = 3, timeout: float = 600.0,
                 backoff_s: float = 20.0, sleep: Callable[[float], None] | None = None):
        import time

        from google import genai
        from google.genai import errors, types

        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set (copy .env.example to .env and fill it in)")
        self._types, self._errors = types, errors
        self._max_retries, self._backoff_s = max_retries, backoff_s
        self._sleep = sleep or time.sleep
        # SDK-level retries off: see _generate.
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=int(timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1)))

    def _generate(self, req: LLMRequest) -> Any:
        config = self._config(req)
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.models.generate_content(model=req.model, contents=req.user, config=config)
            except self._errors.APIError as e:
                last = attempt == self._max_retries
                if e.code == 429:
                    quota_ids, delay = _quota_details(e)
                    if any("PerDay" in q for q in quota_ids):
                        raise QuotaExhausted(f"{req.model}: daily quota exhausted ({', '.join(quota_ids)}); "
                                             f"it resets at midnight Pacific time") from e
                    if last:
                        raise
                    self._sleep(max(delay or 0.0, self._backoff_s))
                elif e.code in self._TRANSIENT and not last:
                    self._sleep(self._backoff_s * 2 ** attempt)
                else:
                    raise
        raise AssertionError("unreachable")

    def _config(self, req: LLMRequest) -> Any:
        t = self._types
        cfg: dict[str, Any] = {
            "max_output_tokens": req.max_tokens,
            "automatic_function_calling": t.AutomaticFunctionCallingConfig(disable=True),
        }
        if req.system:
            cfg["system_instruction"] = req.system
        if req.output_schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = req.output_schema
        if req.effort is not None:
            if req.model.startswith("gemini-2"):
                raise ProviderError(f"{req.model} takes a thinking budget, not an effort level; drop 'effort'")
            cfg["thinking_config"] = t.ThinkingConfig(thinking_level=self._EFFORT_TO_LEVEL[req.effort])
        return t.GenerateContentConfig(**cfg)

    def complete(self, req: LLMRequest) -> LLMResponse:
        r = self._generate(req)

        cand = r.candidates[0] if r.candidates else None
        if cand is None:
            # The prompt itself was blocked; there is no candidate at all.
            block = getattr(getattr(r, "prompt_feedback", None), "block_reason", None)
            stop, finish = "refusal", f"prompt_blocked:{_enum_name(block)}"
        else:
            finish = _enum_name(cand.finish_reason)
            stop = "refusal" if finish in self._REFUSAL else self._STOP.get(finish, finish.lower() or None)
        parts = (cand.content.parts or []) if cand is not None and cand.content is not None else []
        text = "".join(p.text for p in parts if p.text and not p.thought)

        u = r.usage_metadata
        prompt_tokens = (u.prompt_token_count or 0) if u else 0
        cached = (u.cached_content_token_count or 0) if u else 0
        output = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        return LLMResponse(
            text=text,
            model=r.model_version or req.model,
            stop_reason=stop,
            input_tokens=prompt_tokens - cached,  # prompt_token_count includes the cached part
            output_tokens=output,  # billed at the output rate, thinking included
            cache_read_tokens=cached,
            cache_write_tokens=0,  # implicit caching has no write charge
            raw={"id": r.response_id, "finish_reason": finish,
                 "thoughts_tokens": (u.thoughts_token_count or 0) if u else 0},
        )


def _quota_details(e: Any) -> tuple[list[str], float | None]:
    """Quota ids and the suggested retry delay from a Google 429 error body."""
    body = e.details if isinstance(getattr(e, "details", None), dict) else {}
    quota_ids: list[str] = []
    delay: float | None = None
    for d in body.get("error", {}).get("details", []) or []:
        for v in d.get("violations", []) or []:
            if v.get("quotaId"):
                quota_ids.append(v["quotaId"])
        if isinstance(d.get("retryDelay"), str) and d["retryDelay"].endswith("s"):
            try:
                delay = float(d["retryDelay"][:-1])
            except ValueError:
                pass
    return quota_ids, delay


def _enum_name(v: Any) -> str:
    if v is None:
        return ""
    return getattr(v, "name", None) or str(v)


PROVIDERS = {"anthropic": AnthropicProvider, "gemini": GeminiProvider}


def make_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ProviderError(f"unknown provider {name!r}; expected one of {sorted(PROVIDERS)}") from None


class FakeProvider:
    """Deterministic scripted provider for tests.

    ``responder`` receives the request and returns either a JSON-serialisable
    object (sent back as JSON text) or an ``LLMResponse`` for full control.
    """

    name = "fake"

    def __init__(self, responder: Callable[[LLMRequest], Any]):
        self.responder = responder
        self.requests: list[LLMRequest] = []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        out = self.responder(req)
        if isinstance(out, LLMResponse):
            return out
        text = out if isinstance(out, str) else json.dumps(out)
        return LLMResponse(text=text, model="fake", stop_reason="end_turn",
                           input_tokens=len(req.user) // 4, output_tokens=len(text) // 4)
