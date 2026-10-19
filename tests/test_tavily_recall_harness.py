"""Offline transport tests for the bounded live MOOC experiment."""
import asyncio
from dataclasses import fields
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import TavilyProvider
from scripts import test_tavily_mooc_recall as harness


def factory_for(client, captured=None):
    def factory(settings):
        if captured is not None:
            captured.append(settings)
        return TavilyProvider(settings, client=client)
    return factory


async def no_sleep(_):
    return None


def read_all(folder):
    return "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.json"))


@pytest.mark.asyncio
async def test_dry_run_never_constructs_provider_or_loads_credentials(tmp_path):
    def forbidden(_):
        pytest.fail("dry run attempted to construct a provider")
    output = tmp_path / "dry"
    result = await harness.run_recall(configured=Settings(tavily_api_key="do-not-persist"), output=output,
                                      provider_factory=forbidden)
    assert result["status"] == "dry_run"
    assert result["http_requests_started"] == result["actual_api_credits"] == 0
    assert len(json.loads((output / "plan.json").read_text(encoding="utf-8"))["corpus"]) == 20
    assert "do-not-persist" not in read_all(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,key,reason", [(None, "configured-secret", "select_keyless_or_configured_key_mode"),
                                            ("configured_key", "", "TAVILY_API_KEY_not_configured")])
async def test_preflight_blocks_without_selected_mode_or_configured_key(tmp_path, mode, key, reason):
    def forbidden(_):
        pytest.fail("preflight made a request")
    result = await harness.run_recall(configured=Settings(tavily_api_key=key), output=tmp_path / "preflight",
                                      live=True, mode=mode, provider_factory=forbidden)
    assert result["status"] == "preflight_blocked"
    assert result["stop_reason"] == reason
    assert result["http_requests_started"] == 0
    assert result["account_credentials_sent"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 429, 432, 433, 500])
async def test_first_http_error_stops_entire_campaign_without_retry_or_fallback(tmp_path, status):
    calls = []
    async def transport(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "600"}, json={"error": "private response"})
    output = tmp_path / "stopped"
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=Settings(tavily_api_key="secret", search_max_retries=1),
            output=output, live=True, mode="configured_key", limit=20, provider_factory=factory_for(client))
    assert result["status"] == "stopped"
    assert len(calls) == result["http_requests_started"] == result["queries_failed"] == 1
    assert result["queries_attempted"] == 1
    assert "private response" not in read_all(output)
    evidence = json.loads((output / "query-01.json").read_text(encoding="utf-8"))
    assert evidence["provider_trace"][0]["http_status"] == status


@pytest.mark.asyncio
async def test_fixed_limits_fresh_settings_native_count_and_sanitized_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    requests, captured = [], []
    key, llm_key = "configured-api-secret-123", "private-llm-secret-456"
    async def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.host == "api.tavily.com"
        assert payload["include_domains"] == ["icourse163.org"]
        assert payload["search_depth"] == "basic" and payload["auto_parameters"] is False
        assert payload["max_results"] == 5
        assert not payload["include_answer"] and not payload["include_raw_content"]
        return httpx.Response(200, json={"results": [
            {"url": "https://www.icourse163.org/course/PKU-1001?token=secret#private", "title": "Python " + key,
             "content": "学习 " + llm_key + " https://user:pass@example.org/?token=hidden Cookie: cookie-secret"},
            {"url": "https://www.icourse163.org/learn/PKU-1001", "title": "Learn is not native course detail"},
            {"url": "https://www.icourse163.org/course/PKU-1001", "title": "Same course"},
            {"url": "https://www.icourse163.org.attacker.example/course/PKU-1001", "title": "Wrong host"},
        ]})
    configured = Settings(tavily_api_key=key, llm_api_key=llm_key, llm_provider="openai",
        database_path="must-not-be-opened.sqlite3", official_sitemap_fallback=True, public_catalog_fallback=True,
        search_max_retries=1, search_results_per_query=10, searxng_url="https://private.example")
    output = tmp_path / "bounded"
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=configured, output=output, live=True, mode="configured_key",
                                         limit=3, offset=2, provider_factory=factory_for(client, captured))
    assert len(requests) == result["http_requests_started"] == 3
    assert requests[0]["query"].startswith(harness.KNOWLEDGE_POINTS[2])
    assert result["queries_succeeded"] == result["queries_with_native_course"] == 3
    assert result["native_unique_course_count"] == 1
    assert result["native_course_candidate_count"] == 6
    assert result["teaching_coverage"] == result["playback"] == "unknown"
    actual = captured[0]
    assert actual.search_max_retries == 0 and actual.search_min_interval_seconds == 2
    assert actual.fetch_enabled is actual.official_sitemap_fallback is actual.public_catalog_fallback is False
    assert actual.llm_provider == "none" and not actual.llm_api_key and not actual.searxng_url
    assert actual.database_path != configured.database_path
    all_text = read_all(output)
    for secret in (key, llm_key, "cookie-secret", "token=secret", "user:pass", "private.example", "Authorization"):
        assert secret not in all_text
    assert not (tmp_path / "must-not-be-opened.sqlite3").exists()


@pytest.mark.parametrize("url", [
    "https://www.icourse163.org/learn/PKU-1001", "https://www.icourse163.org/course/PKU-1001/private",
    "https://www.icourse163.org.attacker.org/course/PKU-1001", "https://school.icourse163.org/course/PKU-1001",
    "https://user:secret@www.icourse163.org/course/PKU-1001", "https://www.icourse163.org:9090/course/PKU-1001",
    "https://www.icourse163.org/course/", "https://www.icourse163.org/course/PKU%2fsecret",
])
def test_native_filter_is_exact_official_course_path(url):
    assert harness.native_course_url(url) is None


@pytest.mark.parametrize("limit,offset", [(0, 0), (21, 0), (2, 19), (1, -1), (1, 20), (True, 0)])
def test_invalid_budget_rejected_before_output_or_requests(limit, offset):
    with pytest.raises(ValueError):
        harness.make_plan(limit, offset, True, "keyless")


@pytest.mark.asyncio
async def test_existing_output_refused_without_touching_evidence(tmp_path):
    output = tmp_path / "previous"
    output.mkdir()
    marker = output / "summary.json"
    marker.write_text("previous evidence")
    with pytest.raises(FileExistsError):
        await harness.run_recall(configured=Settings(), output=output)
    assert marker.read_text() == "previous evidence"


@pytest.mark.asyncio
async def test_transport_error_and_credential_message_are_not_retried_or_persisted(tmp_path):
    requests = []
    async def transport(request):
        requests.append(request)
        raise httpx.ConnectError("Authorization: Bearer secret-123", request=request)
    output = tmp_path / "transport"
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=Settings(tavily_api_key="secret-123"), output=output,
            live=True, mode="configured_key", limit=20, provider_factory=factory_for(client))
    assert result["status"] == "stopped" and len(requests) == 1
    assert "secret-123" not in read_all(output)


@pytest.mark.asyncio
async def test_keyless_clears_configured_account_key(tmp_path):
    if "tavily_allow_keyless" not in {field.name for field in fields(Settings)}:
        pytest.skip("production keyless support is being added separately")
    requests, captured = [], []
    async def transport(request):
        requests.append(request)
        assert "authorization" not in request.headers
        assert request.headers["x-tavily-access-mode"] == "keyless"
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=Settings(tavily_api_key="must-not-be-sent"),
            output=tmp_path / "keyless", live=True, mode="keyless", limit=1, provider_factory=factory_for(client, captured))
    assert result["status"] == "completed" and len(requests) == 1
    assert captured[0].tavily_allow_keyless is True and captured[0].tavily_api_key == ""
    assert result["account_credentials_sent"] is False
    assert result["actual_api_credits"] == result["observed_api_credits"] == 1


@pytest.mark.asyncio
async def test_request_hook_stops_accidental_second_request_for_same_point(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    requests = []
    async def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})
    class AccidentallyRepeatedProvider(TavilyProvider):
        async def search(self, *args):
            await super().search(*args)
            return await super().search(*args)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=Settings(tavily_api_key="secret"), output=tmp_path / "guard",
            live=True, mode="configured_key", limit=20,
            provider_factory=lambda settings: AccidentallyRepeatedProvider(settings, client=client))
    assert result["status"] == "stopped" and result["stop_reason"] == "harness_request_budget"
    assert result["http_requests_started"] == len(requests) == 1


@pytest.mark.asyncio
async def test_twenty_point_budget_and_empty_response_are_reported_without_fake_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    requests = []
    async def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await harness.run_recall(configured=Settings(tavily_api_key="secret"), output=tmp_path / "all",
            live=True, mode="configured_key", limit=20, provider_factory=factory_for(client))
    assert result["status"] == "completed"
    assert result["http_requests_started"] == result["queries_succeeded"] == len(requests) == 20
    assert result["native_unique_course_count"] == result["native_course_query_hit_rate"] == 0
    assert result["actual_api_credits"] == "unknown"


@pytest.mark.asyncio
async def test_interruption_preserves_incremental_counts_and_query_evidence(tmp_path):
    async def transport(request):
        raise asyncio.CancelledError()
    output = tmp_path / "interrupted"
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(asyncio.CancelledError):
            await harness.run_recall(configured=Settings(tavily_api_key="secret"), output=output,
                live=True, mode="configured_key", limit=20, provider_factory=factory_for(client))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    row = json.loads((output / "query-01.json").read_text(encoding="utf-8"))
    assert summary["status"] == row["status"] == "interrupted"
    assert summary["http_requests_started"] == row["http_requests_started"] == 1
    assert row["provider_trace"][0]["status"] == "cancelled"
    assert "secret" not in read_all(output)
