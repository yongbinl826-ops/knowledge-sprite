import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.http_clients import managed_client, start_http_pool, stop_http_pool
from backend.app.llm import LLM_OBSERVER, complete_json


@pytest.mark.asyncio
async def test_lifespan_reuses_and_isolates_clients_then_closes():
    settings = Settings(llm_api_key="test-key")
    pool = start_http_pool()
    try:
        async with managed_client(settings, "llm", timeout_seconds=10, trust_env=True) as first:
            pass
        async with managed_client(settings, "llm", timeout_seconds=30, trust_env=True) as again:
            assert again is first and not again.is_closed
        async with managed_client(replace(settings, llm_api_key="other-key"), "llm", timeout_seconds=10, trust_env=True) as other:
            assert other is not first
        async with managed_client(settings, "search:tavily", timeout_seconds=10) as search:
            assert search is not first
        assert "test-key" not in repr(pool.clients)
    finally:
        await stop_http_pool(pool)
    assert first.is_closed and other.is_closed and search.is_closed


@pytest.mark.asyncio
async def test_nested_lifespans_do_not_close_each_others_pool():
    first, second = start_http_pool(), start_http_pool()
    assert first is second
    async with managed_client(Settings(), "search:tavily", timeout_seconds=10) as client:
        pass
    await stop_http_pool(second)
    assert not client.is_closed
    await stop_http_pool(first)
    assert client.is_closed


@pytest.mark.asyncio
async def test_standalone_client_closes_without_global_pool():
    async with managed_client(Settings(), "llm", timeout_seconds=10) as client:
        assert not client.is_closed
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": 123, "completion_tokens": 17, "total_tokens": 140,
      "prompt_tokens_details": {"cached_tokens": 100}}, (123, 17, 140, 100)),
    ({"prompt_tokens": 123, "completion_tokens": 17, "prompt_cache_hit_tokens": 80}, (123,17,None,80)),
    ({"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "42"}, (None,None,None,None)),
    (None, (None,None,None,None)),
])
async def test_actual_usage_and_hashed_request_id_are_observed(usage, expected):
    observed=[]
    token = LLM_OBSERVER.set(observed.append)
    def response(_):
        return httpx.Response(200, headers={"x-request-id":"private-request-id"}, json={
            "choices":[{"message":{"content":'{"ok":true}'}, "finish_reason":"stop"}], "usage":usage})
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            assert await complete_json(Settings(), "json", {}, client) == {"ok": True}
            assert not client.is_closed
    finally:
        LLM_OBSERVER.reset(token)
    assert tuple(observed[0]["usage"][key] for key in (
        "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens")) == expected
    assert observed[0]["duration_seconds"] >= 0 and observed[0]["status"] == "completed"
    assert len(observed[0]["request_id_sha256"]) == 64
    assert "private-request-id" not in json.dumps(observed)


@pytest.mark.asyncio
async def test_failure_and_cancellation_emit_once_without_secret_or_retry():
    for error in [httpx.ConnectTimeout("sensitive-key"), asyncio.CancelledError()]:
        observed=[]; calls=[]
        token=LLM_OBSERVER.set(observed.append)
        def fail(_):
            calls.append(1)
            raise error
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
                with pytest.raises(type(error)):
                    await complete_json(Settings(), "json", {}, client)
        finally:
            LLM_OBSERVER.reset(token)
        assert len(calls)==len(observed)==1
        assert "sensitive-key" not in json.dumps(observed)
        assert observed[0]["usage"]["input_tokens"] is None
