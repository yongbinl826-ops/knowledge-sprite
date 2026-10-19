"""Offline transport checks; mocked search rows are not live recall evidence."""
import asyncio
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import SearchError, SerperProvider, build_provider


@pytest.mark.asyncio
async def test_organic_mapping_keeps_source_urls_domain_scope_and_no_nested_fabrication():
    seen = []
    native = "https://www.icourse163.org/course/TEST-123?tid=456"
    legacy = "https://www.icourse163.org/course/detail.htm?cid=789"

    def response(request):
        seen.append(request)
        assert request.method == "POST" and str(request.url) == "https://google.serper.dev/search"
        assert request.headers["x-api-key"] == "offline-serper-secret"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body == {"q": "Python 列表 (site:icourse163.org)", "num": 10, "gl": "cn", "hl": "zh-cn"}
        return httpx.Response(200, json={"credits": 1, "organic": [
            {"title": "Python", "link": native, "snippet": "列表", "sitelinks": [{"link": "https://www.icourse163.org/course/FAKE-222"}]},
            {"title": "Legacy", "link": legacy},
            {"title": "Foreign", "link": "https://icourse163.org.example.org/course/TEST-9"}],
            "answerBox": {"title": "Not organic", "link": "https://www.icourse163.org/course/FAKE-333"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-serper-secret"), client)
        rows = await provider.search("Python 列表", "zh", 20, ["icourse163.org"])
    assert [row.url for row in rows] == [native, legacy]
    assert all(row.query == "Python 列表" and row.source == "serper" for row in rows)
    assert provider.last_requests[0]["api_credits"] == 1
    assert provider.last_requests[0]["raw_candidate_count"] == 3
    assert provider.last_requests[0]["filter_counts"]["domain_mismatch"] == 1
    assert "offline-serper-secret" not in str(provider.last_requests)


@pytest.mark.asyncio
async def test_missing_key_stops_before_transport_and_factory_supports_provider():
    provider = build_provider(Settings(), provider_name="serper")
    with pytest.raises(SearchError) as caught:
        await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert caught.value.code == "configuration_error" and provider.last_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "access_denied"), (403, "access_denied"),
                                        (429, "rate_limited"), (402, "quota_exhausted")])
async def test_denial_rate_and_quota_stop_later_calls_without_retries_or_secret_echo(status, code):
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "3600"}, json={"message": "offline-serper-secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-serper-secret", search_min_interval_seconds=0,
                                           search_max_retries=3), client)
        for query in ("first", "second"):
            with pytest.raises(SearchError) as caught:
                await provider.search(query, "zh", 5, ["icourse163.org"])
            assert caught.value.code == code
            assert "offline-serper-secret" not in str(caught.value) + str(provider.last_requests)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_queued_call_rechecks_shared_quota_before_dispatch():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected request"))) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-key", search_min_interval_seconds=0), client)
        await provider._request_start_lock.acquire()
        pending = asyncio.create_task(provider.search("Python", "zh", 5, ["icourse163.org"]))
        await asyncio.sleep(0)
        provider.quota_exhausted = True
        provider._request_start_lock.release()
        with pytest.raises(SearchError) as caught:
            await pending
    assert caught.value.code == "quota_exhausted" and provider.last_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"results": []}, {"organic": {}}, [], {"organic": None}])
async def test_invalid_envelope_fails_without_invented_empty_success(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-key"), client)
        with pytest.raises(SearchError) as caught:
            await provider.search("Python", "zh", 5, ["icourse163.org"])
    assert caught.value.code == "invalid_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("credits", [None, True, -1, "offline-key", 10**400])
async def test_credits_are_unknown_unless_observed_safe_number(credits):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={"organic": [], "credits": credits}))) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-key"), client)
        await provider.search("Python", "en", 5, [])
    assert "api_credits" not in provider.last_requests[0]


@pytest.mark.asyncio
async def test_invalid_domain_operator_is_rejected_without_request():
    provider = SerperProvider(Settings(serper_api_key="offline-key"))
    with pytest.raises(SearchError) as caught:
        await provider.search("Python", "zh", 5, ["icourse163.org OR another.example"])
    assert caught.value.code == "configuration_error" and provider.last_requests == []


@pytest.mark.asyncio
async def test_existing_native_course_scope_is_sent_byte_for_byte_for_fair_comparison():
    query = "site:icourse163.org/course Python 列表 课程 教学"

    def respond(request):
        assert json.loads(request.content)["q"] == query
        return httpx.Response(200, json={"organic": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SerperProvider(Settings(serper_api_key="offline-key"), client)
        await provider.search(query, "zh", 10, ["icourse163.org"])
