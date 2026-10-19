"""Offline public-directory parser/Fetcher transport tests, no live source calls."""
import asyncio
from dataclasses import replace
import hashlib
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER
from backend.app.providers import SearchBudgetReached, SearchError
from backend.app.techwithtim_catalog import (
    ORIGIN, TechWithTimCatalogProvider, catalog_url, lesson_url, parse_catalog, MAX_INDEX_BYTES,
)

ENTRY = ORIGIN + "/tutorials/game-development-with-python"
SERIES = ENTRY + "/observed-series"
LESSON = SERIES + "/observed-collision-lesson"


def card(href, title="General pygame lessons", description="Build a 2D game with Python and pygame."):
    return (f'<div class="tutorial__TutorialCardContainer-test"><h3 class="tutorial__TutorialCardTitle-test">{title}</h3>'
        f'<p class="tutorial__TutorialCardDescription-test">{description}</p><a href="{href}">Get started</a></div>')


def series_html():
    return ('<div class="tutoriallayout__Lessons-test">' +
        f'<a href="{LESSON}">Collision &amp; Hit Boxes</a>' +
        ''.join(f'<a href="{SERIES}/lesson-{i}">Basic Movement {i}</a>' for i in range(10)) + '</div>').encode()


class Transport:
    def __init__(self, documents=None):
        self.documents = {ORIGIN + "/robots.txt": b"User-agent: *\nAllow: /tutorials\n",
            ENTRY: card(SERIES).encode(), SERIES: series_html()}
        self.documents.update(documents or {})
        self.calls, self.limits = [], []

    async def request(self, url, addresses, max_bytes):
        self.calls.append(url)
        self.limits.append(max_bytes)
        await asyncio.sleep(0)
        value = self.documents[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            status, body, headers = value
            return HTTPResult(status, headers, body, url)
        return HTTPResult(200, {"content-type": "text/html"}, value, url)


async def resolver(url, timeout):
    return ["9.9.9.9"]


def make(documents=None, store=None, **kwargs):
    transport = Transport(documents)
    fetcher = Fetcher(FetcherConfig(global_concurrency=1, min_interval_seconds=0, max_retries=1), resolver=resolver, http_client=transport)
    return TechWithTimCatalogProvider(Settings(**kwargs), fetcher=fetcher, store=store), transport


async def search(provider, query="pygame rectangle collision video", **kwargs):
    return await provider.search(query, "any", 6, [], original_point="pygame rectangle collision", **kwargs)


@pytest.mark.parametrize("url", ["https://techwithtim.net/tutorials/game-development-with-python", "http://www.techwithtim.net/tutorials/game-development-with-python",
    "https://www.techwithtim.net.evil.example/tutorials/game-development-with-python", ORIGIN + "/api/search", ORIGIN + "/_next/data/private.json",
    ENTRY + "?utm_source=x", ENTRY + "#x", ENTRY + "/../private", ENTRY + "/%2e%2e/private", ORIGIN + "/tutorials//private",
    "https://user:pass@www.techwithtim.net/tutorials", "https://127.1/tutorials", "https://www.techwithtim.net:8080/tutorials"])
def test_source_url_guard_rejects_wrong_origin_apis_queries_and_ambiguous_paths(url):
    assert catalog_url(url) is None and lesson_url(url) is None


def test_series_and_lesson_have_separate_scopes_without_guessing_paths():
    assert catalog_url(SERIES) == SERIES and lesson_url(SERIES) is None
    assert lesson_url(LESSON) == LESSON and catalog_url(LESSON) is None
    assert lesson_url(LESSON + "/media.mp4") is None
    assert lesson_url(LESSON + "/") == LESSON


def test_category_parser_scopes_title_and_description_to_one_observed_card():
    body = (card(SERIES, "Observed pygame series", "Own description") + card(SERIES) +
        card(ORIGIN + "/tutorials/other/other-series") + card("https://evil.example/tutorials/a/b") +
        f'<footer><a href="{ENTRY}/footer-series">Collision</a></footer>').encode()
    result = parse_catalog(body, ENTRY)
    assert result["cards"] == [{"url": SERIES, "title": "Observed pygame series", "snippet": "Own description"}]
    assert result["lessons"] == [] and result["kind"] == "category"
    assert result["source_sha256"] == hashlib.sha256(body).hexdigest()


def test_series_parser_admits_only_observed_same_series_lesson_sidebar_links():
    body = (series_html().decode() + f'<a href="{SERIES}/outside-sidebar">Outside</a>' +
        '<div class="tutoriallayout__Lessons-test"><a href="/tutorials/other/other-series/other-lesson">Other</a>' +
        f'<a href="{SERIES}">Series itself</a><a href="{SERIES}/query?private=1">Query route</a></div>').encode()
    result = parse_catalog(body, SERIES)
    assert len(result["lessons"]) == 11 and result["lessons"][0]["title"] == "Collision & Hit Boxes"
    assert result["cards"] == [] and all(row["url"].startswith(SERIES + "/") for row in result["lessons"])


@pytest.mark.parametrize("body,url", [(b"\x00", ENTRY), (b"x" * (MAX_INDEX_BYTES + 1), ENTRY), (b"", ORIGIN + "/api/search")], ids=["nul", "oversized", "outside-scope"])
def test_parser_has_explicit_scope_and_size_limits(body, url):
    with pytest.raises(SearchError):
        parse_catalog(body, url)


@pytest.mark.asyncio
async def test_two_directory_pages_plus_robots_return_six_observed_lessons_without_video_upgrade():
    provider, transport = make()
    rows = await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY, SERIES]
    assert len(rows) == 6 and rows[0].url == LESSON
    assert len(provider.last_requests) == 3 and all(row["source_sha256"] for row in provider.last_requests)
    assert all(row.source == "techwithtim_catalog" and row.resource_type_hint == "unknown" and row.type_source is None for row in rows)
    assert all(row.discovery_evidence["independent_detail_required"] and row.discovery_evidence["confidence"] == "low" for row in rows)
    assert rows[0].discovery_evidence["source_url"] == SERIES
    assert rows[0].snippet == "" and rows[0].discovery_evidence["parent_series_url"] == SERIES
    assert all(limit <= MAX_INDEX_BYTES for limit in transport.limits)
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_selects_series_using_own_card_text_not_url_words_or_other_cards():
    other = ENTRY + "/opaque-series-two"
    provider, transport = make({ENTRY: (card(SERIES, "General game series", "An introductory game.") +
        card(other, "Grid and collision tutorial", "Grid collision movement.")).encode(), other: (f'<div class="tutoriallayout__Lessons-test"><a href="{other}/opaque-lesson">Grid movement</a></div>').encode()})
    rows = await search(provider, "pygame grid collision movement tutorial")
    assert transport.calls[-1] == other and len(transport.calls) == 3
    assert rows[0].title == "Grid movement" and rows[0].resource_type_hint == "unknown"


@pytest.mark.asyncio
async def test_unsupported_tools_missing_explicit_tool_disabled_or_excluded_domain_do_not_fetch():
    provider, transport = make()
    assert await provider.search("JavaScript button", "en", 6, [], original_point="JavaScript button") == []
    assert await provider.search("中文知识点", "zh", 6, [], original_point="中文知识点") == []
    assert await provider.search("pygame collision", "en", 6, ["bilibili.com"], original_point="pygame collision") == []
    provider.settings = replace(provider.settings, fetch_enabled=False)
    assert await search(provider) == [] and transport.calls == []


@pytest.mark.asyncio
async def test_python_category_is_general_source_structure_not_pygame_demo_seed():
    category = ORIGIN + "/tutorials/python-programming"
    observed_series = category + "/an-observed-general-series"
    provider, transport = make({category: card(observed_series, "Python functions", "Functions and return values").encode(),
        observed_series: f'<div class="tutoriallayout__Lessons-test"><a href="{observed_series}/opaque">Function results</a></div>'.encode()})
    rows = await provider.search("Python functions return video", "en", 6, [], original_point="Python functions return")
    assert transport.calls == [ORIGIN + "/robots.txt", category, observed_series]
    assert rows[0].url == observed_series + "/opaque"


@pytest.mark.asyncio
async def test_cached_source_facts_reuse_http_zero_and_source_policy_is_cache_keyed(tmp_path):
    store = Store(str(tmp_path / "test.sqlite3"))
    provider, transport = make(store=store)
    try:
        assert await search(provider)
        count = len(transport.calls)
        rows = await search(provider)
        assert len(transport.calls) == count and provider.last_requests == []
        assert rows[0].discovery_evidence["cache_hit"] is True
        assert store.connection.execute("SELECT count(*) FROM cache WHERE kind='techwithtim_catalog'").fetchone()[0] == 2
        old = provider._key(ENTRY)
        provider.settings = replace(provider.settings, denied_fetch_hosts=("techwithtim.net",))
        assert old != provider._key(ENTRY) and provider._get(ENTRY) is None
        provider.settings = replace(provider.settings, search_cache_ttl=2)
        assert provider._get(ENTRY) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_budget_stop_keeps_directory_facts_but_never_substitutes_series_as_video():
    provider, transport = make()
    reserved = []
    async def reserve():
        if len(reserved) >= 2:
            raise SearchBudgetReached()
        reserved.append(1)
    provider.request_hook = reserve
    with pytest.raises(SearchBudgetReached) as stopped:
        await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY]
    assert stopped.value.partial_candidates == [] and provider._get(ENTRY)
    assert provider.last_discovery["budget_stopped"] is True and NETWORK_OBSERVER.get() is None


@pytest.mark.parametrize("value", [(401, b"", {}), (403, b"", {}), b"<html><title>Verify you are human</title></html>"])
@pytest.mark.asyncio
async def test_access_restriction_persistently_stops_this_source_without_trying_another_category(value):
    provider, transport = make({ENTRY: value})
    with pytest.raises(SearchError) as denied:
        await search(provider)
    assert denied.value.code == "access_denied" and provider.last_discovery["source_stopped"] is True
    count = len(transport.calls)
    with pytest.raises(SearchError):
        await provider.search("Python list video", "en", 6, [], original_point="Python list")
    assert len(transport.calls) == count and provider.last_requests == []


@pytest.mark.parametrize("header,minimum", [("120", 119), (None, 59)])
@pytest.mark.asyncio
async def test_source_retry_after_or_default_cooldown_blocks_later_queries(header, minimum):
    provider, transport = make({ENTRY: (429, b"", {"retry-after": header} if header else {})})
    with pytest.raises(SearchError):
        await search(provider)
    assert provider._hard_stopped is None and provider._cooldown_until - time.monotonic() >= minimum
    count = len(transport.calls)
    with pytest.raises(SearchError):
        await search(provider)
    assert len(transport.calls) == count and provider.last_discovery["stop_reason"] == "rate_limited"


@pytest.mark.asyncio
async def test_robots_denial_stops_before_category():
    provider, transport = make({ORIGIN + "/robots.txt": b"User-agent: *\nDisallow: /tutorials\n"})
    with pytest.raises(SearchError) as denied:
        await search(provider)
    assert denied.value.code == "access_denied" and transport.calls == [ORIGIN + "/robots.txt"]


@pytest.mark.parametrize("target", [ORIGIN + "/api/internal", ENTRY + "/unobserved-series", "https://evil.example/tutorials"])
@pytest.mark.asyncio
async def test_redirect_to_even_same_origin_unobserved_path_is_blocked_before_http(target):
    provider, transport = make({ENTRY: (302, b"", {"location": target})})
    with pytest.raises(SearchError):
        await search(provider)
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY] and NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_timeout_is_not_retried_and_raw_transport_text_is_not_logged():
    provider, transport = make({SERIES: httpx.ReadTimeout("SECRET untrusted error")})
    with pytest.raises(SearchError):
        await search(provider)
    assert transport.calls.count(SERIES) == 1
    assert "SECRET" not in str(provider.last_warnings) + str(provider.last_discovery)
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_cancel_stops_pending_series_and_restores_context():
    provider, transport = make()
    entered = asyncio.Event()
    original = transport.request
    async def blocked(url, addresses, max_bytes):
        if url == SERIES:
            entered.set()
            await asyncio.Event().wait()
        return await original(url, addresses, max_bytes)
    transport.request = blocked
    task = asyncio.create_task(search(provider))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert NETWORK_OBSERVER.get() is None
