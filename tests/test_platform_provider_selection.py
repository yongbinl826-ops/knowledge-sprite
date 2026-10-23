"""Synthetic HTTP routing evidence; no live search, billing or course fetches."""
import json
from contextlib import closing
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Query, SearchRequest
from backend.app.providers import SearXNGProvider, TavilyProvider
from backend.app.service import JobService


class NoFetch:
    async def enrich(self, candidate):
        raise AssertionError("Provider selection tests must not fetch course pages")


def config(tmp_path, **changes):
    return replace(Settings(database_path=str(tmp_path / "selection.sqlite3"),
        searxng_url="http://search.test", searxng_engines=("web",),
        searxng_video_engines=("video",), tavily_api_key="synthetic-key",
        mooc_search_provider="tavily", parallel_platform_search=True,
        open_web_search_enabled=False,  # Isolate the two explicitly scoped provider lanes.
        teaching_match_enabled=False, max_search_requests=20, max_detail_pages=0,
        search_min_interval_seconds=0, search_max_retries=0, deadline_seconds=10), **changes)


def search_request():
    return SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["bilibili", "icourse163"])


def respond(request):
    if request.url.host == "api.tavily.com":
        body = json.loads(request.content)
        assert body["include_domains"] == ["icourse163.org"]
        assert body["search_depth"] == "basic"
        return httpx.Response(200, json={"results": [{"title": "Python 列表课程", "url":
            "https://www.icourse163.org/course/QA-12345", "content": "Python 列表 课程 教学"}]})
    assert "icourse163.org" not in request.url.params["q"]
    return httpx.Response(200, json={"results": [{"title": "Python 列表视频教程", "url":
        "https://www.bilibili.com/video/BVsynthetic001/", "content": "Python 列表 视频教程",
        "template": "videos.html"}], "unresponsive_engines": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_exact_platform_queries_use_separate_sources_in_both_schedulers(tmp_path, parallel):
    calls = []
    def transport(request):
        calls.append(request)
        return respond(request)
    settings = config(tmp_path, parallel_platform_search=parallel)
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            base, mooc = SearXNGProvider(settings, client), TavilyProvider(settings, client)
            service = JobService(settings, store, provider=base, fetcher=NoFetch(),
                                 provider_overrides={"tavily": mooc})
            jid = service.create(search_request())["job_id"]
            await service.run(jid)
            attempts = store.attempts(jid)
            assert any(r.url.host == "api.tavily.com" for r in calls)
            assert any(r.url.host == "search.test" for r in calls)
            assert all(a["provider"] == "tavily" for a in attempts if a["domain_filters"] == ["icourse163.org"])
            assert all(a["provider"] == "searxng" for a in attempts if a["domain_filters"] == ["bilibili.com"])
            assert all(r.url.params["engines"] == "video" for r in calls
                       if r.url.host == "search.test" and "bilibili.com" in r.url.params["q"])
            assert store.get_job(jid)["progress"]["search_requests"] == len(calls)
            assert sum(len(a["provider_requests"]) for a in attempts) == len(calls)
            platforms = {row["resource"]["platform"] for group in service.results(jid)["groups"]
                         for row in group["discovery_items"]}
            # Routing still discovers both platforms, but an unverified MOOC
            # outline cannot enter the main recommendation cards.
            assert {row["platform"] for row in store.resources(jid).values()} == {"bilibili", "icourse163"}
            assert platforms == {"bilibili"}
            diagnostics = [row for group in service.results(jid)["groups"]
                           for row in group["mooc_relevance"]["candidates"]]
            assert diagnostics and all(not row["assessment"]["display_eligible"] for row in diagnostics)
            assert service.provider is base


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_missing_mooc_configuration_preserves_bilibili_without_fallback(tmp_path, parallel):
    calls = []
    def transport(request):
        calls.append(request)
        assert request.url.host == "search.test"
        return respond(request)
    settings = config(tmp_path, tavily_api_key="", tavily_allow_keyless=False,
                      parallel_platform_search=parallel)
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service = JobService(settings, store, provider=SearXNGProvider(settings, client),
                                 fetcher=NoFetch(), provider_overrides={"tavily": TavilyProvider(settings, client)})
            jid = service.create(search_request())["job_id"]
            await service.run(jid)
            attempts = store.attempts(jid)
            mooc = [a for a in attempts if a["provider"] == "tavily"]
            assert mooc and all(a["error_code"] == "configuration_error" for a in mooc)
            assert all(not a["network_attempted"] and not a["provider_requests"] for a in mooc)
            assert any(a["provider"] == "searxng" and a["candidate_count"] for a in attempts)
            assert calls
            assert service.capabilities()["platform_search"]["providers"]["icourse163"]["status"] == "unconfigured"


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("status", [403, 429, 432])
async def test_mooc_stop_is_scoped_and_never_falls_back_to_bilibili_source(tmp_path, parallel, status):
    calls = []
    def transport(request):
        calls.append(request)
        if request.url.host == "api.tavily.com":
            return httpx.Response(status, headers={"retry-after": "60"})
        return respond(request)
    settings = config(tmp_path, parallel_platform_search=parallel)
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service = JobService(settings, store, provider=SearXNGProvider(settings, client),
                                 fetcher=NoFetch(), provider_overrides={"tavily": TavilyProvider(settings, client)})
            jid = service.create(search_request())["job_id"]
            await service.run(jid)
            attempts = store.attempts(jid)
            assert len([r for r in calls if r.url.host == "api.tavily.com"]) == 1
            mooc = [a for a in attempts if a["provider"] == "tavily"]
            expected = {403: "access_denied", 429: "rate_limited", 432: "quota_exhausted"}[status]
            assert all(a["error_code"] == expected for a in mooc)
            assert sum(bool(a["network_attempted"]) for a in mooc) == 1
            assert any(a["provider"] == "searxng" and a["candidate_count"] for a in attempts)
            assert service.provider.access_denied is False and service.provider.paused_until == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_bilibili_source_denial_does_not_stop_independent_mooc_source(tmp_path, parallel):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(403) if request.url.host == "search.test" else respond(request)
    settings = config(tmp_path, parallel_platform_search=parallel)
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service = JobService(settings, store, provider=SearXNGProvider(settings, client),
                                 fetcher=NoFetch(), provider_overrides={"tavily": TavilyProvider(settings, client)})
            jid = service.create(search_request())["job_id"]
            await service.run(jid)
            assert len([r for r in calls if r.url.host == "search.test"]) == 1
            assert any(a["provider"] == "tavily" and a["candidate_count"] for a in store.attempts(jid))
            assert service.health()["search_sources"]["searxng"]["source_access_denied"] is True
            assert service.health()["search_sources"]["tavily"]["source_access_denied"] is False


def test_default_injection_and_exact_single_domain_boundaries(tmp_path):
    settings = config(tmp_path)
    with closing(Store(settings.database_path)) as store:
        base, mooc = object(), object()
        service = JobService(settings, store, provider=base, fetcher=NoFetch(), provider_overrides={"tavily": mooc})
        for domains in ([], ["www.icourse163.org"], ["icourse163.org", "bilibili.com"], ["xuetangx.com"]):
            query = Query(knowledge_point_id="k", query="site:icourse163.org Python", domain_filters=domains)
            assert service._search_source(query) == ("searxng", base, None)
        query = Query(knowledge_point_id="k", query="Python", domain_filters=["icourse163.org"])
        assert service._search_source(query) == ("tavily", mooc, None)
        defaults = JobService(replace(settings, mooc_search_provider=""), store, provider=base, fetcher=NoFetch())
        assert defaults._search_source(query) == ("searxng", base, None)
        replacement = object()
        defaults.provider = replacement
        assert defaults._search_source(query) == ("searxng", replacement, None)


@pytest.mark.asyncio
async def test_tavily_cache_does_not_depend_on_searxng_endpoint_or_engines(tmp_path):
    calls = []
    def transport(request):
        calls.append(request)
        return respond(request)
    settings = config(tmp_path)
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            request = SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["icourse163"])
            for version in (settings, replace(settings, searxng_url="http://changed.test", searxng_engines=("changed",))):
                service = JobService(version, store, provider=SearXNGProvider(version, client), fetcher=NoFetch(),
                                     provider_overrides={"tavily": TavilyProvider(version, client)})
                jid = service.create(request)["job_id"]
                await service.run(jid)
            assert len(calls) == 2  # Initial and supplementary queries in first job only.
            assert all(a["cache_hit"] and not a["network_attempted"] for a in store.attempts(jid))


def test_capabilities_report_explicit_keyless_trial_and_independent_sources(tmp_path):
    settings = config(tmp_path, tavily_api_key="", tavily_allow_keyless=True)
    with closing(Store(settings.database_path)) as store:
        service = JobService(settings, store, fetcher=NoFetch())
        capabilities = service.capabilities()
        providers = capabilities["platform_search"]["providers"]
        assert providers["bilibili"]["name"] == "searxng"
        assert providers["icourse163"]["name"] == "tavily"
        assert providers["icourse163"]["auth_mode"] == "keyless"
        assert providers["icourse163"]["status"] == "configured"
        assert "不代表生产可用性" in providers["icourse163"]["message"]
        assert set(service.health()["search_sources"]) == {"searxng", "tavily"}
