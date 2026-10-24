"""Offline gap-index routing and per-query observations; never real searches."""
import asyncio
import hashlib
import time

import pytest

from backend.app import fast_video_search as module
from backend.app.providers import HTTPProvider, SearchError
from test_fast_video_search import completion, settings, video


POINTS = [{"id": "loops", "name": "循环结构", "technology": "Python"},
          {"id": "lists", "name": "线性表", "technology": "Python"}]
INPUT = {"name": "Synthetic offline recovery", "preferred_platforms": ["bilibili"]}


class ScopedProvider(HTTPProvider):
    """Use production ContextVar scope/hook with controlled offline responses."""
    def __init__(self, config, name, handler):
        super().__init__(config)
        self.name, self.handler, self.calls = name, handler, []

    async def search(self, query, _language, _limit, domains):
        self.last_requests, self.last_warnings = [], []
        await self.request_hook()
        self.calls.append((query, domains[0]))
        trace = {"provider": self.name, "status": "running", "http_status": 200}
        self.last_requests.append(trace)
        try:
            rows = self.handler(self, query, domains, trace)
            rows = await rows if hasattr(rows, "__await__") else rows
            trace.update(status="completed", candidate_count=len(rows))
            return rows
        except SearchError as exc:
            trace.update(status="failed", error_code=exc.code)
            raise
        except asyncio.CancelledError:
            trace.update(status="cancelled", error_code="request_cancelled")
            raise


def good(*_args):
    return [video(91, title="Python 循环与线性表教程", snippet="循环结构与线性表")]


def empty(*_args):
    return []


def failure(code, *, flag=None, http_status=503):
    def fail(provider, _query, _domains, trace):
        if flag:
            setattr(provider, flag, time.monotonic() + 60 if flag == "paused_until" else True)
        trace["http_status"] = http_status
        raise SearchError(code, "Synthetic offline failure")
    return fail


async def run(config=None, handlers=None, *, points=POINTS, model=None, deadline=.4, configure=None):
    config = config or settings(search_provider="searxng", serper_api_key="offline-key")
    handlers = handlers or {"searxng": empty, "serper": good, "tavily": good}
    providers = {name: ScopedProvider(config, name, handler) for name, handler in handlers.items()}
    if configure:
        configure(providers)
    def factory(_settings, provider_name):
        assert provider_name in providers, "An unplanned index must never be constructed"
        return providers[provider_name]
    snapshots = []
    result = await module.run_fast_video_search(config, points, INPUT, publish=snapshots.append,
        deadline_seconds=deadline, provider_factory=factory, complete=model or completion())
    return result, providers, snapshots


def attempts(result):
    return [attempt for row in result["diagnostics"]["searches"] for attempt in row.get("provider_attempts", [])]


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_code,flag", [("access_denied", "access_denied"),
    ("rate_limited", "paused_until"), ("quota_exhausted", "quota_exhausted")])
async def test_preselected_gap_index_does_not_clear_primary_restriction_or_use_legacy_failover(primary_code, flag):
    config = settings(search_provider="searxng", serper_api_key="offline-key", searxng_failover_provider="tavily")
    result, providers, _ = await run(config, {"searxng": failure(primary_code, flag=flag), "serper": good, "tavily": good})
    assert result["diagnostics"]["gap_sources"] == {"bilibili": "serper"}
    assert getattr(providers["searxng"], flag)
    assert len(providers["searxng"].calls) == 1
    assert len(providers["serper"].calls) == 3  # two points and one technology
    assert not providers["tavily"].calls
    assert all(result["recommendations"].values())
    first = next(row for row in result["diagnostics"]["searches"] if row.get("primary_error_code"))
    assert first["provider"] == "searxng" and first["result_provider"] == "serper"
    primary = first["provider_attempts"][0]
    assert primary["error_code"] == primary_code and primary["network_attempted"]
    assert primary["provider_requests"][0]["error_code"] == primary_code
    assert any(a["status"] == "skipped" and not a["network_attempted"] for a in attempts(result))


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", ["default", "tavily"])
async def test_same_configured_index_is_not_queried_again_as_gap_source(selected):
    config = settings(search_provider="tavily", ai_video_search_provider=selected)
    result, providers, _ = await run(config, {"tavily": empty})
    assert result["diagnostics"]["gap_sources"] == {"bilibili": None}
    assert len(providers["tavily"].calls) == 3
    assert all(a["role"] == "primary" and a["status"] == "empty" for a in attempts(result))


@pytest.mark.asyncio
async def test_auto_without_serper_preselects_tavily_after_empty_primary():
    result, providers, _ = await run(settings(search_provider="searxng", serper_api_key=""))
    assert result["diagnostics"]["gap_sources"] == {"bilibili": "tavily"}
    assert providers["tavily"].calls and not providers["serper"].calls
    assert all(row["provider_attempts"][0]["status"] == "empty"
               for row in result["diagnostics"]["searches"] if row.get("provider_attempts"))


@pytest.mark.asyncio
@pytest.mark.parametrize("unusable", [
    {"title": "Python 课程", "url": "https://www.bilibili.com/"},
    {"title": "Python 课程", "url": "https://www.bilibili.com/read/cv12345"},
    {"title": "  ", "url": "https://www.bilibili.com/video/av123456"},
    {"title": "Python 付费课程", "url": "https://www.bilibili.com/video/av123456"},
    {"title": "Python 课程", "url": "https://www.bilibili.com/video/av123456", "requires_payment": True},
])
async def test_raw_results_without_usable_free_or_unknown_price_entry_trigger_gap(unusable):
    result, providers, _ = await run(handlers={"searxng": lambda *_: [unusable], "serper": good})
    assert len(providers["serper"].calls) == 3 and all(result["recommendations"].values())
    primary = [a for a in attempts(result) if a["role"] == "primary"]
    assert all(a["candidate_count"] == 1 and a["status"] == "completed" for a in primary)


@pytest.mark.asyncio
async def test_duplicate_valid_candidates_do_not_spend_gap_queries():
    result, providers, _ = await run(handlers={"searxng": good, "serper": good})
    assert len(providers["searxng"].calls) == 3 and not providers["serper"].calls
    assert all(row["usable_candidate_count"] == 1 for row in result["diagnostics"]["searches"]
               if row.get("provider_attempts"))


@pytest.mark.asyncio
async def test_later_paid_observation_removes_existing_card_before_recovery_fails():
    config = settings(search_provider="searxng", serper_api_key="offline-key")
    shown, snapshots = asyncio.Event(), []

    def publish(snapshot):
        snapshots.append(snapshot)
        if any(snapshot["recommendations"].values()):
            shown.set()

    async def primary(provider, *_args):
        if len(provider.calls) == 1:
            return good()
        await shown.wait()
        paid = good()[0].model_dump()
        paid["requires_payment"] = True
        return [paid]

    def recovery(provider, query, domains, trace):
        assert shown.is_set(), "The test must first publish the original card"
        assert not any(snapshots[-1]["recommendations"].values()), "Withdraw before awaiting recovery"
        return failure("search_unavailable")(provider, query, domains, trace)

    providers = {name: ScopedProvider(config, name, handler) for name, handler in
                 {"searxng": primary, "serper": recovery}.items()}
    result = await module.run_fast_video_search(config, POINTS, INPUT, publish=publish,
        deadline_seconds=.8, provider_factory=lambda _settings, provider_name: providers[provider_name],
        complete=completion())
    assert shown.is_set() and providers["serper"].calls
    assert not any(result["recommendations"].values())
    assert any(attempt["role"] == "recovery" and attempt.get("error_code") == "search_unavailable"
               for attempt in attempts(result))


@pytest.mark.asyncio
@pytest.mark.parametrize("code,flag,status", [("access_denied", "access_denied", 401),
    ("access_denied", "access_denied", 403), ("rate_limited", "paused_until", 429),
    ("quota_exhausted", "quota_exhausted", 402)])
async def test_independent_source_own_restriction_stops_remaining_slots_without_rotation(code, flag, status):
    result, providers, _ = await run(handlers={"searxng": empty,
        "serper": failure(code, flag=flag, http_status=status), "tavily": good})
    assert len(providers["serper"].calls) == 1 and not providers["tavily"].calls
    recovery = [a for a in attempts(result) if a["role"] == "recovery"]
    assert len(recovery) == 3
    assert recovery[0]["provider_requests"][0]["http_status"] == status
    assert all(a["status"] == "skipped" and not a["network_attempted"] for a in recovery[1:])


@pytest.mark.asyncio
async def test_gap_scope_is_reserved_before_concurrent_query_variants_start():
    async def slow_empty(*_args):
        await asyncio.sleep(.02)
        return []
    ordinary = completion()
    async def planned(config, prompt, data, **kwargs):
        if data["task"] == "plan_video_discovery":
            await asyncio.sleep(.005)
            return {"suggestions": [{"point_id": p["id"], "queries": [f"Python alternate {p['id']}"]} for p in POINTS]}
        return await ordinary(config, prompt, data, **kwargs)
    result, providers, _ = await run(handlers={"searxng": slow_empty, "serper": good}, model=planned)
    assert len(providers["searxng"].calls) == 5
    recovery = [row["recovery"]["scope"] for row in result["diagnostics"]["searches"] if "recovery" in row]
    assert len(recovery) == len(set(map(tuple, recovery))) == 3
    assert len(providers["serper"].calls) == 3


@pytest.mark.asyncio
async def test_successful_empty_failover_can_use_distinct_gap_index_without_erasing_primary_failure():
    config = settings(search_provider="searxng", serper_api_key="offline-key", searxng_failover_provider="tavily")
    result, providers, _ = await run(config, {"searxng": failure("search_timeout"), "tavily": empty, "serper": good})
    row = next(row for row in result["diagnostics"]["searches"] if row.get("failover"))
    assert row["provider"] == "searxng" and row["result_provider"] == "serper"
    assert [(a["provider"], a["status"]) for a in row["provider_attempts"]] == [
        ("searxng", "failed"), ("tavily", "empty"), ("serper", "completed")]
    assert row["provider_attempts"][0]["provider_requests"][0]["error_code"] == "search_timeout"


@pytest.mark.asyncio
async def test_gap_reuses_total_http_budget_and_never_starts_a_fresh_allowance():
    result, providers, _ = await run(settings(search_provider="searxng", serper_api_key="offline-key", project_max_search_requests=2))
    assert result["progress"]["search_requests"] == sum(len(p.calls) for p in providers.values()) == 2
    assert result["diagnostics"]["search_budget_reached"]
    assert any(a["status"] == "budget_reached" and not a["network_attempted"] for a in attempts(result))


@pytest.mark.asyncio
async def test_gap_request_cancellation_preserves_trace_and_stays_within_original_deadline():
    active = 0
    async def blocked(*_args):
        nonlocal active
        active += 1
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
    started = time.monotonic()
    result, _, _ = await run(handlers={"searxng": empty, "serper": blocked}, deadline=.08)
    assert time.monotonic() - started < .3 and active == 0
    recovery = [a for a in attempts(result) if a["role"] == "recovery"]
    assert recovery and all(a["network_attempted"] for a in recovery)
    assert all(a["provider_requests"][0]["status"] == "cancelled" for a in recovery)


@pytest.mark.asyncio
async def test_shared_provider_scopes_keep_concurrent_warning_traces_separate_and_compact():
    async def observed(provider, query, _domains, trace):
        marker = hashlib.sha256(query.encode()).hexdigest()[:12]
        provider.last_warnings = [{"engine": marker, "reason_code": "timeout", "message": "SECRET"}]
        trace.update(engines_requested=marker, filter_counts={"off_domain": 2},
            candidate_trace=[{"title": "SECRET" * 10000, "url": "https://secret.example/?token=SECRET"}],
            url="https://secret.example/?token=SECRET", raw_candidate_count=3)
        await asyncio.sleep(.005)
        return good()
    result, providers, _ = await run(handlers={"searxng": observed, "serper": good})
    assert not providers["serper"].calls
    for row in result["diagnostics"]["searches"]:
        if not row.get("provider_attempts"):
            continue
        attempt = row["provider_attempts"][0]
        marker = hashlib.sha256(row["query"].encode()).hexdigest()[:12]
        assert attempt["provider_warnings"] == [{"engine": marker, "reason_code": "timeout"}]
        trace = attempt["provider_requests"][0]
        assert trace["engines_requested"] == marker and trace["raw_candidate_count"] == 3
        assert trace["filter_counts"] == {"off_domain": 2}
        assert "candidate_trace" not in trace and "url" not in trace
    assert "SECRET" not in str(result["diagnostics"])
    assert providers["searxng"].last_warnings == []  # Every query scope restored.


@pytest.mark.asyncio
@pytest.mark.parametrize("all_paused", [False, True])
async def test_primary_skips_only_when_every_selected_explicit_engine_group_is_paused(all_paused):
    config = settings(search_provider="searxng", ai_video_search_provider="default",
        searxng_engines=("primary",), searxng_video_engines=(), searxng_fallback_engines=("backup",))
    def configure(providers):
        providers["searxng"].engine_pauses = {"primary": time.monotonic() + 60,
            **({"backup": time.monotonic() + 60} if all_paused else {})}
    result, providers, _ = await run(config, {"searxng": good}, configure=configure)
    assert bool(providers["searxng"].calls) is not all_paused
    if all_paused:
        assert result["progress"]["search_requests"] == 0
        assert all(a["status"] == "skipped" and not a["network_attempted"] for a in attempts(result))
