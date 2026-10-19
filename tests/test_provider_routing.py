"""Synthetic provider responses; never imported by the live application."""
import httpx
import pytest

from backend.app.config import Settings
from backend.app.models import SearchRequest
from backend.app.providers import SearXNGProvider, SearchError, parse_candidates
from backend.app.queries import generate_queries


@pytest.mark.asyncio
async def test_video_discovery_preserves_engine_and_type_evidence():
    def respond(request):
        assert request.url.params["engines"] == "duckduckgo videos"
        return httpx.Response(200, json={"results": [{"title": "Enter update exit lesson", "url": "https://www.youtube.com/watch?v=example",
            "template": "videos.html", "engines": ["duckduckgo videos"], "content": "D3 video"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_video_engines=("duckduckgo videos",)), client)
        items = await provider.search("D3 video tutorial", "en", 5, [])
    assert items[0].resource_type_hint == "video" and items[0].type_source == "search_template"
    assert items[0].source_engines == ["duckduckgo videos"]
    assert provider.last_requests[0]["http_status"] == 200


@pytest.mark.asyncio
async def test_site_video_search_uses_video_engine_and_fallback_counts_real_requests():
    seen = []
    budget = []
    def respond(request):
        seen.append(request.url.params["engines"])
        if len(seen) == 1:
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [["video", "timeout"]]})
        return httpx.Response(200, json={"results": [{"title": "D3 video", "url": "https://www.bilibili.com/video/BVoffline001/"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_engines=("primary",),
            searxng_video_engines=("video",), searxng_fallback_engines=("backup",)), client)
        async def count():
            budget.append(1)
        provider.request_hook = count
        items = await provider.search("D3 视频教程", "zh", 5, ["bilibili.com"])
    assert seen == ["video", "backup"] and len(budget) == 2 and len(items) == 1
    assert provider.last_warnings[0]["reason"] == "timeout"
    assert provider.last_requests[1]["fallback"] is True
    assert provider.last_requests[1]["filter_counts"] == {"accepted": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("language,topic", [("zh", "Python 列表与字典"), ("en", "linear algebra eigenvalues")])
async def test_generated_platform_queries_retain_site_restriction_and_video_routing(language, topic):
    request = SearchRequest(knowledge_points=[topic], language=language)
    queries = [query for query in generate_queries("k", topic, request) if query.domain_filters]
    seen = []
    def respond(outgoing):
        seen.append(outgoing)
        expected_engine = "bing" if outgoing.url.params["q"].startswith("site:icourse163.org ") else "duckduckgo videos"
        assert outgoing.url.params["engines"] == expected_engine
        assert outgoing.url.params["q"].startswith("site:")
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_engines=("bing",),
            searxng_video_engines=("duckduckgo videos",), search_min_interval_seconds=0), client)
        for query in queries:
            await provider.search(query.query, language, 5, query.domain_filters)
    assert len(seen) == len(queries) == 3
    assert [outgoing.url.params["q"] for outgoing in seen] == [query.query for query in queries]


def test_candidate_filter_audit_is_bounded_and_never_reflects_sensitive_urls():
    items = [
        {"title": "Course", "url": "https://www.icourse163.org/course/ABC-123?token=SECRET#SECRET"},
        {"title": "Wrong site", "url": "https://example.org/course"},
        {"title": "Credentials", "url": "https://user:SECRET@www.icourse163.org/course/123"},
        {"title": "Internal", "url": "http://192.168.1.1/SECRET"},
        {"title": "", "url": "https://www.icourse163.org/course/invalid"},
        "invalid item", {"title": "Missing"},
        {"title": "Long", "url": "https://www.icourse163.org/" + "a" * 650},
        {"title": "Too long", "url": "https://www.icourse163.org/" + "b" * 4100},
    ] + [{"title": "Extra", "url": f"https://www.icourse163.org/course/{index}"} for index in range(25)]
    audit = {}
    candidates = parse_candidates(items, "searxng", "arbitrary", 1, ["icourse163.org"], audit=audit)
    assert len(candidates) == 1 and candidates[0].url == items[0]["url"]
    assert audit["filter_counts"] == {"accepted": 1, "domain_mismatch": 2, "invalid_url": 1,
        "invalid_title": 1, "invalid_item": 1, "missing_url": 1, "limit_reached": 26, "url_too_long": 1}
    assert len(audit["candidate_trace"]) == 20 and audit["candidate_trace_omitted"] == len(items)-20
    assert "SECRET" not in str(audit) and "192.168" not in str(audit)
    assert audit["candidate_trace"][0]["query_redacted"] is True
    assert audit["candidate_trace"][7]["url_truncated"] is True
    assert all(len(item.get("url", "")) <= 500 for item in audit["candidate_trace"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_service_access_controls_never_trigger_fallback(status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "60"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_engines=("primary",), searxng_fallback_engines=("backup",)), client)
        with pytest.raises(SearchError):
            await provider.search("X video", "en", 5, [])
    assert len(calls) == 1 and provider.last_requests[0]["http_status"] == status


@pytest.mark.asyncio
async def test_upstream_rate_limit_pauses_engine_across_queries_and_retains_failure():
    seen = []
    def respond(request):
        seen.append(request.url.params["engines"])
        if seen[-1] == "primary":
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [["primary", "too many requests"]]})
        return httpx.Response(200, json={"results": [{"title": "X lesson", "url": "https://example.org/video/x"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_engines=("primary",), searxng_fallback_engines=("backup",)), client)
        await provider.search("X", "en", 5, [])
        assert provider.last_warnings[0]["reason"] == "too many requests"
        await provider.search("Y", "en", 5, [])
    assert seen == ["primary", "backup", "backup"]
    assert provider.last_warnings[0]["reason_code"] == "suspended"


@pytest.mark.asyncio
async def test_normal_empty_search_does_not_become_network_failure():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted"), client)
        assert await provider.search("absent", "en", 5, []) == []
    assert provider.last_status == "available" and not provider.last_warnings


@pytest.mark.asyncio
async def test_unrecognized_upstream_error_does_not_leak_raw_text():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": [],
        "unresponsive_engines": [["primary", "https://secret:credential@example.org/?api_key=SECRET"]]}))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted"), client)
        with pytest.raises(SearchError):
            await provider.search("X", "en", 5, [])
    assert "SECRET" not in str(provider.last_warnings) and provider.last_warnings[0]["reason"] == "unknown"


@pytest.mark.asyncio
async def test_implicit_default_group_pauses_after_upstream_access_restriction():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [["brave", "too many requests"]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted"), client)
        for query in ["X", "Y"]:
            with pytest.raises(SearchError):
                await provider.search(query, "en", 5, [])
    assert len(calls) == 1 and not provider.last_requests


@pytest.mark.asyncio
async def test_fallback_requires_explicit_primary_group():
    provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_fallback_engines=("backup",)))
    with pytest.raises(SearchError, match="显式配置主引擎"):
        await provider.search("X", "en", 5, [])
    assert not provider.last_requests


@pytest.mark.asyncio
async def test_denied_service_stays_stopped_across_queries():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted"), client)
        for query in ["X", "Y"]:
            with pytest.raises(SearchError):
                await provider.search(query, "en", 5, [])
    assert len(calls) == 1 and not provider.last_requests


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["youtube", "bilibili"])
async def test_unpermitted_direct_platform_engines_never_request(engine):
    provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_video_engines=(engine,)))
    with pytest.raises(SearchError, match="自动访问许可"):
        await provider.search("Python video", "en", 5, [])
    assert provider.last_requests == []


@pytest.mark.asyncio
async def test_user_query_cannot_select_searxng_engine_via_bang():
    def respond(request):
        assert request.url.params["q"] == "youtube Python video"
        assert request.url.params["engines"] == "bing"
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://trusted", searxng_engines=("bing",)), client)
        assert await provider.search("!youtube Python video", "en", 5, []) == []
