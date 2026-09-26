"""Model gateway tests — offline, using the fake provider.

The gateway is the only route to a model, so these pin down the properties
every later phase relies on: identical calls are free after the first, the
budget stops new spending, failures are never cached, and one bad item in a
batch never fails its neighbours.
"""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from tcv.llm.cache import ResponseCache, cache_key
from tcv.llm.gateway import (
    BudgetExceeded,
    Gateway,
    GatewayError,
    ModelsConfig,
    OutputValidationError,
    RefusalError,
    RoleConfig,
)
from tcv.llm.ledger import Ledger
from tcv.llm.pricing import UnknownModelPrice, cost_usd
from tcv.llm.prompts import PromptError, load_prompt, parse_prompt
from tcv.llm.provider import AnthropicProvider, FakeProvider, GeminiProvider, LLMRequest, LLMResponse
from tcv.llm.schema_compat import to_structured_output_schema

PROMPT = parse_prompt("test/echo", 1, """
<<<system>>>
You check claims. Output JSON like {"verdict": "..."}.
<<<user>>>
Claim: ${claim}
""")

BATCH_PROMPT = parse_prompt("test/batch", 1, """
<<<system>>>
Check each item.
<<<user>>>
${items}
""")


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: str


def models(budget=None) -> ModelsConfig:
    return ModelsConfig(roles={"judge": RoleConfig(model="claude-haiku-4-5", max_tokens=100)},
                        budget_usd_per_run=budget)


def make_gateway(tmp_path, responder, budget=None):
    provider = FakeProvider(responder)
    gw = Gateway(provider=provider, models=models(budget), cache=ResponseCache(tmp_path / "cache"),
                 ledger=Ledger(tmp_path / "calls.jsonl"), run_id="run_000000000001")
    return gw, provider


def priced(text: str, in_tok: int = 1000, out_tok: int = 100) -> LLMResponse:
    return LLMResponse(text=text, model="claude-haiku-4-5", stop_reason="end_turn",
                       input_tokens=in_tok, output_tokens=out_tok)


# ---------------------------------------------------------------- prompts


def test_prompt_renders_placeholders_and_leaves_json_braces_alone():
    system, user = PROMPT.render({"claim": "debate helps"})
    assert '{"verdict": "..."}' in system
    assert user == "Claim: debate helps"


def test_prompt_missing_variable_is_an_error():
    with pytest.raises(PromptError):
        PROMPT.render({})


def test_prompt_requires_user_section():
    with pytest.raises(PromptError):
        parse_prompt("x", 1, "<<<system>>>\nonly system")


def test_load_prompt_by_versioned_ref(tmp_path):
    (tmp_path / "checker" / "entail").mkdir(parents=True)
    (tmp_path / "checker" / "entail" / "v2.md").write_text("<<<user>>>\nhello ${x}")
    p = load_prompt("checker/entail@2", root=tmp_path)
    assert (p.ref, p.render({"x": "y"})[1]) == ("checker/entail@2", "hello y")
    with pytest.raises(PromptError):
        load_prompt("checker/entail", root=tmp_path)


# ---------------------------------------------------------------- schema compat, pricing, cache, ledger


def test_schema_compat_strips_constraints_but_keeps_fields_named_like_keywords():
    class Inner(BaseModel):
        title: str  # a *field* named "title" must survive
        n: int = 3

    class Outer(BaseModel):
        items: list[Inner]
        pattern: str | None = None

    s = to_structured_output_schema(Outer.model_json_schema())
    inner = s["$defs"]["Inner"]
    assert set(inner["properties"]) == {"title", "n"}
    assert inner["additionalProperties"] is False and set(inner["required"]) == {"title", "n"}
    assert "default" not in json.dumps(inner["properties"]["n"])
    assert "pattern" in s["properties"] and s["additionalProperties"] is False


def test_cost_uses_list_prices_and_refuses_unknown_models():
    assert cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == pytest.approx(18.0)
    assert cost_usd("claude-sonnet-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.3)
    assert cost_usd("claude-sonnet-5", 1_000_000, 0, batch=True) == pytest.approx(1.5)
    with pytest.raises(UnknownModelPrice):
        cost_usd("claude-mystery-9", 1, 1)


def test_cache_key_is_order_insensitive_and_content_sensitive():
    assert cache_key(a=1, b=2) == cache_key(b=2, a=1)
    assert cache_key(a=1, b=2) != cache_key(a=1, b=3)


def test_ledger_call_ids_continue_across_instances(tmp_path):
    from tcv.llm.ledger import LedgerEntry

    led = Ledger(tmp_path / "calls.jsonl")
    for _ in range(2):
        cid = led.next_call_id()
        led.append(LedgerEntry(call_id=cid, ts=Ledger.now(), run_id=None, role="judge", model="m",
                               requested_model="m", prompt="p@1", prompt_sha256="s", cache_key="k",
                               n_items=1, status="ok"))
    assert Ledger(tmp_path / "calls.jsonl").next_call_id() == "c_000003"  # resume-safe


# ---------------------------------------------------------------- gateway: single calls


def test_call_returns_validated_output_and_logs_cost(tmp_path):
    gw, _ = make_gateway(tmp_path, lambda r: priced('{"verdict": "supported"}'))
    res = gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    assert res.value == Verdict(verdict="supported") and not res.cached
    assert res.usage.cost_usd > 0
    entry = gw.ledger.entries()[-1]
    assert (entry.status, entry.call_id, entry.prompt) == ("ok", res.call_id, "test/echo@1")


def test_identical_call_is_served_from_cache_at_zero_cost(tmp_path):
    gw, provider = make_gateway(tmp_path, lambda r: priced('{"verdict": "supported"}'))
    first = gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    second = gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    assert len(provider.requests) == 1
    assert second.cached and second.usage.cost_usd == 0 and second.value == first.value
    assert gw.ledger.entries()[-1].local_cache_hit


def test_cache_survives_a_new_gateway(tmp_path):
    gw1, p1 = make_gateway(tmp_path, lambda r: priced('{"verdict": "x"}'))
    gw1.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    gw2, p2 = make_gateway(tmp_path, lambda r: priced('{"verdict": "x"}'))
    assert gw2.call("judge", PROMPT, {"claim": "c"}, out=Verdict).cached
    assert len(p2.requests) == 0  # resumed sweep re-bills nothing


def test_edited_prompt_misses_the_cache(tmp_path):
    gw, provider = make_gateway(tmp_path, lambda r: priced('{"verdict": "x"}'))
    gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    edited = parse_prompt("test/echo", 1, "<<<system>>>\nStricter.\n<<<user>>>\nClaim: ${claim}")
    gw.call("judge", edited, {"claim": "c"}, out=Verdict)
    assert len(provider.requests) == 2


def test_budget_stops_new_calls_but_not_cache_hits(tmp_path):
    gw, provider = make_gateway(tmp_path, lambda r: priced('{"verdict": "x"}', in_tok=200_000), budget=0.10)
    gw.call("judge", PROMPT, {"claim": "a"}, out=Verdict)  # costs $0.20 > budget
    assert gw.budget_exceeded
    with pytest.raises(BudgetExceeded):
        gw.call("judge", PROMPT, {"claim": "b"}, out=Verdict)
    assert len(provider.requests) == 1, "no provider call after the budget is reached"
    assert gw.ledger.entries()[-1].status == "budget"
    assert gw.call("judge", PROMPT, {"claim": "a"}, out=Verdict).cached  # free replays still allowed


def test_refusal_raises_and_is_not_cached(tmp_path):
    gw, provider = make_gateway(tmp_path, lambda r: LLMResponse(text="", model="claude-haiku-4-5",
                                                                stop_reason="refusal"))
    for _ in range(2):
        with pytest.raises(RefusalError):
            gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    assert len(provider.requests) == 2
    assert gw.ledger.entries()[-1].status == "refusal"


def test_invalid_output_raises_and_is_not_cached(tmp_path):
    gw, provider = make_gateway(tmp_path, lambda r: priced('{"wrong_field": 1}'))
    with pytest.raises(OutputValidationError) as exc:
        gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    assert exc.value.call_id is not None
    with pytest.raises(OutputValidationError):
        gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    assert len(provider.requests) == 2


def test_provider_failure_is_logged_and_wrapped(tmp_path):
    def boom(req):
        raise ConnectionError("network down")

    gw, _ = make_gateway(tmp_path, boom)
    with pytest.raises(GatewayError):
        gw.call("judge", PROMPT, {"claim": "c"}, out=Verdict)
    entry = gw.ledger.entries()[-1]
    assert entry.status == "error" and "network down" in entry.error


# ---------------------------------------------------------------- gateway: batches


def _batch_responder(skip=(), dupe=(), fail_containing=None):
    def respond(req: LLMRequest):
        items = json.loads(req.user)
        if fail_containing is not None and any(it["index"] == fail_containing for it in items):
            raise TimeoutError("request timed out")
        out = []
        for it in items:
            if it["index"] in skip:
                continue
            out.append({"index": it["index"], "verdict": f"v{it['index']}"})
            if it["index"] in dupe:
                out.append({"index": it["index"], "verdict": "again"})
        return priced(json.dumps({"results": out}))
    return respond


def test_batch_packs_items_and_preserves_order(tmp_path):
    gw, provider = make_gateway(tmp_path, _batch_responder())
    items = [{"claim": f"c{i}"} for i in range(7)]
    res = gw.call_batch("judge", BATCH_PROMPT, items, Verdict, per_request=3)
    assert len(provider.requests) == 3
    assert [r.value.verdict for r in res] == [f"v{i}" for i in range(7)]
    assert all(r.ok for r in res)


def test_batch_isolates_skipped_and_duplicated_items(tmp_path):
    gw, _ = make_gateway(tmp_path, _batch_responder(skip={2}, dupe={4}))
    res = gw.call_batch("judge", BATCH_PROMPT, [{"claim": f"c{i}"} for i in range(6)], Verdict, per_request=6)
    assert [r.ok for r in res] == [True, True, False, True, False, True]
    assert "missing" in res[2].error and "2 times" in res[4].error


def test_batch_failed_request_only_fails_its_own_items(tmp_path):
    gw, _ = make_gateway(tmp_path, _batch_responder(fail_containing=4))
    res = gw.call_batch("judge", BATCH_PROMPT, [{"claim": f"c{i}"} for i in range(7)], Verdict, per_request=3)
    assert [r.ok for r in res] == [True, True, True, False, False, False, True]


def test_batch_propagates_budget_exhaustion(tmp_path):
    def respond(req):
        items = json.loads(req.user)
        return priced(json.dumps({"results": [{"index": it["index"], "verdict": "v"} for it in items]}),
                      in_tok=200_000)

    gw, _ = make_gateway(tmp_path, respond, budget=0.10)
    with pytest.raises(BudgetExceeded):
        gw.call_batch("judge", BATCH_PROMPT, [{"claim": f"c{i}"} for i in range(6)], Verdict, per_request=2)


# ---------------------------------------------------------------- config validation


@pytest.mark.parametrize("kwargs", [{"model": "claude-latest"}, {"model": "gemini-3.1-pro-preview"},
                                    {"model": "claude-sonnet-5", "effort": "ultra"}])
def test_role_config_rejects_floating_models_and_unknown_effort(kwargs):
    with pytest.raises(ValueError):
        RoleConfig(**kwargs)


@pytest.mark.parametrize("path", ["configs/models.yaml", "configs/models.anthropic.yaml"])
def test_repo_models_config_is_valid(path):
    from tcv.llm.gateway import load_models_config
    from tcv.llm.pricing import PRICES

    cfg = load_models_config(path)
    assert {"synthesizer", "economy", "judge"} <= cfg.roles.keys()
    assert all(r.model in PRICES for r in cfg.roles.values()), "every configured model needs a list price"


# ---------------------------------------------------------------- Anthropic request shape (no network)


def _stub_message(model):
    return SimpleNamespace(
        id="msg_1", model=model, stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text='{"verdict": "ok"}')],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


def _stubbed_provider(monkeypatch):
    prov = AnthropicProvider(api_key="test-key-not-used")
    calls = {}

    def plain(**kw):
        calls["plain"] = kw
        return _stub_message(kw["model"])

    def beta(**kw):
        calls["beta"] = kw
        return _stub_message(kw["model"])

    monkeypatch.setattr(prov._client.messages, "create", plain)
    monkeypatch.setattr(prov._client.beta.messages, "create", beta)
    return prov, calls


def test_anthropic_request_shape_for_judge(monkeypatch):
    prov, calls = _stubbed_provider(monkeypatch)
    schema = to_structured_output_schema(Verdict.model_json_schema())
    resp = prov.complete(LLMRequest(model="claude-sonnet-5", system="SYS", user="USR", max_tokens=100,
                                    output_schema=schema, effort="high"))
    kw = calls["plain"]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}  # stable prefix is cached
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": schema}, "effort": "high"}
    assert "beta" not in calls and resp.text == '{"verdict": "ok"}'


def test_anthropic_opus_uses_server_side_fallback(monkeypatch):
    prov, calls = _stubbed_provider(monkeypatch)
    prov.complete(LLMRequest(model="claude-opus-5", system="S", user="U", max_tokens=100))
    kw = calls["beta"]
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "output_config" not in kw  # no schema, no effort → field omitted, not sent empty


def test_anthropic_provider_requires_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from tcv.llm.provider import ProviderError

    with pytest.raises(ProviderError):
        AnthropicProvider()


# ---------------------------------------------------------------- Gemini request shape (no network)


def _gemini_response(finish="STOP", parts=None, usage=None, blocked=None, model="gemini-3.8-flash"):
    parts = parts if parts is not None else [SimpleNamespace(text='{"verdict": "ok"}', thought=None)]
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish), content=SimpleNamespace(parts=parts))
    return SimpleNamespace(
        candidates=[] if blocked else [cand],
        prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name=blocked)) if blocked else None,
        model_version=model, response_id="resp_1",
        usage_metadata=SimpleNamespace(**{"prompt_token_count": 100, "cached_content_token_count": None,
                                          "candidates_token_count": 20, "thoughts_token_count": 30,
                                          **(usage or {})}),
    )


def _stubbed_gemini(monkeypatch, response=None):
    prov = GeminiProvider(api_key="test-key-not-used", sleep=lambda s: None)
    calls = {}

    def generate(**kw):
        calls.update(kw)
        return response or _gemini_response()

    monkeypatch.setattr(prov._client.models, "generate_content", generate)
    return prov, calls


def test_gemini_request_shape_for_judge(monkeypatch):
    prov, calls = _stubbed_gemini(monkeypatch)
    schema = to_structured_output_schema(Verdict.model_json_schema())
    resp = prov.complete(LLMRequest(model="gemini-3.8-flash", system="SYS", user="USR", max_tokens=100,
                                    output_schema=schema, effort="high"))
    cfg = calls["config"]
    assert calls["model"] == "gemini-3.8-flash" and calls["contents"] == "USR"
    assert cfg.system_instruction == "SYS" and cfg.max_output_tokens == 100
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == schema
    assert cfg.thinking_config.thinking_level.name == "HIGH"
    assert cfg.automatic_function_calling.disable is True
    assert resp.text == '{"verdict": "ok"}' and resp.stop_reason == "end_turn"


def test_gemini_free_text_request_sends_no_schema_or_thinking_config(monkeypatch):
    prov, calls = _stubbed_gemini(monkeypatch)
    prov.complete(LLMRequest(model="gemini-3.1-flash-lite", system="", user="U", max_tokens=50))
    cfg = calls["config"]
    assert cfg.response_json_schema is None and cfg.thinking_config is None and cfg.system_instruction is None


def test_gemini_usage_separates_cached_input_and_bills_thinking_as_output(monkeypatch):
    prov, _ = _stubbed_gemini(monkeypatch, _gemini_response(usage={"cached_content_token_count": 60}))
    r = prov.complete(LLMRequest(model="gemini-3.8-flash", system="S", user="U", max_tokens=50))
    assert (r.input_tokens, r.cache_read_tokens, r.output_tokens) == (40, 60, 50)
    assert cost_usd(r.model, r.input_tokens, r.output_tokens, r.cache_read_tokens) == pytest.approx(
        (40 * 0.75 + 50 * 3.75 + 60 * 0.075) / 1e6)


def test_gemini_drops_thought_parts_from_text(monkeypatch):
    parts = [SimpleNamespace(text="thinking...", thought=True), SimpleNamespace(text="answer", thought=None)]
    prov, _ = _stubbed_gemini(monkeypatch, _gemini_response(parts=parts))
    assert prov.complete(LLMRequest(model="gemini-3.8-flash", system="", user="U", max_tokens=50)).text == "answer"


@pytest.mark.parametrize("response", [
    _gemini_response(finish="SAFETY", parts=[]),
    _gemini_response(finish="RECITATION", parts=[]),
    _gemini_response(blocked="PROHIBITED_CONTENT"),
])
def test_gemini_blocks_are_reported_as_refusals(monkeypatch, response):
    prov, _ = _stubbed_gemini(monkeypatch, response)
    r = prov.complete(LLMRequest(model="gemini-3.8-flash", system="", user="U", max_tokens=50))
    assert r.stop_reason == "refusal" and r.text == ""


def test_gemini_refusal_is_not_cached_by_the_gateway(tmp_path, monkeypatch):
    prov, _ = _stubbed_gemini(monkeypatch, _gemini_response(finish="SAFETY", parts=[]))
    models = ModelsConfig(provider="gemini", roles={"judge": RoleConfig(model="gemini-3.8-flash")})
    gw = Gateway(provider=prov, models=models, cache=ResponseCache(tmp_path / "c"), ledger=Ledger(tmp_path / "l"))
    with pytest.raises(RefusalError):
        gw.call("judge", parse_prompt("t", 1, "<<<user>>>\nhi"), {})
    assert not list((tmp_path / "c").rglob("*.json"))


def test_gemini_rejects_effort_on_budget_based_models(monkeypatch):
    from tcv.llm.provider import ProviderError

    prov, _ = _stubbed_gemini(monkeypatch)
    with pytest.raises(ProviderError):
        prov.complete(LLMRequest(model="gemini-2.5-pro", system="", user="U", max_tokens=50, effort="high"))


def test_gemini_provider_requires_a_key(monkeypatch):
    from tcv.llm.provider import ProviderError

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        GeminiProvider()


def test_models_config_rejects_unknown_provider():
    with pytest.raises(ValueError):
        ModelsConfig(provider="agentrouter", roles={})


def _google_error(code, quota_id=None, retry_delay=None):
    from google.genai import errors

    details = []
    if quota_id:
        details.append({"violations": [{"quotaId": quota_id}]})
    if retry_delay:
        details.append({"retryDelay": retry_delay})
    body = {"error": {"code": code, "message": "m", "status": "S", "details": details}}
    return (errors.ClientError if code < 500 else errors.ServerError)(code, body)


def _scripted_gemini(monkeypatch, outcomes):
    """Provider whose API returns/raises the given outcomes in order; records sleeps."""
    sleeps = []
    prov = GeminiProvider(api_key="test-key-not-used", max_retries=3, backoff_s=20.0, sleep=sleeps.append)
    seq = iter(outcomes)

    def generate(**kw):
        o = next(seq)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(prov._client.models, "generate_content", generate)
    return prov, sleeps


REQ = LLMRequest(model="gemini-3.8-flash", system="", user="U", max_tokens=50)


def test_gemini_daily_quota_stops_at_once_without_retrying(monkeypatch):
    from tcv.llm.provider import QuotaExhausted

    prov, sleeps = _scripted_gemini(monkeypatch, [
        _google_error(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "2s")])
    with pytest.raises(QuotaExhausted, match="daily quota"):
        prov.complete(REQ)
    assert sleeps == []


def test_gemini_per_minute_quota_is_waited_out(monkeypatch):
    prov, sleeps = _scripted_gemini(monkeypatch, [
        _google_error(429, "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "45s"), _gemini_response()])
    assert prov.complete(REQ).text == '{"verdict": "ok"}'
    assert sleeps == [45.0]  # the server's suggested delay, when longer than our floor


def test_gemini_overload_retries_with_growing_backoff_then_gives_up(monkeypatch):
    from google.genai import errors

    prov, sleeps = _scripted_gemini(monkeypatch, [_google_error(503)] * 4)
    with pytest.raises(errors.ServerError):
        prov.complete(REQ)
    assert sleeps == [20.0, 40.0, 80.0]


def test_gemini_client_errors_are_not_retried(monkeypatch):
    from google.genai import errors

    prov, sleeps = _scripted_gemini(monkeypatch, [_google_error(400)])
    with pytest.raises(errors.ClientError):
        prov.complete(REQ)
    assert sleeps == []
