"""Local opt-in public video HTML reads; all HTTP/DNS are isolated fixtures."""
from dataclasses import replace

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import (
    Fetcher, FetcherConfig, HTTPResult, PLATFORM_POLICY_REVIEWS,
    public_bilibili_metadata_url,
)
from backend.app.rendering import RenderConfig, SafeRenderer
from backend.app.service import JobService


ORIGIN = "https://www.bilibili.com"
VIDEO = ORIGIN + "/video/BV1VZ4y1G7YB/"
ROBOTS = ORIGIN + "/robots.txt"
PAGE = b"<html><title>Public Python tutorial</title><h1>Public Python tutorial</h1><p>Public video information, including an introduction to Python lists, dictionaries, functions and programming exercises.</p></html>"


class MemoryHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def request(self, url, addresses, max_bytes):
        self.calls.append(url)
        assert url in self.responses, "No external network fallback is permitted"
        return self.responses[url]


def response(url, status=200, body=PAGE, **headers):
    return HTTPResult(status, {"content-type": "text/html", **headers}, body, url)


def isolated_fetcher(responses, **config):
    http = MemoryHTTP(responses)
    dns_calls = []

    async def dns(url, timeout):
        dns_calls.append(url)
        assert url in responses, "Scope-restricted targets must stop before DNS"
        return ["93.184.216.34"]

    settings = FetcherConfig(min_interval_seconds=0, max_retries=0,
        bilibili_public_metadata=True, **config)
    return Fetcher(settings, resolver=dns, http_client=http), http, dns_calls


@pytest.mark.parametrize("url", [
    VIDEO, VIDEO.rstrip("/"), VIDEO + "?p=1", VIDEO + "?p=123",
    "https://bilibili.com/video/av123456", ORIGIN + "/video/av123456/",
    ROBOTS, "https://bilibili.com/robots.txt",
])
def test_strict_public_video_url_scope_accepts_only_supported_shapes(url):
    assert public_bilibili_metadata_url(url)


@pytest.mark.parametrize("url", [
    ORIGIN + "/video/BV123", ORIGIN + "/video/BV1VZ4y1G7YB/extra",
    ORIGIN + "/video/av１２３", ORIGIN + "/read/cv123", ORIGIN + "/login",
    ORIGIN + "/bangumi/play/ep123", ORIGIN + "/medialist/play/123",
    ORIGIN + "/api/view", ORIGIN + "/video/%42V1VZ4y1G7YB/",
    VIDEO + "?p=0", VIDEO + "?p=-1", VIDEO + "?p=１", VIDEO + "?p=",
    VIDEO + "?p=1&p=2", VIDEO + "?p=1&token=x", VIDEO + "?token=x",
    VIDEO + "#chapter", ROBOTS + "?p=1",
    "http://www.bilibili.com/video/BV1VZ4y1G7YB/",
    "https://www.bilibili.com:444/video/BV1VZ4y1G7YB/",
    "https://api.bilibili.com/x/web-interface/view?bvid=BV1VZ4y1G7YB",
    "https://m.bilibili.com/video/BV1VZ4y1G7YB/",
    "https://www.bilibili.com.attacker.example/video/BV1VZ4y1G7YB/",
    "https://user:secret@www.bilibili.com/video/BV1VZ4y1G7YB/",
])
def test_strict_scope_rejects_other_routes_queries_and_origins(url):
    assert not public_bilibili_metadata_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [VIDEO, VIDEO + "?p=2", "https://bilibili.com/video/av123456"])
async def test_opt_in_public_html_reads_robots_then_page(url):
    robots = url.split("/video/")[0] + "/robots.txt"
    fetcher, http, dns_calls = isolated_fetcher({
        robots: response(robots, status=404, body=b""), url: response(url),
    })
    result = await fetcher.enrich({"url": url, "title": "Search title"})
    assert result["fetch_status"] == "fetched"
    assert http.calls == dns_calls == [robots, url]
    assert result["chapters"] == [] and result["requires_login"] is None


@pytest.mark.asyncio
async def test_tracking_parameters_are_normalized_before_scope_check():
    fetcher, http, _ = isolated_fetcher({
        ROBOTS: response(ROBOTS, status=404, body=b""),
        VIDEO + "?p=2": response(VIDEO + "?p=2"),
    })
    result = await fetcher.enrich({"url": VIDEO + "?p=2&uid=example&vd_source=example"})
    assert result["fetch_status"] == "fetched"
    assert http.calls == [ROBOTS, VIDEO + "?p=2"]


@pytest.mark.asyncio
async def test_default_config_retains_existing_policy_and_never_resolves():
    fetcher, http, dns_calls = isolated_fetcher({})
    fetcher.config = replace(fetcher.config, bilibili_public_metadata=False)
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == "site_policy_blocked"
    assert http.calls == dns_calls == []
    assert PLATFORM_POLICY_REVIEWS["bilibili"]["status"] == "explicit_permission_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [
    ORIGIN + "/login", ORIGIN + "/read/cv123", ORIGIN + "/video/BV123",
    VIDEO + "?token=x", "https://api.bilibili.com/x/web-interface/view",
])
async def test_opt_in_does_not_expand_nonpublic_paths_even_with_host_allowlist(target):
    fetcher, http, dns_calls = isolated_fetcher({}, allowed_restricted_hosts=("bilibili.com",))
    result = await fetcher.enrich({"url": target})
    assert result["fetch_status"] == "policy_unreviewed"
    assert http.calls == dns_calls == []
    assert result["fetch_error"] and result["fetched_at"] is None
    # A local scope guard must not manufacture an official platform prohibition.
    assert not any(row["kind"] == "site_policy" for row in result["evidence"])


@pytest.mark.asyncio
@pytest.mark.parametrize("from_robots", [False, True])
@pytest.mark.parametrize("outside", ["https://courses.example.org/public", ORIGIN + "/login"])
async def test_redirect_cannot_escape_scoped_video_or_robots_paths(from_robots, outside):
    responses = {ROBOTS: response(ROBOTS, status=404, body=b"")}
    responses[ROBOTS if from_robots else VIDEO] = response(
        ROBOTS if from_robots else VIDEO, status=302, body=b"", location=outside)
    fetcher, http, dns_calls = isolated_fetcher(responses)
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == "policy_unreviewed"
    assert outside not in http.calls + dns_calls
    assert http.calls == [ROBOTS] + ([] if from_robots else [VIDEO])


@pytest.mark.asyncio
async def test_robots_redirect_cannot_switch_to_an_allowed_video_route():
    fetcher, http, _ = isolated_fetcher({ROBOTS: response(ROBOTS, status=302, body=b"", location=VIDEO)})
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == "policy_unreviewed" and http.calls == [ROBOTS]


@pytest.mark.asyncio
@pytest.mark.parametrize("barrier,expected", [
    ("robots", "robots_blocked"), ("robots_403", "robots_blocked"),
    ("403", "access_denied"), ("captcha", "captcha"),
    ("login", "login_required"), ("429", "rate_limited"),
])
async def test_actual_access_barriers_are_not_bypassed(barrier, expected):
    robots = response(ROBOTS, status=404, body=b"")
    page = response(VIDEO)
    if barrier == "robots":
        robots = response(ROBOTS, body=b"User-agent: *\nDisallow: /video/", **{"content-type": "text/plain"})
    elif barrier == "robots_403":
        robots = response(ROBOTS, status=403, body=b"Forbidden")
    elif barrier == "403":
        page = response(VIDEO, status=403, body=b"Forbidden")
    elif barrier == "captcha":
        page = response(VIDEO, body=b"<title>Verify you are human</title>")
    elif barrier == "login":
        page = response(VIDEO, body=b"<title>Sign in to continue</title>")
    elif barrier == "429":
        page = response(VIDEO, status=429, body=b"", **{"retry-after": "120"})
    fetcher, http, _ = isolated_fetcher({ROBOTS: robots, VIDEO: page})
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == expected and not result["chapters"]
    assert http.calls == [ROBOTS] + ([] if barrier.startswith("robots") else [VIDEO])
    if barrier in {"403", "robots_403", "captcha"}:
        evidence = next(row for row in result["evidence"] if row["kind"] == "access_restriction")
        assert evidence["source"] == ("html.captcha" if barrier == "captcha" else "http.status.403")
        old_calls = list(http.calls)
        again = await fetcher.enrich({"url": ORIGIN + "/video/av123456"})
        assert again["fetch_status"] == expected and http.calls == old_calls


@pytest.mark.asyncio
async def test_opt_in_does_not_override_administrator_host_deny():
    fetcher, http, dns_calls = isolated_fetcher({}, denied_hosts=("bilibili.com",))
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == "site_policy_blocked" and not http.calls and not dns_calls


@pytest.mark.asyncio
async def test_html_only_opt_in_still_prevents_script_execution():
    fetcher, http, _ = isolated_fetcher({})
    renderer = SafeRenderer(RenderConfig(enabled=True, allowed_hosts=("www.bilibili.com",)))
    result = await renderer.render(fetcher, response(VIDEO, body=PAGE + b"<script>throw new Error('must not run')</script>"))
    assert result.status == "render_scope_blocked"
    assert not http.calls and not result.manifest


@pytest.mark.parametrize("url", [VIDEO, "https://courses.example.org/course/entry"])
def test_opt_in_invalidates_prior_page_policy_cache_without_deleting_it(url):
    store = Store(":memory:")
    try:
        disabled = JobService(Settings(bilibili_public_metadata=False), store)
        resource = {"canonical_url": url}
        old_key, _ = disabled._page_cache(resource)
        data = {"fetch_status": "site_policy_blocked", "chapters": []}
        store.cache_set(old_key, "page", data, 86400)
        enabled = JobService(Settings(bilibili_public_metadata=True), store)
        key, cached = enabled._page_cache(resource)
        assert key != old_key and cached is None
        assert store.cache_get(old_key)["data"] == data
    finally:
        store.close()


def test_environment_opt_in_defaults_false_and_reaches_fetcher(monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("BILIBILI_PUBLIC_METADATA", raising=False)
    assert Settings.from_env().bilibili_public_metadata is False
    monkeypatch.setenv("BILIBILI_PUBLIC_METADATA", "true")
    settings = Settings.from_env()
    assert settings.bilibili_public_metadata is True
    store = Store(":memory:")
    try:
        service = JobService(settings, store)
        assert service.fetcher.config.bilibili_public_metadata is True
    finally:
        store.close()


def test_capabilities_distinguish_local_runtime_scope_from_recorded_terms():
    store = Store(":memory:")
    try:
        service = JobService(Settings(bilibili_public_metadata=True), store)
        platforms = {row["id"]: row for row in service.capabilities()["platforms"]}
        assert platforms["bilibili"]["metadata"] == "public_video_metadata_only"
        assert platforms["bilibili"]["policy_status"] == "explicit_permission_required"
        assert platforms["bilibili"]["playback"] == "unknown"
        assert platforms["icourse163"]["metadata"] == "public_course_metadata_only"
        assert platforms["xuetangx"]["metadata"] == "site_policy_blocked"
        disabled = JobService(Settings(bilibili_public_metadata=True, fetch_enabled=False), store)
        assert all(row["metadata"] == "disabled" for row in disabled.capabilities()["platforms"])
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=example", "site_policy_blocked"),
    ("https://www.xuetangx.com/course/example", "site_policy_blocked"),
    ("https://www.icourse163.org/learn/PKU-1003479006", "policy_unreviewed"),
])
async def test_bilibili_opt_in_does_not_expand_other_platforms(url, expected):
    fetcher, http, dns_calls = isolated_fetcher({})
    result = await fetcher.enrich({"url": url})
    assert result["fetch_status"] == expected and not http.calls and not dns_calls
