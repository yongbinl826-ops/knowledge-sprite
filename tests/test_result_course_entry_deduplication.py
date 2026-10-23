"""Read-only result projection: URL variants do not inflate course counts."""
from copy import deepcopy
from types import SimpleNamespace
import json
import pytest

import backend.app.service as service_module
from backend.app.models import Resource, SearchRequest
from backend.app.service import JobService


def test_results_collapse_unknown_offering_course_entries_without_merging_or_hiding_distinct_roles(monkeypatch):
    point = {"knowledge_point_id": "p", "text": "pandas 分组聚合"}
    root = "https://www.icourse163.org/course/NJCIT-1469574161"
    learn = "https://www.icourse163.org/learn/NJCIT-1469574161?tid=1470946446"
    resources, observations, matches = {}, {}, []

    def add(rid, url, *, own=False, platform="icourse163"):
        title = "Python数据处理"
        search_id = "search-" + rid
        rows = [{"evidence_id": search_id, "kind": "search", "source": "synthetic",
                 "knowledge_point_id": "p", "url": url, "title": title,
                 "snippet": "pandas分组聚合", "resource_type_hint": "course", "type_source": "url_pattern"}]
        resource = Resource(resource_id=rid, title=title, url=url, canonical_url=url,
                            platform=platform, resource_type="course", discovered_at="2026-10-19T00:00:00Z").model_dump()
        supporting = [search_id]
        if own:
            eid = "own-" + rid
            text = "项目6 使用pandas进行数据分组与聚合"
            rows.append({"evidence_id": eid, "kind": "page", "field": "description",
                         "source": "html.own_course_description", "url": url, "text": text})
            resource.update(fetch_status="fetched", description=text,
                            field_provenance={"description": {"evidence_id": eid,
                            "source": rows[-1]["source"], "url": url}})
            supporting = [eid]
        resources[rid], observations[rid] = resource, rows
        matches.append({"knowledge_point_id": "p", "resource_id": rid,
                        "ranking_score": 65.75 if own else 80,
                        "topic_evidence_status": "supported", "supporting_evidence_ids": supporting,
                        "matched_evidence_ids": supporting, "coverage_basis": ["description" if own else "snippet"],
                        "subtopic_coverage": [{"id": "whole_topic", "text": point["text"],
                        "status": "supported", "evidence_ids": supporting}]})

    # Actual observed entry shapes. The weaker search score is deliberately higher.
    add("own-course", root, own=True)
    add("learn-entry", learn)
    for rid in ("term-a", "term-b", "lesson", "unknown", "foreign-platform", "other-family"):
        add(rid, root + "?fixture=" + rid, platform="other" if rid == "foreign-platform" else "icourse163")
    original_identity = service_module.derive_course_identity

    def identity(resource, evidence):
        value = original_identity(resource, evidence)
        rid = resource["resource_id"]
        if rid in {"term-a", "term-b"}:
            value["offering_id"] = "offering-" + rid
        elif rid == "lesson":
            value["role"] = "lesson"
        elif rid == "unknown":
            value["status"] = "unknown"
        elif rid == "other-family":
            value["family_id"] = "different-family"
        return value

    monkeypatch.setattr(service_module, "derive_course_identity", identity)
    job = {"job_id": "j", "status": "completed", "warnings": [], "knowledge_points": [point],
           "request": SearchRequest(knowledge_points=[point["text"]]).model_dump()}

    class ReadOnlyStore:
        def get_job(self, job_id):
            assert job_id == "j"
            return deepcopy(job)

        def resources(self, job_id):
            return deepcopy(resources)

        def matches(self, job_id):
            return deepcopy(matches)

        def evidence(self, job_id, rid, point_id=None):
            assert point_id in {None, "p"}
            return deepcopy(observations[rid])

        def attempts(self, job_id):
            return []

    class ValidatedMatches:
        def rank(self, point, resource, evidence, request, **kwargs):
            return deepcopy(next(m for m in matches if m["resource_id"] == resource["resource_id"]))

    service = JobService.__new__(JobService)
    service.settings = SimpleNamespace(teaching_match_enabled=True, max_results_per_point=20)
    service.store, service._read_rank_cache = ReadOnlyStore(), ValidatedMatches()
    before = deepcopy((resources, observations, matches, job))
    result = service.results("j")
    group = result["groups"][0]
    ids = [item["resource"]["resource_id"] for item in group["items"]]
    assert set(ids) == {"own-course", "term-a", "term-b", "lesson", "unknown", "foreign-platform", "other-family"}
    assert ids[0] == "own-course" and group["total_matches"] == 7
    assert len(group["platform_items"]["icourse163"]) == 6
    assert len(group["platform_items"]["other"]) == 1
    kept = group["items"][0]
    assert kept["match"] == matches[0] and kept["evidence"] == observations["own-course"]
    assert kept["resource"]["url"] == root
    assert "search-learn-entry" not in json.dumps(kept, ensure_ascii=False)
    assert "learn-entry" not in group["collection_coverage"]["subtopics"][0]["resource_ids"]
    assert (resources, observations, matches, job) == before
    assert service.results("j") == result  # Stable GET; fake store exposes no write API.


@pytest.mark.parametrize("scenario", ["partial_before_supported", "review_before_supported", "partial_and_review_only"])
def test_same_family_representative_preserves_visible_status_and_separate_review_observations(scenario):
    point = {"knowledge_point_id": "p", "text": "pandas 分组聚合"}
    root = "https://www.icourse163.org/course/NJCIT-1469574161"
    resources, observations, matches = {}, {}, []

    def add(rid, url, status, score, *, own=False):
        sid = "search-" + rid
        rows = [{"evidence_id": sid, "kind": "search", "source": "synthetic", "url": url,
                 "knowledge_point_id": "p", "title": "pandas分组聚合课程", "snippet": "pandas分组聚合"}]
        resource = Resource(resource_id=rid, title=rows[0]["title"], url=url, canonical_url=url,
                            platform="icourse163", resource_type="course", discovered_at="2026-10-19T00:00:00Z").model_dump()
        support = [sid]
        if own:
            eid = "own-" + rid
            text = "项目6 使用pandas进行数据分组与聚合"
            rows.append({"evidence_id": eid, "kind": "page", "field": "description", "text": text,
                         "url": url, "source": "html.own_course_description"})
            resource.update(fetch_status="fetched", description=text,
                            field_provenance={"description": {"evidence_id": eid, "source": rows[-1]["source"], "url": url}})
            support = [eid]
        resources[rid], observations[rid] = resource, rows
        matches.append({"knowledge_point_id": "p", "resource_id": rid, "ranking_score": score,
                        "topic_evidence_status": status, "supporting_evidence_ids": support,
                        "matched_evidence_ids": support, "coverage_basis": ["description" if own else "snippet"],
                        "subtopic_coverage": [{"id": "whole_topic", "text": point["text"],
                        "status": "unknown" if status == "needs_review" else "supported", "evidence_ids": support}]})

    owner_status = "needs_review" if scenario == "review_before_supported" else "partial"
    add("own-entry", root, owner_status, 99, own=True)
    add("search-entry", "https://www.icourse163.org/learn/NJCIT-1469574161?tid=1470946446",
        "partial" if scenario == "partial_and_review_only" else "supported", 60)
    add("other-high", "https://www.icourse163.org/course/OTHER-111", "supported", 88)
    add("other-low", "https://www.icourse163.org/course/OTHER-222", "supported", 55)
    if scenario == "partial_and_review_only":
        add("review-a", root + "?review=a", "needs_review", 100, own=True)
        add("review-b", root + "?review=b", "needs_review", 98, own=True)

    job = {"job_id": "j", "status": "completed", "warnings": [], "knowledge_points": [point],
           "request": SearchRequest(knowledge_points=[point["text"]]).model_dump()}

    class ReadOnlyStore:
        def get_job(self, job_id):
            return deepcopy(job)

        def resources(self, job_id):
            return deepcopy(resources)

        def matches(self, job_id):
            return deepcopy(matches)

        def evidence(self, job_id, rid, point_id=None):
            return deepcopy(observations[rid])

        def attempts(self, job_id):
            return []

    class ValidatedMatches:
        def rank(self, point, resource, evidence, request, **kwargs):
            return deepcopy(next(m for m in matches if m["resource_id"] == resource["resource_id"]))

    service = JobService.__new__(JobService)
    service.settings = SimpleNamespace(teaching_match_enabled=True, max_results_per_point=10)
    service.store, service._read_rank_cache = ReadOnlyStore(), ValidatedMatches()
    before = deepcopy((resources, observations, matches, job))
    result = service.results("j")
    group = result["groups"][0]
    ids = lambda field: [entry["resource"]["resource_id"] for entry in group[field]]
    if scenario == "partial_and_review_only":
        assert ids("items") == ["other-high", "other-low"]
        assert ids("partial_items") == ["own-entry"]
        assert ids("review_items") == ["review-a", "review-b"]
        assert (group["total_matches"], group["total_partial_matches"], group["total_review_matches"]) == (2, 1, 2)
    else:
        assert ids("items") == ["other-high", "search-entry", "other-low"]
        assert ids("partial_items") == []
        expected_reviews = ["own-entry"] if scenario == "review_before_supported" else []
        assert ids("review_items") == expected_reviews
        assert group["total_matches"] == 3 and group["total_review_matches"] == len(expected_reviews)
    for field in ("items", "partial_items", "review_items"):
        for entry in group[field]:
            rid = entry["resource"]["resource_id"]
            assert entry["evidence"] == observations[rid]
            assert entry["match"] == next(m for m in matches if m["resource_id"] == rid)
    covered_resources = group["collection_coverage"]["subtopics"][0]["resource_ids"]
    assert not set(ids("review_items")) & set(covered_resources)
    assert (resources, observations, matches, job) == before
    assert result == service.results("j")
