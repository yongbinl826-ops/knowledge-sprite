"""Offline optimization contracts: never call a real search/model/page service."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import time

import httpx
import pytest

from backend.app import fast_video_search as module
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher
from test_fast_video_search import POINTS, INPUT, Provider, factory, settings, video, completion, rows
from test_helpful_video_chapters import RESOURCE, POINTS as CATALOG_POINTS, cover_metadata


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Optimization tests must stay fully offline")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def source():
    return Provider(lambda _: [video(9100, title="Pygame 键盘教程", snippet="键盘按键状态轮询")])


async def search(provider, *, model=None, cache=None, config=None, input_data=None, **kwargs):
    return await module.run_fast_video_search(config or settings(), POINTS[:1], input_data or INPUT,
        publish=lambda _: None, deadline_seconds=1, provider_factory=factory(provider),
        complete=model or completion(), search_cache=cache, **kwargs)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_connect_failure_retries_same_batch_once_and_counts_every_attempt(error):
    normal, attempted = completion(), []
    async def complete(config, prompt, payload, **kwargs):
        if payload["task"] == "match_helpful_videos":
            attempted.append(deepcopy(payload))
            if len(attempted) == 1:
                raise error("offline connection failure")
        return await normal(config, prompt, payload, **kwargs)
    result = await search(source(), model=complete)
    assert len(attempted) == 2 and attempted[0] == attempted[1]
    batches = [row for row in result["diagnostics"]["model_batches"] if row["task"] == "match_helpful_videos"]
    assert [row["status"] for row in batches] == ["failed", "completed"]
    assert [row["retry_index"] for row in batches] == [0, 1]
    assert len({row["batch_id"] for row in batches}) == 1
    assert all(row["duration_seconds"] >= 0 for row in batches)
    assert result["progress"]["model_calls"] == 3
    assert result["diagnostics"]["matching"]["judged_candidates"] == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("offline read"), TimeoutError("offline timeout"),
    httpx.HTTPStatusError("offline 429", request=httpx.Request("POST", "https://model.example/"),
                         response=httpx.Response(429))])
async def test_response_or_unknown_timeout_is_never_replayed(error):
    async def complete(_config, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": []}
        raise error
    result = await search(source(), model=complete)
    batches = [row for row in result["diagnostics"]["model_batches"] if row["task"] == "match_helpful_videos"]
    assert len(batches) == 1 and batches[0]["retryable_connect_failure"] is False
    assert result["diagnostics"]["matching"]["failed_candidates"] == 1


async def test_connection_recovery_never_expands_shared_model_allowance(monkeypatch):
    monkeypatch.setattr(module, "MAX_MODEL_CALLS", 2)
    async def complete(_config, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": []}
        raise httpx.ConnectTimeout("offline connect")
    result = await search(source(), model=complete)
    assert result["progress"]["model_calls"] == 2
    assert not any(row.get("recovery_scheduled") for row in result["diagnostics"]["model_batches"])


async def test_repeated_connection_failure_stops_after_second_attempt():
    async def complete(_config, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": []}
        raise httpx.ConnectError("offline repeated connect")
    result = await search(source(), model=complete)
    attempts = [row for row in result["diagnostics"]["model_batches"] if row["task"] == "match_helpful_videos"]
    assert len(attempts) == 2 and all(row["status"] == "failed" for row in attempts)
    assert result["diagnostics"]["matching"]["failed_candidates"] == 1


async def test_connection_recovery_reuses_remaining_time_window():
    normal, windows = completion(), []
    async def complete(config, prompt, payload, **kwargs):
        if payload["task"] == "match_helpful_videos":
            windows.append(kwargs["timeout_seconds"])
            if len(windows) == 1:
                await asyncio.sleep(.025)
                raise httpx.ConnectError("offline connect")
        return await normal(config, prompt, payload, **kwargs)
    await search(source(), model=complete)
    assert len(windows) == 2 and windows[1] < windows[0] - .02


@pytest.mark.parametrize("route", ["failover", "gap"])
async def test_tavily_backup_only_is_an_available_source(route):
    async def unavailable(_):
        raise module.SearchError("search_timeout", "offline timeout")
    primary = Provider(unavailable if route == "failover" else lambda _: [])
    secondary = source()
    primary.name, secondary.name = "searxng", "tavily"
    config = settings(search_provider="searxng", tavily_api_key="", tavily_backup_api_key="offline-backup",
        ai_video_search_provider="auto" if route == "gap" else "default",
        searxng_failover_provider="tavily" if route == "failover" else "")
    result = await module.run_fast_video_search(config, POINTS[:1], INPUT, publish=lambda _: None,
        deadline_seconds=1, complete=completion(),
        provider_factory=lambda _settings, provider_name: primary if provider_name == "searxng" else secondary)
    assert secondary.calls and rows(result)
    if route == "gap":
        assert set(result["diagnostics"]["gap_sources"].values()) == {"tavily"}


async def test_search_cache_reuses_observations_but_rejudges_and_counts_zero_http():
    store, provider = Store(":memory:"), source()
    try:
        first = await search(provider, cache=store)
        calls = len(provider.calls)
        original = rows(first)[0]["resource"]["discovered_at"]
        saved = store.connection.execute("SELECT created,expires FROM cache ORDER BY key").fetchall()
        second = await search(provider, cache=store)
        assert len(provider.calls) == calls and calls > 0
        assert second["progress"]["search_requests"] == 0
        assert second["diagnostics"]["cache_candidates"] > 0
        assert second["diagnostics"]["matching"]["judged_candidates"] == 1
        assert second["progress"]["model_calls"] == 2
        assert rows(second)[0]["resource"]["discovered_at"] == original
        assert store.connection.execute("SELECT created,expires FROM cache ORDER BY key").fetchall() == saved
        attempts = [a for row in second["diagnostics"]["searches"] for a in row["provider_attempts"]]
        assert all(a["status"] == "cached" and not a["network_attempted"] and a["http_requests"] == 0 for a in attempts)
        assert all(a["provider_requests"] == [] and a["cache"]["observed_at"] for a in attempts)
    finally:
        store.close()


@pytest.mark.parametrize("variation", ["language", "provider", "mapping", "platform", "expired"])
async def test_search_cache_isolated_or_expired(variation, monkeypatch):
    store, provider = Store(":memory:"), source()
    initial_input = {**INPUT, "preferred_platforms": ["bilibili"]}
    try:
        await search(provider, cache=store, input_data=initial_input)
        calls = len(provider.calls)
        next_input = dict(initial_input)
        if variation == "language": next_input["language"] = "en"
        if variation == "provider": provider.name = "other-offline"
        if variation == "mapping": monkeypatch.setattr(module.provider_module, "SEARCH_THUMBNAIL_VERSION", 999, raising=False)
        if variation == "platform": next_input["preferred_platforms"] = ["icourse163"]
        if variation == "expired": store.connection.execute("UPDATE cache SET expires=0")
        result = await search(provider, cache=store, input_data=next_input)
        assert len(provider.calls) > calls and result["progress"]["search_requests"] > 0
        assert result["diagnostics"]["search_cache_hits"] == 0
    finally:
        store.close()


async def test_partial_upstream_observation_is_not_cached():
    store, provider = Store(":memory:"), source()
    provider.last_warnings = [{"code": "upstream_engine_failed"}]
    try:
        await search(provider, cache=store)
        assert store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
    finally:
        store.close()


async def test_early_cover_precedes_matching_and_reuses_same_page():
    fetched, ready = [], asyncio.Event()
    provider = Provider(lambda _: [video(9500, title="Pygame 键盘教程", snippet="键盘按键状态轮询", url=RESOURCE["url"])])
    async def fetch(resource):
        fetched.append(resource)
        ready.set()
        return cover_metadata()
    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
    normal = completion()
    async def complete(config, prompt, payload, **kwargs):
        if payload["task"] == "match_helpful_videos":
            await asyncio.wait_for(ready.wait(), .5)
        if payload["task"] == "match_video_chapters":
            return {"matches": []}
        return await normal(config, prompt, payload, **kwargs)
    result = await search(provider, model=complete, chapter_enricher_factory=enricher)
    assert result["diagnostics"]["early_cover_scheduled"] == 1
    assert len(fetched) == 1
    assert rows(result)[0]["resource"]["cover_status"] == "ready"
    assert rows(result)[0]["resource"]["thumbnail_url"] == cover_metadata()["thumbnail_url"]
    assert result["diagnostics"]["metrics"]["cover_url_rate"] == 1
    assert result["diagnostics"]["first_recommendation_seconds"] is not None


async def test_early_cover_admission_is_small_and_one_per_point():
    instances = []
    class Enricher:
        def __init__(self, *_args, **_kwargs):
            self.diagnostics = {"network_scheduled_resources": 0}
            self.early = []
            instances.append(self)
        def enqueue_early_cover(self, resource, ids):
            self.early.append((resource["resource_id"], ids))
            return True
        def enqueue(self, *_args): return False
        async def close(self): pass
    serial = 0
    def candidates(_):
        nonlocal serial
        serial += 1
        return [video(serial * 10 + n, title="Pygame 键盘教程", snippet="键盘按键状态轮询") for n in range(5)]
    points = [{**POINTS[0], "id": f"p{i}", "name": f"键盘轮询{i}"} for i in range(7)]
    async def model(_config, _prompt, _payload, **_kwargs): return {"matches": []}
    result = await module.run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=1, provider_factory=factory(Provider(candidates)), complete=model,
        chapter_enricher_factory=Enricher)
    assert len(instances[0].early) == module.EARLY_COVER_MAX_RESOURCES
    assert len({ids[0] for _, ids in instances[0].early}) == len(instances[0].early)
    assert result["recommendations"] == {p["id"]: [] for p in points}


async def test_cover_states_fail_without_provenance_and_do_not_claim_ready():
    states = []
    async def fetch(resource):
        return {"url": resource["url"], "fetch_status": "fetched", "thumbnail_url": "https://i0.hdslb.com/unbound.jpg"}
    service = HelpfulVideoChapterEnricher(Settings(), CATALOG_POINTS, fetch_catalog=fetch,
        on_cover_state=lambda *args: states.append(args), on_cover=lambda *_: pytest.fail("Unbound cover cannot publish"))
    try:
        assert service.enqueue_early_cover(RESOURCE, ["collision"])
        service.finish_admission()
        await service.run_background_match(collect_seconds=0)
        assert states[0][1] == "pending" and states[-1][1:] == ("failed", "no_cover")
        assert not any(row[1] == "ready" for row in states)
    finally:
        await service.close()


async def test_native_catalog_transport_uses_settings_and_phased_owner_deadline():
    config = replace(Settings(), global_concurrency=2, fetch_timeout_seconds=10,
        fetch_phased_timeouts=True, fetch_body_idle_timeout_seconds=6,
        fetch_body_min_bytes_per_second=16384, fetch_body_timeout_cap_seconds=30)
    service = HelpfulVideoChapterEnricher(config, CATALOG_POINTS, deadline=time.monotonic() + .2)
    assert service._fetcher.config.timeout_seconds == 10
    assert service._fetcher.config.global_concurrency == 2
    assert service._fetcher.config.phased_timeouts is True
    assert service._fetcher.config.body_idle_timeout_seconds == 6
    assert service._fetcher.config.body_min_bytes_per_second == 16384
    assert service._fetcher.config.body_timeout_cap_seconds == 30
    async def fetch(_): return cover_metadata()
    service.fetch_catalog = fetch
    try:
        service.enqueue_early_cover(RESOURCE, ["collision"])
        service.finish_admission()
        await service.run_background_match(collect_seconds=0)
        assert 0 < service.diagnostics["resources"][0]["course_timeout_seconds"] <= .2
    finally:
        await service.close()


async def test_native_phased_transport_preserves_body_window():
    config = replace(Settings(), fetch_timeout_seconds=10, fetch_phased_timeouts=True,
                     fetch_body_timeout_cap_seconds=30)
    service = HelpfulVideoChapterEnricher(config, CATALOG_POINTS, deadline=time.monotonic() + 60)
    async def fetch(_): return cover_metadata()
    service.fetch_catalog = fetch
    try:
        service.enqueue_early_cover(RESOURCE, ["collision"])
        service.finish_admission()
        await service.run_background_match(collect_seconds=0)
        assert service.diagnostics["resources"][0]["course_timeout_seconds"] == 40
    finally:
        await service.close()


@pytest.mark.parametrize("promote_while_loading", [False, True])
async def test_selected_early_cover_resumes_explicitly_deferred_catalog_once(promote_while_loading):
    resource = {"resource_id": "mooc", "url": "https://www.icourse163.org/course/PKU-1000000001", "title": "课程"}
    calls, chapters, started, proceed = [], [], asyncio.Event(), asyncio.Event()
    async def fetch(_resource):
        calls.append(_resource)
        started.set()
        if len(calls) == 1:
            await proceed.wait()
            return {"url": resource["url"], "fetch_status": "fetched", "catalog_fetch_status": "not_attempted",
                    "chapters": [], "thumbnail_url": "https://images.example.com/course.jpg",
                    "field_provenance": {"thumbnail_url": {"source": "meta.og:image", "url": resource["url"]}}}
        return {"url": resource["url"], "fetch_status": "fetched", "chapters": [{"title": "碰撞检测",
            "source": "html.icourse163.courseOutline", "source_url": resource["url"]}]}
    service = HelpfulVideoChapterEnricher(Settings(), CATALOG_POINTS, fetch_catalog=fetch,
        publish=lambda *args: chapters.append(args), max_resources=1)
    try:
        service.enqueue_early_cover(resource, ["collision"])
        await started.wait()
        if promote_while_loading:
            service.enqueue(resource, ["collision"])
        proceed.set()
        await asyncio.gather(*tuple(service._tasks))
        if not promote_while_loading:
            assert len(calls) == 1 and not chapters
            service.enqueue(resource, ["collision"])
        service.finish_admission()
        await service.run_background_match(collect_seconds=0)
        assert len(calls) == 2 and chapters[0][2][0]["title"] == "碰撞检测"
        assert service.diagnostics["network_scheduled_resources"] == 1
        assert service.diagnostics["resources"][0]["deferred_catalog_resumed"] is True
    finally:
        await service.close()


async def test_llm_observer_usage_is_bound_to_each_actual_attempt(monkeypatch):
    from contextvars import ContextVar
    observer = ContextVar("offline_llm_observer", default=None)
    monkeypatch.setattr(module.llm_transport, "LLM_OBSERVER", observer, raising=False)
    normal = completion()
    async def model(config, prompt, payload, **kwargs):
        observer.get()({"usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                                  "cached_input_tokens": None}, "http_status": 200})
        return await normal(config, prompt, payload, **kwargs)
    result = await search(source(), model=model)
    assert all(row["usage"]["total_tokens"] == 15 for row in result["diagnostics"]["model_batches"])
    assert observer.get() is None
