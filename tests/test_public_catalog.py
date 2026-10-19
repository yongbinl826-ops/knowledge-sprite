"""Offline transport/parser checks; live HTTP evidence lives under evidence/phase2."""
import asyncio
from dataclasses import replace
import hashlib
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER
from backend.app.public_catalog import PublicCatalogProvider, ORIGIN, VIDEO_DIRECTORY, MAX_INDEX_BYTES, article_url, index_url, parse_index
from backend.app.providers import SearchBudgetReached, SearchError


TOOL_INDEX = ORIGIN + "/news/tag/python/"


def card(slug="python-filter-course", title="Python filtering course", tag="Python", excerpt="list comprehension filtering"):
    return (f'<article class="post-card"><header><span class="post-card-tags"><a href="/news/tag/{tag.lower()}/">#{tag}</a></span>'
            f'<h2 class="post-card-title"><a href="/news/{slug}/">{title}</a></h2></header>'
            f'<p class="post-card-excerpt">{excerpt}</p></article>')


class Transport:
    def __init__(self, documents=None):
        self.documents = {ORIGIN + "/robots.txt": b"User-agent: *\nAllow: /\n", TOOL_INDEX: card().encode(), VIDEO_DIRECTORY: card().encode()}
        self.documents.update(documents or {})
        self.calls, self.byte_limits = [], []

    async def request(self, url, addresses, max_bytes):
        self.calls.append(url)
        self.byte_limits.append(max_bytes)
        response = self.documents[url]
        await asyncio.sleep(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            status, body, headers = response
            return HTTPResult(status, headers, body, url)
        return HTTPResult(200, {"content-type": "text/html"}, response, url)


async def resolver(url, timeout):
    return ["9.9.9.9"]


def make(documents=None, store=None, **settings):
    transport = Transport(documents)
    fetcher = Fetcher(FetcherConfig(global_concurrency=1, min_interval_seconds=0, max_retries=1), resolver=resolver, http_client=transport)
    return PublicCatalogProvider(Settings(**settings), fetcher=fetcher, store=store), transport


async def search(provider, query="Python list comprehension filtering video tutorial", **kwargs):
    return await provider.search(query, "any", 6, [], original_point="Python list comprehension filtering", **kwargs)


def test_parser_accepts_only_observed_same_site_article_cards_and_bounds_fields():
    body = (card() + card() + card("bad", "Bad", "Python").replace('href="/news/bad/"', 'href="https://evil.example/news/bad/"') +
            '<footer><a href="/news/footer-only/">Python course</a></footer>' +
            '<article class="post-card"><h2><a href="/news/unstructured/">Python course</a></h2></article>').encode()
    parsed = parse_index(body, TOOL_INDEX)
    assert len(parsed["cards"]) == 1
    assert parsed["cards"][0]["url"] == ORIGIN + "/news/python-filter-course/"
    assert parsed["source_sha256"] == hashlib.sha256(body).hexdigest()
    assert parsed["cards"][0]["snippet"] == "list comprehension filtering"
    assert parsed["cards"][0]["tags"] == ["Python"]
    assert not parsed["cache_hit"]


@pytest.mark.parametrize("url", ["https://freecodecamp.org/news/tag/python/", "http://www.freecodecamp.org/news/tag/python/",
    "https://www.freecodecamp.org.evil.example/news/tag/python/", ORIGIN + "/news/tag/python/?page=2", ORIGIN + "/news/tag/python/#x",
    ORIGIN + "/news/tag/python/../private/", ORIGIN + "/news/tag/%70ython/", ORIGIN + "/api/search", "https://127.1/news/tag/python/"])
def test_indexes_reject_other_origins_apis_redirect_paths_and_query_routes(url):
    assert index_url(url) is None


@pytest.mark.parametrize("href", ["//evil.example/news/a/", "/news/author/foo/", "/news/tag/python/", "/news/one/?private=1",
    "/news/one/#part", "javascript:alert(1)", "https://user:pass@www.freecodecamp.org/news/a/", "/news/one/%2e%2e/private/"])
def test_card_links_reject_unscoped_paths_and_navigation(href):
    assert article_url(href, TOOL_INDEX) is None


@pytest.mark.parametrize("body,url", [(b"\x00", TOOL_INDEX), (b"x" * (MAX_INDEX_BYTES + 1), TOOL_INDEX), (b"", ORIGIN + "/robots.txt")], ids=["nul", "oversized", "robots-is-not-index"])
def test_untrusted_documents_cannot_exceed_parser_or_scope_bounds(body, url):
    with pytest.raises(SearchError) as stopped:
        parse_index(body, url)
    assert stopped.value.code == "invalid_response"


@pytest.mark.asyncio
async def test_real_fetcher_path_counts_robots_and_indexes_no_identity_upgrade():
    provider, transport = make()
    results = await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", TOOL_INDEX, VIDEO_DIRECTORY]
    assert len(results) == 1 and len(provider.last_requests) == 3
    assert all(row["status"] == "completed" and row["source_sha256"] for row in provider.last_requests)
    item = results[0]
    assert item.source == "public_catalog" and item.resource_type_hint == "unknown" and item.type_source is None
    assert item.discovery_evidence["independent_detail_required"] is True
    assert item.discovery_evidence["confidence"] == "low"
    assert "list comprehension" in item.snippet
    assert not any("body" in key for key in item.discovery_evidence)
    assert all(limit <= MAX_INDEX_BYTES for limit in transport.byte_limits)
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_specific_overlap_then_public_video_category_then_course_wording_prioritize_probe_only():
    provider, _ = make({TOOL_INDEX: (card("specific", "Python filtering", excerpt="filtering") + card("text", "Python manual", excerpt="")).encode(),
                       VIDEO_DIRECTORY: card("broad", "Learn Python course", excerpt="").encode()})
    results = await search(provider, "Python filtering video")
    assert [row.url.rsplit("/", 2)[-2] for row in results] == ["specific", "broad", "text"]
    assert all(row.resource_type_hint == "unknown" for row in results)


@pytest.mark.asyncio
async def test_exact_tool_boundary_cannot_substitute_javascript_for_java():
    provider, transport = make({ORIGIN + "/news/tag/java/": card("javascript", "JavaScript course", "JavaScript").encode()})
    assert await provider.search("Java arrays video", "en", 3, [], original_point="Java arrays") == []
    assert len(transport.calls) == 3


@pytest.mark.asyncio
async def test_cache_reuses_observations_without_http_and_invalidates_policy_and_ttl(tmp_path):
    store = Store(str(tmp_path / "catalog.sqlite3"))
    provider, transport = make(store=store)
    try:
        assert await search(provider)
        before = len(transport.calls)
        second = await search(provider)
        assert len(transport.calls) == before and provider.last_requests == []
        assert second[0].discovery_evidence["cache_hit"] is True
        assert store.connection.execute("SELECT count(*) FROM cache WHERE kind='public_catalog'").fetchone()[0] == 2
        original_key = provider._key(TOOL_INDEX)
        provider.settings = replace(provider.settings, denied_fetch_hosts=("freecodecamp.org",))
        assert provider._key(TOOL_INDEX) != original_key and provider._get(TOOL_INDEX) is None
        provider.settings = replace(provider.settings, denied_fetch_hosts=(), search_cache_ttl=1)
        assert provider._key(TOOL_INDEX) != original_key and provider._get(TOOL_INDEX) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_disabled_domain_exclusion_and_missing_explicit_tool_make_no_requests():
    provider, transport = make()
    assert await provider.search("Python filtering", "en", 5, ["bilibili.com"], original_point="Python filtering") == []
    assert await provider.search("中文知识点", "zh", 5, [], original_point="中文知识点") == []
    provider.settings = replace(provider.settings, fetch_enabled=False)
    assert await search(provider) == []
    assert transport.calls == []


@pytest.mark.asyncio
async def test_network_failure_may_try_second_index_but_retains_failure():
    provider, transport = make({TOOL_INDEX: httpx.ConnectError("synthetic secret must never be logged")})
    rows = await search(provider)
    assert len(rows) == 1 and transport.calls == [ORIGIN + "/robots.txt", TOOL_INDEX, VIDEO_DIRECTORY]
    assert provider.last_discovery["indexes"][0]["status"] == "network_error"
    assert provider.last_warnings[0]["code"] == "search_unavailable"
    assert "secret" not in str(provider.last_discovery) + str(provider.last_warnings)


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.asyncio
async def test_access_denial_stops_source_without_second_path(status):
    provider, transport = make({TOOL_INDEX: (status, b"", {})})
    with pytest.raises(SearchError) as denied:
        await search(provider)
    assert denied.value.code == "access_denied"
    assert transport.calls == [ORIGIN + "/robots.txt", TOOL_INDEX]
    assert NETWORK_OBSERVER.get() is None
    before = list(transport.calls)
    with pytest.raises(SearchError):
        await provider.search("Arduino analog input", "en", 3, [], original_point="Arduino analog input")
    assert transport.calls == before and provider.last_discovery["source_stopped"] is True
    assert provider.last_requests == []


@pytest.mark.asyncio
async def test_robots_denial_stops_before_tag_and_no_alternate_path():
    provider, transport = make({ORIGIN + "/robots.txt": b"User-agent: *\nDisallow: /news/\n"})
    with pytest.raises(SearchError) as denied:
        await search(provider)
    assert denied.value.code == "access_denied" and transport.calls == [ORIGIN + "/robots.txt"]
    assert provider._hard_stopped == "robots_blocked"


@pytest.mark.asyncio
async def test_html_captcha_stops_all_later_tags_without_becoming_empty_success():
    provider, transport = make({TOOL_INDEX: b"<html><title>Verify you are human</title><form id='challenge-form'></form></html>"})
    with pytest.raises(SearchError) as denied:
        await search(provider)
    assert denied.value.code == "access_denied" and provider.last_discovery["stop_reason"] == "captcha"
    before = len(transport.calls)
    with pytest.raises(SearchError):
        await search(provider)
    assert len(transport.calls) == before and provider.last_status == "fault"


@pytest.mark.parametrize("header,minimum", [("120", 119), (None, 59)])
@pytest.mark.asyncio
async def test_retry_after_or_conservative_default_cools_source_without_permanent_ban(header, minimum):
    provider, transport = make({TOOL_INDEX: (429, b"", {"retry-after": header} if header else {})})
    with pytest.raises(SearchError):
        await search(provider)
    assert provider._hard_stopped is None and provider._cooldown_until - time.monotonic() >= minimum
    before = len(transport.calls)
    with pytest.raises(SearchError):
        await search(provider)
    assert len(transport.calls) == before and provider.last_discovery["stop_reason"] == "rate_limited"


@pytest.mark.asyncio
async def test_unexpected_api_content_type_never_becomes_directory_cards():
    provider, transport = make({TOOL_INDEX: (200, card().encode(), {"content-type": "application/json"})})
    with pytest.raises(SearchError) as invalid:
        await search(provider)
    assert invalid.value.code == "invalid_response" and VIDEO_DIRECTORY not in transport.calls


@pytest.mark.asyncio
async def test_redirect_outside_public_directory_is_blocked_before_connection():
    provider, transport = make({TOOL_INDEX: (302, b"", {"location": ORIGIN + "/api/internal"})})
    with pytest.raises(SearchError):
        await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", TOOL_INDEX]
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_budget_preserves_only_already_observed_cards_and_clears_context():
    provider, transport = make()
    reserved = []
    async def reserve():
        if len(reserved) >= 2:
            raise SearchBudgetReached()
        reserved.append(1)
    provider.request_hook = reserve
    with pytest.raises(SearchBudgetReached) as stopped:
        await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", TOOL_INDEX]
    assert len(stopped.value.partial_candidates) == 1
    assert stopped.value.partial_candidates[0].discovery_evidence["source_url"] == TOOL_INDEX
    assert provider.last_discovery["budget_stopped"] is True
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_second_index_failure_returns_first_observations_with_explicit_warning():
    provider, transport = make({VIDEO_DIRECTORY: (401, b"", {})})
    rows = await search(provider)
    assert len(rows) == 1 and provider.last_status == "fault"
    assert provider.last_warnings[0]["code"] == "access_denied"
    assert len(transport.calls) == 3 and NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_cancellation_clears_context_and_has_no_background_requests():
    entered = asyncio.Event()
    provider, transport = make()
    original_request = transport.request
    async def blocked(url, addresses, max_bytes):
        if url == TOOL_INDEX:
            entered.set()
            await asyncio.Event().wait()
        return await original_request(url, addresses, max_bytes)
    transport.request = blocked
    task = asyncio.create_task(search(provider))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert NETWORK_OBSERVER.get() is None and VIDEO_DIRECTORY not in transport.calls
