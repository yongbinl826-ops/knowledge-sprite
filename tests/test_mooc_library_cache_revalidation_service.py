"""Offline service regression for rule-only upgrades of cached public outlines.

Real extraction, SQLite caches, and JobService scheduling are exercised. Search
and page responses are synthetic; HTTP and environment loading are forbidden.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
import time

import httpx
import pytest

from backend.app import mooc_relevance
from backend.app.config import Settings
from backend.app.course_library import content_digest, profile_digest
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, SearchRequest, now
from backend.app.service import JobService
from test_bilibili_embedded_parts import URL as BILIBILI_URL, markup as bilibili_markup
from test_mooc_relevance_service import synthetic_outline


POINT = "Python 列表与字典"
MOOC_URL = "https://www.icourse163.org/course/OWN-123"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This regression must not load credentials or send HTTP")

    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


class Search:
    def __init__(self):
        self.calls = []

    async def search(self, query, *args):
        self.calls.append(query)
        mooc = "icourse163.org" in query
        return [Candidate(id="mooc" if mooc else "bilibili", title=POINT,
            url=MOOC_URL if mooc else BILIBILI_URL, query=query,
            snippet=POINT + " 课程教学", source="offline-cache-regression",
            resource_type_hint="course" if mooc else "video",
            type_source="search_template")]


class Pages:
    def __init__(self):
        self.calls = []

    async def enrich(self, candidate):
        url = candidate["url"]
        self.calls.append(url)
        assert url in {MOOC_URL, BILIBILI_URL}
        html = synthetic_outline() if url == MOOC_URL else bilibili_markup()
        return MetadataExtractor().extract(html, url, now())


def settings(tmp_path, **changes):
    return replace(Settings(database_path=str(tmp_path / "revalidation.sqlite3"),
        parallel_platform_search=True, teaching_match_enabled=False,
        shared_course_library_enabled=True, mooc_gap_search_enabled=True,
        mooc_target_courses_per_point=1, bilibili_search_rounds=2,
        mooc_search_rounds=2, max_search_requests=8, max_detail_pages=4,
        search_min_interval_seconds=0, search_max_retries=0, deadline_seconds=10),
        **changes)


async def run(jobs, *, expected_status="completed"):
    jid = jobs.create(SearchRequest(knowledge_points=[POINT],
        preferred_platforms=["bilibili", "icourse163"]))["job_id"]
    await jobs.run(jid)
    assert jobs.store.get_job(jid)["status"] == expected_status
    return jid


def library_row(store):
    rows = store.connection.execute("SELECT * FROM shared_mooc_courses").fetchall()
    assert len(rows) == 1
    return dict(rows[0])


def cache_row(store, key):
    row = store.connection.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
    return dict(row) if row is not None else None


def course_resource(store, jid, url):
    return next(row for row in store.resources(jid).values() if row["url"] == url)


def watch_observe(jobs, monkeypatch):
    calls = []
    original = jobs.course_library.observe

    def observe(resource, evidence, profile, **kwargs):
        calls.append({"resource": deepcopy(resource), "profile": profile, **kwargs})
        return original(resource, evidence, profile, **kwargs)

    monkeypatch.setattr(jobs.course_library, "observe", observe)
    return calls


def assert_bilibili_visible(jobs, jid):
    items = jobs.results(jid)["groups"][0]["discovery_items"]
    assert any(item["resource"]["url"] == BILIBILI_URL for item in items)


@pytest.mark.asyncio
async def test_rule_upgrade_revalidates_current_fresh_page_without_renewing_age_or_bilibili_cache(tmp_path, monkeypatch):
    config, search, pages = settings(tmp_path), Search(), Pages()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=pages)
        observations = watch_observe(jobs, monkeypatch)
        cold = await run(jobs)
        original = library_row(store)
        original_profile = jobs._course_library_profile()
        assert original["profile"] == profile_digest(original_profile)
        assert store.get_job(cold)["progress"]["library_courses_saved"] == 1
        assert len(observations) == 1 and not observations[0].get("current_page_cache", False)

        course = course_resource(store, cold, MOOC_URL)
        mooc_key, cached = jobs._page_cache(course)
        assert cached is not None
        assert cached["cache"]["hit"] is True and cached["cache"]["stale"] is False
        bili_key, _ = jobs._page_cache(course_resource(store, cold, BILIBILI_URL))
        original_page, original_bili = cache_row(store, mooc_key), cache_row(store, bili_key)
        original_fetches, original_searches = list(pages.calls), list(search.calls)
        assert sorted(original_fetches) == sorted([MOOC_URL, BILIBILI_URL])

        monkeypatch.setattr(mooc_relevance, "MATCH_RULES_VERSION", mooc_relevance.MATCH_RULES_VERSION + 1)
        assert jobs._course_library_profile() != original_profile
        assert jobs._page_cache(course)[0] == mooc_key
        assert not jobs.course_library.lookup({"text": POINT}, jobs._course_library_profile())

        warm = await run(jobs)
        progress = store.get_job(warm)["progress"]
        assert progress["library_hit_pairs"] == 0  # Old profile is not seeded.
        assert progress.get("library_courses_saved", 0) == 1
        assert progress["search_requests"] == 0
        assert progress["details_attempted"] == 0 and progress["details_cached"] == 2
        assert pages.calls == original_fetches and search.calls == original_searches
        assert len(observations) == 2 and observations[-1]["current_page_cache"] is True
        assert observations[-1]["resource"]["fetched_at"] == course["fetched_at"]
        assert observations[-1]["resource"]["cache"]["stale"] is False

        updated = library_row(store)
        assert updated["profile"] == profile_digest(jobs._course_library_profile()) != original["profile"]
        assert {key: updated[key] for key in ("entry_key", "observed", "expires", "status")} == {
            key: original[key] for key in ("entry_key", "observed", "expires", "status")}
        before, after = json.loads(original["data"]), json.loads(updated["data"])
        assert content_digest(before["resource"], before["evidence"]) == content_digest(after["resource"], after["evidence"])
        assert cache_row(store, mooc_key) == original_page
        assert cache_row(store, bili_key) == original_bili
        point = store.get_job(warm)["knowledge_points"][0]
        hits = jobs.course_library.lookup(point, jobs._course_library_profile())
        assert len(hits) == 1 and hits[0]["assessment"]["display_eligible"]
        assert jobs.results(warm)["groups"][0]["mooc_relevance"]["recommended_count"] == 1
        assert_bilibili_visible(jobs, warm)

        # The revalidated record subsequently follows the normal shared-library
        # path without another page replay, search, or extension of its lifetime.
        reused = await run(jobs)
        assert store.get_job(reused)["progress"]["library_hit_pairs"] == 1
        assert len(observations) == 2
        assert library_row(store) == updated
        assert pages.calls == original_fetches and search.calls == original_searches
        assert cache_row(store, bili_key) == original_bili
        assert_bilibili_visible(jobs, reused)


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_case", ["old_extractor", "expired", "expired_allow_stale"])
async def test_old_or_expired_page_cache_cannot_revalidate_an_old_library_profile(tmp_path, monkeypatch, cache_case):
    config = settings(tmp_path, allow_stale_cache=cache_case == "expired_allow_stale")
    search, pages = Search(), Pages()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=pages)
        page_fields = {}
        cache_key = store.cache_key

        def capture_key(kind, fields):
            if kind == "page" and fields.get("url") == MOOC_URL:
                page_fields.update(deepcopy(fields))
            return cache_key(kind, fields)

        monkeypatch.setattr(store, "cache_key", capture_key)
        cold = await run(jobs)
        original = library_row(store)
        course = course_resource(store, cold, MOOC_URL)
        current_key, _ = jobs._page_cache(course)
        bili_key, _ = jobs._page_cache(course_resource(store, cold, BILIBILI_URL))
        original_bili = cache_row(store, bili_key)
        original_fetches, original_searches = list(pages.calls), list(search.calls)
        if cache_case == "old_extractor":
            assert page_fields["extractor_version"] == 15
            legacy_key = cache_key("page", {**page_fields, "extractor_version": 14})
            assert legacy_key != current_key
            with store.connection:
                store.connection.execute("UPDATE cache SET key=? WHERE key=?", (legacy_key, current_key))
        else:
            with store.connection:
                store.connection.execute("UPDATE cache SET expires=? WHERE key=?", (time.time() - 1, current_key))

        monkeypatch.setattr(mooc_relevance, "MATCH_RULES_VERSION", mooc_relevance.MATCH_RULES_VERSION + 1)
        # No new page request may hide a legacy/stale-cache admission defect.
        warm_jobs = JobService(replace(config, max_detail_pages=0), store, provider=search, fetcher=pages)
        observations = watch_observe(warm_jobs, monkeypatch)
        assert warm_jobs._page_cache(course)[0] == current_key
        selected = warm_jobs._page_cache(course)[1]
        if cache_case == "expired_allow_stale":
            assert selected["cache"]["stale"] is True
        else:
            assert selected is None
        warm = await run(warm_jobs, expected_status="completed" if cache_case == "expired_allow_stale" else "partial")

        assert library_row(store) == original
        assert not warm_jobs.course_library.lookup({"text": POINT}, warm_jobs._course_library_profile())
        assert store.get_job(warm)["progress"].get("library_courses_saved", 0) == 0
        assert store.get_job(warm)["progress"]["details_attempted"] == 0
        assert warm_jobs.results(warm)["groups"][0]["mooc_relevance"]["recommended_count"] == 0
        if cache_case == "expired_allow_stale":
            assert len(observations) == 1
            assert observations[0]["resource"]["cache"]["stale"] is True
            assert not observations[0].get("current_page_cache", False)
        else:
            assert not observations
        assert pages.calls == original_fetches
        # An uncovered point may use its independent second search round; all
        # Bilibili queries remain cache hits and its page cache is untouched.
        assert [query for query in search.calls if "bilibili.com" in query] == [
            query for query in original_searches if "bilibili.com" in query]
        assert cache_row(store, bili_key) == original_bili
        assert_bilibili_visible(warm_jobs, warm)
