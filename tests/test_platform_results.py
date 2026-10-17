"""Offline regression: a relevant sixth-ranked platform must remain filterable."""
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService


def test_platform_filter_before_display_limit():
    store = Store(":memory:")
    svc = JobService(Settings(database_path=":memory:"), store)
    job_id = svc.create(SearchRequest(knowledge_points=["Python"]))["job_id"]
    point_id = store.get_job(job_id)["knowledge_points"][0]["knowledge_point_id"]
    for i in range(6):
        rid = f"synthetic-{i}"
        store.save_resource(job_id, {"resource_id": rid, "canonical_url": f"https://example.org/{rid}", "platform": "bilibili" if i < 5 else "icourse163"})
        store.save_match(job_id, {"knowledge_point_id": point_id, "resource_id": rid, "ranking_score": 100 - i})
    # This test isolates grouping/truncation; real evidence admission is covered
    # by the ranking and saved-evidence regressions.
    stored = {match["resource_id"]: match for match in store.matches(job_id)}
    def evaluated_match(point, resource, evidence, request, **kwargs):
        return {**stored[resource["resource_id"]], "topic_evidence_status": "supported",
                "topic_evidence_reasons": [{"code": "isolated_fixture", "message": "Grouping fixture", "evidence_ids": []}],
                "supporting_evidence_ids": [], "subtopic_coverage": [], "matched_evidence_ids": [],
                "recommendation_reason": "Grouping fixture", "coverage_basis": [], "topic_match_rules": []}
    with patch("backend.app.service.rank_resource", side_effect=evaluated_match):
        group = svc.results(job_id)["groups"][0]
    assert group["total_matches"] == 6
    assert len(group["items"]) == 5
    assert all(item["resource"]["platform"] == "bilibili" for item in group["items"])
    assert len(group["platform_items"]["icourse163"]) == 1
    assert group["platform_items"]["icourse163"][0]["resource"]["resource_id"] == "synthetic-5"
    store.close()
