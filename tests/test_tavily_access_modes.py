"""Offline transport checks; these responses are not live recall evidence."""
import asyncio
import json
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import SearchError, TavilyProvider, build_provider


@pytest.mark.asyncio
async def test_keyless_is_explicit_basic_domain_restricted_and_never_sends_credentials():
    seen = []
    def respond(request):
        seen.append(request)
        assert request.url == "https://api.tavily.com/search"
        assert request.headers["X-Tavily-Access-Mode"] == "keyless"
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        assert body["search_depth"] == "basic" and body["auto_parameters"] is False
        assert body["include_domains"] == ["icourse163.org"]
        assert body["include_domains_mode"] == "restrict"
        assert body["include_answer"] is body["include_raw_content"] is False
        assert body["include_usage"] is True
        return httpx.Response(200, json={"usage": {"credits": 1}, "results": [
            {"title": "Python", "url": "https://www.icourse163.org/course/TEST-123"},
            {"title": "Wrong domain", "url": "https://icourse163.org.example.com/course/123"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = TavilyProvider(Settings(tavily_allow_keyless=True), client)
        rows = await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert len(seen) == len(rows) == 1
    assert provider.last_requests[0]["auth_mode"] == "keyless"
    assert provider.last_requests[0]["api_credits"] == 1
    assert provider.last_requests[0]["filter_counts"]["domain_mismatch"] == 1


@pytest.mark.asyncio
async def test_absent_key_does_not_enable_keyless_implicitly():
    provider = TavilyProvider(Settings())
    with pytest.raises(SearchError) as error:
        await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert error.value.code == "configuration_error"
    assert provider.last_requests == []


@pytest.mark.asyncio
async def test_configured_key_uses_only_bearer_auth_and_never_leaks_it():
    def respond(request):
        assert request.headers["authorization"] == "Bearer offline-secret"
        assert "x-tavily-access-mode" not in request.headers
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = TavilyProvider(Settings(tavily_api_key="offline-secret", tavily_allow_keyless=True), client)
        await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert provider.last_requests[0]["auth_mode"] == "api_key"
    assert "offline-secret" not in str(provider.last_requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401,"access_denied"), (403,"access_denied"),
    (429,"rate_limited"), (402,"quota_exhausted"), (432,"quota_exhausted"), (433,"quota_exhausted")])
async def test_restrictions_stop_later_queries_without_mode_switch(status, code):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after":"120"},
                              json={"error":{"message":"secret do not log"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider=TavilyProvider(Settings(tavily_allow_keyless=True, search_min_interval_seconds=0),client)
        for query in ("first", "second"):
            with pytest.raises(SearchError) as error:
                await provider.search(query, "zh", 5, ["icourse163.org"])
            assert error.value.code==code
            assert "secret" not in str(error.value)
    assert len(calls)==1
    assert "authorization" not in calls[0].headers


@pytest.mark.parametrize("usage", [None, {}, {"credits":True}, {"credits":-1}, {"credits":"secret"}, {"credits":10**400}])
@pytest.mark.asyncio
async def test_usage_is_observed_only_when_numeric(usage):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={"results":[], "usage":usage}))) as client:
        provider=TavilyProvider(Settings(tavily_allow_keyless=True),client)
        await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert "api_credits" not in provider.last_requests[0]


@pytest.mark.asyncio
async def test_keyless_limit_body_extends_cooldown_without_echoing_instructions():
    response=httpx.Response(429,json={"error":{"code":"untrusted-secret", "message":"secret",
        "retry_after_seconds":7200,"next_actions":["buy something"]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:response)) as client:
        provider=TavilyProvider(Settings(tavily_allow_keyless=True),client)
        with pytest.raises(SearchError):
            await provider.search("Python","zh",5,["icourse163.org"])
    assert provider.paused_until-time.monotonic()>7100
    assert provider.last_requests[0]["service_retry_after_seconds"]==7200
    assert "secret" not in str(provider.last_requests) and "buy" not in str(provider.last_requests)


@pytest.mark.asyncio
async def test_queued_request_checks_quota_again_before_network():
    def forbidden(_):
        raise AssertionError("Quota was exhausted before dispatch")
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        provider=TavilyProvider(Settings(tavily_allow_keyless=True,search_min_interval_seconds=0),client)
        await provider._request_start_lock.acquire()
        pending=asyncio.create_task(provider.search("Python","zh",5,["icourse163.org"]))
        await asyncio.sleep(0)
        provider.quota_exhausted=True
        provider._request_start_lock.release()
        with pytest.raises(SearchError) as error:
            await pending
    assert error.value.code=="quota_exhausted" and provider.last_requests==[]


def test_platform_settings_default_to_existing_provider_and_factory_accepts_override():
    old=Settings()
    assert old.search_provider_for("icourse163")==old.search_provider_for("bilibili")=="searxng"
    split=Settings(mooc_search_provider="tavily",bilibili_search_provider="searxng")
    assert split.search_provider_for("icourse163")=="tavily"
    assert split.search_provider_for("bilibili")=="searxng"
    assert split.search_provider_for("other")=="searxng"
    assert build_provider(split,provider_name="tavily").name=="tavily"


@pytest.mark.parametrize("kwargs", [{"mooc_search_provider":"unknown"},
    {"bilibili_search_provider":"official_sitemap"}, {"tavily_allow_keyless":"true"},
    {"search_provider":"official_sitemap","mooc_search_provider":"tavily"}])
def test_bad_platform_configuration_fails_closed(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs).validate()


def test_platform_environment_loading(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER","searxng")
    monkeypatch.setenv("BILIBILI_SEARCH_PROVIDER","searxng")
    monkeypatch.setenv("MOOC_SEARCH_PROVIDER","tavily")
    monkeypatch.setenv("TAVILY_ALLOW_KEYLESS","true")
    settings=Settings.from_env()
    assert settings.search_provider_for("icourse163")=="tavily"
    assert settings.search_provider_for("bilibili")=="searxng"
    assert settings.tavily_allow_keyless is True
