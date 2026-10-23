"""Local contract checks; no playback, network, model or production state."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from backend.app.models import SearchRequest
from backend.app.related_recommendations import (
    related_recommendation, reference_link_eligible, _weak_framework_capability,
    bound_native_course_identity,
)
from backend.app.ai_video_service import visible_point_ids
from backend.app.extractor import MetadataExtractor
from backend.app.grounded_related import prepare_pair

FIXTURES = Path(__file__).parent / "fixtures" / "reference_threshold"
URL = "https://www.bilibili.com/video/BV1xx411c7Df/"
OTHER = "https://www.bilibili.com/video/BV1xx411c7Dg/"
STAMP = "2026-10-21T01:00:00+00:00"


def search_case(concept="set difference", technology="Python", title=None, body=""):
    title = title or technology + " " + concept
    point = {"knowledge_point_id": "p", "text": concept, "technology": technology}
    resource = {"resource_id": "r", "url": URL, "canonical_url": URL, "resolved_url": URL,
        "platform": "bilibili", "resource_type": "video", "title": title,
        "fetch_status": "javascript_required", "video_evidence_status": "search_discovered",
        "field_provenance": {"resource_type": {"evidence_id": "s", "source": "search_template", "url": URL},
            "video_evidence_status": {"evidence_id": "s", "source": "search_template", "url": URL}}}
    evidence = [{"evidence_id": "s", "kind": "search", "source": "serper", "knowledge_point_id": "p",
        "type_source": "search_template", "resource_type_hint": "video", "url": URL,
        "title": title, "snippet": body, "observed_at": STAMP}]
    request = SearchRequest(knowledge_points=[concept], topic_technologies={concept: technology})
    return point, resource, evidence, request


def own_identity_case():
    point, resource, evidence, request = search_case()
    data = {"@context": "https://schema.org", "@type": "VideoObject", "name": "Python course",
            "description": "Python programming lessons", "contentUrl": "https://media.example.org/lesson.mp4"}
    own = MetadataExtractor().extract('<script type="application/ld+json">' + json.dumps(data) + '</script>', URL, STAMP)
    own_evidence = own.pop("evidence")
    resource.update(own)
    resource["resource_id"] = "r"
    resource["fetch_status"] = "fetched"
    evidence += own_evidence
    return point, resource, evidence, request


def service_for(point, resource, evidence, item):
    group = {**point, "recommendation_policy": "related-reference-v1", "related_recommendations": [item]}
    return SimpleNamespace(results=lambda _: {"groups": [group]}, store=SimpleNamespace(
        resources=lambda _: {resource["resource_id"]: resource}, evidence=lambda *_: evidence)), {"job_id": "j"}


@pytest.mark.parametrize("concept,body", [
    ("data model constraints", "Key features include type safety, data model constraints, performance and integration support."),
    ("type safety", "Framework capabilities include type safety, performance and flexible integration."),
])
def test_english_generic_framework_capabilities_are_not_lesson_relevance(concept, body):
    args = search_case(concept, "Pydantic", "Pydantic AI framework overview", body)
    assert _weak_framework_capability(concept, args[1]["title"], body)
    assert related_recommendation(*args) is None


@pytest.mark.parametrize("title,body", [
    ("Pydantic data model constraints", "Key framework features include type safety and integration."),
    ("Pydantic framework tutorial", "Learn data model constraints; key features include type safety."),
])
def test_actual_lesson_title_or_instruction_survives_weak_feature_filter(title, body):
    args = search_case("data model constraints", "Pydantic", title, body)
    item = related_recommendation(*args)
    assert item and item["reference"]["link_eligible"] is True
    assert item["reference"]["exact_teaching_verified"] is False


def test_own_identity_does_not_disqualify_same_source_search_relevance():
    point, resource, evidence, request = own_identity_case()
    search = evidence[0]
    assert reference_link_eligible(resource, evidence, [search])
    item = related_recommendation(point, resource, evidence, request)
    assert item and item["reference"]["link_eligible"] is True
    assert item["reference"]["technical_context"] == "observed"
    assert item["reference"]["basis"] == ["search"]
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == {"p"}


@pytest.mark.parametrize("change", ["foreign", "stale", "unknown_provider", "query_only", "unbound"])
def test_own_identity_does_not_promote_invalid_search_relevance(change):
    _, resource, evidence, _ = own_identity_case()
    search = evidence[0]
    if change == "foreign": search["url"] = OTHER
    elif change == "stale": search["cache"] = {"stale": True}
    elif change == "unknown_provider": search["source"] = "model"
    elif change == "query_only": search.update(title="", snippet="", query="Python set difference")
    else: search["knowledge_point_id"] = None
    assert not reference_link_eligible(resource, evidence, [search])


@pytest.mark.parametrize("status", ["unsafe_url", "not_found", "error_page", "unavailable", "removed", "deleted",
                                    "access_denied", "access_blocked", "robots_blocked"])
def test_known_unavailable_reference_is_not_eligible(status):
    point, resource, evidence, request = search_case()
    item = related_recommendation(point, resource, evidence, request)
    resource["fetch_status"] = status
    assert not reference_link_eligible(resource, evidence, evidence)
    assert related_recommendation(point, resource, evidence, request) is None
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == set()


@pytest.mark.parametrize("change", ["resource_stale", "cache_stale", "evidence_stale", "unbound_target", "foreign_resolved"])
def test_link_signal_cannot_override_current_resource_or_evidence(change):
    point, resource, evidence, request = search_case()
    item = related_recommendation(point, resource, evidence, request)
    assert item["reference"]["link_eligible"] is True
    if change == "resource_stale": resource["stale"] = True
    elif change == "cache_stale": resource["cache"] = {"stale": True}
    elif change == "evidence_stale": evidence[0]["cache"] = {"stale": True}
    elif change == "unbound_target": item["resource"]["canonical_url"] = OTHER
    else: resource["resolved_url"] = OTHER
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == set()


@pytest.mark.parametrize("signal", [False, None, 1, "true"])
def test_explicit_non_true_signal_never_uses_legacy_fallback(signal):
    point, resource, evidence, request = own_identity_case()
    item = related_recommendation(point, resource, evidence, request)
    item["reference"]["link_eligible"] = signal
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == set()


def test_eligible_search_link_closes_gap_without_claiming_playback_or_full_teaching():
    point, resource, evidence, request = search_case()
    item = related_recommendation(point, resource, evidence, request)
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == {"p"}
    assert item["reference"]["exact_teaching_verified"] is False
    assert resource["video_evidence_status"] == "search_discovered"
    assert resource["fetch_status"] == "javascript_required"
    item["reference"].pop("link_eligible")
    assert visible_point_ids(service, job) == set()


def test_missing_signal_keeps_legacy_qualified_page_path():
    point, resource, evidence, _ = own_identity_case()
    own = next(row for row in evidence if row.get("field") == "title")
    item = {"resource": resource, "reference": {"technical_context": "observed", "basis": ["page"],
        "evidence_ids": [own["evidence_id"]]}}
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == {"p"}
    resource["fetch_status"] = "javascript_required"
    assert visible_point_ids(service, job) == set()


@pytest.mark.parametrize("context", ["unconfirmed", None])
def test_true_signal_does_not_override_unconfirmed_requested_technology(context):
    point, resource, evidence, request = search_case()
    item = related_recommendation(point, resource, evidence, request)
    item["reference"]["technical_context"] = context
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == set()


def test_explicit_wrong_technology_and_external_only_course_do_not_match():
    assert related_recommendation(*search_case(title="JavaScript set difference")) is None
    body = "Complete course download: https://example.org/full-course Python set difference tutorial"
    assert related_recommendation(*search_case(title="Python introductory clip", body=body)) is None


def test_access_requirements_remain_attached_to_relevant_link():
    point, resource, evidence, request = search_case()
    resource.update(requires_payment=True, requires_login=True, access_notice="Platform payment required; playback unverified")
    item = related_recommendation(point, resource, evidence, request)
    assert item["reference"]["link_eligible"] is True
    assert item["resource"]["requires_payment"] is True
    assert item["resource"]["requires_login"] is True
    service, job = service_for(point, resource, evidence, item)
    assert visible_point_ids(service, job) == {"p"}


REAL = json.loads((FIXTURES / "v23-search-references.json").read_text(encoding="utf-8"))
@pytest.mark.parametrize("case", REAL, ids=[str(i) + "-" + c["point_id"] for i,c in enumerate(REAL)])
def test_frozen_v23_twelve_reference_replay(case):
    args = deepcopy(case["args"])
    args[3] = SearchRequest(**args[3])
    item = related_recommendation(*args)
    assert bool(item and item["reference"]["link_eligible"]) is case["expected"]
    if item:
        assert item["reference"]["exact_teaching_verified"] is False
        assert {r["evidence_id"] for r in item["evidence"]} <= {r["evidence_id"] for r in args[2]}
        service, job = service_for(*args[:3], item)
        assert visible_point_ids(service, job) == ({args[0]["knowledge_point_id"]} if case["expected"] else set())


def test_frozen_native_course_identity_and_grounded_preparation_remain_supported():
    case = json.loads((FIXTURES / "v23-own-course.json").read_text(encoding="utf-8"))
    args = case["args"]
    args[3] = SearchRequest(**args[3])
    point, resource, evidence, request = args
    assert bound_native_course_identity(resource, evidence)
    pair = prepare_pair(point, resource, evidence, request)
    assert pair and pair["sources"]
    assert resource["video_evidence_status"] == "none"
