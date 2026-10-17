"""Dynamic catalog retry/cache regressions; injected sources, no external traffic."""
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult
from backend.app.models import Candidate, SearchRequest
from backend.app.service import JobService, PLATFORM_POLICY_REVIEWS


URL = "https://courses.example.org/public-course"
TRANSIENT = ("render_timeout", "render_incomplete", "render_dependency_blocked", "render_failed")


class SearchFixture:
    async def search(self, query, language, limit, domains):
        return [Candidate(id="one", title="Python 列表 video course", url=URL,
            snippet="Python 列表 teaching", query=query, source="isolated-cache-test",
            type_source="search_template", resource_type_hint="video")]


class RenderFixture:
    def __init__(self, status):
        self.status, self.calls = status, 0

    async def enrich(self, candidate):
        self.calls += 1
        evidence = [{"evidence_id": "author", "kind": "page", "field": "author",
            "source": "meta.author", "url": URL, "text": "Recorded teacher"}]
        chapters = []
        if self.status == "rendered":
            evidence.append({"evidence_id": "chapter", "kind": "catalog", "field": "chapters.0",
                "source": "rendered_dom", "url": URL, "text": "Python 列表基础"})
            chapters = [{"title": "Python 列表基础", "url": None, "evidence_id": "chapter"}]
        return {"fetch_status": "fetched", "metadata_evidence_level": "page", "author": "Recorded teacher",
            "render_diagnostics": {"status": self.status}, "chapters": chapters, "evidence": evidence,
            "field_provenance": {"author": {"evidence_id": "author", "source": "meta.author"}}}


def make_service(fetcher, **settings):
    store = Store(":memory:")
    service = JobService(Settings(allow_stale_cache=True, max_search_requests=1, max_detail_pages=1,
        **settings), store, provider=SearchFixture(), fetcher=fetcher)
    return service


async def run_job(service):
    job = service.create(SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=[]))["job_id"]
    await service.run(job)
    return job, next(iter(service.store.resources(job).values()))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", TRANSIENT)
async def test_empty_dynamic_catalog_retries_after_short_cache_and_preserves_page_evidence(status):
    fetcher = RenderFixture(status)
    service = make_service(fetcher)
    try:
        first, original = await run_job(service)
        assert original["chapters"] == [] and original["author"] == "Recorded teacher"
        assert original["render_diagnostics"]["status"] == status
        row = service.store.connection.execute("SELECT expires-created ttl FROM cache WHERE kind='page'").fetchone()
        assert row["ttl"] == 300
        second, cached = await run_job(service)
        assert fetcher.calls == 1 and service.store.get_job(second)["progress"]["details_cached"] == 1
        assert cached["author"] == original["author"] and cached["render_diagnostics"] == original["render_diagnostics"]
        service.store.connection.execute("UPDATE cache SET expires=0 WHERE kind='page'")
        service.store.connection.commit()
        fetcher.status = "rendered"
        third, recovered = await run_job(service)
        assert fetcher.calls == 2 and service.store.get_job(third)["progress"]["details_cached"] == 0
        assert recovered["chapters"][0]["title"] == "Python 列表基础"
        records = service.store.evidence(third, recovered["resource_id"])
        chapter_record = next(row for row in records if row["evidence_id"] == recovered["chapters"][0]["evidence_id"])
        assert chapter_record["kind"] == "catalog" and chapter_record["text"] == "Python 列表基础"
        assert service.store.resources(first)[original["resource_id"]] == original
        row = service.store.connection.execute("SELECT expires-created ttl FROM cache WHERE kind='page'").fetchone()
        assert row["ttl"] == service.settings.page_cache_ttl
    finally:
        service.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["render_resource_budget", "render_request_budget", "render_dns_budget",
    "render_byte_budget", "render_input_budget", "render_output_budget"])
async def test_render_budget_failure_is_not_cached_but_page_evidence_survives(status):
    fetcher = RenderFixture(status)
    service = make_service(fetcher)
    try:
        first, original = await run_job(service)
        assert original["author"] == "Recorded teacher" and original["render_diagnostics"]["status"] == status
        assert service.store.connection.execute("SELECT count(*) FROM cache WHERE kind='page'").fetchone()[0] == 0
        await run_job(service)
        assert fetcher.calls == 2 and service.store.resources(first)[original["resource_id"]] == original
    finally:
        service.store.close()


@pytest.mark.parametrize("status", [None, "disabled", "render_host_not_enabled", "rendered"])
def test_non_attempt_or_success_is_not_misclassified_as_transient(status):
    service = make_service(RenderFixture(status))
    try:
        data = {"fetch_status": "fetched", "chapters": [], "render_diagnostics": {"status": status}}
        key, _ = service._page_cache({"canonical_url": URL})
        assert service._page_cache_ttl(data) == service.settings.page_cache_ttl
        service.store.cache_set(key, "page", data, -1)
        assert service._page_cache({"canonical_url": URL})[1]["data"] == data
    finally:
        service.store.close()


def test_recorded_catalog_is_not_discarded_and_shorter_configured_ttl_is_respected():
    service = make_service(RenderFixture("render_timeout"), page_cache_ttl=60)
    try:
        data = {"fetch_status": "fetched", "chapters": [{"title": "Observed chapter", "evidence_id": "c1"}],
            "render_diagnostics": {"status": "render_timeout"},
            "evidence": [{"evidence_id": "c1", "kind": "catalog", "field": "chapters.0", "text": "Observed chapter"}]}
        before = deepcopy(data)
        assert service._page_cache_complete(data) and service._page_cache_ttl(data) == 60
        assert data == before
        data["chapters"] = []
        assert not service._page_cache_complete(data) and service._page_cache_ttl(data) == 60
    finally:
        service.store.close()


def test_old_long_lived_render_failure_profile_is_preserved_but_not_replayed(monkeypatch):
    service = make_service(RenderFixture("render_timeout"))
    try:
        profile = service._renderer_profile()
        assert profile["version"] == 6
        data = {"fetch_status": "fetched", "chapters": [], "render_diagnostics": {"status": "render_timeout"}}
        with monkeypatch.context() as patch:
            patch.setattr(service, "_renderer_profile", lambda: {**profile, "version": 5})
            old_key, _ = service._page_cache({"canonical_url": URL})
            service.store.cache_set(old_key, "page", data, 86400)
        key, cached = service._page_cache({"canonical_url": URL})
        assert key != old_key and cached is None
        assert service.store.cache_get(old_key)["data"] == data
    finally:
        service.store.close()


@pytest.mark.parametrize("platform,url", [
    ("bilibili", "https://www.bilibili.com/video/BV1234567890/"),
    ("icourse163", "https://www.icourse163.org/course/PKU-1003479006"),
])
@pytest.mark.parametrize("field", ["status", "reviewed_at", "source_url", "terms_date", "section", "review_method", "basis"])
def test_changed_platform_review_invalidates_old_policy_cache_without_deleting_evidence(monkeypatch, platform, url, field):
    service = make_service(RenderFixture("disabled"))
    try:
        original = deepcopy(PLATFORM_POLICY_REVIEWS[platform])
        resource = {"canonical_url": url}
        old_key, _ = service._page_cache(resource)
        data = {"fetch_status": "site_policy_blocked", "policy_review": original}
        service.store.cache_set(old_key, "page", data, 86400)
        monkeypatch.setitem(PLATFORM_POLICY_REVIEWS, platform, {**original, field: "updated-review-value"})
        key, cached = service._page_cache(resource)
        assert key != old_key and cached is None
        assert service.store.cache_get(old_key)["data"] == data
    finally:
        service.store.close()


def test_policy_cache_is_stable_for_dict_order_and_unrelated_platform_updates(monkeypatch):
    service = make_service(RenderFixture("disabled"))
    try:
        resource = {"canonical_url": "https://www.bilibili.com/video/BV1234567890/"}
        key, _ = service._page_cache(resource)
        original = deepcopy(PLATFORM_POLICY_REVIEWS["bilibili"])
        monkeypatch.setitem(PLATFORM_POLICY_REVIEWS, "bilibili", dict(reversed(list(original.items()))))
        assert service._page_cache(resource)[0] == key
        unrelated = {**PLATFORM_POLICY_REVIEWS["icourse163"], "reviewed_at": "different-date"}
        monkeypatch.setitem(PLATFORM_POLICY_REVIEWS, "icourse163", unrelated)
        assert service._page_cache(resource)[0] == key
    finally:
        service.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,target", [
    ("bilibili", "https://www.bilibili.com/video/BV1234567890/"),
    ("icourse163", "https://www.icourse163.org/learn/PKU-1003479006"),
])
@pytest.mark.parametrize("via_catalog", [False, True])
async def test_unclassified_entry_cache_tracks_policy_reached_by_redirect_or_catalog(monkeypatch, platform, target, via_catalog):
    # Exercise the real redirect and same-course catalog-followup code with an
    # in-memory transport. No platform response or external DNS is permitted.
    origin = "https://ocw.mit.edu" if via_catalog else "https://courses.example.org"
    entry = origin + "/courses/example/"
    gallery = entry + "video_galleries/lectures/"
    home = b'<html><title>Example Course</title><div id="course-banner"><h1>Example Course</h1></div><a href="video_galleries/lectures/">Video Lectures</a><p>Official university course overview with material links.</p></html>'
    redirect = HTTPResult(302, {"location": target}, b"", gallery if via_catalog else entry)
    responses = {
        origin + "/robots.txt": HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", origin + "/robots.txt"),
        entry: HTTPResult(200, {"content-type": "text/html"}, home, entry) if via_catalog else redirect,
    }
    if via_catalog:
        responses[gallery] = redirect
    requests, dns_requests = [], []

    class MemoryHTTP:
        async def request(self, url, addresses, max_bytes):
            requests.append(url)
            assert url in responses, "No real network fallback is allowed"
            return responses[url]

    async def memory_dns(url, timeout):
        dns_requests.append(url)
        assert url in responses, "Restricted platform must stop before DNS"
        return ["93.184.216.34"]

    async def allow_catalog():
        return True

    fetcher = Fetcher(FetcherConfig(min_interval_seconds=0, max_retries=0), resolver=memory_dns, http_client=MemoryHTTP())
    service = make_service(fetcher)
    try:
        original = deepcopy(PLATFORM_POLICY_REVIEWS[platform])
        enriched = await fetcher.enrich({"url": entry, "title": "Example course", "source": "isolated-cache-test"},
            catalog_budget_hook=allow_catalog)
        assert enriched["canonical_url"] == entry and enriched["platform"] == "other"
        expected_status = "site_policy_blocked" if original["status"] in {"explicit_permission_required", "explicit_scraping_prohibition"} else "policy_unreviewed"
        assert enriched["catalog_fetch_status" if via_catalog else "fetch_status"] == expected_status
        policies = [row for row in enriched["evidence"] if row["kind"] == "site_policy"]
        assert len(policies) == 1 and policies[0]["text"] == original["basis"]
        assert policies[0]["restricted_target_request_sent"] is False
        assert policies[0]["blocked_target_url"] == target
        assert policies[0]["restricted_target_http_status"] is None
        assert "request_sent" not in policies[0] and entry in requests and target not in requests + dns_requests
        assert requests == [origin + "/robots.txt", entry, *([gallery] if via_catalog else [])]
        data = service._page_metadata(enriched)
        key, _ = service._page_cache(enriched)
        service.store.cache_set(key, "page", data, service._page_cache_ttl(data))
        assert service._page_cache(enriched)[1]["data"] == data
        monkeypatch.setitem(PLATFORM_POLICY_REVIEWS, platform, {**original, "basis": "Updated official policy review basis"})
        new_key, cached = service._page_cache(enriched)
        assert new_key != key and cached is None
        assert service.store.cache_get(key)["data"] == data
        fresh = await fetcher.enrich({"url": entry, "title": "Example course", "source": "isolated-cache-test"},
            catalog_budget_hook=allow_catalog)
        fresh_policy = next(row for row in fresh["evidence"] if row["kind"] == "site_policy")
        assert fresh_policy["text"] == "Updated official policy review basis"
        assert fresh_policy["blocked_target_url"] == target and fresh_policy["restricted_target_request_sent"] is False
        assert target not in requests + dns_requests
    finally:
        service.store.close()
