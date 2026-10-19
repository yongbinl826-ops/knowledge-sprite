"""Synthetic, no-network continuation harness checks; never a live result."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from backend.app.platform_search import platform_query
from backend.app.providers import SearchBudgetReached, TavilyProvider
from scripts import verify_mooc_target_three_live as harness
from test_mooc_gaps_live_harness import configuration, install_sources
from test_course_library import observed


@pytest.fixture(autouse=True)
def no_environment_or_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline harness test read credentials or attempted external transport")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def prior(tmp_path):
    root = tmp_path / "prior"
    for stage in harness.PRIOR_STAGES:
        folder = root / stage
        folder.mkdir(parents=True)
        source = "serper" if stage == "live/serper" else "tavily"
        documents = {
            "summary": {"job_terminal": True, "error_type": None, "source_states": {
                name: {"source_access_denied": False, "source_cooldown_seconds": 0, "engine_cooldowns": {}}
                for name in ("tavily", "serper")}},
            "job": {"status": "completed", "phase": "done"},
            "search_attempts": [{"provider": source, "status": "completed", "network_attempted": True,
                "provider_requests": [{"provider": source, "http_status": 200, "status": "completed"}]}],
            "resources": {}, "evidence": {}, "network": {"target_http_requests": 0, "responses": []},
        }
        for name, value in documents.items():
            (folder / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
    source = root / "route-recheck" / "library.sqlite3"
    store = Store(str(source))
    store.connection.execute("CREATE TABLE original_private(value TEXT)")
    store.connection.execute("INSERT INTO original_private VALUES('leave unchanged')")
    store.connection.commit()
    store.close()
    return root, source


def change(root, stage, name, update):
    path = root / stage / (name + ".json")
    value = json.loads(path.read_text(encoding="utf-8"))
    update(value)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.asyncio
async def test_default_dry_run_requires_explicit_paths_without_runtime_or_network(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    before = source.read_bytes()
    monkeypatch.setattr(harness, "Store", lambda *_: pytest.fail("Dry run opened writable database"))
    monkeypatch.setattr(harness, "fetch_tavily_usage", lambda *_: pytest.fail("Dry run queried quota"))
    output = tmp_path / "dry"
    result = await harness.run(output, source_database=source, prior_evidence=evidence)
    assert result["status"] == "dry_run" and result["search_http_requests"] == result["usage_http_requests"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert plan["source_request_caps"] == {"tavily": 18, "serper": 18, "bilibili": 0}
    assert plan["stages"] == ["cache_tavily", "cache_serper", "tavily_mooc", "serper_mooc", "warm"]
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        await harness.run(output, source_database=source, prior_evidence=evidence)
    with pytest.raises(ValueError):
        await harness.run(harness.ROOT / "never-create", source_database=source, prior_evidence=evidence)
    with pytest.raises(ValueError):
        await harness.run(tmp_path / "relative", source_database=Path("relative.sqlite3"), prior_evidence=evidence)


def test_settings_keep_renderer_and_bilibili_configuration_with_new_bounded_mooc_stages(tmp_path):
    config = configuration(tmp_path, bilibili_search_provider="searxng", bilibili_search_rounds=4,
                           js_render_enabled=True, js_render_max_target_requests=13)
    for stage in harness.STAGE_SOURCES:
        settings = harness.isolated_settings(config, tmp_path / "clone.sqlite3", stage)
        assert settings.max_search_requests == 18 and settings.max_detail_pages == 36 and settings.deadline_seconds == 360
        assert settings.mooc_target_courses_per_point == 3 and settings.mooc_search_rounds == 6 and settings.search_results_per_query == 10
        assert settings.bilibili_search_provider == config.bilibili_search_provider and settings.bilibili_search_rounds == 4
        assert settings.js_render_enabled and settings.js_render_max_target_requests == 13
        assert settings.mooc_search_provider == harness.STAGE_SOURCES[stage]
        assert settings.mooc_refresh_enabled is (stage != "warm")
        assert settings.llm_provider == "none" and not settings.llm_api_key
        assert not settings.public_catalog_fallback and not settings.official_sitemap_fallback


def test_prior_audit_accepts_only_bound_proof_that_old_route_block_sent_no_request(tmp_path):
    evidence, _ = prior(tmp_path)
    assert harness.audit_prior_evidence(evidence)["allowed"]
    url = "https://www.icourse163.org/course/OLD-123?outVendor=observed"
    resource = {"url": url, "fetch_status": "policy_unreviewed", "field_provenance": {
        "fetch_status": {"evidence_id": "bound", "source": "official_policy_review"}}}
    proof = {"evidence_id": "bound", "kind": "site_policy", "source": "official_policy_review",
             "blocked_target_url": url, "restricted_target_request_sent": False, "restricted_target_http_status": None}
    change(evidence, "live/tavily", "resources", lambda d: d.update(r=resource))
    change(evidence, "live/tavily", "evidence", lambda d: d.update(r=[proof]))
    result = harness.audit_prior_evidence(evidence)
    assert result["allowed"] and result["local_route_rejections"] == 1
    change(evidence, "live/tavily", "evidence", lambda d: d["r"][0].update(restricted_target_request_sent=True))
    assert not harness.audit_prior_evidence(evidence)["allowed"]


@pytest.mark.parametrize("damage", ["missing", "unfinished", "source_pause", "source_denied", "provider_429",
    "provider_uncertain", "target_403", "captcha", "policy_unproven", "host_stop", "bad_shape"])
def test_prior_restrictions_and_incomplete_evidence_fail_closed(tmp_path, damage):
    evidence, _ = prior(tmp_path)
    if damage == "missing":
        (evidence / "live/serper/network.json").unlink()
    elif damage == "unfinished":
        change(evidence, "live/tavily", "job", lambda d: d.update(status="running"))
    elif damage in {"source_pause", "source_denied"}:
        change(evidence, "live/tavily", "summary", lambda d: d["source_states"]["tavily"].update(
            {"source_cooldown_seconds": 20} if damage == "source_pause" else {"source_access_denied": True}))
    elif damage in {"provider_429", "provider_uncertain"}:
        change(evidence, "live/serper", "search_attempts", lambda d: d[0]["provider_requests"][0].update(
            http_status=429 if damage == "provider_429" else None))
    elif damage == "target_403":
        change(evidence, "route-recheck/sql", "network", lambda d: d["responses"].append(
            {"url": "https://www.icourse163.org/course/OLD-123", "http_status": 403}))
    elif damage in {"captcha", "policy_unproven"}:
        change(evidence, "live/tavily", "resources", lambda d: d.update(r={
            "url": "https://www.icourse163.org/course/OLD-123", "fetch_status": "captcha" if damage == "captcha" else "policy_unreviewed"}))
    elif damage == "host_stop":
        change(evidence, "live/tavily", "summary", lambda d: d.update(fetch_host_controls={"blocked_hosts": ["www.icourse163.org"]}))
    elif damage == "bad_shape":
        (evidence / "live/tavily/resources.json").write_text("[]", encoding="utf-8")
    result = harness.audit_prior_evidence(evidence)
    assert not result["allowed"] and result["reasons"]


@pytest.mark.asyncio
async def test_restricted_prior_evidence_blocks_before_quota_and_source_requests(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    change(evidence, "live/tavily", "summary", lambda d: d["source_states"]["tavily"].update(source_access_denied=True))
    monkeypatch.setattr(harness, "fetch_tavily_usage", lambda *_: pytest.fail("Restricted source was queried"))
    result = await harness.run(tmp_path / "blocked", source_database=source, prior_evidence=evidence,
        live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "preflight_blocked" and result["usage_http_requests"] == result["search_http_requests"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,count", [("cache_tavily", 0), ("cache_serper", 0), ("warm", 0), ("serper_mooc", 0), ("tavily_mooc", 18)])
async def test_ledger_prevents_cache_warm_wrong_provider_and_nineteenth_request(stage, count):
    provider = TavilyProvider(Settings(tavily_api_key="offline-only", search_min_interval_seconds=0))
    ledger = harness.SourceLedger()
    ledger.install({"tavily": provider})
    ledger.stage, ledger.total["tavily"] = stage, count
    with provider.query_scope(None):
        with pytest.raises(SearchBudgetReached):
            await provider.search("site:icourse163.org/course pandas", "zh", 10, ["icourse163.org"])
        assert not provider.last_requests
    assert ledger.total["tavily"] == count


def test_numeric_coverage_never_counts_aliases_or_terms_as_separate_courses():
    urls = ["https://www.icourse163.org/course/A-123", "https://www.icourse163.org/course/B-123?tid=456",
            "https://www.icourse163.org/course/detail.htm?cid=123&tid=789", "https://www.icourse163.org/course/C-124"]
    hits = [{"resource": {"url": url, "title": "Synthetic"}, "entry_key": str(i)} for i, url in enumerate(urls)]
    service = SimpleNamespace(course_library=SimpleNamespace(lookup=lambda *args, **kwargs: hits),
        _course_library_profile=lambda: "profile", settings=SimpleNamespace(shared_course_library_max_candidates=100))
    assert all(row["qualified_count"] == 2 and row["remaining"] == 1 for row in harness.numeric_coverage(service))


def install_continuation_sources(monkeypatch, **options):
    result = install_sources(monkeypatch, **options)
    for name in ("build_provider", "JobService", "make_fetcher", "fetch_tavily_usage"):
        monkeypatch.setattr(harness, name, getattr(harness.base, name))
    return result


@pytest.mark.asyncio
async def test_mocked_continuation_has_four_mooc_stages_shared_controls_then_three_course_warm(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    original = source.read_bytes()
    calls, fetches, providers, services, fetcher = install_continuation_sources(monkeypatch)
    output = tmp_path / "continued"
    result = await harness.run(output, source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_at_target" and result["all_tests_finished"] and result["warm_demonstrated"]
    assert source.read_bytes() == original
    assert len(services) == 1 and services[0].fetcher is fetcher
    assert all(services[0]._providers[name] is provider for name, provider in providers.items())
    assert "searxng" not in calls and all("icourse163.org" in url for url in fetches)
    assert calls.count("tavily") <= 18 and calls.count("serper") <= 18
    assert result["source_ledger"]["actual_dispatch_reservations"] == {"tavily": calls.count("tavily"), "serper": calls.count("serper"), "bilibili": 0}
    for name in ("cache_tavily", "cache_serper", "warm"):
        assert result["stages"][name]["search_http_requests"] == 0
    assert all(row["qualified_count"] == 3 for row in result["library_coverage"])
    assert all(row["library_cards"] >= 3 for row in result["stages"]["warm"]["per_point"])
    assert len({row["job_id"] for row in result["stages"].values()}) == 5
    for stage in harness.STAGE_SOURCES:
        for name in ("job", "search_attempts", "network", "stream-events", "resources", "evidence", "results", "source-ledger", "host-controls"):
            assert (output / stage / (name + ".json")).is_file()
    combined = json.dumps(result) + "".join(p.read_text(encoding="utf-8") for p in output.rglob("*.json"))
    assert all(key not in combined for key in ("offline-t-key", "offline-s-key", "offline-llm-key"))
    assert (output / "library.sqlite3").is_file()


@pytest.mark.asyncio
async def test_limited_source_stays_stopped_and_shortfall_is_not_reported_as_success(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    calls, _, providers, _, _ = install_continuation_sources(monkeypatch, mode="limited")
    result = await harness.run(tmp_path / "limited", source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_with_gaps" and not result["warm_demonstrated"]
    assert calls.count("tavily") == 1 and providers["tavily"].paused_until > 0 and "searxng" not in calls
    assert result["stages"]["warm"]["status"] == "not_demonstrated"


@pytest.mark.asyncio
async def test_both_original_source_caches_are_replayed_before_new_searches_without_fresh_timestamps(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    config = configuration(tmp_path)
    store = Store(str(source))
    settings = harness.isolated_settings(config, source, "cache_tavily")
    inert = object()
    service = harness.JobService(settings, store, provider=inert, fetcher=inert, llm=inert,
        provider_overrides={"searxng": inert, "tavily": inert, "serper": inert})
    request = SearchRequest(knowledge_points=harness.POINTS, preferred_platforms=["icourse163"], language="zh")
    cached = {}
    for source_index, provider in enumerate(("tavily", "serper")):
        for index, text in enumerate(harness.POINTS):
            point = {"knowledge_point_id": "prior-point-" + str(index), "text": text}
            query = platform_query(point, "icourse163", request)
            url = "https://www.icourse163.org/course/CACHED-" + str(2000 + index * 10 + source_index)
            title = ("pandas数据处理", "SQL数据库", "HTML网页设计")[index]
            candidate = Candidate(id="cached-" + provider + str(index), title=title, url=url,
                snippet=text, source=provider, query=query.query, resource_type_hint="course")
            key = store.cache_key("search", {"policy": "platform-rounds-v2", **service._search_identity(provider),
                "original_point": text, "query": query.query, "domains": query.domain_filters, "language": "zh", "limit": 10})
            store.cache_set(key, "search", {"candidates": [candidate.model_dump()], "upstream_warnings": []}, 21600)
            cached[url] = (title, index)
    old_rows = [tuple(row) for row in store.connection.execute("SELECT key,created,expires FROM cache ORDER BY key")]
    store.close()
    calls, fetches, _, _, fetcher = install_continuation_sources(monkeypatch, mode="empty")
    original_enrich = fetcher.enrich
    async def enrich(candidate):
        if candidate["url"] not in cached:
            return await original_enrich(candidate)
        fetches.append(candidate["url"])
        title, index = cached[candidate["url"]]
        chapters = (("数据分组", "聚合"), ("多表连接", "分组查询"), ("表单", "网页结构"))[index]
        resource, observations = observed(chapters=chapters, title=title, url=candidate["url"], timestamp=time.time() - 10)
        return {**resource, "evidence": observations}
    fetcher.enrich = enrich
    output = tmp_path / "cache-replay"
    result = await harness.run(output, source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=config)
    for stage in ("cache_tavily", "cache_serper"):
        assert result["stages"][stage]["search_http_requests"] == 0
        assert result["stages"][stage]["new_verified_entries"] == 3
        assert sum(row["cache_hits"] for row in result["stages"][stage]["sources"].values()) == 3
    assert all(row["qualified_count"] == 2 for row in result["library_coverage"])
    assert result["status"] == "finished_with_gaps" and not result["warm_demonstrated"]
    connection = sqlite3.connect((output / "library.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        for key, created, expires in old_rows:
            assert connection.execute("SELECT created,expires FROM cache WHERE key=?", (key,)).fetchone() == (created, expires)
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_interruption_exports_current_evidence_and_backup_before_second_fresh_source(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    reached = asyncio.Event()
    calls, *_ = install_continuation_sources(monkeypatch, interrupted=reached)
    output = tmp_path / "cancel"
    task = asyncio.create_task(harness.run(output, source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path)))
    await asyncio.wait_for(reached.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["status"] == "interrupted" and not result["all_tests_finished"] and "serper" not in calls
    assert (output / "tavily_mooc/job.json").is_file() and (output / "library.sqlite3").is_file()
