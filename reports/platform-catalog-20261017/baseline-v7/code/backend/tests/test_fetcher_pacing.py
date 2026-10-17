"""Deterministic offline network-policy tests; no real DNS, HTTP, or browser."""
import asyncio
import json
import math
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

import backend.app.fetcher as module
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, RobotsRules, retry_after_seconds


BASE = "https://learning.example.org"
HTML = b"<html><title>Public tutorial</title><main>This public tutorial explains data structures and contains educational examples for students learning Python programming.</main></html>"


@pytest.fixture
def clock(monkeypatch):
    state = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: state[0], time=lambda: 1_790_000_000.0))
    async def sleep(seconds):
        state[0] += seconds
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    return state


def make_fetcher(clock, route=None, config=None):
    requests, dns_calls = [], []
    async def resolver(url, timeout):
        dns_calls.append(url)
        return ["93.184.216.34"]
    class OfflineHTTP:
        async def request(self, url, addresses, max_bytes):
            requests.append((url, clock[0]))
            if route:
                result = route(url, requests)
                if result is not None:
                    if isinstance(result, Exception):
                        raise result
                    return result
            body = b"User-agent: *\nAllow: /" if url.endswith("/robots.txt") else HTML
            return HTTPResult(200, {"content-type": "text/html"}, body, url)
    return Fetcher(config or FetcherConfig(), resolver=resolver, http_client=OfflineHTTP()), requests, dns_calls


@pytest.mark.asyncio
async def test_default_minimum_interval_applies_to_robots_and_pages(clock):
    fetcher, requests, _ = make_fetcher(clock)
    for path in ("/one", "/two"):
        assert (await fetcher.enrich({"url": BASE + path}))["fetch_status"] == "fetched"
    assert [stamp for _, stamp in requests] == [1000.0, 1000.5, 1001.0]


@pytest.mark.asyncio
async def test_every_retry_respects_robots_delay_and_redoes_dns(clock):
    def route(url, requests):
        if url.endswith("robots.txt"):
            return HTTPResult(200, {}, b"User-agent: *\nCrawl-delay: 5", url)
        if len(requests) == 2:
            return httpx.ReadTimeout("offline synthetic timeout")
    fetcher, requests, dns = make_fetcher(clock, route)
    assert (await fetcher.enrich({"url": BASE + "/one"}))["fetch_status"] == "fetched"
    assert [stamp for _, stamp in requests] == [1000.0, 1005.0, 1010.0]
    assert len(dns) == 3
    assert fetcher.trace_counts["retry_scheduled"] == 1
    assert fetcher.trace_counts["http_failed"] == 1
    assert [event["attempt"] for event in fetcher.request_trace if event["event"] == "http_started"] == [0, 0, 1]


@pytest.mark.asyncio
async def test_other_origin_cannot_lower_known_delay_on_same_hostname(clock):
    def route(url, requests):
        if url.endswith("robots.txt"):
            rules = b"User-agent: *\nCrawl-delay: 5" if url.startswith("https:") else b"User-agent: *\nAllow: /"
            return HTTPResult(200, {}, rules, url)
    fetcher, requests, _ = make_fetcher(clock, route)
    for url in (BASE + "/one", BASE.replace("https:", "http:") + "/two", BASE + "/three"):
        assert (await fetcher.enrich({"url": url}))["fetch_status"] == "fetched"
    assert [stamp for _, stamp in requests] == [1000.0, 1005.0, 1010.0, 1015.0, 1020.0]


@pytest.mark.asyncio
async def test_503_retry_after_stops_host_without_retry_and_other_host_continues(clock):
    def route(url, requests):
        if url == BASE + "/one":
            return HTTPResult(503, {"retry-after": "120"}, b"", url)
    fetcher, requests, dns = make_fetcher(clock, route)
    first = await fetcher.enrich({"url": BASE + "/one"})
    assert first["fetch_status"] == "rate_limited" and "503" in first["fetch_error"]
    before = (len(requests), len(dns))
    assert (await fetcher.enrich({"url": BASE + "/two"}))["fetch_status"] == "rate_limited"
    assert (len(requests), len(dns)) == before
    assert (await fetcher.enrich({"url": "https://other.example.org/one"}))["fetch_status"] == "fetched"
    clock[0] += 121
    assert (await fetcher.enrich({"url": BASE + "/two"}))["fetch_status"] == "fetched"
    assert fetcher.trace_counts["retry_scheduled"] == 0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "nonsense", "", "1e9999"])
def test_invalid_retry_after_is_finite_default(value):
    assert retry_after_seconds(value) == 60.0


def test_retry_after_http_date_and_valid_seconds():
    assert retry_after_seconds("120") == 120.0
    assert retry_after_seconds("0") == 0.0
    now = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc).timestamp()
    assert retry_after_seconds("Tue, 13 Oct 2026 10:02:00 GMT", now=now) == 120.0


@pytest.mark.parametrize("rejection", ["403", "captcha", "robots_403", "robots_captcha"])
@pytest.mark.asyncio
async def test_explicit_denial_freezes_only_observed_host_with_trigger_evidence(clock, rejection):
    def route(url, requests):
        if not url.startswith(BASE):
            return None
        on_robots = url.endswith("robots.txt")
        if on_robots != rejection.startswith("robots_"):
            return None
        if rejection.endswith("403"):
            return HTTPResult(403, {}, b"", url)
        body = b"<html><title>Verify you are human</title><body>Security challenge</body></html>"
        return HTTPResult(200, {"content-type": "text/html"}, body, url)
    fetcher, requests, dns = make_fetcher(clock, route)
    first = await fetcher.enrich({"url": BASE + "/one", "title": "Search discovered example"})
    assert first["fetch_status"] in {"access_denied", "captcha", "robots_blocked"}
    before = (len(requests), len(dns))
    second = await fetcher.enrich({"url": BASE + "/two", "title": "Different search result"})
    assert second["fetch_status"] == first["fetch_status"]
    assert second["title"] == "Different search result"
    assert (len(requests), len(dns)) == before
    evidence_id = second["field_provenance"]["fetch_status"]["evidence_id"]
    evidence = next(item for item in second["evidence"] if item["evidence_id"] == evidence_id)
    record = json.loads(evidence["text"])
    assert record["trigger_url"] == BASE + ("/robots.txt" if rejection.startswith("robots_") else "/one")
    assert record["scope"] == "fetcher_instance_host"
    assert evidence["kind"] == "access_restriction"
    assert (await fetcher.enrich({"url": "https://other.example.org/one"}))["fetch_status"] == "fetched"


@pytest.mark.parametrize("status", [401, 404, 503])
@pytest.mark.asyncio
async def test_login_not_found_and_503_without_retry_after_do_not_freeze_host(clock, status):
    def route(url, requests):
        if url == BASE + "/one":
            return HTTPResult(status, {}, b"", url)
    fetcher, _, _ = make_fetcher(clock, route)
    await fetcher.enrich({"url": BASE + "/one"})
    assert (await fetcher.enrich({"url": BASE + "/two"}))["fetch_status"] == "fetched"


@pytest.mark.asyncio
async def test_redirects_converging_on_denied_host_do_not_repeat_target_request(clock):
    target = "https://shared.example.org/catalog"
    def route(url, requests):
        if url.endswith("/start"):
            return HTTPResult(302, {"location": target}, b"", url)
        if url.startswith("https://shared.example.org/"):
            return HTTPResult(403, {}, b"", url)
    fetcher, requests, dns = make_fetcher(clock, route)
    results = await asyncio.gather(fetcher.enrich({"url": BASE + "/start"}),
                                  fetcher.enrich({"url": "https://other.example.org/start"}))
    assert all(result["fetch_status"] == "robots_blocked" for result in results)
    assert len([url for url, _ in requests if url.startswith("https://shared.example.org/")]) == 1
    assert len([url for url in dns if url.startswith("https://shared.example.org/")]) == 1
    assert (await fetcher.enrich({"url": BASE + "/public"}))["fetch_status"] == "fetched"


@pytest.mark.asyncio
async def test_cancelled_http_request_releases_host_lock(clock):
    entered, release = asyncio.Event(), asyncio.Event()
    async def resolver(url, timeout):
        return ["93.184.216.34"]
    class SlowHTTP:
        async def request(self, url, addresses, max_bytes):
            if url.endswith("/slow"):
                entered.set()
                await release.wait()
            return HTTPResult(200, {}, b"", url)
    fetcher = Fetcher(FetcherConfig(min_interval_seconds=0), resolver=resolver, http_client=SlowHTTP())
    task = asyncio.create_task(fetcher._request(BASE + "/slow", 1000))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await fetcher._request(BASE + "/next", 1000)).status_code == 200
    assert fetcher.trace_counts["http_cancelled"] == 1


def test_trace_is_bounded_query_redacted_and_counts_survive_eviction(clock):
    fetcher, _, _ = make_fetcher(clock)
    for _ in range(600):
        fetcher._trace("offline_example", BASE + "/course?token=do-not-log#secret", attempt=0)
    assert len(fetcher.request_trace) == 512
    assert fetcher.trace_counts["offline_example"] == 600
    assert all(event["url"] == BASE + "/course" for event in fetcher.request_trace)
    assert "do-not-log" not in json.dumps(list(fetcher.request_trace))
    assert len(fetcher.request_trace[0]["url_sha256"]) == 64


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1"])
def test_nonfinite_robots_delay_is_not_an_infinite_pause(value):
    rules = RobotsRules("User-agent: *\nCrawl-delay: " + value, "ProjectLearningDiscovery/0.1")
    assert rules.delay == 0 and math.isfinite(rules.delay)


@pytest.mark.parametrize("path,rule,expected", [
    ("/catalog/chapter", "/catalog", True), ("/catalog/chapter", "/catalog$", False),
    ("/catalog", "/catalog$", True), ("/catalog?term=2", "/*?term=*$", True),
    ("/a/b/c", "/a/*/c$", True), ("/a/b/c/d", "/a/*/c$", False),
    ("/a/b/c/d", "/a/*/c", True), ("/ababa", "/a*aba$", True),
    ("/aba", "/aba*aba$", False), ("/abc", "/a**b*c*$", True),
    ("/ab$", "/ab$$", True), ("/ab", "/ab$$", False),
    ("/x[y]", "/x[y]$", True), ("/abc", "*$", True),
    ("/abc", "/missing*", False),
])
def test_robots_literal_wildcards_and_only_terminal_dollar(path, rule, expected):
    assert RobotsRules._matches(path, rule) is expected


def test_robots_many_wildcards_do_not_use_catastrophic_regex_backtracking():
    rules = RobotsRules("User-agent: *\nDisallow: /" + "*a" * 25 + "Z", "ProjectLearningDiscovery/0.1")
    assert rules.allowed("https://example.org/" + "a" * 50)
    assert not rules.allowed("https://example.org/" + "a" * 50 + "Z")


def test_robots_decoded_variants_and_longest_allow_tie_are_retained():
    rules = RobotsRules("User-agent: *\nDisallow: /private/*\nAllow: /private/open$", "ProjectLearningDiscovery/0.1")
    assert not rules.allowed(BASE + "/private%2Fsecret")
    assert rules.allowed(BASE + "/private/open")
    tied = RobotsRules("User-agent: *\nDisallow: /course*\nAllow: /course*", "ProjectLearningDiscovery/0.1")
    assert tied.allowed(BASE + "/course/chapter")
