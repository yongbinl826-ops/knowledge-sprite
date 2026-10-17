"""Isolated service/cache/cancellation integration; never accesses the network."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import CloudflareDoHResolver, Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER
from backend.app.models import Candidate, Query, SearchRequest, now
from backend.app.official_sitemap import OfficialSitemapProvider, ORIGIN
from backend.app.providers import SearchError
from backend.app.service import BudgetReached, JobService

ROOT = ORIGIN + "/catalog-index.xml"
CHILD = ORIGIN + "/courses/1-probability-2020/sitemap.xml"
COURSE = ORIGIN + "/courses/1-probability-2020/"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def xml(kind, urls):
    tag = "sitemap" if kind == "sitemapindex" else "url"
    return (f"<{kind} {NS}>" + "".join(f"<{tag}><loc>{url}</loc></{tag}>" for url in urls) + f"</{kind}>").encode()


class Transport:
    def __init__(self, title="Probability", description="Probability course", blocked=None):
        self.calls = []
        self.blocked = blocked
        self.documents = {
            ORIGIN + "/robots.txt": b"User-agent: *\nAllow: /\nSitemap: " + ROOT.encode(),
            ROOT: xml("sitemapindex", [CHILD]), CHILD: xml("urlset", [COURSE]),
            COURSE: ("<html><head><title>" + title + "</title><script type='application/ld+json'>" + json.dumps({"@type": "Course", "name": title, "description": description}) + "</script></head><body><h1>" + title + "</h1></body></html>").encode(),
        }

    async def request(self, url, addresses, max_bytes):
        self.calls.append(url)
        await asyncio.sleep(0)
        if self.blocked == url:
            return HTTPResult(401, {"content-type": "text/html"}, b"", url)
        return HTTPResult(200, {"content-type": "text/html" if url == COURSE else "application/xml"}, self.documents[url], url)


async def resolver(url, timeout):
    return ["9.9.9.9"]


def make(tmp_path, transport=None, **kwargs):
    settings = Settings(database_path=str(tmp_path / "test.sqlite3"), search_provider="official_sitemap",
        global_concurrency=1, fetch_min_interval_seconds=0, **kwargs)
    transport = transport or Transport()
    fetcher = Fetcher(FetcherConfig(global_concurrency=1, min_interval_seconds=0, max_retries=1), resolver=resolver, http_client=transport)
    service = JobService(settings, Store(settings.database_path), fetcher=fetcher)
    return service, transport


@pytest.mark.asyncio
async def test_real_loc_page_validation_and_global_one_no_deadlock(tmp_path):
    service, transport = make(tmp_path)
    try:
        jid = service.create(SearchRequest(knowledge_points=["probability"], language="en", preferred_platforms=[]))["job_id"]
        await asyncio.wait_for(service.run(jid), 2)
        job = service.store.get_job(jid)
        result = service.results(jid)
        assert job["status"] == "completed"
        assert job["progress"]["search_requests"] == 3
        assert transport.calls == [ORIGIN + "/robots.txt", ROOT, CHILD, COURSE]
        resource = result["groups"][0]["items"][0]["resource"]
        assert resource["url"] == COURSE and resource["title"] == "Probability"
        assert resource["resource_type"] == "course" and resource["video_evidence_status"] == "none"
        assert result["identity_summary"]["identified_course_families"] == 1
        evidence = result["groups"][0]["items"][0]["evidence"]
        assert next(row for row in evidence if row["kind"] == "search")["discovery_evidence"]["source_url"] == CHILD
        assert NETWORK_OBSERVER.get() is None
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_expired_job_does_not_poison_next_job_source(tmp_path):
    from backend.app.fetcher import FETCH_DEADLINE_AT
    class SlowOnce(Transport):
        slow = True
        async def request(self, url, addresses, max_bytes):
            if self.slow:
                self.slow = False
                await asyncio.sleep(1)
            return await super().request(url, addresses, max_bytes)
    service, transport = make(tmp_path, SlowOnce(), deadline_seconds=0.08)
    req = SearchRequest(knowledge_points=["probability"], preferred_platforms=[])
    try:
        first = service.create(req)["job_id"]
        await service.run(first)
        assert service.store.get_job(first)["status"] == "failed"
        assert any("期限" in s for s in service.store.get_job(first)["warnings"])
        assert service.provider._stopped_code is None
        assert FETCH_DEADLINE_AT.get() is None
        second = service.create(req)["job_id"]
        await service.run(second)
        assert service.store.get_job(second)["status"] == "completed"
        assert service.results(second)["identity_summary"]["identified_course_families"] == 1
        assert FETCH_DEADLINE_AT.get() is None
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_official_slug_does_not_replace_page_topic_evidence(tmp_path):
    service, transport = make(tmp_path, Transport("General mathematics", "A general course"))
    try:
        jid = service.create(SearchRequest(knowledge_points=["probability"], preferred_platforms=[]))["job_id"]
        await service.run(jid)
        assert COURSE in transport.calls
        assert service.store.get_job(jid)["progress"]["resources_discovered"] == 1
        assert service.results(jid)["groups"][0]["items"] == []
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_cache_ttl_source_policy_and_current_trace_are_separate(tmp_path):
    service, transport = make(tmp_path, official_sitemap_cache_ttl=20, search_cache_ttl=500)
    try:
        req = SearchRequest(knowledge_points=["probability"], preferred_platforms=[])
        first = service.create(req)["job_id"]
        await service.run(first)
        rows = service.store.connection.execute("SELECT kind,expires-created AS ttl FROM cache WHERE kind IN ('search','official_sitemap')").fetchall()
        assert rows and all(row["ttl"] <= 20.01 for row in rows)
        before = len(transport.calls)
        second = service.create(req)["job_id"]
        await service.run(second)
        attempt = service.store.attempts(second)[0]
        assert len(transport.calls) == before and attempt["provider_requests"] == []
        assert attempt["discovery"]["index"]["cache_hit"] is True
        assert service.store.connection.execute("SELECT count(*) FROM cache WHERE kind='search'").fetchone()[0] == 0
        key = service.provider._key(ROOT)
        service.provider.settings = replace(service.provider.settings, official_sitemap_cache_ttl=5)
        assert service.provider._key(ROOT) != key
        service.provider.settings = replace(service.provider.settings, denied_fetch_hosts=("ocw.mit.edu",))
        assert service.provider._get(ROOT) is None
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_budget_reserves_each_robot_index_child_and_resets_context(tmp_path):
    service, transport = make(tmp_path, max_search_requests=2)
    try:
        jid = service.create(SearchRequest(knowledge_points=["probability"], preferred_platforms=[]))["job_id"]
        await service.run(jid)
        assert transport.calls == [ORIGIN + "/robots.txt", ROOT]
        assert service.store.get_job(jid)["progress"]["search_requests"] == 2
        assert service.store.attempts(jid)[0]["status"] == "budget_exhausted"
        assert NETWORK_OBSERVER.get() is None
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_cancel_clears_only_this_tasks_hook_and_stops_pending_child(tmp_path):
    entered = asyncio.Event()
    cleaned = asyncio.Event()
    class Pending(Transport):
        async def request(self, url, addresses, max_bytes):
            if url == CHILD:
                self.calls.append(url)
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            return await super().request(url, addresses, max_bytes)
    service, transport = make(tmp_path, Pending())
    try:
        jid = service.create(SearchRequest(knowledge_points=["probability"], preferred_platforms=[]))["job_id"]
        task = asyncio.create_task(service.run(jid))
        await asyncio.wait_for(entered.wait(), 1)
        assert NETWORK_OBSERVER.get() is None
        response = await service.cancel(jid)
        assert response["cancelled"] and cleaned.is_set()
        await asyncio.gather(task, return_exceptions=True)
        assert service.store.attempts(jid)[0]["provider_requests"][-1]["status"] == "cancelled"
        assert NETWORK_OBSERVER.get() is None
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_normal_empty_fallback_honors_domains_and_errors(tmp_path):
    class Primary:
        name = "searxng"
        last_requests = []
        last_warnings = []
        async def search(self, *args):
            return []
    service, transport = make(tmp_path)
    try:
        official = service.provider
        service.provider, service.official_fallback = Primary(), official
        request = SearchRequest(knowledge_points=["probability"], preferred_platforms=[])
        assert await service._discover(Query(knowledge_point_id="k", query="probability video", domain_filters=["bilibili.com"]), request, "probability") == []
        assert not transport.calls
        items = await service._discover(Query(knowledge_point_id="k", query="probability video", domain_filters=["ocw.mit.edu", "open.edu"]), request, "probability")
        assert items[0].url == COURSE
        assert items[0].query == "probability"
        before = len(transport.calls)
        async def denied(*args):
            raise SearchError("access_denied", "Synthetic denied")
        service.provider.search = denied
        with pytest.raises(SearchError):
            await service._discover(Query(knowledge_point_id="k", query="probability"), request, "probability")
        assert len(transport.calls) == before
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_official_failure_does_not_retry_shared_fetcher_or_next_query(tmp_path):
    class Broken(Transport):
        async def request(self, url, addresses, max_bytes):
            if url == ROOT:
                self.calls.append(url)
                raise httpx.ConnectError("synthetic transport failure")
            return await super().request(url, addresses, max_bytes)
    service, transport = make(tmp_path, Broken())
    try:
        for _ in range(2):
            with pytest.raises(SearchError):
                await service.provider.search("probability", "en", 5, [])
        assert transport.calls.count(ROOT) == 1
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_doh_hooks_are_optional_and_record_actual_http(monkeypatch):
    from backend.app import fetcher as module
    original = httpx.AsyncClient
    observed, reserved = [], []
    class Bytes(httpx.AsyncByteStream):
        def __init__(self, data):
            self.data = data
        async def __aiter__(self):
            yield self.data
    def response(request):
        record_type = request.url.params["type"]
        payload = {"Status": 0, "Question": [{"name": "ocw.mit.edu", "type": 1 if record_type == "A" else 28}],
            "Answer": [{"type": 1, "data": "9.9.9.9"}] if record_type == "A" else []}
        return httpx.Response(200, stream=Bytes(json.dumps(payload).encode()))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs))
    async def count():
        reserved.append(1)
    token = NETWORK_OBSERVER.set({"before_dns_http": count, "dns_trace": observed.append})
    try:
        assert await CloudflareDoHResolver()(COURSE) == ["9.9.9.9"]
        assert len(reserved) == len(observed) == 2
        assert all(row["status"] == "completed" and row["http_status"] == 200 and row["source_sha256"] for row in observed)
    finally:
        NETWORK_OBSERVER.reset(token)
    assert await CloudflareDoHResolver()(COURSE) == ["9.9.9.9"]
    assert len(observed) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["official_403", "official_config", "primary_denied"])
async def test_optional_source_failure_never_stops_successful_primary_for_next_point(tmp_path, failure):
    class Primary:
        name = "searxng"
        last_warnings = []
        request_hook = None
        def __init__(self):
            self.calls, self.last_requests = [], []
        async def search(self, query, language, limit, domains):
            self.calls.append(query)
            await self.request_hook()
            self.last_requests = [{"provider": "searxng", "http_status": 200}]
            self.last_warnings = []
            if failure == "primary_denied":
                raise SearchError("access_denied", "Primary denied")
            if "geology" in query:
                return [Candidate(id="geo", title="Geology course video", url="https://www.bilibili.com/video/BV1234567890/",
                    snippet="Geology video teaching", source="searxng", query=query, type_source="search_template", resource_type_hint="video")]
            return []
    class Denied(Transport):
        async def request(self, url, addresses, max_bytes):
            if url == ROOT:
                self.calls.append(url)
                return HTTPResult(403, {}, b"", url)
            return await super().request(url, addresses, max_bytes)
    service, transport = make(tmp_path, Denied(), max_detail_pages=0)
    primary = Primary()
    service.settings = replace(service.settings, search_provider="searxng", official_sitemap_fallback=True)
    service.official_fallback, service.provider = service.provider, primary
    if failure == "official_config":
        service.official_fallback.settings = replace(service.official_fallback.settings, fetch_enabled=False)
    try:
        jid = service.create(SearchRequest(knowledge_points=["probability", "geology"], language="en", preferred_platforms=[]))["job_id"]
        await service.run(jid)
        if failure == "primary_denied":
            assert len(primary.calls) == 1 and transport.calls == []
            assert service.store.get_job(jid)["errors"][0]["code"] == "access_denied"
        else:
            assert any("geology" in query for query in primary.calls)
            assert service.results(jid)["groups"][1]["items"]
            attempt = service.store.attempts(jid)[0]
            assert attempt["status"] == "completed" and attempt["error_code"] is None
            assert attempt["upstream_warnings"][-1]["code"] == "official_source_failed"
            assert attempt["discovery"]["failure"]["reason_code"] == ("access_denied" if failure == "official_403" else "configuration_error")
            assert transport.calls.count(ROOT) == (1 if failure == "official_403" else 0)
    finally:
        service.store.close()
