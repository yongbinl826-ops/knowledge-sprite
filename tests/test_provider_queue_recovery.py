"""A queued request may skip its paused group, never retry that restricted group."""
import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import SearXNGProvider, SearchError


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["captcha", "access denied", "too many requests"])
async def test_concurrent_group_pause_keeps_configured_independent_backup(reason):
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    calls, reservations, observations = [], [], {}

    async def respond(request):
        engine, query = request.url.params["engines"], request.url.params["q"]
        calls.append((query, engine))
        if engine == "duckduckgo videos":
            first_entered.set()
            await release_first.wait()
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [[engine, reason]]})
        return httpx.Response(200, json={"results": [{"url": "https://www.bilibili.com/video/BV1q741157jG",
            "title": "Pygame lesson", "engine": engine}]})

    settings = Settings(searxng_url="http://offline", searxng_video_engines=("duckduckgo videos",),
        searxng_fallback_engines=("bing",), search_min_interval_seconds=.05, search_max_retries=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings, client)

        async def search(query):
            async def reserve():
                reservations.append(query)
            with provider.query_scope(reserve):
                result = await provider.search(query + " video", "en", 5, ["bilibili.com"])
                observations[query] = (provider.last_requests.copy(), provider.last_warnings.copy())
                return result

        first = asyncio.create_task(search("first"))
        await first_entered.wait()
        second = asyncio.create_task(search("second"))
        # Let second select primary and enter the send lock before first pauses it.
        await asyncio.sleep(0)
        release_first.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert all(len(rows) == 1 for rows in results)
        assert sum(engine == "duckduckgo videos" for _, engine in calls) == 1
        assert sum(engine == "bing" for _, engine in calls) == 2
        assert len(reservations) == len(calls) == 3
        assert len(observations["first"][0]) == 2 and len(observations["second"][0]) == 1
        assert observations["first"][1][0]["reason_code"] in {"captcha", "access_denied", "rate_limited"}
        assert observations["second"][1][0]["code"] == "upstream_engine_failed"
        assert observations["second"][1][0]["reason_code"] == "paused_while_queued"
        assert observations["second"][1][0]["network_attempted"] is False
        assert provider.engine_pauses["duckduckgo videos"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_service_wide_denial_does_not_start_any_backup(status):
    calls = []

    def respond(request):
        calls.append(request.url.params["engines"])
        return httpx.Response(status, headers={"Retry-After": "120"})

    settings = Settings(searxng_url="http://offline", searxng_video_engines=("duckduckgo videos",),
        searxng_fallback_engines=("bing",), search_min_interval_seconds=0, search_max_retries=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings, client)
        for _ in range(2):
            with pytest.raises(SearchError):
                await provider.search("Pygame video", "en", 5, ["bilibili.com"])
        assert calls == ["duckduckgo videos"]
