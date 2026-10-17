"""Offline lifecycle/cache regressions; no external requests or production SQLite."""
import asyncio
from collections import Counter, deque
from dataclasses import replace
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher
from backend.app.main import create_app
from backend.app.models import Candidate, SearchRequest, now
from backend.app.service import IdempotencyConflict, JobService


class Search:
    def __init__(self):
        self.calls = []

    async def search(self, query, language, limit, domain_filters):
        self.calls.append(query)
        await asyncio.sleep(0)
        return [Candidate(id=str(len(self.calls)), title=query, snippet=query,
            url="https://example.org/lesson", source="isolated-lifecycle-test", query=query,
            resource_type_hint="video", type_source="search_template")]


class QuickFetcher:
    async def enrich(self, candidate):
        return {"fetch_status": "policy_unreviewed", "evidence": []}


def make_service(tmp_path, provider=None, fetcher=None, llm=None, **settings):
    options = Settings(database_path=str(tmp_path / "lifecycle.sqlite3"), searxng_url="http://search.example", **settings)
    return JobService(options, Store(options.database_path), provider or Search(), fetcher or QuickFetcher(), llm)


def request(point="Python 列表", **kwargs):
    return SearchRequest(knowledge_points=[point], preferred_platforms=[], **kwargs)


async def join(service):
    await asyncio.wait_for(service.queue.join(), 3)


@pytest.mark.asyncio
async def test_queued_request_coalescing_normalization_and_cancel(tmp_path):
    svc = make_service(tmp_path)
    first = svc.create(request(" Python  列表 ", project_context="  同一  项目 ", technical_version=" Python  3 "))
    second = svc.create(request(project_context="同一 项目", technical_version="Python 3"))
    assert first["reused"] is False and second == {"job_id": first["job_id"], "status": "queued", "reused": True}
    assert svc.queue.qsize() == 1
    cancelled = await svc.cancel(first["job_id"])
    assert cancelled == {"job_id": first["job_id"], "status": "cancelled", "cancelled": True}
    assert await svc.cancel(first["job_id"]) == cancelled
    assert await svc.cancel("missing-job") is None
    await svc.run(first["job_id"])
    assert not svc.provider.calls
    assert svc.create(request(project_context="同一 项目", technical_version="Python 3"))["job_id"] != first["job_id"]
    assert svc.results(first["job_id"])["status"] == "cancelled"
    svc.store.close()


@pytest.mark.asyncio
async def test_running_cancel_cleans_http_and_all_details_but_worker_continues(tmp_path):
    network_started, network_cancelled, details_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def pending_http(_):
        network_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            network_cancelled.set()
            raise

    class ConcurrentSearch(Search):
        async def search(self, query, *args):
            if "Python" in query and self.calls:
                async with httpx.AsyncClient(transport=httpx.MockTransport(pending_http)) as client:
                    await client.get("https://search.example/isolated")
            results = await super().search(query, *args)
            return [results[0].model_copy(update={"id": str(i), "url": f"https://host{i}.example.org/lesson"}) for i in range(2)]

    class BlockingDetails:
        active = 0
        cancelled = 0

        async def enrich(self, candidate):
            if "Python" not in candidate["title"]:
                return {"fetch_status": "policy_unreviewed"}
            self.active += 1
            if self.active == 2:
                details_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            finally:
                self.active -= 1

    fetcher = BlockingDetails()
    svc = make_service(tmp_path, ConcurrentSearch(), fetcher, global_concurrency=3)
    svc.start()
    try:
        first = svc.create(request())
        await asyncio.wait_for(network_started.wait(), 3)
        await asyncio.wait_for(details_started.wait(), 3)
        assert svc.create(request()) == {"job_id": first["job_id"], "status": "running", "reused": True}
        responses = await asyncio.gather(svc.cancel(first["job_id"]), svc.cancel(first["job_id"]))
        assert all(response["status"] == "cancelled" for response in responses)
        assert network_cancelled.is_set() and fetcher.cancelled == 2 and fetcher.active == 0
        assert svc.store.attempts(first["job_id"])[-1]["status"] == "cancelled"
        assert svc.store.attempts(first["job_id"])[-1]["network_attempted"] is True
        snapshot = svc.store.get_job(first["job_id"])
        assert snapshot["progress"]["details_attempted"] == 2 and snapshot["progress"]["details_completed"] == 0
        assert len(svc.results(first["job_id"])["groups"][0]["items"]) == 2
        assert all(svc.store.evidence(first["job_id"], rid) for rid in svc.store.resources(first["job_id"]))
        second = svc.create(request("SQL 连接"))
        await join(svc)
        assert svc.store.get_job(second["job_id"])["status"] == "completed"
        assert svc.store.get_job(first["job_id"]) == snapshot
        assert not svc.worker.done() and not svc.active_tasks and not svc.cancel_requested
        terminal = await svc.cancel(second["job_id"])
        assert terminal["status"] == "completed" and terminal["cancelled"] is False
    finally:
        await svc.stop()
        svc.store.close()


@pytest.mark.asyncio
async def test_worker_contains_failure_before_execution_and_redacts_error(tmp_path):
    svc = make_service(tmp_path)
    original = svc._run_job

    async def fail_one(job):
        if job["request"]["knowledge_points"] == ["broken"]:
            raise RuntimeError("SECRET http://internal.example/private")
        await original(job)

    svc._run_job = fail_one
    svc.start()
    try:
        failed = svc.create(request("broken"))["job_id"]
        next_job = svc.create(request())["job_id"]
        await join(svc)
        assert svc.store.get_job(failed)["status"] == "failed"
        assert "SECRET" not in json.dumps(svc.store.get_job(failed))
        assert "internal.example" not in json.dumps(svc.store.get_job(failed))
        assert svc.store.get_job(next_job)["status"] == "completed" and not svc.worker.done()
    finally:
        await svc.stop()
        svc.store.close()


@pytest.mark.asyncio
async def test_single_network_slot_and_repeated_start_do_not_deadlock(tmp_path):
    svc = make_service(tmp_path, global_concurrency=1)
    svc.start()
    worker = svc.worker
    svc.start()
    assert svc.worker is worker
    try:
        job_id = svc.create(request())["job_id"]
        await join(svc)
        job = svc.store.get_job(job_id)
        assert job["status"] == "completed"
        assert job["progress"]["details_attempted"] == job["progress"]["details_completed"] == 1
        assert svc.results(job_id)["groups"][0]["items"]
    finally:
        await svc.stop()
        svc.store.close()


@pytest.mark.asyncio
async def test_deadline_during_llm_ranking_retains_rule_results_without_late_writes(tmp_path):
    class SlowRanking:
        entered = False
        cancelled = False

        async def expand(self, *args):
            return []

        async def rerank(self, *args):
            self.entered = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    llm = SlowRanking()
    svc = make_service(tmp_path, llm=llm, deadline_seconds=.05)
    try:
        job_id = svc.create(request())["job_id"]
        await svc.run(job_id)
        assert llm.entered and llm.cancelled
        job = svc.store.get_job(job_id)
        assert job["status"] == "partial" and job["phase"] == "done"
        result = svc.results(job_id)
        assert result["groups"][0]["items"] and svc.store.matches(job_id)
        await asyncio.sleep(0)
        assert svc.store.get_job(job_id) == job and svc.results(job_id) == result
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_shutdown_distinguishes_interrupted_and_recovers_queued_tasks(tmp_path):
    started = asyncio.Event()

    class PendingSearch(Search):
        async def search(self, *args):
            started.set()
            await asyncio.Event().wait()

    svc = make_service(tmp_path, PendingSearch())
    svc.start()
    first = svc.create(request())["job_id"]
    second = svc.create(request("SQL"))["job_id"]
    await asyncio.wait_for(started.wait(), 3)
    await svc.stop()
    assert {svc.store.get_job(job_id)["status"] for job_id in (first, second)} == {"interrupted"}
    assert not svc.active_tasks and svc.worker is None
    svc.store.close()


@pytest.mark.asyncio
async def test_idempotency_survives_terminal_status_and_reopen(tmp_path):
    svc = make_service(tmp_path)
    first = svc.create(request(), "fixed-key")
    await svc.run(first["job_id"])
    assert svc.create(request(), "fixed-key") == {"job_id": first["job_id"], "status": "completed", "reused": True}
    with pytest.raises(IdempotencyConflict):
        svc.create(request("SQL"), "fixed-key")
    svc.store.close()
    reopened = make_service(tmp_path)
    try:
        reopened.store.recover()
        assert reopened.create(request(), "fixed-key")["job_id"] == first["job_id"]
        assert reopened.queue.qsize() == 0
        assert reopened.create(request(), "new-key")["job_id"] != first["job_id"]
    finally:
        reopened.store.close()


@pytest.mark.asyncio
async def test_api_cancel_idempotency_conflict_and_missing_job(tmp_path):
    started = asyncio.Event()

    class PendingSearch(Search):
        async def search(self, *args):
            started.set()
            await asyncio.Event().wait()

    app = create_app(Settings(database_path=str(tmp_path / "api.sqlite3")), PendingSearch(), QuickFetcher())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/search-jobs", json=request().model_dump(), headers={"Idempotency-Key": "api-key"})
            assert response.status_code == 202 and not response.json()["reused"]
            job_id = response.json()["job_id"]
            await asyncio.wait_for(started.wait(), 3)
            response = await client.post(f"/api/search-jobs/{job_id}/cancel")
            assert response.json() == {"job_id": job_id, "status": "cancelled", "cancelled": True}
            assert (await client.get(f"/api/search-jobs/{job_id}/results")).json()["status"] == "cancelled"
            retry = await client.post("/api/search-jobs", json=request().model_dump(), headers={"Idempotency-Key": "api-key"})
            assert retry.status_code == 202 and retry.json() == {"job_id": job_id, "status": "cancelled", "reused": True}
            conflict = await client.post("/api/search-jobs", json=request("SQL").model_dump(), headers={"Idempotency-Key": "api-key"})
            assert conflict.status_code == 409
            invalid = await client.post("/api/search-jobs", json=request().model_dump(), headers={"Idempotency-Key": "invalid key"})
            assert invalid.status_code == 422
            assert (await client.post("/api/search-jobs/missing/cancel")).status_code == 404
            preflight = await client.options("/api/search-jobs", headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Idempotency-Key"})
            assert preflight.status_code == 200


class CatalogFetcher(Fetcher):
    def __init__(self, status="fetched"):
        self.status, self.calls = status, 0

    async def enrich(self, candidate, *, catalog_budget_hook=None):
        self.calls += 1
        allowed = await catalog_budget_hook()
        return {"fetch_status": "fetched", "metadata_evidence_level": "page", "author": "Recorded teacher",
            "catalog_fetch_status": self.status if allowed else "budget_limited", "catalog_pages_completed": int(allowed),
            "field_provenance": {"author": {"evidence_id": "author-page", "source": "meta.author"}},
            "evidence": [{"evidence_id": "author-page", "kind": "page", "field": "author", "source": "meta.author", "url": candidate["url"], "text": "Recorded teacher"}]}


@pytest.mark.asyncio
async def test_budget_limited_catalog_does_not_freeze_in_page_cache(tmp_path):
    fetcher = CatalogFetcher()
    svc = make_service(tmp_path, fetcher=fetcher, max_detail_pages=1)
    try:
        first = svc.create(request())["job_id"]
        await svc.run(first)
        resource = next(iter(svc.store.resources(first).values()))
        assert resource["author"] == "Recorded teacher" and resource["catalog_fetch_status"] == "budget_limited"
        assert svc.store.connection.execute("SELECT count(*) FROM cache WHERE kind='page'").fetchone()[0] == 0
        svc.settings = replace(svc.settings, max_detail_pages=2)
        second = svc.create(request())["job_id"]
        await svc.run(second)
        assert fetcher.calls == 2
        assert next(iter(svc.store.resources(second).values()))["catalog_fetch_status"] == "fetched"
        assert svc.store.get_job(second)["progress"]["catalog_pages_completed"] == 1
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_failed_catalog_has_short_ttl_and_retries_after_expiry_even_with_stale_enabled(tmp_path):
    fetcher = CatalogFetcher("timeout")
    svc = make_service(tmp_path, fetcher=fetcher, allow_stale_cache=True)
    try:
        first = svc.create(request())["job_id"]
        await svc.run(first)
        row = svc.store.connection.execute("SELECT expires-created ttl FROM cache WHERE kind='page'").fetchone()
        assert row["ttl"] == 300 and svc.store.get_job(first)["status"] == "partial"
        svc.store.connection.execute("UPDATE cache SET expires=0 WHERE kind='page'")
        svc.store.connection.commit()
        fetcher.status = "fetched"
        second = svc.create(request())["job_id"]
        await svc.run(second)
        assert fetcher.calls == 2 and svc.store.get_job(second)["status"] == "completed"
        assert next(iter(svc.store.resources(second).values()))["author"] == "Recorded teacher"
    finally:
        svc.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page_text", [False, True])
async def test_page_cache_never_replays_another_queries_search_fallback(tmp_path, page_text):
    class SearchFallbackFetcher:
        calls = 0

        async def enrich(self, candidate):
            self.calls += 1
            origin = "page" if page_text else "search"
            values = {"title": "Python 列表 SQL 连接 video course" if page_text else candidate["title"],
                      "description": "Recorded Python 列表 SQL 连接 lessons" if page_text else candidate["snippet"]}
            return {"fetch_status": "fetched", "metadata_evidence_level": "page", **values,
                "field_provenance": {field: {"evidence_id": field, "source": origin} for field in values},
                "evidence": [{"evidence_id": field, "kind": origin, "field": field, "source": origin,
                              "url": candidate["url"], "text": value, "query": candidate["query"] if origin == "search" else None} for field, value in values.items()]}

    fetcher = SearchFallbackFetcher()
    svc = make_service(tmp_path, fetcher=fetcher)
    try:
        first = svc.create(request())["job_id"]
        await svc.run(first)
        second = svc.create(request("SQL 连接"))["job_id"]
        await svc.run(second)
        assert fetcher.calls == 1 and svc.store.get_job(second)["progress"]["details_cached"] == 1
        resource = next(iter(svc.store.resources(second).values()))
        evidence = svc.store.evidence(second, resource["resource_id"])
        assert resource["title"].startswith("Python" if page_text else "SQL")
        assert resource["description"].startswith("Recorded" if page_text else "SQL")
        assert all("SQL" in record["query"] for record in evidence if record["kind"] == "search")
        record = next(record for record in evidence if record["evidence_id"] == resource["field_provenance"]["title"]["evidence_id"])
        assert record["kind"] == ("page" if page_text else "search")
        cache = json.loads(svc.store.connection.execute("SELECT data FROM cache WHERE kind='page'").fetchone()[0])
        assert not any(record["kind"] == "search" for record in cache["evidence"])
        assert ("title" in cache) is page_text
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_cache_source_identity_and_page_policy_settings_are_isolated(tmp_path):
    svc = make_service(tmp_path)
    try:
        first = svc.create(request())["job_id"]
        await svc.run(first)
        calls = len(svc.provider.calls)
        resource = next(iter(svc.store.resources(first).values()))
        original_page_key, cached = svc._page_cache(resource)
        assert cached
        svc.settings = replace(svc.settings, denied_fetch_hosts=("open.edu",))
        assert svc._page_cache(resource)[0] != original_page_key
        assert svc.capabilities()["fetch"]["stopped_hosts"] == ["open.edu"]
        svc.settings = replace(svc.settings, searxng_url="http://different-search.example", dns_resolver="cloudflare_doh")
        assert svc._page_cache(resource)[0] != original_page_key
        second = svc.create(request())["job_id"]
        await svc.run(second)
        assert len(svc.provider.calls) > calls and svc.store.get_job(second)["progress"]["cache_hits"] == 0
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_source_identities_are_remapped_persisted_and_summary_covers_only_displayed_rows(tmp_path):
    class CourseSearch(Search):
        async def search(self, query, *args):
            base = (await super().search(query, *args))[0]
            return [base.model_copy(update={"id": str(index), "url": url}) for index, url in enumerate([
                "https://ocw.mit.edu/courses/1-first-course-fall-2020/",
                "https://ocw.mit.edu/courses/1-first-course-fall-2020/video_galleries/lectures/",
                "https://ocw.mit.edu/courses/2-second-course-spring-2021/",
            ])]

    svc = make_service(tmp_path, CourseSearch(), max_results_per_point=2, max_detail_pages=0)
    try:
        job_id = svc.create(request())["job_id"]
        await svc.run(job_id)
        resources = svc.store.resources(job_id)
        assert len(resources) == 3
        for rid, resource in resources.items():
            assert resource["course_identity"]["status"] == "identified"
            assert set(resource["course_identity"]["evidence_ids"]) <= {r["evidence_id"] for r in svc.store.evidence(job_id, rid)}
        result = svc.results(job_id)
        families = {item["resource"]["course_identity"]["family_id"] for item in result["groups"][0]["items"]}
        assert len(families) == 2
        assert result["identity_summary"]["resource_records"] == 2
        assert result["identity_summary"]["identified_course_families"] == 2
        assert len(svc.store.resources(job_id)) == 3  # Selection does not delete related entries.
        legacy = next(iter(resources.values()))
        legacy.pop("course_identity")
        svc.store.save_resource(job_id, legacy)
        assert svc.results(job_id)["identity_summary"] == result["identity_summary"]
        assert "course_identity" not in svc.store.resources(job_id)[legacy["resource_id"]]
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_configured_open_course_domains_reach_fair_search_plan(tmp_path):
    provider = Search()
    svc = make_service(tmp_path, provider, open_course_domains=("ocw.mit.edu", "open.edu"), max_detail_pages=0)
    try:
        job_id = svc.create(request())["job_id"]
        await svc.run(job_id)
        assert len(provider.calls) == 3
        assert any("site:ocw.mit.edu" in query and "site:open.edu" in query for query in provider.calls)
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_fetch_diagnostics_are_bounded_and_do_not_mix_jobs(tmp_path):
    class TracedFetcher:
        def __init__(self):
            self.request_trace = deque(maxlen=512)
            self.trace_counts = Counter()

        async def enrich(self, candidate):
            for _ in range(515):
                self.trace_counts["http_started"] += 1
                self.request_trace.append({"event": "http_started", "at": now(), "url": candidate["url"]})
            return {"fetch_status": "fetched", "evidence": []}

    class DifferentURLSearch(Search):
        async def search(self, query, *args):
            base = (await super().search(query, *args))[0]
            return [base.model_copy(update={"url": "https://example.org/python" if "Python" in query else "https://example.org/sql"})]

    svc = make_service(tmp_path, DifferentURLSearch(), TracedFetcher())
    try:
        for point, path in [("Python", "/python"), ("SQL", "/sql")]:
            job_id = svc.create(request(point))["job_id"]
            await svc.run(job_id)
            diagnostic = svc.store.get_job(job_id)["fetch_diagnostics"]
            assert diagnostic["available"] and diagnostic["counts_delta"] == {"http_started": 515}
            assert len(diagnostic["events"]) == 512 and diagnostic["truncated"]
            assert all(event["url"].endswith(path) for event in diagnostic["events"])
            assert "DoH HTTP uncounted" in diagnostic["scope"]
        cached = svc.create(request("SQL"))["job_id"]
        await svc.run(cached)
        assert svc.store.get_job(cached)["fetch_diagnostics"]["counts_delta"] == {}
        assert svc.store.get_job(cached)["fetch_diagnostics"]["events"] == []
    finally:
        svc.store.close()


@pytest.mark.asyncio
async def test_shared_resource_order_does_not_cross_point_rule_or_llm_text(tmp_path):
    class PointSearch(Search):
        async def search(self, query, *args):
            base = (await super().search(query, *args))[0]
            title = "Python lists course" if "Python" in query else "SQL joins course"
            return [base.model_copy(update={"title": title, "snippet": ""})]

    class RecordingLLM:
        def __init__(self):
            self.inputs = []

        async def expand(self, *args):
            return []

        async def rerank(self, point, candidates):
            self.inputs.append((point, candidates))
            return []

    llm = RecordingLLM()
    svc = make_service(tmp_path, PointSearch(), llm=llm)
    scores = []
    try:
        for points in [["Python lists", "SQL joins"], ["SQL joins", "Python lists"]]:
            job_id = svc.create(SearchRequest(knowledge_points=points, preferred_platforms=[], language="en"))["job_id"]
            await svc.run(job_id)
            result = svc.results(job_id)
            assert len(svc.store.resources(job_id)) == 1
            assert all(len(group["items"]) == 1 for group in result["groups"])
            scores.append({group["text"]: group["items"][0]["match"]["ranking_score"] for group in result["groups"]})
            for group in result["groups"]:
                item = group["items"][0]
                ids = {entry["evidence_id"] for entry in svc.store.evidence(job_id, item["resource"]["resource_id"], group["knowledge_point_id"])}
                assert set(item["match"]["matched_evidence_ids"]) <= ids
        assert scores[0] == scores[1]
        assert len(llm.inputs) == 4
        for point, candidates in llm.inputs:
            assert candidates[0]["title"] == point + " course"
            assert candidates[0]["description"] == ""
    finally:
        svc.store.close()
