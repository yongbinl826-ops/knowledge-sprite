"""Offline checks for fair, bounded, free-only MOOC comparison planning."""
import asyncio
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult
from backend.app.providers import HTTPProvider
from scripts import compare_mooc_providers_live as harness


def free_usage(**changes):
    account = {"current_plan": "Researcher", "plan_usage": 0, "plan_limit": 1000,
               "paygo_usage": 0, "paygo_limit": 0}
    account.update(changes)
    return {"account": account, "key": {"usage": 0, "limit": 1000}}


@pytest.mark.asyncio
async def test_dry_run_is_network_free_and_rejects_overwrite(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Dry run touched configuration or runtime")
    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    monkeypatch.setattr(harness, "fetch_tavily_usage", forbidden)
    output = tmp_path / "dry"
    result = await harness.run(output)
    assert result["status"] == "dry_run"
    assert result["search_http_requests"] == result["usage_http_requests"] == result["llm_calls"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    assert plan["knowledge_points"] == harness.POINTS
    assert plan["max_search_http_requests_per_provider"] == 8
    assert plan["shared_library_enabled"] is plan["gap_search_enabled"] is False
    assert plan["precision"] == plan["recall"] == "unknown"
    with pytest.raises(FileExistsError):
        await harness.run(output)
    with pytest.raises(ValueError):
        await harness.run(harness.ROOT / "reports" / "must-not-create")


@pytest.mark.asyncio
@pytest.mark.parametrize("tavily,serper,confirm,reason", [("", "", True, "missing_api_keys"),
    ("t-key", "", True, "missing_api_keys"), ("", "s-key", True, "missing_api_keys"),
    ("t-key", "s-key", False, "serper_free_trial_not_confirmed")])
async def test_incomplete_preflight_does_not_call_either_provider_or_usage(tmp_path, monkeypatch, tavily, serper, confirm, reason):
    def forbidden(*args, **kwargs):
        pytest.fail("Incomplete preflight touched network or runtime")
    monkeypatch.setattr(harness, "fetch_tavily_usage", forbidden)
    monkeypatch.setattr(harness, "Store", forbidden)
    result = await harness.run(tmp_path / "blocked", live=True, confirm_serper_free_trial=confirm,
        configured=Settings(tavily_api_key=tavily, serper_api_key=serper))
    assert result["status"] == "preflight_blocked" and result["reason"] == reason
    assert result["search_http_requests"] == result["usage_http_requests"] == 0
    assert "t-key" not in json.dumps(result) and "s-key" not in json.dumps(result)


@pytest.mark.parametrize("account", [{"current_plan": "Bootstrap"}, {"current_plan": "secret-plan"},
    {"plan_usage": 995}, {"plan_usage": "unknown"}, {"plan_limit": True},
    {"paygo_usage": 1}, {"paygo_usage": None}])
def test_tavily_unknown_paid_or_insufficient_allowance_fails_closed(account):
    result = harness.assess_free_usage(free_usage(**account))
    assert not result["allowed"] and "secret-plan" not in json.dumps(result)


def test_tavily_free_account_with_enough_remaining_or_no_key_limit_passes():
    body = free_usage()
    assert harness.assess_free_usage(body)["allowed"]
    body["key"]["limit"] = None
    assert harness.assess_free_usage(body)["allowed"]
    body["key"]["limit"] = 7
    assert not harness.assess_free_usage(body)["allowed"]
    assert not harness.assess_free_usage({"account": {}, "key": {}})["allowed"]
    assert not harness.assess_free_usage({})["allowed"]


@pytest.mark.parametrize("paygo_limit", [0, None, 100])
def test_free_remaining_covers_bounded_run_without_treating_paygo_limit_as_usage(paygo_limit):
    body = free_usage(paygo_limit=paygo_limit)
    body["key"]["limit"] = None
    result = harness.assess_free_usage(body)
    assert result["allowed"]
    assert result["plan_remaining"] == 1000 and result["key_remaining"] == "no_key_limit"
    assert result["paygo_usage"] == 0 and result["paygo_limit"] == paygo_limit
    body["account"]["plan_usage"] = 993
    assert not harness.assess_free_usage(body)["allowed"]
    body["account"]["plan_usage"] = 0
    body["account"]["paygo_usage"] = 1
    assert not harness.assess_free_usage(body)["allowed"]


def test_settings_match_budgets_and_disable_reuse_llms_gaps_and_fallbacks(tmp_path):
    original = Settings(database_path="original.sqlite3", tavily_api_key="t-key", serper_api_key="s-key",
                        shared_course_library_enabled=True, mooc_gap_search_enabled=True,
                        llm_provider="openai_compatible", llm_api_key="llm-key", mooc_search_rounds=5)
    versions = [harness.isolated_settings(original, tmp_path / provider, provider) for provider in harness.PROVIDERS]
    assert original.shared_course_library_enabled and original.llm_api_key == "llm-key"
    for settings, provider in zip(versions, harness.PROVIDERS):
        assert settings.search_provider_for("icourse163") == provider
        assert settings.max_search_requests == 8 and settings.max_detail_pages == 12
        assert settings.search_results_per_query == 10 and settings.mooc_search_rounds == 2
        assert not settings.shared_course_library_enabled and not settings.mooc_gap_search_enabled
        assert not settings.allow_stale_cache and not settings.tavily_allow_keyless
        assert not settings.js_render_enabled and not settings.official_sitemap_fallback and not settings.public_catalog_fallback
        assert settings.llm_provider == "none" and not settings.llm_api_key
        assert settings.search_max_retries == 0 and settings.deadline_seconds == 250


@pytest.mark.asyncio
async def test_usage_denial_stops_both_provider_runs(tmp_path, monkeypatch):
    async def denied(_):
        return {"allowed": False, "reason": "usage_http_error", "http_status": 429}
    monkeypatch.setattr(harness, "fetch_tavily_usage", denied)
    monkeypatch.setattr(harness, "run_provider", lambda *args: pytest.fail("Search after failed usage check"))
    result = await harness.run(tmp_path / "usage-blocked", live=True, confirm_serper_free_trial=True,
        configured=Settings(tavily_api_key="t-key", serper_api_key="s-key"))
    assert result["status"] == "preflight_blocked"
    assert result["usage_http_requests"] == 1 and result["search_http_requests"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,reason", [
    (401, b'{"secret":"offline-usage-key"}', "usage_http_error"),
    (429, b'{"secret":"offline-usage-key"}', "usage_http_error"),
    (302, b'', "usage_http_error"),
    (200, b'not json offline-usage-key', "usage_request_failed"),
    (200, b'x' * 65537, "usage_body_too_large"),
], ids=["unauthorized", "rate-limit", "redirect", "invalid-json", "oversized-body"])
async def test_usage_transport_is_single_bounded_read_only_request_without_secret_echo(monkeypatch, status, content, reason):
    original_client = httpx.AsyncClient
    requests = []

    def response(request):
        requests.append(request)
        assert request.method == "GET" and str(request.url) == "https://api.tavily.com/usage"
        assert request.headers["authorization"] == "Bearer offline-usage-key"
        return httpx.Response(status, content=content, headers={"Location": "https://example.org/never-follow"})

    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original_client(**kwargs, transport=httpx.MockTransport(response))

    monkeypatch.setattr(harness.httpx, "AsyncClient", factory)
    result = await harness.fetch_tavily_usage("offline-usage-key")
    assert len(requests) == 1 and not result["allowed"] and result["reason"] == reason
    assert "offline-usage-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_real_jobservice_with_mock_transport_runs_equal_queries_and_no_reused_database(tmp_path, monkeypatch):
    calls = []
    output = tmp_path / "comparison"

    async def usage(_):
        return harness.assess_free_usage(free_usage())

    async def no_sleep(_):
        pass

    async def response(client, method, url, trace, **kwargs):
        assert (output / "plan.json").is_file()
        provider = "serper" if "serper" in url else "tavily"
        calls.append((provider, kwargs["json"]))
        assert "llm-key" not in str(kwargs)
        return httpx.Response(200, json={"organic": [], "credits": 1} if provider == "serper" else
                              {"results": [], "usage": {"credits": 1}})

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    original = tmp_path / "original.sqlite3"
    original.write_bytes(b"Original database must not be opened")
    result = await harness.run(output, live=True, confirm_serper_free_trial=True,
        configured=Settings(database_path=str(original), tavily_api_key="t-key", serper_api_key="s-key", llm_api_key="llm-key"))
    assert original.read_bytes() == b"Original database must not be opened"
    counts = {provider: sum(source == provider for source, _ in calls) for provider in harness.PROVIDERS}
    assert counts == {"tavily": 8, "serper": 8}
    assert result["search_http_requests"] == 16 and result["detail_target_http_requests"] == result["llm_calls"] == 0
    queries = {provider: [body.get("q", body.get("query")) for source, body in calls if source == provider] for provider in harness.PROVIDERS}
    assert queries["tavily"] == [query.removesuffix(" (site:icourse163.org)") for query in queries["serper"]]
    for row in result["providers"].values():
        assert row["observed_api_credits"] == 8 and row["credits_complete"]
        assert not row["search_http_budget_exceeded"]
        assert row["precision"] == row["recall"] == "unknown"
    text = "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
    assert all(secret not in text for secret in ("t-key", "s-key", "llm-key"))
    assert not list(output.rglob("*.sqlite3"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 402])
async def test_restricted_serper_run_stops_after_one_request(tmp_path, monkeypatch, status):
    calls = []

    async def usage(_):
        return harness.assess_free_usage(free_usage())

    async def no_sleep(_):
        pass

    async def response(client, method, url, trace, **kwargs):
        source = "serper" if "serper" in url else "tavily"
        calls.append(source)
        return httpx.Response(status if source == "serper" else 200,
            headers={"retry-after": "3600"}, json={"results": []})

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    result = await harness.run(tmp_path / "restricted", live=True, confirm_serper_free_trial=True,
        configured=Settings(tavily_api_key="t-key", serper_api_key="s-key"))
    assert calls.count("serper") == 1 and calls.count("tavily") == 8
    assert result["providers"]["serper"]["search_http_requests"] == 1
    assert result["providers"]["serper"]["observed_api_credits"] == "unknown"


def _course_search_response(provider):
    course = {"title": "Python 程序设计", "url": "https://www.icourse163.org/course/OWN-123",
              "content": "Python 列表与字典课程教学", "score": 0.9}
    if provider == "serper":
        return httpx.Response(200, json={"organic": [{"title": course["title"], "link": course["url"],
            "snippet": course["content"], "position": 1}], "credits": 1})
    return httpx.Response(200, json={"results": [course], "usage": {"credits": 1}})


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status,control,event", [(403, "blocked_hosts", "blocked_before_request"),
                                                       (429, "paused_hosts", "paused_before_request")])
async def test_shared_fetcher_preserves_course_host_controls_across_provider_runs(
        tmp_path, monkeypatch, http_status, control, event):
    """Fresh provider databases must not reset the target website's denial."""
    output = tmp_path / "shared-host-controls"
    searches, target_urls, fetchers = [], [], []
    actual_sleep = asyncio.sleep

    async def usage(_):
        return harness.assess_free_usage(free_usage())

    async def yield_only(_):
        await actual_sleep(0)

    async def resolver(url, timeout):
        return ["93.184.216.34"]

    class HTTP:
        async def request(self, url, addresses, max_bytes):
            target_urls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            return HTTPResult(http_status, {"content-type": "text/html", "retry-after": "3600"}, b"denied", url)

    def make_fetcher(settings):
        fetcher = Fetcher(FetcherConfig(max_retries=0, min_interval_seconds=0), resolver=resolver, http_client=HTTP())
        fetchers.append(fetcher)
        return fetcher

    async def response(client, method, url, trace, **kwargs):
        provider = "serper" if "serper" in url else "tavily"
        searches.append(provider)
        return _course_search_response(provider)

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "make_fetcher", make_fetcher)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", yield_only)
    result = await harness.run(output, live=True, confirm_serper_free_trial=True,
        configured=Settings(tavily_api_key="t-key", serper_api_key="s-key"))

    assert len(fetchers) == 1
    assert searches.count("tavily") == searches.count("serper") == 8
    assert target_urls == ["https://www.icourse163.org/robots.txt", "https://www.icourse163.org/course/OWN-123"]
    assert result["providers"]["tavily"]["detail_target_http_requests"] == 2
    assert result["providers"]["serper"]["detail_target_http_requests"] == 0
    assert result["detail_target_http_requests"] == 2
    for provider in harness.PROVIDERS:
        controls = result["providers"][provider]["fetch_host_controls"]
        assert len(controls[control]) == 1 and controls[control][0]["host"] == "www.icourse163.org"
        if control == "paused_hosts":
            assert controls[control][0]["remaining_seconds"] > 3500
        else:
            assert controls[control][0]["status"] == "access_denied"
    network = json.loads((output / "serper" / "network.json").read_text(encoding="utf-8"))
    assert network["target_http_requests"] == 0 and network["responses"] == []
    assert any(row["event"] == event for row in network["events"])
    assert not any(row["event"] in {"dns_started", "http_started"} for row in network["events"])
    resources = json.loads((output / "serper" / "resources.json").read_text(encoding="utf-8"))
    assert any(row["fetch_status"] == ("access_denied" if http_status == 403 else "rate_limited") for row in resources.values())


@pytest.mark.asyncio
async def test_cancellation_exports_spent_and_inflight_traces_without_starting_serper(tmp_path, monkeypatch):
    output = tmp_path / "cancelled-comparison"
    searches, target_urls = [], []
    second_search_started, detail_started, never_finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    actual_sleep = asyncio.sleep

    async def usage(_):
        return harness.assess_free_usage(free_usage())

    async def yield_only(_):
        await actual_sleep(0)

    async def resolver(url, timeout):
        return ["93.184.216.34"]

    class HTTP:
        async def request(self, url, addresses, max_bytes):
            target_urls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            detail_started.set()
            await never_finish.wait()
            raise AssertionError("Cancelled detail transport unexpectedly resumed")

    def make_fetcher(settings):
        return Fetcher(FetcherConfig(max_retries=0, min_interval_seconds=0), resolver=resolver, http_client=HTTP())

    async def response(client, method, url, trace, **kwargs):
        provider = "serper" if "serper" in url else "tavily"
        searches.append(provider)
        assert provider == "tavily", "Cancellation must not spend Serper trial credits"
        if len(searches) > 1:
            second_search_started.set()
            await never_finish.wait()
            raise AssertionError("Cancelled search transport unexpectedly resumed")
        return _course_search_response(provider)

    monkeypatch.setattr(harness, "fetch_tavily_usage", usage)
    monkeypatch.setattr(harness, "make_fetcher", make_fetcher)
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", yield_only)
    task = asyncio.create_task(harness.run(output, live=True, confirm_serper_free_trial=True,
        configured=Settings(tavily_api_key="offline-tavily-key", serper_api_key="offline-serper-key")))
    try:
        await asyncio.wait_for(asyncio.gather(second_search_started.wait(), detail_started.wait()), 5)
        # These must already be on disk while requests are in flight, not merely
        # written during final export after an orderly run.
        live_network = json.loads((output / "tavily" / "network.json").read_text(encoding="utf-8"))
        live_attempts = json.loads((output / "tavily" / "search_attempts.json").read_text(encoding="utf-8"))
        assert live_network["target_http_requests"] == 2
        assert len(live_network["responses"]) == 1 and live_network["responses"][0]["kind"] == "robots"
        assert sum(row["event"] == "http_started" for row in live_network["events"]) == 2
        assert len(live_attempts) == 1 and live_attempts[0]["provider_requests"][0]["api_credits"] == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    retained = summary["providers"]["tavily"]
    assert summary["status"] == retained["status"] == "cancelled"
    assert set(summary["providers"]) == {"tavily"} and not (output / "serper").exists()
    assert searches == ["tavily", "tavily"]
    assert len(target_urls) == summary["detail_target_http_requests"] == retained["detail_target_http_requests"] == 2
    assert summary["search_http_requests"] == retained["search_http_requests"] == 2
    assert retained["observed_api_credits"] == 1 and not retained["credits_complete"]
    attempts = json.loads((output / "tavily" / "search_attempts.json").read_text(encoding="utf-8"))
    requests = [row for attempt in attempts for row in attempt["provider_requests"]]
    assert len(requests) == 2
    assert requests[0]["http_status"] == 200 and requests[0]["api_credits"] == 1
    assert requests[1]["status"] == "cancelled"
    network = json.loads((output / "tavily" / "network.json").read_text(encoding="utf-8"))
    assert any(row["event"] == "http_cancelled" for row in network["events"])
    assert len(network["responses"]) == 1
    assert all((output / "tavily" / name).is_file() for name in ("resources.json", "evidence.json", "results.json", "quality.json"))
    exported = "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
    assert "offline-tavily-key" not in exported and "offline-serper-key" not in exported
    assert not list(output.rglob("*.sqlite3"))
