"""Offline verification of the opt-in real HTTP/SSE observation harness."""
import asyncio
import hashlib
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import HTTPProvider
from scripts import verify_streaming_recall_live as harness


async def lines(*values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_dry_run_seals_plan_without_environment_runtime_or_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry run touched configuration or network")
    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "loopback_server", forbidden)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", forbidden)
    output = tmp_path / "dry"
    summary = await harness.run(output)
    assert summary["status"] == "dry_run"
    assert summary["search_http_requests"] == summary["detail_target_http_requests"] == summary["stream_events"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert plan["knowledge_points"] == ["pandas 数据分组与聚合", "Python 列表与字典"]
    assert plan["planned_search_requests"] == 16
    assert plan["overrides"]["search_results_per_query"] == 12
    assert plan["overrides"]["max_detail_pages"] == 60
    assert plan["source_sha256"]["scripts/verify_streaming_recall_live.py"] == hashlib.sha256(
        (harness.ROOT / "scripts/verify_streaming_recall_live.py").read_bytes()).hexdigest()
    before = (output / "plan.json").read_bytes()
    with pytest.raises(FileExistsError):
        await harness.run(output, live=True)
    assert (output / "plan.json").read_bytes() == before


def test_isolation_removes_credentials_and_preserves_transport_restrictions(tmp_path):
    original = Settings(database_path="original.sqlite3", searxng_url="http://127.0.0.1:18888",
        tavily_api_key="account-secret", llm_api_key="llm-secret", llm_provider="openai_compatible",
        max_search_requests=9, max_detail_pages=9, bilibili_public_metadata=True,
        denied_fetch_hosts=("open.edu",), dns_resolver="cloudflare_doh")
    settings = harness.isolated_settings(original, tmp_path / "isolated.sqlite3")
    assert settings.tavily_api_key == settings.llm_api_key == "" and settings.llm_provider == "none"
    assert settings.tavily_allow_keyless and settings.bilibili_search_rounds == 3 and settings.mooc_search_rounds == 5
    assert settings.max_search_requests == 80 and settings.max_detail_pages == 60
    assert settings.search_results_per_query == 12 and settings.deadline_seconds == 360
    assert settings.search_max_retries == 0 and settings.search_min_interval_seconds == settings.fetch_min_interval_seconds == 2
    assert not settings.teaching_match_enabled and not settings.project_semantic_review_enabled
    assert not settings.allow_stale_cache and not settings.official_sitemap_fallback and not settings.public_catalog_fallback
    assert settings.denied_fetch_hosts == original.denied_fetch_hosts and settings.dns_resolver == original.dns_resolver
    assert original.tavily_api_key == "account-secret" and original.database_path == "original.sqlite3"


@pytest.mark.asyncio
async def test_missing_search_endpoint_blocks_before_api_start(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight tried to start API")
    monkeypatch.setattr(harness, "loopback_server", forbidden)
    result = await harness.run(tmp_path / "blocked", live=True, configured=Settings())
    assert result["status"] == "preflight_blocked" and result["reason"] == "SEARXNG_URL_not_configured"


@pytest.mark.asyncio
async def test_sse_parser_uses_blank_boundaries_handles_comments_and_discards_partial_eof():
    frames = [row async for row in harness.sse_frames(lines(
        ": heartbeat", "", "event: snapshot", "id: 17", "data: {", 'data: "value": 1}', "",
        "retry: 1000", "event: complete", 'data: {"done":true}', "", "event: snapshot", "data: incomplete"))]
    assert frames == [{"event": "snapshot", "id": "17", "data": '{\n"value": 1}'},
                      {"event": "complete", "id": None, "data": '{"done":true}'}]


@pytest.mark.asyncio
async def test_sse_parser_bounds_memory_even_without_blank_frame_boundary(monkeypatch):
    monkeypatch.setattr(harness, "MAX_SSE_FRAME_BYTES", 10)
    with pytest.raises(ValueError, match="bounded observation limit"):
        _ = [row async for row in harness.sse_frames(lines("data: 123456789", ""))]


def frame(payload, event="snapshot"):
    return {"event": event, "id": "1", "data": json.dumps(payload)}


def payload(terminal=False, mooc=None):
    return {"job": {"status": "completed" if terminal else "running"},
            "pipeline": {"terminal": terminal, "candidates": 3, "stage": "matching"},
            "groups": [{"discovery_platform_items": {
                "bilibili": [{"resource": {"resource_id": "b1"}}],
                "icourse163": [] if mooc is None else [{"resource": {"resource_id": "m1"}, "mooc_relevance": mooc}]}}]}


def test_timeline_preserves_intermediate_proof_and_flags_unverified_courses():
    good = {"status": "outline_supported", "display_eligible": True}
    first = harness.timeline_row(frame(payload(mooc=good)), 100)
    last = harness.timeline_row(frame(payload(terminal=True, mooc=good), "complete"), 900)
    result = harness.stream_summary([first, last])
    assert result["first_display_ms"] == result["first_verified_mooc_ms"] == 100
    assert result["cards_observed_before_completion"] and result["mooc_observed_before_completion"]
    assert result["complete_received"] and result["complete_terminal"]
    assert result["displayed_mooc_without_verified_outline_count"] == 0
    bad = harness.timeline_row(frame(payload(mooc={"status": "search_candidate"})), 50)
    assert bad["displayed_mooc_without_verified_outline"] == ["m1"]
    assert harness.stream_summary([bad, last])["displayed_mooc_without_verified_outline_count"] == 1


def test_terminal_only_cards_do_not_claim_incremental_streaming():
    row = harness.timeline_row(frame(payload(terminal=True)), 100)
    result = harness.stream_summary([row, harness.timeline_row(frame(payload(terminal=True), "complete"), 100)])
    assert not result["cards_observed_before_completion"] and result["first_display_ms"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_status", [None, 429])
async def test_live_runtime_is_real_local_sse_with_mocked_upstreams_and_no_keys(tmp_path, monkeypatch, blocked_status):
    calls = {"tavily": 0, "searxng": 0}
    output = tmp_path / "integration"
    monkeypatch.setitem(harness.OVERRIDES, "search_min_interval_seconds", 0)
    monkeypatch.setitem(harness.OVERRIDES, "fetch_min_interval_seconds", 0)

    async def response(client, method, url, trace, **kwargs):
        assert (output / "plan.json").is_file()
        provider = "tavily" if "tavily" in url else "searxng"
        calls[provider] += 1
        if provider == "tavily":
            assert kwargs["headers"]["X-Tavily-Access-Mode"] == "keyless"
            assert not any(key.lower() == "authorization" for key in kwargs["headers"])
        assert "account-secret" not in str(kwargs) and "llm-secret" not in str(kwargs)
        # Every external search request is intercepted; detail fetches have no candidates.
        return httpx.Response(blocked_status if provider == "tavily" and blocked_status else 200,
                              headers={"Retry-After": "3600"}, json={"results": []})

    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    original = tmp_path / "untouched.sqlite3"
    original.write_bytes(b"User database remains untouched")
    result = await harness.run(output, live=True, configured=Settings(database_path=str(original),
        searxng_url="http://127.0.0.1:18888", tavily_api_key="account-secret", llm_api_key="llm-secret"))
    assert original.read_bytes() == b"User database remains untouched"
    assert result["search_http_requests"] == sum(calls.values()) <= 16
    assert calls["searxng"] == 6 and calls["tavily"] == (1 if blocked_status else 10)
    assert result["llm_calls"] == result["detail_target_http_requests"] == 0
    assert result["streaming"]["complete_received"] and result["streaming"]["complete_terminal"]
    assert not result["streaming"]["cards_observed_before_completion"]
    assert result["streaming"]["snapshot_count"] >= 1
    assert result["source_states"]["searxng"]["source_access_denied"] is False
    text = "".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    assert "account-secret" not in text and "llm-secret" not in text
    assert not list(output.rglob("*.sqlite3"))


@pytest.mark.asyncio
async def test_card_arrives_over_http_while_later_source_requests_are_still_running(tmp_path, monkeypatch):
    calls = {"tavily": 0, "searxng": 0}
    monkeypatch.setitem(harness.OVERRIDES, "search_min_interval_seconds", 0)
    monkeypatch.setitem(harness.OVERRIDES, "fetch_min_interval_seconds", 0)
    monkeypatch.setitem(harness.OVERRIDES, "fetch_enabled", False)

    async def response(client, method, url, trace, **kwargs):
        provider = "tavily" if "tavily" in url else "searxng"
        calls[provider] += 1
        if provider == "searxng" and calls[provider] > 1:
            # Leave a real interval in which the API must emit the first card.
            await asyncio.sleep(0.45)
        candidates = [{"url": "https://www.bilibili.com/video/BV1xx411c7mD",
                       "title": "pandas 数据分组与聚合 Python 列表与字典", "content": "视频教程"}]
        return httpx.Response(200, json={"results": candidates if provider == "searxng" else []})

    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    output = tmp_path / "incremental"
    summary = await harness.run(output, live=True, configured=Settings(searxng_url="http://127.0.0.1:18888"))
    timeline = json.loads((output / "stream-timeline.json").read_text(encoding="utf-8"))
    early = [row for row in timeline if not row["pipeline"]["terminal"] and row["displayed_unique_counts"]["bilibili"]]
    assert summary["streaming"]["cards_observed_before_completion"] and early
    assert early[0]["pipeline"]["search_requests"] < 16
    assert early[0]["elapsed_ms"] < timeline[-1]["elapsed_ms"]
    assert summary["search_http_requests"] == 16 and summary["detail_target_http_requests"] == 0
