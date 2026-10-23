"""Bounded query outcomes do not retain model text or change source matching."""
from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from backend.app.ai_video_fallback import normalize_video_discovery_with_diagnostics
from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases, video_recovery_search_phrases_with_diagnostics
from backend.app.ai_video_service import visible_point_ids
from test_ai_grounded_recovery import URL, SourcePages, recovery_service


def test_query_normalization_distinguishes_omitted_empty_filtered_and_duplicates():
    points = [f"private point {index}" for index in range(5)]
    body = {"suggestions": [
        {"point_id": "kp_0", "urls": []},
        {"point_id": "kp_1", "urls": [], "queries": []},
        {"point_id": "kp_2", "urls": [], "queries": ["  ", "https://private.invalid/secret-key"]},
        {"point_id": "kp_3", "urls": [], "queries": ["Rust  borrowing lifetime", "rust borrowing lifetime"]},
    ]}
    plan, audit = normalize_video_discovery_with_diagnostics(body, points, ["bilibili"])
    query = audit["query_normalization"]
    assert [item["query_state"] for item in query["points"]] == [
        "missing_field", "empty", "filtered", "accepted", "missing_point"]
    assert query["returned_query_fields"] == 3
    assert query["missing_points"] == query["missing_query_fields"] == query["empty_query_points"] == 1
    assert query["input_queries"] == 4 and query["accepted_queries"] == 1
    assert query["rejected_queries"] == {"empty": 1, "invalid": 1, "duplicate": 1}
    assert plan[points[3]]["queries"] == ["Rust borrowing lifetime"]
    for row in query["points"]:
        assert row["input_queries"] == row["accepted_queries"] + sum(row["rejected_queries"].values())
    assert query["input_queries"] == sum(row["input_queries"] for row in query["points"])
    assert query["accepted_queries"] == sum(row["accepted_queries"] for row in query["points"])
    serialized = json.dumps(audit)
    assert not any(value in serialized for value in points + ["Rust", "borrowing", "https://", "secret-key", "private.invalid"])


def test_query_dedupe_stays_per_point_and_total_never_exceeds_ten():
    points = [f"point {index}" for index in range(5)]
    body = {"suggestions": [{"point_id": f"kp_{index}", "urls": [],
        "queries": ["Rust borrow checker", "Rust lifetime inference"]} for index in range(5)]}
    plan, audit = normalize_video_discovery_with_diagnostics(body, points, ["bilibili"])
    assert audit["query_normalization"]["input_queries"] == audit["query_normalization"]["accepted_queries"] == 10
    assert all(len(row["queries"]) == 2 for row in plan.values())
    body["suggestions"][0]["queries"].append("Rust arbitrary tail")
    with pytest.raises(ValidationError):
        normalize_video_discovery_with_diagnostics(body, points, ["bilibili"])


@pytest.mark.parametrize("hint,reason", [
    ("", "empty"), ("Rust https://private.invalid/secret", "invalid_syntax_or_length"),
    ("Rust one two three four five six seven eight", "word_limit"),
    ("Python borrow checker", "missing_literal"), ("Rust borrow checker 2027", "version_conflict"),
    ("Rust tutorial", "insufficient_specificity"),
])
def test_planning_rejections_are_fixed_labels_with_conserved_counts(hint, reason):
    point = "借用检查与生命周期推断"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Rust"})
    phrases, audit = video_recovery_search_phrases_with_diagnostics(point, request, [hint])
    assert phrases == ["Rust " + point]
    assert audit["input_hints"] == 1 and audit["accepted_hints"] == audit["not_evaluated_hints"] == 0
    assert audit["rejected_hints"][reason] == 1
    assert sum(audit["rejected_hints"].values()) == 1
    assert audit["phrase_kinds"] == ["original"]
    assert all(value not in json.dumps(audit) for value in ["Rust", point, "private.invalid", "secret"])


def test_planning_duplicates_and_slots_are_counted_without_treating_them_as_model_empty():
    point = "借用检查与生命周期推断"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Rust"})
    phrases, audit = video_recovery_search_phrases_with_diagnostics(point, request,
        ["Rust borrow checker", "rust borrow checker", "ignored"])
    assert phrases == ["Rust " + point, "Rust borrow checker"]
    assert audit["input_hints"] == 2 and audit["accepted_hints"] == 1
    assert audit["rejected_hints"]["duplicate"] == 1
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"})
    phrases, audit = video_recovery_search_phrases_with_diagnostics("文件下载", request,
        ["Streamlit download button", "Streamlit download files"])
    assert len(phrases) == 3 and audit["accepted_hints"] == 1
    assert audit["rejected_hints"]["slots_exhausted"] == 1


def test_unavailable_target_preserves_not_evaluated_state_and_original_limit():
    request = SearchRequest(knowledge_points=["known"])
    phrases, audit = video_recovery_search_phrases_with_diagnostics("foreign", request, ["Rust borrow checker"])
    assert not phrases and audit["status"] == "target_unavailable"
    assert audit["not_evaluated_hints"] == 1 and not any(audit["rejected_hints"].values())
    request = SearchRequest(knowledge_points=["site:private.invalid"])
    phrases, audit = video_recovery_search_phrases_with_diagnostics("site:private.invalid", request, ["Rust borrow checker"])
    assert not phrases and audit["status"] == "original_rejected" and audit["not_evaluated_hints"] == 1


@pytest.mark.parametrize("point,hint", [
    ("表单输入校验与提交控制", "Streamlit form input validation and submission control"),
    ("文件下载与权限核对", "Streamlit download button permission validation"),
])
def test_mixed_known_unknown_english_is_independent_before_ui_mechanical_alternative(point, hint):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    before = deepcopy(request.model_dump())
    phrases, audit = video_recovery_search_phrases_with_diagnostics(point, request, [hint])
    assert phrases[0] == "Streamlit " + point
    assert phrases[-1] == hint and len(phrases) == 3
    assert audit["accepted_hints"] == 1 and audit["phrase_kinds"] == ["original", "deterministic", "model"]
    assert request.model_dump() == before
    assert video_recovery_search_phrases(point, request, [hint]) == phrases


@pytest.mark.parametrize("hint", ["Streamlit validation submission control", "Streamlit form input", "Streamlit input widgets"])
def test_mixed_hint_cannot_drop_known_core_or_use_only_that_core(hint):
    point = "表单输入校验与提交控制"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    phrases, audit = video_recovery_search_phrases_with_diagnostics(point, request, [hint])
    assert hint not in phrases and audit["accepted_hints"] == 0
    assert sum(audit["rejected_hints"].values()) == 1


@pytest.mark.parametrize("teaching", [False, True])
@pytest.mark.parametrize("source_topic,covered", [("Streamlit 表单输入数组排序", False), ("Streamlit 表单输入校验与提交控制", True)])
async def test_independent_mixed_hint_cannot_close_gap_without_original_source_topic(teaching, source_topic, covered, recovery_service):
    point = "表单输入校验与提交控制"
    hint = "Streamlit form input array sorting"  # Untrusted, potentially wrong discovery lead.
    original = "Streamlit " + point

    def respond(query, _count):
        return httpx.Response(200, json={"organic": [] if not query.endswith(hint) else [
            {"title": original, "snippet": original, "link": URL}]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": [hint]}},
        respond=respond, teaching_match_enabled=teaching)
    service.fetcher = SourcePages({URL: source_topic})
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Streamlit"}))["job_id"]
    await service.run(identifier)
    job = service.store.get_job(identifier)
    assert len(searches) == 3 and searches[-1] == "site:bilibili.com " + hint
    assert len(service.fetcher.calls) == 1 and bool(visible_point_ids(service, job)) is covered
    assert job["knowledge_points"][0]["text"] == point
    audit = job["ai_video_fallback"]["query_planning"][0]
    assert audit["accepted_hints"] == 1 and audit["phrase_kinds"] == ["original", "deterministic", "model"]
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    assert hint not in resource["title"] and hint not in resource["description"]
    public = json.dumps(service.results(identifier))
    assert "query_planning" not in public and "query_normalization" not in public


@pytest.mark.parametrize("point", ["指针输入与坐标换算", "指针输入和坐标换算"])
def test_unfamiliar_compound_lead_is_not_a_translation_assertion(point):
    # Former atomic-only exclusions now exercise the explicit discovery-lead
    # contract. Known core omissions remain rejected in the original suite.
    hint = "Streamlit pointer input"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    before = deepcopy(request.model_dump())
    phrases = video_recovery_search_phrases(point, request, [hint])
    assert phrases == ["Streamlit " + point, hint]
    assert len(phrases) <= 3 and request.model_dump() == before


@pytest.mark.parametrize("point", ["指针输入与坐标换算", "指针输入和坐标换算"])
@pytest.mark.parametrize("teaching", [False, True])
async def test_partial_english_pointer_lead_and_full_snippet_cannot_cover_original_compound(point, teaching, recovery_service):
    hint = "Streamlit pointer input"
    original = "Streamlit " + point

    def respond(query, _count):
        return httpx.Response(200, json={"organic": [] if not query.endswith(hint) else [
            {"title": original, "snippet": original, "link": URL}]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": [hint]}},
        respond=respond, teaching_match_enabled=teaching)
    service.fetcher = SourcePages({URL: hint})  # Own page only supports the partial operation.
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Streamlit"}))["job_id"]
    await service.run(identifier)
    job = service.store.get_job(identifier)
    assert searches == ["site:bilibili.com " + original, "site:bilibili.com " + hint]
    assert len(service.fetcher.calls) == 1 and not visible_point_ids(service, job)
    assert job["knowledge_points"][0]["text"] == point and job["ai_video_fallback"]["remaining_points"] == 1
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    assert resource["title"] == hint + "公开教学视频" and point not in resource["description"]
