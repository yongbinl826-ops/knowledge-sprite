"""Offline HTTP observations: engine timeout backoff never infers access rights."""
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app import providers as module
from backend.app.providers import SearXNGProvider, SearchError


VIDEO = "duckduckgo videos"
BACKUP = "bing"


def settings(**overrides):
    return Settings(**({"searxng_url": "http://trusted", "searxng_engines": ("bing",),
        "searxng_video_engines": (VIDEO,), "searxng_fallback_engines": (BACKUP,),
        "search_min_interval_seconds": 0, "search_max_retries": 0} | overrides))


def lesson(engine):
    return {"results": [{"title": "Python collision lesson", "url": "https://example.org/lesson", "engine": engine}]}


@pytest.mark.asyncio
async def test_two_real_http_timeout_observations_skip_later_requests_and_recover(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls, reservations = [], []
    timeouts_remaining = [2]
    def respond(request):
        engine = request.url.params["engines"]
        calls.append(engine)
        if engine == VIDEO and timeouts_remaining[0]:
            timeouts_remaining[0] -= 1
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"]]})
        return httpx.Response(200, json=lesson(engine))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(), client)
        async def reserve():
            reservations.append(1)
        provider.request_hook = reserve
        await provider.search("Python collision video", "en", 5, [])
        assert provider.last_requests[0]["engine_health"][0]["consecutive_timeout_count"] == 1
        await provider.search("Python restart video", "en", 5, [])
        health = provider.last_requests[0]["engine_health"][0]
        assert health["consecutive_timeout_count"] == 2 and health["cooldown_seconds"] == 60
        assert provider.engine_pauses[VIDEO] == 1060
        await provider.search("Python score video", "en", 5, [])
        assert calls == [VIDEO, BACKUP, VIDEO, BACKUP, BACKUP]
        assert len(reservations) == 5 and len(provider.last_requests) == 1
        skipped = provider.last_warnings[0]
        assert skipped["reason_code"] == "timeout_cooldown" and skipped["cooldown_remaining_seconds"] == 60
        assert skipped["observed_timeout_count"] == skipped["consecutive_timeout_count"] == 2
        clock[0] = 1061
        await provider.search("Python list video", "en", 5, [])
        assert calls[-1] == VIDEO and len(calls) == 6
        assert provider.engine_timeout_streaks.get(VIDEO, 0) == 0
        assert provider.last_requests[0]["engine_health"][0]["reason_code"] == "success"
        timeouts_remaining[0] = 1
        await provider.search("Python file video", "en", 5, [])
        assert provider.engine_timeout_streaks[VIDEO] == 1
        assert provider.last_requests[0]["engine_health"][0]["cooldown_seconds"] == 0


@pytest.mark.asyncio
async def test_empty_success_breaks_consecutive_timeout_streak():
    sequence = iter([True, False, True])
    calls = []
    def respond(request):
        calls.append(request.url.params["engines"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"]] if next(sequence) else []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(searxng_fallback_engines=()), client)
        for failure in [True, False, True]:
            if failure:
                with pytest.raises(SearchError):
                    await provider.search("Python video", "en", 5, [])
            else:
                assert await provider.search("Python video", "en", 5, []) == []
        assert len(calls) == 3 and provider.engine_timeout_streaks[VIDEO] == 1
        assert VIDEO not in provider.engine_pauses


@pytest.mark.asyncio
async def test_multi_engine_response_pauses_only_explicit_failing_requested_engine():
    calls = []
    def respond(request):
        engines = request.url.params["engines"]
        calls.append(engines)
        body = lesson(BACKUP)
        if VIDEO in engines:
            body["unresponsive_engines"] = [[VIDEO, "timeout"]]
        return httpx.Response(200, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(searxng_video_engines=(VIDEO, BACKUP), searxng_fallback_engines=()), client)
        for _ in range(3):
            assert await provider.search("Python video", "en", 5, [])
        assert calls == [VIDEO + "," + BACKUP, VIDEO + "," + BACKUP, BACKUP]
        assert set(provider.engine_pauses) == {VIDEO}
        assert all(set(call.split(",")) <= {VIDEO, BACKUP} for call in calls)


@pytest.mark.parametrize("engine,reason", [("duckduckgo", "timeout"), ("unknown", "timeout"),
    ("DuckDuckGo videos", "timeout"), ("unconfigured", "timeout"), (VIDEO, "timed out"),
    (VIDEO, "SECRET arbitrary timeout")])
@pytest.mark.asyncio
async def test_unconfigured_ambiguous_names_and_unknown_reasons_do_not_trip_engine(engine, reason):
    calls = []
    def respond(request):
        calls.append(request.url.params["engines"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [[engine, reason]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(searxng_fallback_engines=()), client)
        for _ in range(3):
            with pytest.raises(SearchError):
                await provider.search("Python video", "en", 5, [])
        assert calls == [VIDEO] * 3
        assert not provider.engine_pauses and not provider.engine_timeout_observations
        assert "SECRET" not in str(provider.last_warnings) + str(provider.last_requests)


@pytest.mark.asyncio
async def test_configured_but_not_requested_engine_timeout_does_not_infer_failure():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        json={"results": [], "unresponsive_engines": [[BACKUP, "timeout"]]}))) as client:
        provider = SearXNGProvider(settings(searxng_fallback_engines=()), client)
        for _ in range(2):
            with pytest.raises(SearchError):
                await provider.search("Python video", "en", 5, [])
        assert not provider.engine_pauses and not provider.engine_timeout_observations


@pytest.mark.asyncio
async def test_implicit_default_group_timeout_never_infers_authorized_engine():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(searxng_video_engines=(), searxng_engines=(), searxng_fallback_engines=()), client)
        for _ in range(3):
            with pytest.raises(SearchError):
                await provider.search("Python video", "en", 5, [])
        assert len(calls) == 3 and all("engines" not in request.url.params for request in calls)
        assert not provider.engine_pauses and not provider.engine_timeout_observations


@pytest.mark.asyncio
async def test_transport_timeout_does_not_guess_upstream_engine_or_add_engine():
    calls = []
    def respond(request):
        engine = request.url.params["engines"]
        calls.append(engine)
        if engine == VIDEO:
            raise httpx.ReadTimeout("SECRET unrelated transport timeout")
        return httpx.Response(200, json=lesson(engine))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(), client)
        for _ in range(3):
            await provider.search("Python video", "en", 5, [])
        assert calls == [VIDEO, BACKUP] * 3
        assert not provider.engine_pauses and not provider.engine_timeout_observations
        assert "SECRET" not in str(provider.last_requests) + str(provider.last_warnings)


@pytest.mark.asyncio
async def test_duplicate_failure_rows_in_one_response_are_only_one_observation():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
        json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"], [VIDEO, "timeout"]]}))) as client:
        provider = SearXNGProvider(settings(searxng_fallback_engines=()), client)
        with pytest.raises(SearchError):
            await provider.search("Python video", "en", 5, [])
        assert provider.engine_timeout_streaks == {VIDEO: 1} and not provider.engine_pauses


@pytest.mark.asyncio
async def test_duplicate_engine_configuration_cannot_fake_two_timeout_observations():
    calls = []
    def respond(request):
        calls.append(request.url.params["engines"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(searxng_video_engines=(VIDEO, VIDEO), searxng_fallback_engines=()), client)
        with pytest.raises(SearchError):
            await provider.search("Python video", "en", 5, [])
        assert calls == [VIDEO] and provider.engine_timeout_streaks == {VIDEO: 1}
        assert not provider.engine_pauses


@pytest.mark.parametrize("reason,pause", [("captcha", 3600), ("access denied", 3600), ("too many requests", 300)])
@pytest.mark.asyncio
async def test_stronger_engine_restrictions_remain_stronger_than_timeout_backoff(monkeypatch, reason, pause):
    clock = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []
    def respond(request):
        engine = request.url.params["engines"]
        calls.append(engine)
        if engine == VIDEO:
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [[VIDEO, "timeout"], [VIDEO, reason]]})
        return httpx.Response(200, json=lesson(engine))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(), client)
        await provider.search("Python video", "en", 5, [])
        await provider.search("Python video", "en", 5, [])
        assert calls == [VIDEO, BACKUP, BACKUP]
        assert provider.engine_pauses[VIDEO] == 1000 + pause
        assert not provider.engine_timeout_streaks
        assert provider.last_warnings[0]["reason_code"] == "suspended"


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.asyncio
async def test_service_denial_and_retry_after_still_stop_all_engine_groups(status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "120"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings(), client)
        for _ in range(2):
            with pytest.raises(SearchError):
                await provider.search("Python video", "en", 5, [])
        assert len(calls) == 1 and not provider.engine_timeout_observations
