"""Actual rank/service regressions from a retained public JS-shell response."""
from copy import deepcopy
import json
from pathlib import Path

from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.ranking import rank_resource
from tests.test_learning_target_persistence import offline_service


def retained(point_id="p"):
    record = json.loads((Path(__file__).parent / "fixtures/video_shell/observed-shell.json").read_text(encoding="utf-8"))["resource"]
    evidence = record.pop("own_evidence")
    for row in evidence:
        if row.get("kind") == "search":
            row["knowledge_point_id"] = point_id
    for key in ("assessment_current", "match_current", "identity_eligible", "rejection_layer_current"):
        record.pop(key, None)
    record["discovered_at"] = "2026-10-18T00:00:00Z"
    record["platform"] = "other"
    return record, evidence


def test_real_shell_goes_to_review_and_cannot_supply_coverage_or_invalid_link_claim():
    resource, evidence = retained()
    point = {"knowledge_point_id": "p", "text": "pandas 读取骑行 CSV 与列结构检查", "learning_targets": ["read_csv"]}
    before = deepcopy((resource, evidence))
    result = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result and result["topic_evidence_status"] == "needs_review"
    assert result["topic_evidence_reasons"][0]["code"] == "page_shell_unconfirmed"
    assert result["coverage_basis"] == result["supporting_evidence_ids"] == []
    assert all(row["status"] == "unknown" and row["evidence_ids"] == [] for row in result["subtopic_coverage"])
    assert "JavaScript" in result["recommendation_reason"]
    assert (resource, evidence) == before


def test_old_stored_shell_is_repaired_by_read_without_rewriting_resource_cache_or_evidence(tmp_path):
    path = tmp_path / "legacy-shell.sqlite3"
    store = Store(str(path))
    try:
        service = offline_service(path, store)
        text = "pandas 读取骑行 CSV 与列结构检查"
        identifier = service.create(SearchRequest(knowledge_points=[text], learning_targets={text: ["read_csv"]}))["job_id"]
        job = store.get_job(identifier)
        point = job["knowledge_points"][0]
        resource, evidence = retained(point["knowledge_point_id"])
        store.save_resource(identifier, resource)
        for row in evidence:
            store.add_evidence(identifier, resource["resource_id"], point["knowledge_point_id"] if row.get("kind") == "search" else None, row)
        store.cache_set("retained-shell", "page", resource, 300)
        before = list(store.connection.iterdump())
        results = service.results(identifier)
        group = results["groups"][0]
        assert group["items"] == group["partial_items"] == []
        assert len(group["review_items"]) == 1
        visible = group["review_items"][0]["resource"]
        assert visible["title"] == next(row["title"] for row in evidence if row.get("kind") == "search")
        assert visible["url"] == resource["url"]
        assert "JavaScript" in visible["access_notice"]
        assert group["collection_coverage"]["status"] == "unknown"
        assert list(store.connection.iterdump()) == before
    finally:
        store.close()
