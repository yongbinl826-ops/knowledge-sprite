"""Job copies respect live library validity without rewriting job history."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app import course_library as library_module
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest, now
from backend.app.service import JobService
from test_gap_library_search import Outline, POINT, Search, URL, settings
from test_mooc_relevance_service import synthetic_outline


async def _warm(jobs):
    first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
    await jobs.run(first)
    second = jobs.create(SearchRequest(knowledge_points=[POINT, "Python 列表"],
                                      preferred_platforms=["icourse163"]))["job_id"]
    await jobs.run(second)
    assert jobs.store.get_job(second)["progress"]["library_hit_pairs"] == 2
    assert jobs.store.get_job(second)["progress"]["search_requests"] == 0
    assert all(group["mooc_relevance"]["recommended_count"] == 1 for group in jobs.results(second)["groups"])
    return first, second


def _state(jobs, jid):
    job = jobs.store.get_job(jid)
    resources = jobs.store.resources(jid)
    groups = {point["knowledge_point_id"]: [] for point in job["knowledge_points"]}
    for rid in resources:
        for row in jobs.store.evidence(jid, rid):
            pid = row.get("knowledge_point_id")
            if row.get("kind") in {"search", "course_library"} and pid in groups and rid not in groups[pid]:
                groups[pid].append(rid)
    return job, {"resources": resources, "candidate_groups": groups}


def _new_outline(jobs, chapters):
    resource = MetadataExtractor().extract(synthetic_outline(chapters=chapters), URL, now())
    evidence = resource.pop("evidence")
    resource.update(url=URL, canonical_url=URL, resource_id="new_observation", platform="icourse163")
    assert jobs.course_library.observe(resource, evidence, jobs._course_library_profile())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "new_content", "new_observation", "profile", "disabled", "library_unavailable", "expired", "shorter_ttl"])
async def test_warm_job_cards_and_gap_counts_follow_current_library_without_erasing_history(tmp_path, monkeypatch, change):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first, warm = await _warm(jobs)
        warm_job, warm_state = _state(jobs, warm)
        cold_job, cold_state = _state(jobs, first)
        assert all(jobs._mooc_coverage_count(warm_job, point, warm_state) == 1 for point in warm_job["knowledge_points"])
        retained_resources = deepcopy(store.resources(warm))
        retained_evidence = {rid: store.evidence(warm, rid) for rid in retained_resources}
        source_calls = list(search.calls), list(outline.calls)
        resource = next(iter(retained_resources.values()))

        if change == "revoked":
            assert not jobs.course_library.observe({"url": URL, "fetch_status": "not_found", "fetched_at": now()},
                                                   [], jobs._course_library_profile())
        elif change == "new_content": _new_outline(jobs, ("异常处理",))
        elif change == "new_observation": _new_outline(jobs, ("列表", "字典"))
        elif change == "profile": jobs.settings = replace(config, fetch_enabled=False)
        elif change == "disabled": jobs.settings = replace(config, shared_course_library_enabled=False)
        elif change == "library_unavailable": jobs.course_library = None
        elif change == "expired":
            monkeypatch.setattr(library_module, "time", SimpleNamespace(time=lambda: resource["course_library"]["expires_at"]))
        elif change == "shorter_ttl":
            jobs.course_library.ttl_seconds = 60
            monkeypatch.setattr(library_module, "time", SimpleNamespace(time=lambda: resource["course_library"]["observed_at"] + 61))

        groups = jobs.results(warm)["groups"]
        assert all(group["mooc_relevance"]["recommended_count"] == 0 and not group["discovery_items"] for group in groups)
        assert all(group["mooc_relevance"]["candidates"][0]["assessment"]["status"] == "outline_unavailable" for group in groups)
        assert all(jobs._mooc_coverage_count(warm_job, point, warm_state) == 0 for point in warm_job["knowledge_points"])

        # The original real-job page/outline is an immutable historical record;
        # only shared-library copies consult the current library on reads.
        assert all(not item.get("course_library") for item in cold_state["resources"].values())
        assert jobs.results(first)["groups"][0]["mooc_relevance"]["recommended_count"] == 1
        assert jobs._mooc_coverage_count(cold_job, cold_job["knowledge_points"][0], cold_state) == 1
        assert store.resources(warm) == retained_resources
        assert {rid: store.evidence(warm, rid) for rid in retained_resources} == retained_evidence
        assert (search.calls, outline.calls) == source_calls


@pytest.mark.asyncio
async def test_rediscovery_search_does_not_make_a_revoked_library_outline_current(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=Search(), fetcher=Outline())
        _, warm = await _warm(jobs)
        job, state = _state(jobs, warm)
        rid = next(iter(state["resources"]))
        assert not jobs.course_library.observe({"url": URL, "fetch_status": "site_policy_blocked", "fetched_at": now()},
                                               [], jobs._course_library_profile())
        for point in job["knowledge_points"]:
            store.add_evidence(warm, rid, point["knowledge_point_id"], {
                "evidence_id": "fresh_search_" + str(uuid4()), "kind": "search", "source": "offline_fixture",
                "knowledge_point_id": point["knowledge_point_id"], "url": URL, "title": "Python 程序设计",
                "snippet": "Python 列表与字典", "observed_at": now()})
        assert all(group["mooc_relevance"]["recommended_count"] == 0 for group in jobs.results(warm)["groups"])
        assert all(jobs._mooc_coverage_count(job, point, state) == 0 for point in job["knowledge_points"])


@pytest.mark.asyncio
async def test_disabling_library_before_new_job_prevents_seeding_and_preserves_gap_search(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(first)
        assert jobs.course_library.stats()["fresh"] == 1
        jobs.settings = replace(config, shared_course_library_enabled=False)
        second = jobs.create(SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(second)
        job = store.get_job(second)
        assert not job.get("shared_course_library", {}).get("loaded")
        assert not job["progress"].get("library_hit_pairs")
        assert job["progress"]["search_requests"] >= 1
        assert all(not resource.get("course_library") for resource in store.resources(second).values())
