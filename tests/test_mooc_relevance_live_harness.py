"""Offline checks for the explicit, credential-free live relevance harness."""
import hashlib
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import HTTPProvider
from scripts import verify_mooc_relevance_live as harness


@pytest.mark.asyncio
async def test_dry_run_does_not_load_environment_construct_runtime_or_touch_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry run touched configuration, runtime, or network")

    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "JobService", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", forbidden)
    output = tmp_path / "dry"
    result = await harness.run(output)
    assert result["status"] == "dry_run"
    assert result["search_http_requests"] == result["detail_target_http_requests"] == result["llm_calls"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert plan["knowledge_points"] == ["Python 列表与字典", "pandas 数据分组与聚合",
                                         "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
    assert plan["manual_gold_labels"] is False and plan["precision"] == plan["recall"] == "unknown"
    assert plan["source_sha256"]["scripts/verify_mooc_relevance_live.py"] == hashlib.sha256(
        (harness.ROOT / "scripts/verify_mooc_relevance_live.py").read_bytes()).hexdigest()
    before = (output / "plan.json").read_bytes()
    with pytest.raises(FileExistsError):
        await harness.run(output, live=True)
    assert (output / "plan.json").read_bytes() == before


def test_live_settings_remove_keys_bound_costs_and_preserve_source_transport_rules(tmp_path):
    original = Settings(database_path="original.sqlite3", searxng_url="http://127.0.0.1:18888",
        tavily_api_key="account-secret", llm_api_key="llm-secret", llm_provider="openai_compatible",
        max_search_requests=99, max_detail_pages=99, deadline_seconds=900, search_max_retries=3,
        teaching_match_enabled=True, teaching_match_max_calls_per_job=10, project_semantic_review_enabled=True,
        js_render_enabled=True, official_sitemap_fallback=True, public_catalog_fallback=True,
        bilibili_public_metadata=True, searxng_video_engines=("duckduckgo videos",),
        searxng_engines=("bing",), denied_fetch_hosts=("open.edu",), dns_resolver="cloudflare_doh")
    settings = harness.isolated_settings(original, tmp_path / "isolated.sqlite3")
    assert original.tavily_api_key == "account-secret" and original.database_path == "original.sqlite3"
    assert settings.tavily_api_key == settings.llm_api_key == "" and settings.llm_provider == "none"
    assert settings.tavily_allow_keyless and settings.search_provider_for("bilibili") == "searxng"
    assert settings.search_provider_for("icourse163") == "tavily"
    assert settings.max_search_requests == 16 and settings.max_detail_pages == 12 and settings.deadline_seconds == 250
    assert settings.search_max_retries == 0 and settings.search_min_interval_seconds == settings.fetch_min_interval_seconds == 2
    assert not settings.teaching_match_enabled and settings.teaching_match_max_calls_per_job == 0
    assert not settings.js_render_enabled and not settings.official_sitemap_fallback and not settings.public_catalog_fallback
    assert not settings.project_semantic_review_enabled and not settings.allow_stale_cache
    assert settings.searxng_video_engines == original.searxng_video_engines
    assert settings.searxng_engines == original.searxng_engines
    assert settings.bilibili_public_metadata and settings.denied_fetch_hosts == original.denied_fetch_hosts
    assert settings.dns_resolver == original.dns_resolver


@pytest.mark.asyncio
async def test_missing_searxng_blocks_before_runtime_or_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight failure touched runtime")

    monkeypatch.setattr(harness, "Store", forbidden)
    monkeypatch.setattr(harness, "JobService", forbidden)
    result = await harness.run(tmp_path / "preflight", live=True,
                               configured=Settings(tavily_api_key="secret", llm_api_key="secret"))
    assert result["status"] == "preflight_blocked"
    assert result["reason"] == "SEARXNG_URL_not_configured"


@pytest.mark.asyncio
async def test_real_jobservice_mock_transport_is_free_bounded_isolated_and_preplanned(tmp_path, monkeypatch):
    calls = []
    output = tmp_path / "integration"

    async def no_sleep(_):
        pass

    async def response(client, method, url, trace, **kwargs):
        # Every transport request observes a plan sealed before runtime began.
        plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
        assert plan["source_sha256"]["backend/app/service.py"]
        assert plan["overrides"]["max_search_requests"] == 16
        calls.append((url, kwargs))
        if "tavily" in url:
            assert kwargs["headers"]["X-Tavily-Access-Mode"] == "keyless"
            assert not any(name.lower() == "authorization" for name in kwargs["headers"])
        assert "account-secret" not in str(kwargs) and "llm-secret" not in str(kwargs)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    original = tmp_path / "untouched.sqlite3"
    original.write_bytes(b"Original user database is not opened.")
    result = await harness.run(output, live=True,
        configured=Settings(database_path=str(original), searxng_url="http://127.0.0.1:18888",
                            tavily_api_key="account-secret", llm_api_key="llm-secret"))
    assert original.read_bytes() == b"Original user database is not opened."
    assert 0 < len(calls) <= 16 and result["search_http_requests"] == len(calls)
    assert result["account_credentials_sent"] is False
    assert result["detail_target_http_requests"] == result["llm_calls"] == 0
    assert len(result["per_point"]) == 4
    assert result["relevance"]["original_type_only_discovery_count"] == result["relevance"]["filtered_discovery_count"] == 0
    attempts = json.loads((output / "search_attempts.json").read_text(encoding="utf-8"))
    assert {row["provider"] for row in attempts if row["platform"] == "bilibili"} == {"searxng"}
    assert {row["provider"] for row in attempts if row["platform"] == "icourse163"} == {"tavily"}
    assert all(not row.get("cache_hit") for row in attempts)
    all_text = "".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    assert "account-secret" not in all_text and "llm-secret" not in all_text
    assert not list(output.rglob("*.sqlite3"))


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_status", [403, 429, 432])
async def test_mooc_denial_or_quota_stops_without_stopping_bilibili(tmp_path, monkeypatch, blocked_status):
    seen = {"tavily": 0, "searxng": 0}

    async def no_sleep(_):
        pass

    async def response(client, method, url, trace, **kwargs):
        provider = "tavily" if "tavily" in url else "searxng"
        seen[provider] += 1
        return httpx.Response(blocked_status if provider == "tavily" else 200,
                              headers={"Retry-After": "3600"}, json={"results": []})

    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    result = await harness.run(tmp_path / "blocked", live=True,
                               configured=Settings(searxng_url="http://127.0.0.1:18888"))
    assert seen["tavily"] == 1 and 4 <= seen["searxng"] <= 8
    assert result["search_http_requests"] <= 16
    assert result["source_states"]["searxng"]["source_access_denied"] is False


def example(resource_id="course1", point_id="p1"):
    url = f"https://www.icourse163.org/course/COURSE-{1 if resource_id == 'course1' else 2}"
    search = {"evidence_id": f"search-{resource_id}", "kind": "search", "source": "tavily",
              "knowledge_point_id": point_id, "url": url, "title": "Python 编程", "snippet": "列表与字典"}
    resource = {"resource_id": resource_id, "platform": "icourse163", "resource_type": "course",
                "url": url, "canonical_url": url, "title": "Python 编程", "fetch_status": "not_fetched",
                "chapters": [], "field_provenance": {"resource_type": {
                    "source": "url_pattern", "evidence_id": search["evidence_id"]}}}
    return resource, search


@pytest.mark.parametrize("change", ["different_point", "different_url", "missing_id", "missing_title", "not_found", "unknown_type"])
def test_type_only_baseline_preserves_original_evidence_gate(change):
    point = {"knowledge_point_id": "p1", "text": "Python 列表与字典"}
    resource, search = example()
    assert harness.type_only_eligible(point, resource, [search])
    if change == "different_point":
        search["knowledge_point_id"] = "p2"
    elif change == "different_url":
        search["url"] = "https://www.icourse163.org/course/OTHER-999"
    elif change == "missing_id":
        search.pop("evidence_id")
    elif change == "missing_title":
        search.pop("title")
    elif change == "not_found":
        resource["fetch_status"] = "not_found"
    else:
        resource["resource_type"] = "unknown"
    assert not harness.type_only_eligible(point, resource, [search])


def test_quality_compares_same_observations_and_never_borrows_cross_point_evidence(monkeypatch):
    import backend.app.mooc_relevance as relevance
    points = [{"knowledge_point_id": "p1", "text": "Python 列表与字典"},
              {"knowledge_point_id": "p2", "text": "pandas 数据分组与聚合"}]
    resource, first_search = example()
    other, other_search = example("course2")
    second_search = {**first_search, "knowledge_point_id": "p2", "evidence_id": "other-point"}
    observed = []

    def assessment(point, row, rows):
        observed.append((point["knowledge_point_id"], row["resource_id"], rows))
        supported = row["resource_id"] == "course1" and point["knowledge_point_id"] == "p1"
        return {"status": "outline_supported" if supported else "rejected", "display_eligible": supported,
                "probe_eligible": False, "reason_codes": [], "subtopics": [],
                "matched_chapters": [{"title": "列表", "evidence_id": "chapter1"}] if supported else [],
                "evidence_ids": ["chapter1"] if supported else []}

    monkeypatch.setattr(relevance, "assess_mooc_relevance", assessment)
    results = {"groups": [{**points[0], "discovery_platform_items": {
        "icourse163": [{"resource": resource}], "bilibili": [{"resource": {"resource_id": "b1"}}]}}]}
    report = harness.assess_candidates({"knowledge_points": points},
        {"course1": resource, "course2": other},
        {"course1": [first_search, second_search], "course2": [other_search]}, results)
    assert len(observed) == 3
    assert all(all(row.get("knowledge_point_id") in {None, point_id} for row in rows)
               for point_id, _, rows in observed)
    assert report["original_type_only_discovery_count"] == 3
    assert report["filtered_discovery_count"] == report["actually_displayed_count"] == 1
    assert report["displayed_without_eligible_assessment_count"] == 0
    assert report["per_point"][0]["removed_resource_ids"] == ["course2"]
    assert report["per_point"][0]["bilibili_discovery_count"] == 1
    assert report["per_point"][0]["displayed_evidence"][0]["evidence_ids"] == ["chapter1"]
    assert report["precision"] == report["recall"] == "unknown" and not report["manual_gold_labels"]
