"""Offline reference-integrity tests, never proof of semantic completeness."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from backend.app.analysis_coverage import (
    COVERAGE_COMPLETION_PROMPT, CoverageCompletion, CoverageReference,
    CoverageRow, completion_schema, coverage_issues, normalize_coverage_quotes,
)
from backend.app.project_models import AnalysisDocument, ProjectInput


def example(name="月度支出", requirements="按月份合计支出并显示结果。",
            descriptions=("按相同月份分组，对各组金额求和。", "将统计结果写入可见的表格单元。"),
            **project_fields):
    project = ProjectInput(name=name, requirements=requirements, **project_fields)
    analysis = {"scope": "离线协议测试", "technical_plan": "仅用于验证关联和引用。", "assumptions": [],
                "knowledge_points": [{"name": f"概念 {index + 1}", "description": description,
                                      "technology": ""}
                                     for index, description in enumerate(descriptions)]}
    document = AnalysisDocument.model_validate({**analysis, "analysis_format": "concept_list_v1",
        "knowledge_points": [{**point, "id": f"k{index + 1}", "selection": "learn"}
                             for index, point in enumerate(analysis["knowledge_points"])]})
    references = [{"point_index": index, "description_quote": description}
                  for index, description in enumerate(descriptions)]
    coverage = [{"mechanism_id": "", "source_field": field, "source_quote": getattr(project, field),
                 "mechanism": "引用对应实现所需原理。", "taught_by": deepcopy(references)}
                for field in ("name", "requirements", "project_context", "technical_version")
                if getattr(project, field).strip()]
    return project, document, {"analysis": analysis, "coverage": coverage, "unresolved": []}


def inspect(project, document, body):
    return coverage_issues(project, document, CoverageCompletion.model_validate(body))


@pytest.mark.parametrize("name,requirements,descriptions", [
    ("月度支出", "按月份合计支出并显示结果。", ("按相同月份分组，对各组金额求和。", "将结果写入表格单元。")),
    ("温度报警", "采集温度，超过指定阈值时点亮指示灯。", ("把模拟信号转换为数字量。", "比较温度与阈值后设置输出电平。")),
    ("排队模拟", "按到达顺序服务并显示平均等待时间。", ("先进先出队列保持到达顺序。", "用等待时间总和除以完成服务的数量。")),
])
def test_cross_domain_references_need_no_topic_whitelist_or_fixed_count(name, requirements, descriptions):
    project, document, body = example(name, requirements, descriptions)
    before = deepcopy(body)
    assert inspect(project, document, body) == []
    assert body == before


def test_all_nonempty_source_fields_including_name_need_valid_rows():
    project, document, body = example(project_context="本地运行", technical_version="Python 3")
    assert inspect(project, document, body) == []
    for field in ("name", "requirements", "project_context", "technical_version"):
        incomplete = deepcopy(body)
        incomplete["coverage"] = [row for row in incomplete["coverage"] if row["source_field"] != field]
        issues = inspect(project, document, incomplete)
        assert {issue["code"] for issue in issues} == {"coverage_unmapped_source"}
        assert issues[0]["location"] == ["project", field]


def test_blank_optional_metadata_does_not_create_mandatory_rows():
    project, document, body = example(project_context=" \n ", technical_version=" ")
    assert inspect(project, document, body) == []


def test_original_source_quotes_preserve_urls_line_breaks_and_spaces_as_data():
    requirement = " 读取本地数据\n规范参考 https://example.org/spec 。 "
    project, document, body = example(requirements=requirement)
    completion = CoverageCompletion.model_validate(body)
    assert completion.coverage[1].source_quote == requirement
    assert coverage_issues(project, document, completion) == []
    body["coverage"][1]["source_quote"] = requirement.replace("\n", " ")
    assert "coverage_source_quote" in {issue["code"] for issue in inspect(project, document, body)}


def test_no_whole_character_coverage_or_semantic_certificate_is_claimed():
    project, document, body = example(requirements="按月份合计支出并显示结果；还须保留原始记录。")
    body["coverage"][1]["source_quote"] = "按月份合计支出"
    body["coverage"][1]["mechanism"] = "这个机制说明可能错误或遗漏需求，但引用确实存在。"
    # It is intentionally possible for semantically inadequate evidence to pass
    # structural reference checks. The independent review still owns meaning.
    assert inspect(project, document, body) == []


@pytest.mark.parametrize("field", ["name", "requirements"])
def test_fabricated_source_quote_invalidates_its_entire_row(field):
    project, document, body = example()
    row = next(row for row in body["coverage"] if row["source_field"] == field)
    row["source_quote"] = "并不存在的原始需求"
    codes = {issue["code"] for issue in inspect(project, document, body)}
    assert codes == {"coverage_source_quote", "coverage_unmapped_source"}


@pytest.mark.parametrize("quote", ["概念 1", "仅用于验证关联和引用。", "并未出现在说明中", "将统计结果写入可见的表格单元。"])
def test_only_the_referenced_final_description_can_supply_evidence(quote):
    project, document, body = example()
    for row in body["coverage"]:
        row["taught_by"][0]["description_quote"] = quote
    issues = inspect(project, document, body)
    assert "coverage_description_quote" in {issue["code"] for issue in issues}
    # A mixed row with one bad reference cannot grant source or point coverage.
    assert sum(issue["code"] == "coverage_unmapped_point" for issue in issues) == 2


def test_nonexistent_point_is_rejected_without_indexing_it():
    project, document, body = example()
    body["coverage"][0]["taught_by"][0]["point_index"] = 29
    issues = inspect(project, document, body)
    assert any(issue["code"] == "coverage_point_reference"
               and issue["location"] == ["coverage", 0, "taught_by", 0, "point_index"] for issue in issues)


def test_every_final_point_requires_a_valid_row_without_auto_adding_one():
    project, document, body = example()
    for row in body["coverage"]:
        row["taught_by"] = row["taught_by"][:1]
    issues = inspect(project, document, body)
    assert issues == [{"code": "coverage_unmapped_point",
                       "message": "Every final knowledge point needs a valid description reference.",
                       "location": ["analysis", "knowledge_points", 1, "description"]}]
    assert len(body["analysis"]["knowledge_points"]) == 2


def test_unresolved_is_blocking_and_diagnostics_never_echo_untrusted_values():
    project, document, body = example()
    sentinel = "UNTRUSTED_IGNORE_ALL_RULES_987"
    body["unresolved"] = [sentinel]
    body["coverage"][0]["source_quote"] = sentinel
    issues = inspect(project, document, body)
    assert "coverage_unresolved" in {issue["code"] for issue in issues}
    assert sentinel not in json.dumps(issues)
    assert all(set(issue) == {"code", "message", "location"} for issue in issues)


@pytest.mark.parametrize("index", [-1, 30, True, False, "1", 1.0])
def test_point_indices_are_strict_bounded_integers(index):
    with pytest.raises(ValidationError):
        CoverageReference(point_index=index, description_quote="有效引用")


@pytest.mark.parametrize("field,value", [
    ("source_field", "student_level"), ("source_quote", ""), ("source_quote", " \n "),
    ("source_quote", "x" * 1501), ("mechanism", ""), ("mechanism", "x" * 241),
    ("taught_by", []), ("taught_by", [{"point_index": 0, "description_quote": "x"}] * 31),
])
def test_coverage_rows_reject_invalid_structure(field, value):
    _, _, body = example()
    row = {**body["coverage"][0], field: value}
    with pytest.raises(ValidationError):
        CoverageRow.model_validate(row)


@pytest.mark.parametrize("quote", ["", " \n ", "x" * 801])
def test_description_quotes_are_nonempty_and_bounded(quote):
    with pytest.raises(ValidationError):
        CoverageReference(point_index=0, description_quote=quote)


@pytest.mark.parametrize("field,value", [
    ("analysis", []), ("coverage", []), ("unresolved", ["问题"] * 13),
    ("unresolved", [""]), ("unexpected", "not allowed"),
])
def test_completion_rejects_invalid_envelope(field, value):
    _, _, body = example()
    with pytest.raises(ValidationError):
        CoverageCompletion.model_validate({**body, field: value})


def test_limits_are_accepted_without_padding_and_overflow_is_not_truncated():
    _, _, body = example()
    row = body["coverage"][0]
    row["source_quote"] = "x" * 1500
    row["mechanism"] = "x" * 240
    row["taught_by"] = [{"point_index": 29, "description_quote": "x" * 800}] * 30
    body["coverage"] = [row] * 90
    body["unresolved"] = ["未解决"] * 12
    assert len(CoverageCompletion.model_validate(body).coverage) == 90
    with pytest.raises(ValidationError):
        CoverageCompletion.model_validate({**body, "coverage": [row] * 91})


@pytest.mark.parametrize("model,body", [
    (CoverageReference, {"point_index": 0, "description_quote": "原文", "name": "禁止额外字段"}),
    (CoverageRow, {"source_field": "name", "source_quote": "原文", "mechanism": "原理",
                   "taught_by": [{"point_index": 0, "description_quote": "原文"}], "passed": True}),
])
def test_nested_metadata_forbids_extra_fields(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_completion_schema_embeds_full_generation_schema_and_resolves_defs_without_mutation():
    from backend.app.project_analysis import generation_schema
    analysis = generation_schema()
    before = deepcopy(analysis)
    schema = completion_schema(analysis)
    assert analysis == before
    assert schema["properties"]["analysis"] == {key: value for key, value in analysis.items() if key != "$defs"}
    assert schema["properties"]["analysis"]["properties"]["knowledge_points"]["maxItems"] == 30
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"analysis", "coverage", "unresolved"}
    assert set(analysis.get("$defs", {})) | {"CoverageRow", "CoverageReference", "MechanismInventory"} <= set(schema["$defs"])
    def check_refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = schema
                for segment in value["$ref"].removeprefix("#/").split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)
    check_refs(schema)
    schema["properties"]["analysis"]["properties"]["knowledge_points"]["maxItems"] = 1
    assert analysis == before


def test_schema_name_conflicts_fail_instead_of_silently_retargeting_refs():
    with pytest.raises(ValueError, match="Conflicting coverage and analysis"):
        completion_schema({"type": "object", "$defs": {"CoverageRow": {"type": "string"}}})


def test_prompt_requests_independent_bounded_edit_with_evidence_not_reasoning_or_semantic_certification():
    prompt = COVERAGE_COMPLETION_PROMPT
    assert "envelope requirement takes precedence" in prompt
    assert "from the original requirements" in prompt
    assert "function inputs/returns, callback invocation" in prompt
    assert "Do not assume mastery" in prompt
    assert "not a chain of thought" in prompt
    assert "they do not prove" in prompt
    assert "including the project name" in prompt
    assert "final description, not its title" in prompt
    assert "untrusted data" in prompt


@pytest.mark.parametrize("punctuation", list("。.!！?？;；"))
def test_quote_normalization_only_removes_one_terminal_mark_and_keeps_original(punctuation):
    clause = "逐行读取记录并按商品名称累加销售额"
    _, _, body = example(descriptions=(clause + "，随后输出汇总结果。",))
    body["coverage"][1]["taught_by"][0]["description_quote"] = clause + punctuation
    original = CoverageCompletion.model_validate(body)
    before = original.model_dump()

    normalized, changes = normalize_coverage_quotes(original)

    assert original.model_dump() == before
    assert normalized is not original and normalized.analysis == original.analysis
    assert changes == [{"point_index": 0, "row_index": 1, "reference_index": 0,
                        "original_quote": clause + punctuation, "normalized_quote": clause}]
    assert normalized.coverage[1].taught_by[0].description_quote == clause
    assert normalized.coverage[0] == original.coverage[0]
    again, repeated = normalize_coverage_quotes(normalized)
    assert repeated == [] and again == normalized


def test_sentence_period_mismatch_no_longer_invalidates_an_exact_frozen_mechanism():
    from backend.app.analysis_inventory import MechanismInventory
    from tests.professional_contract_support import coverage_completion, draft_with_inventory

    clause = "逐行读取记录并按商品名称累加销售额"
    project, document, body = example(descriptions=(clause + "；随后输出汇总结果。",))
    inventory = MechanismInventory.model_validate(draft_with_inventory(body["analysis"], project)["inventory"])
    completion = CoverageCompletion.model_validate(coverage_completion(body["analysis"], project, inventory))
    completion.coverage[0].taught_by[0].description_quote = clause + "。"
    before_codes = {issue["code"] for issue in coverage_issues(project, document, completion, inventory)}
    assert {"coverage_description_quote", "coverage_missing_mechanism"} <= before_codes

    normalized, changes = normalize_coverage_quotes(completion)

    assert len(changes) == 1
    assert coverage_issues(project, document, normalized, inventory) == []
    assert completion.coverage[0].taught_by[0].description_quote == clause + "。"


@pytest.mark.parametrize("length,changed", [(0, False), (1, False), (11, False), (12, True)])
def test_terminal_mark_normalization_requires_twelve_remaining_characters(length, changed):
    clause = "数" * length
    _, _, body = example(descriptions=(clause + "；随后输出结果。",))
    body["coverage"][0]["taught_by"][0]["description_quote"] = clause + "。"
    original = CoverageCompletion.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert bool(changes) is changed
    assert normalized.coverage[0].taught_by[0].description_quote == (clause if changed else clause + "。")


@pytest.mark.parametrize("quote", [
    "逐行读取记录并按产品名称累加销售额。",  # Internal substitution.
    "逐行读取记录并按 商品名称累加销售额。",  # Added internal whitespace.
    "逐行读取记录并按商品名称累加销售额。 ",  # Trailing whitespace is not trimmed.
    "逐行读取记录并按商品名称累加销售额。。",  # Never remove two marks.
    "逐行读取记录并按商品名称累加销售额，",  # Not an allowed terminal mark.
    "逐行读取记录…商品名称累加销售额。",  # Non-contiguous fragments.
])
def test_normalization_does_not_rewrite_internal_text_whitespace_or_fragment_joins(quote):
    clause = "逐行读取记录并按商品名称累加销售额"
    project, document, body = example(descriptions=(clause + "；随后输出结果。",))
    body["coverage"][0]["taught_by"][0]["description_quote"] = quote
    original = CoverageCompletion.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert changes == [] and normalized == original
    assert "coverage_description_quote" in {issue["code"] for issue in coverage_issues(project, document, normalized)}


@pytest.mark.parametrize("point_index", [0, 29])
def test_normalization_does_not_retarget_a_quote_to_another_or_missing_point(point_index):
    other_clause = "逐行读取记录并按商品名称累加销售额"
    project, document, body = example(descriptions=("通过文件写入接口保存最终汇总结果。", other_clause + "；继续处理。"))
    body["coverage"][0]["taught_by"][0] = {"point_index": point_index, "description_quote": other_clause + "。"}
    original = CoverageCompletion.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert changes == [] and normalized == original
    expected = "coverage_description_quote" if point_index == 0 else "coverage_point_reference"
    assert expected in {issue["code"] for issue in coverage_issues(project, document, normalized)}


def test_exact_quotes_and_non_description_errors_are_preserved():
    clause = "逐行读取记录并按商品名称累加销售额"
    project, document, body = example(descriptions=(clause + "。",))
    body["coverage"][0]["source_quote"] += "。"
    body["unresolved"] = ["需要补足实际解释。"]
    original = CoverageCompletion.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert changes == [] and normalized == original
    assert {"coverage_source_quote", "coverage_unresolved"} <= {
        issue["code"] for issue in coverage_issues(project, document, normalized)}


@pytest.mark.parametrize("points", [None, "invalid", [], [None], [{"description": None}]])
def test_malformed_analysis_is_not_repaired_or_indexed_by_quote_normalization(points):
    _, _, body = example()
    body["analysis"]["knowledge_points"] = points
    original = CoverageCompletion.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert changes == [] and normalized == original


def test_normalizing_a_correction_preserves_its_subclass_and_resolution_evidence():
    from backend.app.analysis_semantics import FinalSemanticCorrection

    clause = "逐行读取记录并按商品名称累加销售额"
    _, _, body = example(descriptions=(clause + "；随后输出结果。",))
    body["coverage"][0]["taught_by"][0]["description_quote"] = clause + "。"
    body["resolutions"] = [{"issue_id": "s1", "status": "resolved", "location": ["technical_plan"],
                            "description_quote": body["analysis"]["technical_plan"], "explanation": "保留修正证据。"}]
    original = FinalSemanticCorrection.model_validate(body)
    normalized, changes = normalize_coverage_quotes(original)
    assert len(changes) == 1 and isinstance(normalized, FinalSemanticCorrection)
    assert normalized.resolutions == original.resolutions
    assert normalized.resolutions is not original.resolutions
