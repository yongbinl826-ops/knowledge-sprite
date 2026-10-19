"""Offline harness checks using synthetic search/page observations, never live claims."""
import asyncio
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.providers import HTTPProvider
from scripts import verify_course_library_live as harness


@pytest.mark.asyncio
async def test_dry_run_is_network_free_and_refuses_overwrite_or_repository_output(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Dry run touched environment, network or database")

    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "fetch_tavily_usage", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    output = tmp_path / "dry"
    result = await harness.run(output)
    assert result["status"] == "dry_run"
    assert result["search_http_requests"] == result["usage_http_requests"] == result["llm_calls"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert plan["knowledge_points"] == ["pandas 数据分组与聚合"]
    assert plan["max_search_http_requests_per_phase"] == 5
    assert plan["max_mooc_http_requests_both_phases"] == 6
    assert plan["prior_artifacts_read"] is plan["known_urls_seeded"] is False
    with pytest.raises(FileExistsError):
        await harness.run(output)
    with pytest.raises(ValueError):
        await harness.run(harness.ROOT / "reports" / "must-not-create")


@pytest.mark.asyncio
@pytest.mark.parametrize("key,url,provider,reason", [
    ("", "http://search.test", "searxng", "missing_configuration"),
    ("t-key", "", "searxng", "missing_configuration"),
    ("t-key", "http://search.test", "serper", "bilibili_provider_not_searxng"),
])
async def test_preflight_missing_config_never_makes_usage_or_source_request(tmp_path, monkeypatch, key, url, provider, reason):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid preflight touched runtime")

    monkeypatch.setattr(harness, "fetch_tavily_usage", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    result = await harness.run(tmp_path / "blocked", live=True,
        configured=Settings(tavily_api_key=key, searxng_url=url, bilibili_search_provider=provider))
    assert result["status"] == "preflight_blocked" and result["reason"] == reason
    assert result["search_http_requests"] == result["usage_http_requests"] == 0


def test_isolated_settings_bound_free_search_and_preserve_source_policy(tmp_path):
    configured = Settings(database_path="never-open.sqlite3", tavily_api_key="t-key", serper_api_key="s-key",
        llm_api_key="llm-key", llm_provider="openai_compatible", searxng_url="http://search.test",
        denied_fetch_hosts=("open.edu",), dns_resolver="cloudflare_doh", bilibili_public_metadata=True)
    result = harness.isolated_settings(configured, tmp_path / "fresh.sqlite3")
    assert result.max_search_requests == 5 and result.max_detail_pages == 8 and result.deadline_seconds == 180
    assert result.bilibili_search_rounds == 2 and result.mooc_search_rounds == 3
    assert result.shared_course_library_enabled and result.mooc_gap_search_enabled and result.mooc_target_courses_per_point == 1
    assert result.search_provider_for("icourse163") == "tavily" and result.search_provider_for("bilibili") == "searxng"
    assert not result.tavily_allow_keyless and result.llm_provider == "none" and not result.llm_api_key
    assert not result.official_sitemap_fallback and not result.public_catalog_fallback and not result.js_render_enabled
    assert result.denied_fetch_hosts == configured.denied_fetch_hosts and result.dns_resolver == configured.dns_resolver
    assert result.bilibili_public_metadata and configured.database_path == "never-open.sqlite3"


@pytest.mark.asyncio
async def test_usage_denial_blocks_sources_and_scrubs_return_value(tmp_path, monkeypatch):
    async def usage(_):
        return {"allowed": False, "reason": "usage_http_error", "http_status": 429, "echo": "t-key s-key llm-key"}

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "Store", lambda *_: pytest.fail("Usage denial opened database"))
    result = await harness.run(tmp_path / "denied", live=True,
        configured=Settings(tavily_api_key="t-key", serper_api_key="s-key", llm_api_key="llm-key", searxng_url="http://search.test"))
    assert result["status"] == "preflight_blocked"
    assert result["usage_http_requests"] == 1 and result["search_http_requests"] == 0
    assert all(secret not in json.dumps(result) for secret in ("t-key", "s-key", "llm-key"))


def install_mock_sources(monkeypatch, *, course=True, denied_status=None):
    calls, fetched = [], []
    original_sleep = asyncio.sleep

    async def short_sleep(delay):
        await original_sleep(min(delay, .02))

    async def usage(_):
        return {"allowed": True, "current_plan": "researcher", "plan_remaining": 1000,
                "paygo_usage": 0, "paygo_limit": None}

    async def response(client, method, url, trace, **kwargs):
        source = "tavily" if "tavily" in url else "searxng"
        calls.append(source)
        await original_sleep(.01)
        if source == "tavily" and denied_status:
            return httpx.Response(denied_status, headers={"retry-after": "3600"}, json={"results": []})
        if source == "tavily":
            rows = [{"title": "pandas 数据处理", "url": "https://www.icourse163.org/course/OFFLINE-123",
                     "content": "pandas 数据分组与聚合 课程教学"}] if course else []
        else:
            rows = [{"title": "pandas 数据分组与聚合", "url": "https://www.bilibili.com/video/BV1VZ4y1G7YB/",
                     "content": "pandas 数据分组与聚合 视频教程", "template": "videos.html"}]
        return httpx.Response(200, json={"results": rows, "usage": {"credits": 1}})

    class Fetcher:
        config = SimpleNamespace(max_retries=0)

        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            await original_sleep(.02)
            if "icourse163" not in candidate["url"]:
                return {"fetch_status": "policy_unreviewed", "evidence": []}
            term = {"id": "456", "outLineDto": {"outLine": "", "outLineStructureDtos": [
                {"name": "使用pandas进行数据分组与聚合", "plan": "", "goals": ""}]}}
            page = ("<html><body><div id='j-course-heading-intro'><div class='course-heading-intro_intro'></div></div>"
                    "<div id='j-rectxt'>spContent=本课程讲授pandas数据处理，包含循序渐进的课程内容和练习。</div>"
                    "<div id='j-course-outline'></div><script>window.termDto = " + json.dumps(term)
                    + "; window.courseDto = " + json.dumps({"id": "123", "name": "pandas数据处理"})
                    + ";</script></body></html>")
            return MetadataExtractor().extract(page, candidate["url"], now())

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "make_fetcher", lambda _: Fetcher())
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", short_sleep)
    return calls, fetched


@pytest.mark.asyncio
async def test_real_services_observe_cold_course_then_distinct_warm_job_with_no_mooc_http(tmp_path, monkeypatch):
    calls, fetched = install_mock_sources(monkeypatch)
    original = tmp_path / "user.sqlite3"
    original.write_bytes(b"User database never opened")
    output = tmp_path / "observed"
    result = await harness.run(output, live=True,
        configured=Settings(database_path=str(original), tavily_api_key="t-key", serper_api_key="s-key",
                            llm_api_key="llm-key", searxng_url="http://search.test"))
    assert original.read_bytes() == b"User database never opened"
    assert result["status"] == "completed" and result["reuse"]["status"] == "demonstrated"
    cold, warm = result["phases"]["cold"], result["phases"]["warm"]
    assert cold["job_id"] != warm["job_id"] and cold["job_terminal"] and warm["job_terminal"]
    assert cold["progress"]["library_courses_saved"] == 1
    assert cold["platforms"]["icourse163"]["search_http_requests"] == 1
    assert warm["platforms"]["icourse163"]["search_http_requests"] == 0
    assert warm["platforms"]["icourse163"]["search_slots_skipped"] == 3
    assert warm["platforms"]["icourse163"]["library_cards"] == warm["platforms"]["icourse163"]["outline_supported_cards"] == 1
    assert warm["progress"]["library_courses_reused"] == warm["progress"]["library_hit_pairs"] == 1
    assert calls.count("tavily") == 1 and sum("icourse163" in url for url in fetched) == 1
    assert warm["stream"]["first_library_card_ms"] is not None and warm["stream"]["complete_received"]
    assert warm["stream"]["displayed_mooc_without_outline_count"] == 0
    assert cold["platforms"]["bilibili"]["displayed_unique_courses"] == warm["platforms"]["bilibili"]["displayed_unique_courses"] == 1
    assert result["database_backup"]["status"] == "saved"
    with sqlite3.connect(output / "library.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM shared_mooc_courses WHERE status='verified'").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    text = json.dumps(result) + "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
    assert all(secret not in text for secret in ("t-key", "s-key", "llm-key"))


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_status", [None, 429, 403])
async def test_empty_or_limited_cold_run_never_spends_again_for_unproven_warm_phase(tmp_path, monkeypatch, denied_status):
    calls, _ = install_mock_sources(monkeypatch, course=False, denied_status=denied_status)
    result = await harness.run(tmp_path / "no-course", live=True,
        configured=Settings(tavily_api_key="t-key", searxng_url="http://search.test"))
    assert result["status"] == "not_demonstrated" and result["reuse"]["status"] == "not_demonstrated"
    assert result["reuse"]["mooc_http_requests_saved"] == "unknown"
    assert result["phases"]["warm"]["status"] == "not_demonstrated"
    assert result["phases"]["warm"]["search_http_requests"] == 0
    assert calls.count("tavily") == (1 if denied_status else 3)
    assert calls.count("searxng") == 2
    assert not (tmp_path / "no-course" / "warm").exists()


def test_backup_omits_database_if_an_external_source_echoed_known_key(tmp_path):
    store = Store(str(tmp_path / "sensitive.sqlite3"))
    try:
        store.connection.execute("CREATE TABLE external_echo(value TEXT)")
        store.connection.execute("INSERT INTO external_echo VALUES(?)", ("offline-key",))
        store.connection.commit()
        target = tmp_path / "backup.sqlite3"
        result = harness.backup_library(store, target, ("offline-key",))
        assert result["status"] == "omitted_sensitive_content" and not target.exists()
        assert "offline-key" not in json.dumps(result)
    finally:
        store.close()


def test_stream_does_not_claim_nonterminal_display_from_terminal_only_card():
    payload = {"job": {"status": "completed"}, "pipeline": {"terminal": True}, "groups": [
        {"discovery_platform_items": {"icourse163": [{"resource": {"resource_id": "course"},
          "discovery_evidence": [{"kind": "course_library", "source": "shared_course_library"}],
          "mooc_relevance": {"status": "outline_supported", "display_eligible": True}}]}}]}
    message = "event: snapshot\ndata: " + json.dumps(payload) + "\n\n"
    row = harness.frame_observation(message, 350)
    summary = harness.summarize_stream([row])
    assert summary["first_library_card_ms"] == 350
    assert summary["first_nonterminal_library_card_ms"] is None
    assert not summary["library_card_observed_before_completion"]
