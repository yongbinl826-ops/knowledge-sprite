"""Retrieval-only display preserves actual sources without teaching judgements."""
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService
from test_teaching_match import lesson


def setup(count=8):
    service = JobService(Settings(teaching_match_enabled=False), Store(":memory:"))
    request = SearchRequest(knowledge_points=["QuillFlow queues", "QuillFlow updates"],
                            learning_skills={"QuillFlow queues": ["QuillFlow bounded queues"]})
    job = service.store.get_job(service.create(request)["job_id"])
    for index in range(count):
        resource, rows = lesson(url=f"https://lessons.example/queue-{index}")
        rid = f"r{index}"
        resource.update(resource_id=rid, platform="other")
        for row in rows:
            row["evidence_id"] += str(index)
        for provenance in resource["field_provenance"].values():
            provenance["evidence_id"] += str(index)
        service.store.save_resource(job["job_id"], resource)
        for row in rows:
            service.store.add_evidence(job["job_id"], rid, None, row)
        point = job["knowledge_points"][0]
        search = {"evidence_id": f"search{index}", "kind": "search", "source": "offline",
                  "knowledge_point_id": point["knowledge_point_id"], "url": resource["url"],
                  "title": resource["title"], "query": point["text"]}
        service.store.add_evidence(job["job_id"], rid, point["knowledge_point_id"], search)
    return service, job


def test_all_discovered_videos_are_visible_without_five_item_or_teaching_gate():
    service, job = setup()
    before = service.store.connection.total_changes
    with patch("backend.app.service.rank_resource", side_effect=AssertionError("no teaching ranking")):
        result = service.results(job["job_id"])
        assert service.results(job["job_id"]) == result
    group = result["groups"][0]
    assert len(group["discovery_items"]) == 8
    assert len(group["discovery_platform_items"]["other"]) == 8
    assert group["discovery_only"] is True
    assert group["items"] == group["partial_items"] == group["review_items"] == []
    assert "learning_coverage" not in group
    assert result["groups"][1]["discovery_items"] == []
    assert service.store.connection.total_changes == before


@pytest.mark.parametrize("change", ["unknown_type", "wrong_url", "wrong_point", "not_found"])
def test_no_invented_type_cross_point_or_unavailable_candidates(change):
    service, job = setup(1)
    resource = service.store.resources(job["job_id"])["r0"]
    if change == "unknown_type":
        resource["resource_type"] = "unknown"
    elif change == "not_found":
        resource["fetch_status"] = "not_found"
    else:
        # Replace the only search observation while leaving own-page facts intact.
        store = service.store
        row = next(row for row in store.evidence(job["job_id"], "r0") if row["kind"] == "search")
        if change == "wrong_url":
            row["url"] = "https://other.example/course"
        else:
            row["knowledge_point_id"] = "different-point"
        import json
        store.connection.execute("UPDATE evidence SET data=? WHERE id=?", (json.dumps(row), row["evidence_id"]))
    service.store.save_resource(job["job_id"], resource)
    assert service.results(job["job_id"])["groups"][0]["discovery_items"] == []


def test_search_only_mooc_is_retained_as_pending_without_claiming_outline_coverage():
    service, job = setup(1)
    resource = service.store.resources(job["job_id"])["r0"]
    resource.update(resource_type="course", fetch_status="not_fetched", metadata_evidence_level="search",
                    video_evidence_status="none", url="https://www.icourse163.org/course/COURSE-123",
                    canonical_url="https://www.icourse163.org/course/COURSE-123")
    resource["field_provenance"]["resource_type"] = {"evidence_id": "course-search", "source": "url_pattern"}
    service.store.save_resource(job["job_id"], resource)
    point = job["knowledge_points"][0]
    service.store.add_evidence(job["job_id"], "r0", point["knowledge_point_id"], {
        "evidence_id": "course-search", "kind": "search", "source": "offline", "url": resource["url"],
        "title": "QuillFlow course", "knowledge_point_id": point["knowledge_point_id"]})
    group = service.results(job["job_id"])["groups"][0]
    assert group["discovery_items"] == []
    assessment = group["mooc_relevance"]["candidates"][0]["assessment"]
    assert assessment["status"] == "search_candidate"
    assert not assessment["display_eligible"] and assessment["probe_eligible"]
    retained = service.store.resources(job["job_id"])["r0"]
    assert retained["resource_type"] == "course"
    assert retained["video_evidence_status"] == "none"
    assert not retained.get("playback_verified")


def test_future_search_skips_teaching_calls_and_reserves_no_teaching_budget():
    service, job = setup(0)
    service.llm = object()
    service._search_queries = AsyncMock()
    service._run_details = AsyncMock()
    service._match_learning_skills = AsyncMock(side_effect=AssertionError("teaching must be skipped"))
    service._rerank = AsyncMock(side_effect=AssertionError("reranking must be skipped"))
    asyncio.run(service._execute(job))
    service._match_learning_skills.assert_not_awaited()
    service._rerank.assert_not_awaited()
    assert "teaching_match_reserved_seconds" not in job["budgets"]


def test_default_and_restored_mode_remain_teaching_matching():
    assert Settings().teaching_match_enabled is True
    service, job = setup(1)
    service.settings = replace(service.settings, teaching_match_enabled=True)
    assert "discovery_only" not in service.results(job["job_id"])
