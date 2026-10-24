"""Offline exact native catalog reuse; no recommendation or query reuse."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest

from backend.app import course_library
from backend.app import native_catalog_cache as module
from backend.app.course_library import CourseLibrary, course_entry_key
from backend.app.db import Store
from backend.app.helpful_video_chapters import catalog_identity, observed_chapters, observed_cover
from backend.app.native_catalog_cache import NativeCatalogCache
from tests.test_course_library import observed, PROFILE, URL as MOOC_URL


NOW = 1800000000.0
URL = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
RESOURCE = {"url": URL, "resource_id": "private-job-id", "title": "Python 教程"}


def iso(value=NOW - 10):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def metadata(*, stamp=None, title="第3章 条件分支"):
    return {"url": URL, "fetched_at": stamp or iso(), "fetch_status": "fetched", "catalog_kind": "video_parts",
            "chapters": [{"title": title, "source_url": URL, "source": "html.bilibili.__INITIAL_STATE__.videoData.pages",
                          "page_number": 3, "url": URL + "?p=3"}]}


def with_cover(raw, *, source="html.bilibili.__INITIAL_STATE__.videoData.pic"):
    return {**raw, "thumbnail_url": "http://i1.hdslb.com/bfs/archive/real-cover.jpg",
            "field_provenance": {"thumbnail_url": {"source": source, "url": URL,
                "fetched_at": raw["fetched_at"], "evidence_id": "private-job-evidence"}}}


@pytest.fixture
def env(monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(course_library, "time", SimpleNamespace(time=lambda: clock[0]))
    store = Store(":memory:")
    yield store, clock
    store.close()


def own_row(store):
    return store.connection.execute("SELECT * FROM cache WHERE kind='native_catalog_v1'").fetchone()


def test_own_cache_reuses_same_video_parts_without_private_metadata_or_mutation(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    raw = metadata()
    raw.update(query="private-query", point_id="private-point", user_id="private-user", matching_evidence="private-match")
    raw["chapters"][0].update(evidence_id="private-job-evidence", project_id="private-project", point_id="private-point")
    before = deepcopy((RESOURCE, raw))
    assert cache.observe(RESOURCE, raw) is None
    hit = cache.lookup({"url": URL.replace("www.", "") + "/?p=9", "resource_id": "other-job"})
    assert len(observed_chapters(RESOURCE, hit)) == 1
    assert hit["catalog_cache"] == {"source": "native_catalog_cache", "observed_at": iso()}
    assert (RESOURCE, raw) == before
    persisted = own_row(store)["data"]
    assert "private" not in persisted and "query" not in persisted and "point" not in persisted
    hit["chapters"][0]["title"] = "caller change"
    assert cache.lookup(RESOURCE)["chapters"][0]["title"] == "第3章 条件分支"


@pytest.mark.parametrize("has_chapters", [True, False])
def test_cache_preserves_native_cover_with_or_without_chapters_and_strips_job_fields(env, has_chapters):
    store, _ = env
    raw = with_cover(metadata())
    if not has_chapters:
        raw["chapters"] = []
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, raw)
    hit = cache.lookup(RESOURCE)
    cover = observed_cover(RESOURCE, hit)
    assert cover["thumbnail_url"] == "https://i1.hdslb.com/bfs/archive/real-cover.jpg"
    assert cover["observed_at"] == iso()
    assert cover["provenance"]["original_thumbnail_url"] == raw["thumbnail_url"]
    assert bool(hit["chapters"]) is has_chapters
    assert "private" not in own_row(store)["data"]


@pytest.mark.parametrize("source", ["meta.og:image", "meta.og:image:secure_url"])
def test_cache_preserves_source_bound_og_cover_without_requiring_a_catalog(env, source):
    store, _ = env
    raw = with_cover({**metadata(), "chapters": []}, source=source)
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, raw)
    assert observed_cover(RESOURCE, cache.lookup(RESOURCE))["source"] == source


@pytest.mark.parametrize("damage", ["foreign", "search", "jsonld", "no_provenance", "old_cover", "future_cover", "http", "paid", "not_found"])
def test_cache_rejects_unbound_stale_or_unsupported_cover_only_observations(env, damage):
    store, _ = env
    raw = with_cover({**metadata(), "chapters": []})
    receipt = raw["field_provenance"]["thumbnail_url"]
    if damage == "foreign": receipt["url"] = "https://www.bilibili.com/video/av999"
    elif damage == "search": receipt["source"] = "search.thumbnail"
    elif damage == "jsonld": receipt["source"] = "jsonld.image"
    elif damage == "no_provenance": raw.pop("field_provenance")
    elif damage == "old_cover": receipt["fetched_at"] = iso(NOW - 86400)
    elif damage == "future_cover": receipt["fetched_at"] = iso(NOW + 1)
    elif damage == "http": raw["thumbnail_url"] = "http://images.example.com/cover.jpg"
    elif damage == "paid": raw["requires_payment"] = True
    elif damage == "not_found": raw["fetch_status"] = "not_found"
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, raw)
    assert cache.lookup(RESOURCE) is None and own_row(store) is None


def test_cover_only_update_preserves_fresh_chapters_and_their_original_time(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, metadata())
    cache.observe(RESOURCE, with_cover({**metadata(stamp=iso(NOW - 2)), "chapters": []}))
    hit = cache.lookup(RESOURCE)
    assert len(hit["chapters"]) == 1 and hit["chapters"][0]["observed_at"] == iso()
    assert observed_cover(RESOURCE, hit)["observed_at"] == iso(NOW - 2)


def test_later_chapter_observation_preserves_cover_age_without_extending_it(env):
    store, clock = env
    cache = NativeCatalogCache(store, ttl_seconds=30)
    cache.observe(RESOURCE, with_cover({**metadata(), "chapters": []}))
    cache.observe(RESOURCE, metadata(stamp=iso(NOW - 2)))
    assert observed_cover(RESOURCE, cache.lookup(RESOURCE))["observed_at"] == iso()
    clock[0] += 21
    hit = cache.lookup(RESOURCE)
    assert hit["chapters"] and observed_cover(RESOURCE, hit) is None


def test_equal_time_cover_can_fill_old_cache_without_changing_existing_chapter_facts(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, metadata())
    cache.observe(RESOURCE, with_cover(metadata(title="changed same-time chapter")))
    hit = cache.lookup(RESOURCE)
    assert hit["chapters"][0]["title"] == "第3章 条件分支"
    assert observed_cover(RESOURCE, hit)


def test_fresh_page_cache_can_supply_cover_only_native_metadata(env):
    store, _ = env
    raw = with_cover({**metadata(), "chapters": []})
    cache = NativeCatalogCache(store, page_lookup=lambda _: ("page", {"data": raw, "cache": {"hit": True, "stale": False}}))
    hit = cache.lookup(RESOURCE)
    assert observed_cover(RESOURCE, hit) and hit["catalog_cache"]["source"] == "page_cache"


def test_cache_hit_never_extends_original_observation_or_expiry(env):
    store, clock = env
    cache = NativeCatalogCache(store, ttl_seconds=30)
    cache.observe(RESOURCE, metadata())
    first = dict(own_row(store))
    assert first["created"] == NOW - 10 and first["expires"] == NOW + 20
    clock[0] += 15
    assert cache.lookup(RESOURCE)["fetched_at"] == iso()
    cache.observe(RESOURCE, metadata())
    assert dict(own_row(store)) == first
    clock[0] += 6
    assert cache.lookup(RESOURCE) is None


def test_older_and_equal_observations_cannot_overwrite_newer_facts(env):
    store, _ = env
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, metadata())
    cache.observe(RESOURCE, metadata(stamp=iso(NOW - 20), title="older"))
    cache.observe(RESOURCE, metadata(title="same-time-different"))
    assert cache.lookup(RESOURCE)["chapters"][0]["title"] == "第3章 条件分支"
    cache.observe(RESOURCE, metadata(stamp=iso(NOW - 5), title="newer"))
    assert cache.lookup(RESOURCE)["chapters"][0]["title"] == "newer"
    assert own_row(store)["expires"] == NOW - 5 + 86400


@pytest.mark.parametrize("stamp", ["2027-01-15T08:00:00", "invalid", NOW - 10, True, iso(NOW + 1), iso(NOW - 86400)])
def test_observation_time_requires_timezone_nonfuture_and_ttl(env, stamp):
    store, _ = env
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, metadata(stamp=stamp))
    assert cache.lookup(RESOURCE) is None and own_row(store) is None


@pytest.mark.parametrize("damage", ["paid", "failed", "catalog_failed", "foreign_url", "foreign_resolved",
                                    "foreign_source", "foreign_chapter", "search_source", "paid_chapter",
                                    "future_chapter", "old_chapter", "empty", "stale"])
def test_only_fresh_identity_bound_unpaid_native_chapters_are_saved(env, damage):
    store, _ = env
    raw = metadata()
    chapter = raw["chapters"][0]
    other = "https://www.bilibili.com/video/BV1eu4y1y7pb"
    if damage == "paid": raw["requires_payment"] = True
    elif damage == "failed": raw["fetch_status"] = "robots_disallowed"
    elif damage == "catalog_failed": raw["catalog_fetch_status"] = "catalog_payload_invalid"
    elif damage == "foreign_url": raw["url"] = other
    elif damage == "foreign_resolved": raw["resolved_url"] = other
    elif damage == "foreign_source": chapter["source_url"] = other
    elif damage == "foreign_chapter": chapter["url"] = other
    elif damage == "search_source": chapter["source"] = "search"
    elif damage == "paid_chapter": chapter["requires_payment"] = True
    elif damage == "future_chapter": chapter["observed_at"] = iso(NOW + 1)
    elif damage == "old_chapter": chapter["observed_at"] = iso(NOW - 86400)
    elif damage == "empty": raw["chapters"] = []
    elif damage == "stale": raw["cache"] = {"stale": True}
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, raw)
    assert cache.lookup(RESOURCE) is None and own_row(store) is None


def test_zero_ttl_disables_reads_writes_and_page_callback(env):
    store, _ = env
    calls = []
    cache = NativeCatalogCache(store, ttl_seconds=0, page_lookup=lambda r: calls.append(r))
    cache.observe(RESOURCE, metadata())
    assert cache.lookup(RESOURCE) is None and own_row(store) is None and calls == []


def test_fresh_exact_shared_outline_is_revalidated_without_point_matching_or_writes(env):
    store, _ = env
    library = CourseLibrary(store)
    raw, evidence = observed()
    assert library.observe(raw, evidence, PROFILE)
    before = store.connection.total_changes
    cache = NativeCatalogCache(store)
    # This is a provided real URL form; no organization slug is synthesized.
    hit = cache.lookup({"url": "https://www.icourse163.org/course/detail.htm?cid=123"})
    assert len(hit["chapters"]) == 3
    assert hit["catalog_cache"] == {"source": "shared_course_library", "observed_at": iso()}
    assert "assessment" not in hit and "evidence" not in hit and "course_library" not in hit
    assert store.connection.total_changes == before and own_row(store) is None
    assert cache.lookup({"url": MOOC_URL + "?tid=456"}) is None
    assert cache.lookup({"url": MOOC_URL.replace("123", "999")}) is None


@pytest.mark.parametrize("damage", ["chapter_hash", "course", "observed", "expired", "old", "future", "revoked", "json"])
def test_shared_metadata_is_not_trusted_from_verified_status_alone(env, damage):
    store, _ = env
    library = CourseLibrary(store)
    assert library.observe(*observed(), PROFILE)
    row = dict(store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
    payload = json.loads(row["data"])
    if damage == "chapter_hash":
        chapter_id = payload["resource"]["chapters"][0]["evidence_id"]
        next(item for item in payload["evidence"] if item["evidence_id"] == chapter_id)["id"] = "broken"
    elif damage == "course": payload["resource"]["url"] = MOOC_URL.replace("123", "999")
    elif damage == "observed": row["observed"] -= 1
    elif damage == "expired": row["expires"] = NOW
    elif damage == "old": row["observed"] = NOW - 86400
    elif damage == "future": row["observed"] = NOW + 1
    elif damage == "revoked": row["status"] = "revoked"
    row["data"] = "{" if damage == "json" else json.dumps(payload)
    store.connection.execute("UPDATE shared_mooc_courses SET observed=?,expires=?,status=?,data=?",
                             (row["observed"], row["expires"], row["status"], row["data"]))
    assert NativeCatalogCache(store).lookup({"url": MOOC_URL}) is None


def test_shared_library_can_be_disabled_without_touching_the_own_cache(env):
    store, _ = env
    library = CourseLibrary(store)
    raw, evidence = observed()
    assert library.observe(raw, evidence, PROFILE)
    cache = NativeCatalogCache(store, shared_library_enabled=False)
    assert cache.lookup({"url": MOOC_URL}) is None
    cache.observe({"url": MOOC_URL}, raw)
    assert cache.lookup({"url": MOOC_URL})["catalog_cache"]["source"] == "native_catalog_cache"


@pytest.mark.parametrize("enabled", [True, False])
def test_newer_revocation_blocks_own_and_page_cache_without_resurrection(env, enabled):
    store, _ = env
    library = CourseLibrary(store)
    raw, evidence = observed()
    assert library.observe(raw, evidence, PROFILE)
    resource = {"url": MOOC_URL}
    cache = NativeCatalogCache(store, shared_library_enabled=enabled,
        page_lookup=lambda _: ("page", {"data": raw, "cache": {"hit": True, "stale": False}}))
    cache.observe(resource, raw)
    store.connection.execute("UPDATE shared_mooc_courses SET status='revoked',observed=?,expires=?", (NOW - 5, NOW - 1))
    assert cache.lookup(resource) is None
    # A new source observation after revocation is allowed, with its own age.
    newer = {**raw, "fetched_at": iso(NOW - 2)}
    cache.observe(resource, newer)
    assert cache.lookup(resource)["fetched_at"] == newer["fetched_at"]


@pytest.mark.parametrize("stale,hit", [(False, True), (True, True), (None, True), (False, False)])
def test_page_lookup_is_exact_and_fresh_only_without_job_or_history_scans(env, stale, hit):
    store, _ = env
    calls, queries = [], []
    store.connection.set_trace_callback(queries.append)

    def page(resource):
        calls.append(resource)
        assert resource["canonical_url"] == RESOURCE["url"]
        return "existing-exact-page-key", {"data": metadata(), "cache": {"hit": hit, "stale": stale}}

    found = NativeCatalogCache(store, page_lookup=page).lookup(RESOURCE)
    assert bool(found) == (hit and stale is False)
    if found: assert found["catalog_cache"]["source"] == "page_cache"
    assert len(calls) == 1
    assert not any("from jobs" in sql.lower() or "from resources" in sql.lower() for sql in queries)


def test_missing_tables_corrupt_cache_and_callback_failure_are_misses(env):
    store, _ = env
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        absent = NativeCatalogCache(SimpleNamespace(connection=connection))
        assert absent.lookup(RESOURCE) is None
        assert absent.observe(RESOURCE, metadata()) is None
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        connection.close()
    cache = NativeCatalogCache(store)
    cache.observe(RESOURCE, metadata())
    store.connection.execute("UPDATE cache SET data='{' WHERE kind='native_catalog_v1'")
    assert cache.lookup(RESOURCE) is None

    def broken(_resource):
        raise RuntimeError("optional cache unavailable")

    assert NativeCatalogCache(store, page_lookup=broken).lookup(RESOURCE) is None
