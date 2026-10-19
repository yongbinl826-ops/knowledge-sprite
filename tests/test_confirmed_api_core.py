from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import ranking
from backend.app.models import SearchRequest


def actual():
    return json.loads((Path(__file__).parent / "fixtures/confirmed_api_core_actual_v6.json").read_text(encoding="utf-8"))


def set_title(fixture, title):
    fixture["resource"]["title"] = title
    for row in fixture["evidence"]:
        if row.get("field") == "title":
            row["text"] = title


def set_body(fixture, body):
    fixture["resource"]["description"] = body
    for row in fixture["evidence"]:
        if row.get("field") == "description":
            row["text"] = body


def assessment(fixture):
    return ranking.assess_topic_evidence(fixture["point"], fixture["resource"], fixture["evidence"])


def cores(result):
    return [row for row in (result or {}).get("subtopic_coverage", []) if row["id"].startswith("api_operation_core_")]


def test_actual_v6_only_source_spelled_core_is_partial_not_original_parameter_target():
    fixture = actual()
    before = deepcopy(fixture)
    result = assessment(fixture)
    assert result["topic_evidence_status"] == "partial"
    assert [row["text"] for row in cores(result)] == ["pandas.to_datetime API 使用核心（参数未确认）"]
    assert all(row["status"] == "unknown" for row in result["subtopic_coverage"] if not row["id"].startswith("api_operation_core_"))
    assert cores(result)[0]["evidence_ids"] == [fixture["resource"]["field_provenance"]["title"]["evidence_id"]]
    assert "pd.to_datetime" not in cores(result)[0]["text"]
    assert fixture == before


def test_actual_full_rank_bucket_reason_and_collection_preserve_original_denominator():
    fixture = actual()
    point, resource, evidence = (fixture[k] for k in ("point", "resource", "evidence"))
    request = SearchRequest(knowledge_points=[point["text"]], learning_targets={point["text"]: point["learning_targets"]}, student_level="advanced", language="zh")
    match = ranking.rank_resource(point, resource, evidence, request)
    assert match["topic_evidence_status"] == "partial"
    assert "pandas.to_datetime API 使用核心（参数未确认）" in match["recommendation_reason"]
    assert "pd.to_datetime(errors)" in match["recommendation_reason"]
    item = {"resource": resource, "match": match, "evidence": evidence}
    collection = ranking.summarize_collection_coverage(point["text"], [item], point["learning_targets"])
    original = ranking.coverage_targets(point["text"], point["learning_targets"])
    assert [(x["id"], x["text"]) for x in collection["subtopics"]] == [(x["id"], x["text"]) for x in original["subtopics"]]
    assert all(x["status"] == "unknown" for x in collection["subtopics"])
    assert collection["status"] == "unknown" and not collection["single_resource_full_coverage"]
    # A partial material is present; original objectives have zero completion.
    assert len([item]) == 1 and len(collection["subtopics"]) == 8


@pytest.mark.parametrize("change", ["search_discovered", "no_video_fact", "wrong_url", "wrong_title_binding", "search_title", "search_video_fact"])
def test_requires_same_page_verified_own_video_identity_and_own_title(change):
    f = actual()
    if change == "search_discovered":
        f["resource"]["video_evidence_status"] = "search_discovered"
    elif change == "no_video_fact":
        f["evidence"] = [x for x in f["evidence"] if x.get("field") != "video_evidence_status"]
    elif change == "wrong_url":
        for row in f["evidence"]:
            if row.get("kind") == "page":
                row["url"] = "https://example.org/different"
    elif change == "wrong_title_binding":
        f["resource"]["field_provenance"]["title"]["evidence_id"] = "not-observed"
    elif change == "search_title":
        for row in f["evidence"]:
            if row.get("field") == "title":
                row["source"] = "search"
    else:
        for row in f["evidence"]:
            if row.get("field") == "video_evidence_status":
                row["source"] = "search_template"
    assert not cores(assessment(f))


@pytest.mark.parametrize("body", [
    "本课不讲 pandas.to_datetime。",
    "需要预先掌握 pandas.to_datetime。",
    "pandas.to_datetime will be covered in the next lesson.",
    "pandas.to_datetime 在下一课讲解。",
    "Related APIs: pandas.to_datetime.",
    "TODO pandas.to_datetime.",
    "本视频只是项目演示，不讲实现。",
    "This is only a project demo showcase.",
])
def test_negative_prerequisite_future_reference_and_demo_veto_independent_of_title(body):
    f = actual()
    set_body(f, body)
    assert not cores(assessment(f))


def test_related_tail_cannot_donate_api_topic_or_independent_teaching_action():
    f = actual()
    set_title(f, "pandas 基础教程")
    set_body(f, "pandas基础。相关视频：pandas.to_datetime函数方法使用教程")
    assert not cores(assessment(f))
    set_title(f, "Python pandas.to_datetime")
    assert not cores(assessment(f))


@pytest.mark.parametrize("title", ["NumPy np.to_datetime 函数使用教程", "Pandas 与 NumPy np.to_datetime 函数使用教程", "pandas.to_datetime_extra 函数方法使用教程", "pandas.fake_to_datetime 函数方法使用教程"])
def test_wrong_owner_or_different_api_spelling_cannot_match_same_prefix(title):
    f = actual()
    set_title(f, title)
    set_body(f, title)
    assert not cores(assessment(f))


@pytest.mark.parametrize("owner,target,title", [
    ("ExampleTool", "alias.foo_bar(errors)", "ExampleTool.foo_bar 函数使用教程"),
    ("Arduino", "millis()非阻塞定时采样", "Arduino millis() 函数使用教程"),
    ("WidgetKit", "focus-visible 样式参数", "WidgetKit focus-visible 使用教程"),
])
def test_generic_declared_owner_and_shapes_without_api_semantics_or_vocabulary(owner, target, title):
    f = actual()
    f["point"] = {"knowledge_point_id": "generic", "text": owner + " 具体项目任务", "learning_targets": [target]}
    set_title(f, title)
    set_body(f, title)
    result = assessment(f)
    assert result["topic_evidence_status"] == "partial"
    assert len(cores(result)) == 1
    assert next(x for x in result["subtopic_coverage"] if x["id"] == "learning_target_1")["status"] == "unknown"


def test_numeric_api_core_does_not_assert_range_arguments():
    f = actual()
    f["point"] = {"knowledge_point_id": "generic", "text": "Arduino 随机等待", "learning_targets": ["random(2000, 5001)范围"]}
    set_title(f, "Arduino random() 函数使用教程")
    set_body(f, "本课演示 random() 的使用。")
    result = assessment(f)
    assert result["topic_evidence_status"] == "partial"
    assert next(x for x in result["subtopic_coverage"] if x["id"] == "learning_target_1")["status"] == "unknown"
    assert "2000" not in cores(result)[0]["text"] and "5001" not in cores(result)[0]["text"]


@pytest.mark.parametrize("label", ["函数清单", "方法列表", "API索引", "符号索引", "速查列表", "函数列表", "方法清单", "API list", "symbol index"])
@pytest.mark.parametrize("location", ["title", "body"])
def test_index_is_not_usage_teaching_even_with_function_or_method_words(label, location):
    f = actual()
    text = "pandas.to_datetime " + label
    if location == "title":
        set_title(f, text)
        set_body(f, "本页是符号索引。")
    else:
        set_body(f, text)
    assert not cores(assessment(f))


def test_repeated_confirmed_api_targets_emit_one_supplemental_source_core():
    f = actual()
    f["point"]["learning_targets"] = ["pd.to_datetime(errors)", "pd.to_datetime(format)", "pandas.to_datetime 与 NaT"]
    before = deepcopy(f["point"])
    result = assessment(f)
    assert len(cores(result)) == 1
    targets = [row for row in result["subtopic_coverage"] if row["id"].startswith("learning_target_")]
    assert [row["text"] for row in targets] == before["learning_targets"]
    assert all(row["status"] == "unknown" for row in targets)
    assert f["point"] == before


@pytest.mark.parametrize("foreign", ["numpy", "polars", "matplotlib", "scipy", "torch"])
def test_explicit_known_foreign_target_namespace_cannot_borrow_declared_tool_same_leaf(foreign):
    f = actual()
    f["point"]["learning_targets"] = [foreign + ".average(axis)"]
    set_title(f, "pandas.average 函数方法使用教程")
    set_body(f, "本课讲解 pandas.average 的使用。")
    assert not cores(assessment(f))


def test_rejected_foreign_target_does_not_hide_an_independent_owned_target():
    f = actual()
    f["point"]["learning_targets"] = ["numpy.average(axis)", "pandas.to_datetime(errors)"]
    result = assessment(f)
    assert [row["text"] for row in cores(result)] == ["pandas.to_datetime API 使用核心（参数未确认）"]
    assert all(row["status"] == "unknown" for row in result["subtopic_coverage"] if row["id"].startswith("learning_target_"))


def test_normal_jobservice_results_read_replay_places_core_only_in_partial_bucket():
    from backend.app.config import Settings
    from backend.app.read_rank_cache import ReadRankCache
    from backend.app.service import JobService
    f = actual()
    before = deepcopy(f)
    point = f["point"]
    request = SearchRequest(knowledge_points=[point["text"]], learning_targets={point["text"]: point["learning_targets"]}, student_level="advanced", language="zh")
    rid = f["resource"]["resource_id"]

    class ReadFixtureStore:
        def get_job(self, job_id):
            return {"request": request.model_dump(), "knowledge_points": [deepcopy(point)], "status": "completed", "warnings": []}
        def resources(self, job_id):
            return {rid: deepcopy(f["resource"])}
        def matches(self, job_id):
            return []
        def evidence(self, job_id, resource_id, point_id=None):
            assert resource_id == rid
            return deepcopy([row for row in f["evidence"] if point_id is None or row.get("kind") != "search" or row.get("knowledge_point_id") in {None, point_id}])
        def attempts(self, job_id):
            return []

    service = JobService.__new__(JobService)
    service.settings = Settings(max_results_per_point=5)
    service.store = ReadFixtureStore()
    service._read_rank_cache = ReadRankCache(ranker=ranking.rank_resource)
    group = service.results("offline-fixture")["groups"][0]
    assert group["total_matches"] == group["total_review_matches"] == 0
    assert group["total_partial_matches"] == len(group["partial_items"]) == 1
    assert list(group["partial_platform_items"]) == ["bilibili"]
    assert not group["items"] and not group["review_items"]
    assert group["collection_coverage"]["status"] == "unknown"
    assert len(group["collection_coverage"]["subtopics"]) == 8
    assert all(row["status"] == "unknown" for row in group["collection_coverage"]["subtopics"])
    assert len(cores(group["partial_items"][0]["match"])) == 1
    assert f == before


@pytest.mark.parametrize("field", ["video_evidence_status", "title"])
@pytest.mark.parametrize("property_name,value", [("source", "html.unbound.unknown_source"), ("url", "https://example.org/a-different-page")])
def test_r2_provenance_source_and_url_must_bind_to_the_own_observed_field(field, property_name, value):
    f = actual()
    f["resource"]["field_provenance"][field][property_name] = value
    assert not cores(assessment(f))


@pytest.mark.parametrize("change", ["empty_provenance", "empty_fact", "resource_search_discovered", "generic_og_video_proof"])
def test_r2_existing_verified_video_contract_and_nonempty_observation_required(change):
    f = actual()
    if change == "empty_provenance":
        f["resource"]["field_provenance"]["video_evidence_status"] = {}
    elif change == "empty_fact":
        for row in f["evidence"]:
            if row.get("field") == "video_evidence_status":
                row["text"] = "  "
    elif change == "resource_search_discovered":
        f["resource"]["video_evidence_status"] = "search_discovered"
    else:
        f["resource"]["field_provenance"]["video_evidence_status"]["source"] = "html.meta.og:type"
        for row in f["evidence"]:
            if row.get("field") == "video_evidence_status":
                row["source"] = "html.meta.og:type"
    assert not cores(assessment(f))


def test_r2_formal_observation_is_not_a_status_enum_and_actual_result_stays_unchanged():
    from backend.app.video_availability import _bound_page_video
    f = actual()
    video_row = next(row for row in f["evidence"] if row.get("field") == "video_evidence_status")
    assert video_row["text"].startswith("Observed same-BV video metadata")
    assert video_row["text"] != f["resource"]["video_evidence_status"]
    assert _bound_page_video(f["resource"], f["evidence"])
    assert len(cores(assessment(f))) == 1


@pytest.mark.parametrize("body", [
    "本视频不提供任何教学。",
    "This video does not teach anything.",
    "本视频仅演示效果。",
])
def test_whole_source_disclaimer_cannot_be_restored_by_supplemental_api_core(body):
    fixture = actual()
    set_body(fixture, body)
    before = deepcopy(fixture)
    point, resource, evidence = (fixture[k] for k in ("point", "resource", "evidence"))
    request = SearchRequest(knowledge_points=[point["text"]],
        learning_targets={point["text"]: point["learning_targets"]}, student_level="advanced", language="zh")
    assert not cores(assessment(fixture))
    assert ranking.rank_resource(point, resource, evidence, request) is None
    assert fixture == before
