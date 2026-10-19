"""Offline, synthetic-only tests for the bounded three-point live harness."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.providers import HTTPProvider, SearchBudgetReached, TavilyProvider
from scripts import verify_mooc_gaps_live as harness


def configuration(tmp_path, **extra):
    return Settings(database_path=str(tmp_path / "original.sqlite3"), tavily_api_key="offline-t-key",
        serper_api_key="offline-s-key", llm_api_key="offline-llm-key", searxng_url="https://search.test", **extra)


@pytest.mark.asyncio
async def test_dry_run_is_network_free_and_does_not_read_configuration(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Dry run used runtime or credentials")
    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "fetch_tavily_usage", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    output = tmp_path / "dry"
    result = await harness.run(output)
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert result["status"] == "dry_run" and not result["all_tests_finished"]
    assert result["search_http_requests"] == result["usage_http_requests"] == 0
    assert plan["source_request_caps"] == {"tavily": 18, "serper": 18, "searxng": 9}
    assert plan["knowledge_points"] == ["pandas 数据分组与聚合", "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
    assert plan["prior_artifacts_read"] is plan["known_urls_seeded"] is False
    with pytest.raises(FileExistsError):
        await harness.run(output)
    with pytest.raises(ValueError):
        await harness.run(harness.ROOT / "never-create")


def test_settings_keep_renderer_profile_while_bounding_each_stage(tmp_path):
    configured = configuration(tmp_path, js_render_enabled=True, js_render_allowed_hosts=("www.icourse163.org",),
        js_render_allowed_entries=("https://www.icourse163.org/course/",), js_render_timeout_seconds=17,
        js_render_max_target_requests=11, dns_resolver="cloudflare_doh", denied_fetch_hosts=("open.edu",))
    for stage, total, target, source in (("tavily", 27, 3, "tavily"), ("serper", 18, 3, "serper"), ("warm", 18, 1, "tavily")):
        settings = harness.isolated_settings(configured, tmp_path / "fresh.sqlite3", stage)
        assert settings.max_search_requests == total and settings.mooc_target_courses_per_point == target
        assert settings.search_provider_for("icourse163") == source
        assert settings.mooc_search_rounds == 6 and settings.bilibili_search_rounds == 3
        assert settings.max_detail_pages == 24 and settings.deadline_seconds == 300 and settings.search_results_per_query == 10
        assert settings.shared_course_library_enabled and settings.mooc_gap_search_enabled and settings.mooc_refresh_enabled
        assert settings.mooc_refresh_interval_seconds == 86400
        assert settings.llm_provider == "none" and not settings.llm_api_key and not settings.tavily_allow_keyless
        assert not settings.public_catalog_fallback and not settings.official_sitemap_fallback
        assert settings.js_render_enabled == configured.js_render_enabled
        assert settings.js_render_allowed_hosts == configured.js_render_allowed_hosts
        assert settings.js_render_allowed_entries == configured.js_render_allowed_entries
        assert settings.js_render_timeout_seconds == 17 and settings.js_render_max_target_requests == 11
        assert settings.dns_resolver == configured.dns_resolver and settings.denied_fetch_hosts == configured.denied_fetch_hosts


@pytest.mark.parametrize("plan,key,allowed", [(18, 18, True), (1000, "no_key_limit", True),
    (17, 100, False), (100, 17, False), ("unknown", 100, False), (100, "unknown", False), (True, 100, False)])
def test_preflight_requires_eighteen_free_credits_not_previous_eight(plan, key, allowed):
    assert harness.sufficient_free_usage({"allowed": True, "plan_remaining": plan, "key_remaining": key, "paygo_usage": 0}) is allowed
    assert not harness.sufficient_free_usage({"allowed": True, "plan_remaining": 1000, "key_remaining": 1000, "paygo_usage": 1})


@pytest.mark.asyncio
async def test_missing_serper_confirmation_does_not_even_query_tavily_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "fetch_tavily_usage", lambda *_: pytest.fail("Usage before confirmation"))
    result = await harness.run(tmp_path / "blocked", live=True, configured=configuration(tmp_path))
    assert result["status"] == "preflight_blocked" and result["reason"] == "serper_free_trial_not_confirmed"
    assert result["usage_http_requests"] == result["search_http_requests"] == 0


@pytest.mark.asyncio
async def test_usage_budget_failure_scrubs_every_return_and_stops_both_sources(tmp_path, monkeypatch):
    async def usage(_):
        return {"allowed": True, "plan_remaining": 17, "key_remaining": 1000, "paygo_usage": 0,
                "echo": "offline-t-key offline-s-key offline-llm-key"}
    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "Store", lambda *_: pytest.fail("Insufficient free allowance opened runtime"))
    result = await harness.run(tmp_path / "too-small", live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "preflight_blocked" and result["usage_http_requests"] == 1
    assert result["search_http_requests"] == 0 and "offline-t-key" not in json.dumps(result)
    assert "offline-s-key" not in json.dumps(result) and "offline-llm-key" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,used", [("warm", 0), ("serper", 0), ("tavily", 18)])
async def test_global_ledger_blocks_warm_wrong_stage_and_exhausted_source_before_http(stage, used):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Unauthorized source request"))) as client:
        provider = TavilyProvider(Settings(tavily_api_key="offline-key", search_min_interval_seconds=0), client)
        ledger = harness.SourceLedger()
        ledger.install({"tavily": provider})
        ledger.stage, ledger.total["tavily"] = stage, used
        with provider.query_scope(None):
            with pytest.raises(SearchBudgetReached):
                await provider.search("site:icourse163.org/course pandas", "zh", 10, ["icourse163.org"])
            assert provider.last_requests == []
        assert ledger.total["tavily"] == used


def install_sources(monkeypatch, *, mode="complete", interrupted=None):
    calls, fetches, objects, services = [], [], {}, []
    original_sleep = asyncio.sleep
    original_build, original_service = harness.build_provider, harness.JobService
    course_info = {}

    async def sleep(delay):
        await original_sleep(min(delay, .01))

    async def usage(_):
        return {"allowed": True, "current_plan": "researcher", "plan_remaining": 1000,
                "key_remaining": "no_key_limit", "paygo_usage": 0, "paygo_limit": None}

    def build(settings, **kwargs):
        source = kwargs["provider_name"]
        assert source not in objects
        objects[source] = original_build(settings, **kwargs)
        return objects[source]

    def service(*args, **kwargs):
        instance = original_service(*args, **kwargs)
        services.append(instance)
        return instance

    async def response(client, method, url, trace, **kwargs):
        source = "tavily" if "tavily" in url else "serper" if "serper" in url else "searxng"
        calls.append(source)
        if interrupted is not None:
            interrupted.set()
            await asyncio.Event().wait()
        await original_sleep(.005)
        if mode == "limited" and source == "tavily":
            return httpx.Response(429, headers={"retry-after": "3600"}, json={"results": []})
        query = kwargs["json"].get("query", kwargs["json"].get("q", "")) if "json" in kwargs else kwargs["params"]["q"]
        index = next((i for i, owner in enumerate(("pandas", "SQL", "HTML")) if owner in query), 0)
        if source == "searxng":
            rows = [{"title": harness.POINTS[index], "url": "https://www.bilibili.com/video/BV1VZ4y1G7YB/",
                     "content": harness.POINTS[index], "template": "videos.html"}]
        else:
            rows = []
            if mode != "empty":
                for offset in ([0] if source == "tavily" else [1, 2]):
                    course_id = str(1000 + index * 10 + offset)
                    link = "https://www.icourse163.org/course/OFFLINE-" + course_id
                    title = ("pandas数据处理", "SQL数据库", "HTML网页设计")[index]
                    course_info[link] = (course_id, title, index)
                    rows.append({"title": title, "url": link, "content": harness.POINTS[index]})
        if source == "serper":
            return httpx.Response(200, json={"organic": [{"title": row["title"], "link": row["url"], "snippet": row["content"]} for row in rows], "credits": 1})
        return httpx.Response(200, json={"results": rows, "usage": {"credits": 1}})

    class Fetcher:
        config = SimpleNamespace(max_retries=0)
        renderer = object()

        async def enrich(self, candidate):
            fetches.append(candidate["url"])
            await original_sleep(.005)
            if candidate["url"] not in course_info:
                return {"fetch_status": "policy_unreviewed", "evidence": []}
            course_id, title, index = course_info[candidate["url"]]
            chapters = (("数据分组", "聚合"), ("多表连接", "分组查询"), ("表单", "网页结构"))[index]
            term = {"id": "456", "outLineDto": {"outLine": "", "outLineStructureDtos": [
                {"name": chapter, "plan": "", "goals": ""} for chapter in chapters]}}
            page = ("<html><body><div id='j-course-heading-intro'><div class='course-heading-intro_intro'></div></div>"
                    "<div id='j-rectxt'>spContent=本课程讲授" + title + "，包含循序渐进的课程内容和练习。</div>"
                    "<div id='j-course-outline'></div><script>window.termDto = " + json.dumps(term)
                    + "; window.courseDto = " + json.dumps({"id": course_id, "name": title})
                    + ";</script></body></html>")
            return MetadataExtractor().extract(page, candidate["url"], now())

    fetcher = Fetcher()
    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "build_provider", build)
    monkeypatch.setattr(harness, "JobService", service)
    monkeypatch.setattr(harness, "make_fetcher", lambda _: fetcher)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", sleep)
    return calls, fetches, objects, services, fetcher


@pytest.mark.asyncio
async def test_two_explicit_sources_share_runtime_then_warm_spends_zero_and_keeps_evidence(tmp_path, monkeypatch):
    calls, fetches, objects, services, fetcher = install_sources(monkeypatch)
    original = tmp_path / "original.sqlite3"
    original.write_bytes(b"Original database must not be read")
    output = tmp_path / "live-mocked"
    result = await harness.run(output, live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_at_target" and result["all_tests_finished"]
    assert result["all_points_at_target"] and result["all_points_have_qualified_course"] and result["warm_demonstrated"]
    assert original.read_bytes() == b"Original database must not be read"
    assert len(services) == 1 and services[0].fetcher is fetcher
    assert all(services[0]._providers[name] is provider for name, provider in objects.items())
    assert calls.count("tavily") <= 18 and calls.count("serper") <= 18 and calls.count("searxng") <= 9
    assert result["source_ledger"]["actual_dispatch_reservations"] == {source: calls.count(source) for source in harness.SOURCE_CAPS}
    assert result["stages"]["warm"]["search_http_requests"] == 0
    assert result["stages"]["warm"]["stream"]["first_library_card_ms"] is not None
    assert all(row["library_cards"] >= 1 for row in result["stages"]["warm"]["per_point"])
    assert all(row["qualified_count"] >= 3 for row in result["library_coverage"])
    assert result["stages"]["tavily"]["new_verified_entries"] == 3
    assert result["stages"]["serper"]["new_verified_entries"] == 6
    assert all(row["bilibili_cards"] >= 1 for row in result["stages"]["tavily"]["per_point"])
    assert len({row["job_id"] for row in result["stages"].values()}) == 3
    assert result["database_backup"]["status"] == "saved" and (output / "library.sqlite3").is_file()
    for stage in ("tavily", "serper", "warm"):
        for name in ("job", "search_attempts", "network", "stream-events", "resources", "evidence", "results", "source-ledger"):
            assert (output / stage / (name + ".json")).is_file()
    text = json.dumps(result) + "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
    assert all(secret not in text for secret in ("offline-t-key", "offline-s-key", "offline-llm-key"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty", "limited"])
async def test_gaps_or_missing_recent_tavily_clock_skip_warm_without_claiming_coverage(tmp_path, monkeypatch, mode):
    calls, _, objects, services, _ = install_sources(monkeypatch, mode=mode)
    result = await harness.run(tmp_path / mode, live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_with_gaps" and result["all_tests_finished"]
    assert not result["all_points_at_target"] and not result["warm_demonstrated"]
    assert result["stages"]["warm"]["status"] == "not_demonstrated"
    assert result["stages"]["warm"]["search_http_requests"] == 0
    assert calls.count("tavily") == (1 if mode == "limited" else 18)
    assert calls.count("serper") == 18 and calls.count("searxng") <= 9
    if mode == "limited":
        assert objects["tavily"].paused_until > 0 and services[0]._providers["tavily"] is objects["tavily"]
        assert result["all_points_have_qualified_course"]
        assert not all(row["recent_tavily_refresh"] for row in result["warm_admission"]["per_point"])
    else:
        assert not result["all_points_have_qualified_course"]


@pytest.mark.asyncio
async def test_cancellation_exports_current_job_attempts_stream_and_database_without_starting_second_source(tmp_path, monkeypatch):
    reached = asyncio.Event()
    calls, _, _, _, _ = install_sources(monkeypatch, interrupted=reached)
    output = tmp_path / "cancelled"
    task = asyncio.create_task(harness.run(output, live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path)))
    await asyncio.wait_for(reached.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "interrupted" and not summary["all_tests_finished"]
    assert "serper" not in calls and "serper" not in summary["stages"]
    assert summary["stages"]["tavily"]["job_status"] == "interrupted"
    assert (output / "tavily" / "search_attempts.json").is_file()
    assert (output / "tavily" / "stream-events.json").is_file()
    assert (output / "library.sqlite3").is_file()
