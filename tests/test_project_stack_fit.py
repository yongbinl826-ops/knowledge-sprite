"""Relocatable, offline admission tests; retained synthetic-input own evidence."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
from backend.app import ranking
from backend.app.learning_support import summarize_learning_support
from backend.app.models import SearchRequest

FIXTURE = Path(__file__).parent / "fixtures" / "project_stack_fit.json"


def fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = json.dumps({"prior_own_lesson": data["prior_own_lesson"], "live": data["live"]},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(payload).hexdigest() == data["payload_canonical_sha256"]
    return data


def own_rows(pool, resource):
    urls = {ranking.normalize_url(resource[k]) for k in ("url", "canonical_url", "resolved_url") if resource.get(k)}
    return [row for row in pool["evidence"] if ranking.normalize_url(row["url"]) in urls]


def arduino():
    data = fixture()["live"]["arduino-real"]
    resource = next(row for row in data["pool"]["resources"] if "CubeMX" in row.get("description", ""))
    return deepcopy((data["job"], resource, own_rows(data["pool"], resource)))


def set_field(resource, evidence, field, value):
    resource[field] = value
    row = next(row for row in evidence if row["evidence_id"] == resource["field_provenance"][field]["evidence_id"])
    row["text"] = value


def rank(job, resource, evidence, **kwargs):
    return ranking.rank_resource(job["knowledge_points"][0], resource, evidence,
        SearchRequest.model_validate(job["request"]), eligibility_evidence=evidence, **kwargs)


def test_actual_same_point_Uno_context_keeps_Arduino_but_quarantines_CubeMX():
    data = fixture()["live"]["arduino-real"]
    before = deepcopy(data)
    for resource in data["pool"]["resources"]:
        evidence = own_rows(data["pool"], resource)
        match = rank(data["job"], resource, evidence)
        assert match and match["supporting_evidence_ids"]
        if "CubeMX" in resource.get("description", ""):
            assert match["topic_evidence_status"] == "needs_review"
            assert "project_stack_mismatch" in match["topic_match_rules"]
            assert "跨技术栈迁移" in match["recommendation_reason"]
            reason = next(r for r in match["topic_evidence_reasons"] if r["code"] == "project_stack_mismatch")
            assert reason["evidence_ids"] == [resource["field_provenance"]["description"]["evidence_id"]]
            assert "与当前学习阶段相符" not in match["recommendation_reason"]
        else:
            assert match["topic_evidence_status"] == "supported"
            assert "project_stack_mismatch" not in match["topic_match_rules"]
        assert resource["url"].startswith("https://www.bilibili.com/video/")
        # No claim of a stable-time-window algorithm or Uno-specific code.
        assert "已支持millis" not in match["recommendation_reason"]
    assert data == before


@pytest.mark.parametrize("context", ["使用 Arduino 学习按键消抖。板型尚未指定。", "学习按键消抖的通用原理。", ""])
def test_no_explicit_board_or_no_project_stack_does_not_invent_conflict(context):
    job, resource, evidence = arduino()
    job["request"]["project_context"] = context
    assert rank(job, resource, evidence)["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("description", [
    "本课按键消抖与松手检测。", "Mixly 按键消抖与松手检测，适用Arduino。",
    "Arduino Core 按键消抖与松手检测，不使用CubeMX。",
    "适用Arduino Uno，另有STM32对照。",
    "本课按键消抖与松手检测，不使用CubeMX。",
    "本课按键消抖与松手检测，之后会讲CubeMX。",
    "本课按键消抖与松手检测；其他课程使用STM32。",
    "本课按键消抖与松手检测；先修：CubeMX基础。",
    "本课按键消抖与松手检测；CubeMX is not used。",
    "本课按键消抖与松手检测。相关视频：STM32按键消抖教程",
])
def test_generic_compatible_negative_future_related_are_not_conflicts(description):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", description)
    match = rank(job, resource, evidence)
    assert match and match["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("stack", ["CubeMX", "STM32F103", "ESP32", "C51", "8051", "FPGA", "Verilog"])
def test_explicit_alternative_board_implementation_is_reference_only(stack):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", f"本课{stack}按键消抖与松手检测。")
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


@pytest.mark.parametrize("mutation", ["origin_url", "row_url", "row_text", "row_source", "origin_source", "search_only"])
def test_foreign_or_broken_scalar_proof_cannot_supply_stack_conflict(mutation):
    job, resource, evidence = arduino()
    origin = resource["field_provenance"]["description"]
    row = next(row for row in evidence if row["evidence_id"] == origin["evidence_id"])
    if mutation == "origin_url": origin["url"] = "https://www.bilibili.com/video/BV1otherPage/"
    elif mutation == "row_url": row["url"] = "https://www.bilibili.com/video/BV1otherPage/"
    elif mutation == "row_text": row["text"] = "另一个页面"
    elif mutation == "row_source": row["source"] = "foreign.source"
    elif mutation == "origin_source": origin["source"] = "search"
    else: row["kind"] = "search"
    match = rank(job, resource, evidence)
    assert match and match["topic_evidence_status"] == "supported"


def prior():
    data = fixture()["prior_own_lesson"]
    job = {"request": data["case"]["request"], "knowledge_points": [data["case"]["product_results"]["groups"][0]]}
    return deepcopy((job, data["row"]["projected_resource"], data["row"]["all_evidence"]))


def test_actual_Vue_own_lesson_is_related_but_not_main_for_explicit_native_web():
    job, resource, evidence = prior()
    match = rank(job, resource, evidence)
    assert match and match["topic_evidence_status"] == "needs_review"
    assert "Vue" in match["recommendation_reason"]
    assert "跨技术栈迁移" in match["recommendation_reason"]
    parts = {"".join(p["text"].split()): p for p in match["subtopic_coverage"]}
    assert parts["读写"]["status"] == "unknown"
    assert parts["JSON序列化"]["status"] == "supported"  # source fact preserved; not counted as fit
    summary = ranking.summarize_collection_coverage(job["knowledge_points"][0]["text"],
        [{"resource": resource, "match": match, "evidence": evidence}])
    assert summary["status"] == "unknown"
    assert not summary["single_resource_full_coverage"]
    assert all(not p["resource_ids"] for p in summary["subtopics"])


@pytest.mark.parametrize("context", ["使用JavaScript做本地存储演示。", "已会Vue，但本项目用什么框架尚未决定。", ""])
def test_framework_course_is_not_conflict_without_explicit_no_framework_requirement(context):
    job, resource, evidence = prior()
    job["request"]["project_context"] = context
    assert rank(job, resource, evidence)["topic_evidence_status"] == "partial"


def test_explicit_independent_native_chapter_in_framework_course_is_not_mechanically_blocked():
    job, resource, evidence = prior()
    heading = "本节只用原生JavaScript，不依赖框架：localStorage存储、JSON.stringify"
    chapter = resource["chapters"][0]
    chapter["title"] = heading
    next(e for e in evidence if e["evidence_id"] == chapter["evidence_id"])["text"] = heading
    assert rank(job, resource, evidence)["topic_evidence_status"] == "partial"


def test_search_only_alternative_stack_does_not_contaminate_own_generic_lesson():
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", "本课按键消抖与松手检测。")
    evidence.append({"evidence_id": "search-stack", "kind": "search", "source": "search", "url": resource["url"],
                     "title": "STM32 CubeMX 按键消抖与松手检测", "snippet": "ESP32教程", "knowledge_point_id": job["knowledge_points"][0]["knowledge_point_id"]})
    assert rank(job, resource, evidence)["topic_evidence_status"] == "supported"


def test_prefetch_ordering_does_not_apply_display_only_fit_gate():
    job, resource, evidence = arduino()
    assert rank(job, resource, evidence, require_type=False)["topic_evidence_status"] == "supported"


def test_actual_new_JS_zero_and_pandas_own_positive_unchanged():
    data = fixture()["live"]
    for resource in data["js-recovery-real-API"]["pool"]["resources"]:
        rows = own_rows(data["js-recovery-real-API"]["pool"], resource)
        assert rank(data["js-recovery-real-API"]["job"], resource, rows) is None
    sample = data["pandas-success-control-real"]
    resource = sample["pool"]["resources"][0]
    match = rank(sample["job"], resource, own_rows(sample["pool"], resource))
    assert match and match["topic_evidence_status"] == "supported"


def test_cross_stack_reference_cannot_enter_legacy_skill_coverage():
    # Existing learning_support admission already excludes needs_review. Keep
    # this invariant without reintroducing legacy skills into professional jobs.
    point = {"knowledge_point_id": "p", "learning_skills": ["按键消抖"]}
    item = {"resource": {"resource_id": "r"},
        "match": {"knowledge_point_id": "p", "resource_id": "r", "topic_evidence_status": "partial", "teaching_support": [{
            "skill_id": "skill_1", "skill": "按键消抖", "basis": "title", "evidence_id": "e", "quote": "按键消抖",
            "source_text_sha256": hashlib.sha256("按键消抖".encode()).hexdigest()}]},
        "evidence": [{"evidence_id": "e", "kind": "page", "text": "按键消抖"}]}
    assert summarize_learning_support(point, [item])["skills"][0]["title_resource_ids"] == ["r"]
    item["match"]["topic_evidence_status"] = "needs_review"
    result = summarize_learning_support(point, [item])
    assert all(not row["content_resource_ids"] and not row["title_resource_ids"] for row in result["skills"])


def complementary(heading, rid):
    job, resource, evidence = prior()
    resource["resource_id"] = rid
    set_field(resource, evidence, "title", "原生JavaScript本地存储教程")
    set_field(resource, evidence, "description", "本课演示原生JavaScript本地存储。")
    chapter = resource["chapters"][0]
    chapter["title"] = heading
    next(e for e in evidence if e["evidence_id"] == chapter["evidence_id"])["text"] = heading
    return job, resource, evidence


def test_separate_genuine_IO_and_JSON_lessons_collectively_cover_without_one_full_claim():
    name = prior()[0]["knowledge_points"][0]["text"]
    items = []
    for heading, rid in [("JavaScript localStorage读写：getItem读取、setItem写入", "io"),
                         ("JavaScript localStorage存储、JSON.stringify", "json")]:
        job, resource, evidence = complementary(heading, rid)
        match = rank(job, resource, evidence)
        assert match and match["topic_evidence_status"] == "partial"
        items.append({"resource": resource, "match": match, "evidence": evidence})
    summary = ranking.summarize_collection_coverage(name, items)
    assert summary["status"] == "all_subtopics_supported"
    assert not summary["single_resource_full_coverage"]
    assert {rid for p in summary["subtopics"] for rid in p["resource_ids"]} == {"io", "json"}
    assert len(summary["subtopics"]) == 2
    assert "互补" in summary["disclaimer"]


def test_complementary_resources_cannot_fill_IO_from_search_or_JSON_parse():
    job, resource, evidence = complementary("localStorage存储、JSON.parse", "parse")
    evidence.append({"evidence_id": "query", "kind": "search", "source": "search", "url": resource["url"],
        "title": "localStorage读写与JSON序列化", "snippet": "localStorage.getItem setItem JSON.stringify",
        "knowledge_point_id": job["knowledge_points"][0]["knowledge_point_id"]})
    match = rank(job, resource, evidence)
    assert match is None


@pytest.mark.parametrize("description", [
    "本课STM32按键消抖与松手检测，不兼容Uno。",
    "本课CubeMX按键消抖与松手检测，不能用于Arduino Uno。",
    "本课CubeMX按键消抖与松手检测；其他课程使用Arduino Core。",
])
def test_denied_or_foreign_compatibility_cannot_cancel_real_stack_conflict(description):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", description)
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


@pytest.mark.parametrize("mutation", ["row_url", "row_source", "row_title", "search_kind"])
def test_unbound_catalog_heading_cannot_establish_stack_conflict(mutation):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", "本课按键消抖与松手检测。")
    chapter = resource["chapters"][0]
    chapter["title"] = "CubeMX按键消抖与松手检测"
    row = next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])
    row["text"] = chapter["title"]
    if mutation == "row_url": row["url"] = "https://www.bilibili.com/video/BV1otherPage/"
    elif mutation == "row_source": row["source"] = "foreign.source"
    elif mutation == "row_title": row["text"] = "按键消抖与松手检测"
    else: row["kind"] = "search"
    assert rank(job, resource, evidence)["topic_evidence_status"] == "supported"


def test_actual_source_heading_can_supply_conflict_without_a_description():
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", "本课按键消抖与松手检测。")
    chapter = resource["chapters"][0]
    chapter["title"] = "CubeMX按键消抖与松手检测"
    row = next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])
    record = json.loads(row["text"])
    record["title"] = chapter["title"]
    row["text"] = json.dumps(record, ensure_ascii=False)
    match = rank(job, resource, evidence)
    assert match["topic_evidence_status"] == "needs_review"
    reason = next(r for r in match["topic_evidence_reasons"] if r["code"] == "project_stack_mismatch")
    assert reason["evidence_ids"] == [row["evidence_id"]]


@pytest.mark.parametrize("description", [
    "使用STM32CubeMX实现按键消抖状态检测，板上提供Arduino Uno兼容连接器。",
    "使用STM32CubeMX实现按键消抖状态检测，Arduino Uno仅作接口对照。",
])
def test_connector_or_interface_comparison_is_not_same_implementation_compatibility(description):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", description)
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


@pytest.mark.parametrize("heading", ["Arduino Uno接口兼容性对照", "本节Arduino Core按键教程", "本节适用Arduino Uno"])
def test_unrelated_chapter_cannot_cancel_real_CubeMX_implementation(heading):
    job, resource, evidence = arduino()
    chapter = resource["chapters"][0]
    chapter["title"] = heading
    next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])["text"] = heading
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


@pytest.mark.parametrize("description", [
    "使用Arduino Core演示按键消抖与松手检测。",
    "适用Arduino Uno并展示STM32按键消抖与松手检测。",
])
def test_explicit_same_implementation_compatibility_stays_eligible(description):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", description)
    assert rank(job, resource, evidence)["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("role", [
    "Arduino Core是先修要求", "Arduino Core prerequisite", "Arduino Core is a prerequisite",
    "Arduino Core作为先修", "Arduino Core仅作参考", "Arduino Core作为对照",
])
def test_postposed_prerequisite_or_reference_does_not_donate_implementation_owner(role):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", role + "，本课使用CubeMX实现按键消抖状态检测。")
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


@pytest.mark.parametrize("description", [
    "Arduino Core 按键消抖与松手检测，展示ESP32。",
    "使用Arduino Core在ESP32演示按键消抖与松手检测。",
    "Arduino Core，本课使用CubeMX实现按键消抖状态检测。",
    "适用Arduino Uno。下一实施示例使用CubeMX进行按键消抖与松手检测。",
])
def test_language_or_previous_applicability_cannot_resolve_selected_board_conflict(description):
    job, resource, evidence = arduino()
    set_field(resource, evidence, "description", description)
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"


def test_unrelated_native_chapter_cannot_make_Vue_lesson_independent_for_current_target():
    job, resource, evidence = prior()
    extra = {**resource["chapters"][0], "title": "本节只用原生JavaScript，绘制CSS圆形。", "evidence_id": "extra-native"}
    resource["chapters"].append(extra)
    original = next(row for row in evidence if row["evidence_id"] == resource["chapters"][0]["evidence_id"])
    evidence.append({**original, "evidence_id": "extra-native", "text": extra["title"], "field": "chapters.24"})
    assert rank(job, resource, evidence)["topic_evidence_status"] == "needs_review"
