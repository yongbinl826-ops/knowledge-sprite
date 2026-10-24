import asyncio
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import SearchError, TavilyProvider


def settings():
    return Settings(tavily_api_key="offline-primary", tavily_backup_api_key="offline-backup",
                    search_min_interval_seconds=0, search_max_retries=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [402,432,433])
async def test_explicit_quota_exhaustion_uses_backup_and_keeps_both_request_counts(status):
    seen=[]; reserved=[]
    def response(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(status if seen[-1]=="Bearer offline-primary" else 200,
                              json={"results":[], "usage":{"credits":1}})
    async def reserve():
        reserved.append(1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider=TavilyProvider(settings(),client)
        with provider.query_scope(reserve):
            await provider.search("test","zh",5,["icourse163.org"])
            traces=list(provider.last_requests)
        await provider.search("next","zh",5,["icourse163.org"])
    assert seen==["Bearer offline-primary","Bearer offline-backup","Bearer offline-backup"]
    assert len(reserved)==2
    assert [r["credential_slot"] for r in traces]==["primary","backup"]
    assert traces[0]["error_code"]=="quota_exhausted"
    assert "offline-primary" not in json.dumps(traces) and "offline-backup" not in json.dumps(traces)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401,403,429])
async def test_denial_or_rate_limit_never_rotates_credentials(status):
    seen=[]
    def response(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(status,headers={"retry-after":"120"},json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider=TavilyProvider(settings(),client)
        with pytest.raises(SearchError):
            await provider.search("test","zh",5,[])
    assert seen==["Bearer offline-primary"]


@pytest.mark.asyncio
async def test_both_exhausted_stop_future_queries():
    seen=[]
    def response(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(432,json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider=TavilyProvider(settings(),client)
        for _ in range(2):
            with pytest.raises(SearchError,match="Tavily") as error:
                await provider.search("test","zh",5,[])
            assert error.value.code=="quota_exhausted"
    assert len(seen)==2 and provider.quota_exhausted


@pytest.mark.asyncio
async def test_backup_still_requires_request_budget_before_dispatch():
    seen=[]; calls=0
    def response(request):
        seen.append(request)
        return httpx.Response(432,json={})
    async def reserve():
        nonlocal calls
        calls+=1
        if calls>1:
            raise TimeoutError("budget-ended")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider=TavilyProvider(settings(),client)
        with provider.query_scope(reserve), pytest.raises(TimeoutError):
            await provider.search("test","zh",5,[])
    assert len(seen)==1


@pytest.mark.asyncio
async def test_backup_only_configuration_uses_key_and_reports_no_secret(tmp_path):
    from dataclasses import replace
    from backend.app.db import Store
    from backend.app.service import JobService
    configured = replace(settings(), tavily_api_key="", search_provider="tavily")
    seen = []
    def respond(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = TavilyProvider(configured, client)
        await provider.search("test", "zh", 5, [])
        store = Store(str(tmp_path / "test.sqlite3"))
        try:
            service = JobService(configured, store, provider=provider)
            capabilities = service.capabilities()
            serialized = json.dumps(capabilities)
            assert "offline-backup" not in serialized
            assert '"backup_configured": true' in serialized
            assert provider.auth_mode == "api_key"
        finally:
            store.close()
    assert seen == ["Bearer offline-backup"]
