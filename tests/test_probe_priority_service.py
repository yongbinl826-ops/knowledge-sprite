from copy import deepcopy
from types import SimpleNamespace

from backend.app import service as service_module


def _context(monkeypatch):
    point = {"knowledge_point_id": "unit", "text": "tool 具体项目任务", "learning_targets": ["tool.method() 参数"]}
    titles = {"api": "tool.method function", "broad": "tool 具体项目任务", "public": "tool public lesson", "sitemap": "tool sitemap", "provisional": "tool proven lesson"}
    resources = {rid: {"resource_id": rid, "title": title, "resource_type": "video", "video_evidence_status": "search_discovered"} for rid, title in titles.items()}
    evidence = {rid: [{"kind": "search", "source": "searxng", "knowledge_point_id": "unit", "title": title, "evidence_id": "search_" + rid}] for rid, title in titles.items()}
    evidence["provisional"].append({"kind": "page", "evidence_id": "verified", "field": "description", "text": "Actual own lesson proof"})
    monkeypatch.setattr(service_module, "rank_resource", lambda point, resource, evidence, request, require_type=False: {"ranking_score": 90, "topic_evidence_status": "partial", "supporting_evidence_ids": ["verified"]} if resource["resource_id"] == "provisional" else None)
    monkeypatch.setattr(service_module, "has_learning_evidence", lambda *args: True)
    fake = SimpleNamespace(
        store=SimpleNamespace(evidence=lambda job, rid, pid: evidence[rid]),
        _teaching_evidence=lambda rows: rows,
        _gap_catalog_probe=lambda point, resource, evidence, state: resource["resource_id"] in {"api", "broad"},
        _targeted_catalog_probe=lambda *args: False,
        _public_catalog_probe=lambda point, resource, evidence, state: resource["resource_id"] == "public",
        _public_catalog_probe_priority=service_module.JobService._public_catalog_probe_priority,
        _sitemap_only=lambda rows: rows[0]["title"] == titles["sitemap"],
    )
    state = {"points": [point], "resources": resources, "candidate_groups": {"unit": list(resources)}, "started": set(), "request": None, "gap_probes_started": {"unit": {"already_used"}}}
    return fake, state, evidence


def test_only_admitted_probe_tie_gets_priority_and_all_existing_tuple_categories_still_compare(monkeypatch):
    fake, state, _ = _context(monkeypatch)
    queue = service_module.JobService._detail_queues(fake, {"job_id": "offline"}, state)["unit"]
    assert queue[:2] == ["api", "broad"]
    assert queue[2:] == ["public", "provisional", "sitemap"]
    # Existing five-element entry categories and their precedence stay intact.
    # The helper is used only to split api/broad within admitted probes.


def test_queue_build_does_not_spend_probe_or_detail_budgets_or_change_requirements(monkeypatch):
    fake, state, evidence = _context(monkeypatch)
    before = deepcopy((state["points"], evidence, state["gap_probes_started"]))
    service_module.JobService._detail_queues(fake, {"job_id": "offline"}, state)
    assert (state["points"], evidence, state["gap_probes_started"]) == before
    assert "reserved" not in state


def test_initial_and_gap_probe_caps_are_unchanged():
    point = {"knowledge_point_id": "unit", "text": "tool 项目任务", "learning_targets": ["tool.method()"]}
    resource = {"title": "tool.method"}
    evidence = [{"kind": "search", "source": "searxng", "knowledge_point_id": "unit", "query": "gap", "title": "tool.method"}]
    assert not service_module.JobService._targeted_catalog_probe(point, resource, evidence, {"gap_probes_started": {"unit": {"one", "two"}}})
    assert not service_module.JobService._gap_catalog_probe(point, resource, evidence, {"gap_query_history": {"unit": {"gap"}}, "gap_probes_started": {"unit": {"one", "two", "three", "four"}}})
