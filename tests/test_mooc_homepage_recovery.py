"""Offline official-homepage evidence, background routing, and spend contracts."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.app import fast_video_search as fast
from backend.app import helpful_video_chapters as chapters
from backend.app import native_catalog_cache as cache_module
from backend.app.course_library import CourseLibrary, course_entry_key
from backend.app.db import Store
from backend.app.fetcher import Fetcher, NETWORK_OBSERVER
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher
from backend.app.native_catalog_cache import NativeCatalogCache
from test_background_covers import POINTS, state_with_cards
from test_fast_video_search import settings


NOW = 1800000000.0
DETAIL = "https://www.icourse163.org/course/detail.htm?cid=9003"
HOME = "https://www.icourse163.org/course/HIT-9003"
DOC = "https://docs.icourse163.org/api-doc/get-info.html"
IMAGE = "https://mooc-image.nosdn.127.net/observed-course-cover.jpg"
RESOURCE = {"resource_id": "same-course", "url": DETAIL, "canonical_url": DETAIL,
            "title": "公开课程", "thumbnail_url": None}


def stamp(seconds=NOW - 10):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Homepage tests cannot search, call a model, or use the real network")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(fast, "build_provider", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)
    monkeypatch.setattr(chapters, "COVER_TRANSIENT_RETRY_BACKOFF_SECONDS", .01)


@pytest.fixture
def env(monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(time=lambda: clock[0]))
    store = Store(":memory:")
    try:
        yield store, clock
    finally:
        store.close()


def remember(cache, resource=RESOURCE, home=HOME, *, source=DOC, observed_at=None):
    return cache.observe_homepage(resource, home, source_url=source,
                                  observed_at=stamp() if observed_at is None else observed_at)


def alias_row(store):
    return store.connection.execute("SELECT * FROM cache WHERE kind='mooc_homepage_alias_v1'").fetchone()


def native_cover(resource):
    return {"url": resource["url"], "resolved_url": resource["url"], "fetch_status": "fetched",
            "fetched_at": stamp(), "thumbnail_url": IMAGE,
            "field_provenance": {"thumbnail_url": {"source": "html.icourse163.course_cover",
                "url": resource["url"], "fetched_at": stamp()}},
            "chapters": [{"title": "不应替换已审核章节", "source_url": resource["url"],
                "source": "html.icourse163.course_outline", "page_number": 99}]}


async def fake_native_request(resource, calls, *, failure=None):
    calls.append(deepcopy(resource))
    observer = NETWORK_OBSERVER.get()
    assert observer is not None
    await observer["before_target_http"]()
    return ({"url": resource["url"], "fetch_status": failure}
            if failure else native_cover(resource))


async def finish(enricher):
    enricher.finish_admission()
    await asyncio.wait_for(enricher.run_background_match(collect_seconds=0), 2)


@pytest.mark.parametrize("source", [HOME, DETAIL, DOC])
def test_official_observation_is_stored_without_guessing_or_private_fields(env, source):
    store, _ = env
    cache = NativeCatalogCache(store)
    resource = {**RESOURCE, "project_id": "private-project", "query": "private-query",
                "school": "do-not-guess-this-prefix"}
    original = deepcopy(resource)
    assert remember(cache, resource, source=source) is True
    assert cache.lookup_homepage(resource) == HOME
    assert resource == original
    saved = alias_row(store)
    assert saved["created"] == NOW - 10 and saved["expires"] == NOW - 10 + 86400
    assert HOME in saved["data"] and source in saved["data"] and stamp() in saved["data"]
    assert "private" not in saved["data"] and "do-not-guess" not in saved["data"]
    before = store.connection.total_changes
    assert cache.lookup_homepage({**RESOURCE, "resource_id": "another-job"}) == HOME
    assert store.connection.total_changes == before


@pytest.mark.parametrize("home", [
    "https://www.icourse163.org/course/HIT-9004", HOME + "?tid=4", DETAIL,
    "http://www.icourse163.org/course/HIT-9003", "https://evil.example/course/HIT-9003",
    "https://www.icourse163.org.evil.example/course/HIT-9003", HOME + "#chapter",
    "https://name:secret@www.icourse163.org/course/HIT-9003",
    "https://www.icourse163.org:8443/course/HIT-9003", HOME + "?redirect=https://evil.example",
    "https://www.icourse163.org/learn/HIT-9003", "/course/HIT-9003", "HIT-9003",
])
def test_alias_must_be_same_course_and_term_public_https_homepage(env, home):
    store, _ = env
    cache = NativeCatalogCache(store)
    assert remember(cache, home=home) is False
    assert cache.lookup_homepage(RESOURCE) is None and alias_row(store) is None


@pytest.mark.parametrize("source", [
    "https://evil.example/observed", "https://docs.icourse163.org.evil.example/read",
    "http://docs.icourse163.org/api-doc/get-info.html", "https://user:pass@docs.icourse163.org/read",
    "https://docs.icourse163.org:8443/read", DOC + "#guess", "search result", None,
])
def test_external_or_unsafe_source_claim_is_not_persisted(env, source):
    store, _ = env
    cache = NativeCatalogCache(store)
    assert remember(cache, source=source) is False
    assert alias_row(store) is None


def test_school_prefix_is_observed_not_generated_and_terms_never_cross(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    resource = {**RESOURCE, "url": DETAIL + "&tid=123", "canonical_url": DETAIL + "&tid=123"}
    before = store.connection.total_changes
    assert cache.lookup_homepage({**resource, "school": "HIT"}) is None
    assert store.connection.total_changes == before
    assert remember(cache, resource, HOME + "?tid=123") is True
    assert cache.lookup_homepage(resource) == HOME + "?tid=123"
    assert cache.lookup_homepage(RESOURCE) is None
    assert cache.lookup_homepage({"url": DETAIL + "&tid=124"}) is None
    assert cache.lookup_homepage({"url": "https://www.icourse163.org/course/detail.htm?cid=9004&tid=123"}) is None


@pytest.mark.parametrize("observed_at", [stamp(NOW + 1), stamp(NOW - 86400),
    "2027-01-15T08:00:00", "invalid", NOW, None])
def test_alias_requires_current_timezone_bound_observation(env, observed_at):
    store, _ = env
    cache = NativeCatalogCache(store)
    assert cache.observe_homepage(RESOURCE, HOME, source_url=DOC, observed_at=observed_at) is False
    assert alias_row(store) is None


def test_expiry_does_not_extend_on_lookup_and_zero_ttl_disables_aliases(env):
    store, clock = env
    cache = NativeCatalogCache(store, ttl_seconds=30)
    assert remember(cache)
    original = dict(alias_row(store))
    clock[0] += 19
    assert cache.lookup_homepage(RESOURCE) == HOME
    assert dict(alias_row(store)) == original
    clock[0] += 2
    assert cache.lookup_homepage(RESOURCE) is None
    disabled = NativeCatalogCache(store, ttl_seconds=0)
    assert remember(disabled, observed_at=stamp(clock[0] - 1)) is False
    assert disabled.lookup_homepage(RESOURCE) is None


def test_older_or_equal_alias_evidence_cannot_overwrite_original_source(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    assert remember(cache)
    original = dict(alias_row(store))
    alternative = "https://www.icourse163.org/course/OTHER-9003"
    assert remember(cache, home=alternative, observed_at=stamp(NOW - 20)) is False
    assert remember(cache, home=alternative) is False
    assert dict(alias_row(store)) == original
    assert cache.lookup_homepage(RESOURCE) == HOME


@pytest.mark.parametrize("damage", ["course", "term", "source", "time", "created", "expired", "json"])
def test_retained_alias_is_revalidated_on_read(env, damage):
    store, _ = env
    cache = NativeCatalogCache(store)
    assert remember(cache)
    row = dict(alias_row(store))
    data = json.loads(row["data"])
    if damage == "course": data["homepage_url"] = HOME.replace("9003", "9004")
    elif damage == "term": data["homepage_url"] = HOME + "?tid=456"
    elif damage == "source": data["source_url"] = "https://evil.example/claim"
    elif damage == "time": data["observed_at"] = stamp(NOW + 1)
    elif damage == "created": row["created"] -= 1
    elif damage == "expired": row["expires"] = NOW
    row["data"] = "{" if damage == "json" else json.dumps(data)
    store.connection.execute("UPDATE cache SET created=?,expires=?,data=? WHERE key=?",
        (row["created"], row["expires"], row["data"], row["key"]))
    changes = store.connection.total_changes
    assert cache.lookup_homepage(RESOURCE) is None
    assert store.connection.total_changes == changes


@pytest.mark.parametrize("damage", [None, "not_fetched", "paid", "canonical", "stale"])
def test_only_identity_bound_actual_page_observation_can_seed_an_alias(env, damage):
    store, _ = env
    cache = NativeCatalogCache(store)
    metadata = {"url": DETAIL, "resolved_url": HOME, "fetch_status": "fetched", "fetched_at": stamp()}
    if damage == "not_fetched": metadata["fetch_status"] = "timeout"
    elif damage == "paid": metadata["requires_payment"] = True
    elif damage == "canonical": metadata["canonical_url"] = HOME.replace("9003", "9004")
    elif damage == "stale": metadata["cache"] = {"stale": True}
    original = deepcopy(metadata)
    cache.observe(RESOURCE, metadata)
    assert cache.lookup_homepage(RESOURCE) == (HOME if damage is None else None)
    # An observed URL alone is neither a cover nor a catalog fact.
    assert cache.lookup(RESOURCE) is None and metadata == original


@pytest.mark.parametrize("shared_enabled", [True, False])
def test_revocation_blocks_older_alias_even_after_negative_expiry(env, shared_enabled):
    store, _ = env
    CourseLibrary(store)
    cache = NativeCatalogCache(store, shared_library_enabled=shared_enabled)
    assert remember(cache)
    store.connection.execute("INSERT INTO shared_mooc_courses VALUES(?,?,?,?,?,?)",
        (course_entry_key(DETAIL), "{}", NOW - 5, NOW - 1, "revoked", "{}"))
    assert cache.lookup_homepage(RESOURCE) is None
    assert remember(cache, observed_at=stamp(NOW - 2)) is True
    assert cache.lookup_homepage(RESOURCE) == HOME


@pytest.mark.parametrize("damage", ["paid", "canonical", "non_mooc"])
def test_resource_itself_must_be_eligible_and_identity_consistent(env, damage):
    store, _ = env
    resource = deepcopy(RESOURCE)
    if damage == "paid": resource["requires_payment"] = True
    elif damage == "canonical": resource["canonical_url"] = HOME.replace("9003", "9004")
    else: resource.update(url="https://www.bilibili.com/video/av9003", canonical_url="https://www.bilibili.com/video/av9003")
    cache = NativeCatalogCache(store)
    assert remember(cache, resource) is False
    assert cache.lookup_homepage(resource) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["foreground", "background_chapters", "background_covers"])
async def test_homepage_lookup_only_changes_background_cover_fetch_input(monkeypatch, mode):
    calls, looked_up, covers, published = [], [], [], []
    original = deepcopy(RESOURCE)
    async def fetch(_self, resource, **_kwargs):
        return await fake_native_request(resource, calls)
    def lookup(resource):
        looked_up.append(deepcopy(resource))
        return HOME
    monkeypatch.setattr(Fetcher, "enrich", fetch)
    cover_only = mode == "background_covers"
    enricher = HelpfulVideoChapterEnricher(settings(), POINTS, homepage_lookup=lookup,
        background_mode=mode != "foreground", cover_only=cover_only, deadline=time.monotonic() + 2,
        max_semantic_batches=0, on_cover=lambda *args: covers.append(args), publish=lambda *args: published.append(args))
    try:
        assert enricher.enqueue(RESOURCE, ["loop"])
        await finish(enricher)
        assert [row["url"] for row in calls] == [HOME if cover_only else DETAIL]
        assert bool(looked_up) is cover_only
        assert RESOURCE == original
        assert enricher.diagnostics["network_scheduled_resources"] == 1
        assert enricher.diagnostics["fetch_attempts"] == enricher.diagnostics["http_requests"] == 1
        assert covers[0][0] == RESOURCE["resource_id"]
        if cover_only:
            assert covers[0][1]["source_url"] == HOME and published == []
        assert all(task.done() for task in enricher._tasks)
    finally:
        await enricher.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup_result", [HOME.replace("9003", "9004"), HOME + "?tid=9",
    "http://www.icourse163.org/course/HIT-9003", "https://evil.example/course/HIT-9003", DETAIL, None])
async def test_callback_output_is_revalidated_before_background_fetch(monkeypatch, lookup_result):
    calls = []
    async def fetch(_self, resource, **_kwargs):
        return await fake_native_request(resource, calls)
    monkeypatch.setattr(Fetcher, "enrich", fetch)
    enricher = HelpfulVideoChapterEnricher(settings(), POINTS, homepage_lookup=lambda _: lookup_result,
        cover_only=True, background_mode=True, deadline=time.monotonic() + 2, max_semantic_batches=0)
    try:
        assert enricher.enqueue(RESOURCE, ["loop"])
        await finish(enricher)
        assert [row["url"] for row in calls] == [DETAIL]
    finally:
        await enricher.close()


def mooc_state(count):
    state = state_with_cards(count)
    for index, row in enumerate(state["recommendations"]["loop"]):
        url = f"https://www.icourse163.org/course/detail.htm?cid={9003 + index}"
        row["resource"].update(url=url, canonical_url=url, platform="icourse163")
    return state


@pytest.mark.asyncio
async def test_remaining_three_admissions_prioritize_observed_aliases_without_resetting_spend(env, monkeypatch):
    store, _ = env
    cache = NativeCatalogCache(store)
    state = mooc_state(5)
    state["diagnostics"]["covers"] = {"network_scheduled_resources": 93, "http_requests": 145,
        "fetch_attempts": 93, "cover_retry_attempts": 4, "cover_retry_succeeded": 2}
    original, calls = deepcopy(state), []
    for index in (3, 4):
        resource = state["recommendations"]["loop"][index]["resource"]
        assert remember(cache, resource, f"https://www.icourse163.org/course/OBSERVED-{9003 + index}")
    async def fetch(_self, resource, **_kwargs):
        return await fake_native_request(resource, calls)
    monkeypatch.setattr(Fetcher, "enrich", fetch)
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None, catalog_cache=cache)
    assert [row["url"] for row in calls] == [
        "https://www.icourse163.org/course/OBSERVED-9006",
        "https://www.icourse163.org/course/OBSERVED-9007", DETAIL]
    detail = result["diagnostics"]["covers"]
    assert detail["network_scheduled_resources"] == 96 and detail["http_requests"] == 148
    assert detail["fetch_attempts"] == 96 and detail["cover_retry_attempts"] == 4
    assert detail["cover_retry_succeeded"] == 2
    assert result["catalog_enrichment"]["status"] == "partial"
    for before, after in zip(original["recommendations"]["loop"], result["recommendations"]["loop"]):
        assert after["resource"]["url"] == before["resource"]["url"]
        assert after["resource"]["canonical_url"] == before["resource"]["canonical_url"]
        assert after["resource"]["resource_id"] == before["resource"]["resource_id"]
        assert after["matched_chapters"] == before["matched_chapters"]
        assert after["added_at"] == before["added_at"]
    for field in ("status", "started_at", "finished_at", "elapsed_seconds", "progress"):
        assert result[field] == original[field]
    assert result["diagnostics"]["searches"] == original["diagnostics"]["searches"]
    assert result["diagnostics"]["chapters"] == original["diagnostics"]["chapters"]
    assert state == original


@pytest.mark.asyncio
async def test_alias_retry_spends_two_http_but_one_course_and_preserves_cumulative_history(env, monkeypatch):
    store, _ = env
    cache = NativeCatalogCache(store)
    state = mooc_state(1)
    assert remember(cache, state["recommendations"]["loop"][0]["resource"])
    state["diagnostics"]["covers"] = {"network_scheduled_resources": 95, "http_requests": 286,
        "fetch_attempts": 97, "cover_retry_attempts": 2, "cover_retry_succeeded": 1}
    original, calls = deepcopy(state), []
    async def fetch(_self, resource, **_kwargs):
        return await fake_native_request(resource, calls, failure="network_error" if not calls else None)
    monkeypatch.setattr(Fetcher, "enrich", fetch)
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None, catalog_cache=cache)
    assert [row["url"] for row in calls] == [HOME, HOME]
    detail = result["diagnostics"]["covers"]
    assert detail["network_scheduled_resources"] == 96 and detail["http_requests"] == 288
    assert detail["fetch_attempts"] == 99 and detail["cover_retry_attempts"] == 3
    assert detail["cover_retry_succeeded"] == 2 and detail["page_failures_unresolved"] == 0
    assert len(detail["resources"][0]["attempts"]) == 2
    assert result["catalog_enrichment"]["status"] == "completed"
    assert result["recommendations"]["loop"][0]["matched_chapters"] == original["recommendations"]["loop"][0]["matched_chapters"]
    assert result["progress"] == original["progress"]
    assert result["elapsed_seconds"] == original["elapsed_seconds"]
