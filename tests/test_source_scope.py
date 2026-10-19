"""Offline source-scope regressions with five self-contained retained real resources."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path

import pytest

from backend.app import ranking, service, topic_operations as operations
from backend.app.models import SearchRequest
from tests.test_project_followup_matching import lesson
from tests.test_video_readiness import record


FIXTURES = Path(__file__).parent / "fixtures" / "source_scope"


def retained(name):
    row = json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
    for key in ("resource", "evidence"):
        value = json.dumps(row[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert hashlib.sha256(value).hexdigest() == row["origin"][key + "_sha256"]
    assert row["resource"]["resource_id"] == row["origin"]["resource_id"]
    assert [item["evidence_id"] for item in row["evidence"]] == row["origin"]["evidence_ids"]
    return row


def assess(text):
    return operations.assess_operation_fallback("pandas 清洗结果与汇总 CSV 导出及复核日志", [
        {"text": text, "evidence_ids": ["own-page"]}])


@pytest.mark.parametrize("text", [
    "【Python Pandas教程】4-读写CSV EXCEL文件",
    "Python Pandas Tutorial 4 - Read Write Excel CSV File",
    "pandas 写出CSV文件教程", "pandas 保存CSV文件示例", "pandas 导出CSV教程",
    "pandas CSV写出教程", "pandas DataFrame.to_csv('results.csv') 示例",
    "pandas to_csv(index=False) 用法",
])
def test_csv_write_is_only_a_partial_core_with_original_residual_unknown(text):
    result = assess(text)
    assert result and result["topic_evidence_status"] == "partial"
    core, residual = result["subtopic_coverage"]
    assert core["text"] == "pandas CSV 写出" and core["status"] == "supported"
    assert core["evidence_ids"] == ["own-page"]
    assert residual["status"] == "unknown" and residual["evidence_ids"] == []
    assert all(term in residual["text"] for term in ("清洗结果", "汇总", "复核日志"))


@pytest.mark.parametrize("text", [
    "pandas 读取CSV教程", "pandas read_csv('source.csv') 示例", "pandas CSV教程",
    "pandas 读取CSV并保存Excel", "pandas read CSV and write Excel file",
    "pandas 导出CSV到Excel", "pandas CSV导出Excel教程", "pandas 将CSV保存到Excel",
    "pandas 写出Excel文件", "pandas 写出CSV截图", "pandas Export JSON Tutorial",
    "pandas API列表 DataFrame.to_csv('results.csv')", "pandas DataFrame.to_csv API reference",
    "pandas 不讲导出CSV", "pandas 禁止保存CSV", "pandas never write CSV file",
    "pandas don't write CSV files", "pandas won't write CSV files", "pandas does not save CSV",
    "Prerequisites: pandas DataFrame.to_csv('results.csv')",
    "pandas 简介。写出CSV教程", "pandas 简介，polars 写出CSV教程",
    "pandas helper.to_csv('results.csv')", "pandas.to_csv('results.csv') 示例",
    "pandas https://example.org/write/CSV/tutorial",
])
def test_csv_output_never_borrows_input_reverse_direction_competing_owner_or_non_teaching(text):
    assert assess(text) is None


def test_csv_output_requires_same_own_observation_and_keeps_all_requested_concepts_unknown():
    point = {"knowledge_point_id": "point", "text": "pandas 清洗结果与汇总 CSV 导出及复核日志",
             "learning_targets": ["to_csv(index=False)", "复核计数链", "业务日志"]}
    resource, evidence = lesson("Python Pandas Tutorial 4 - Read Write Excel CSV File")
    before = deepcopy((resource, evidence))
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result["topic_evidence_status"] == "partial"
    by_text = {part["text"]: part for part in result["subtopic_coverage"]}
    assert by_text["pandas CSV 写出"]["status"] == "supported"
    assert all(by_text[target]["status"] == "unknown" for target in point["learning_targets"])
    assert (resource, evidence) == before
    assert operations.assess_operation_fallback(point["text"], [
        {"text": "pandas课程", "evidence_ids": ["owner"]},
        {"text": "写出CSV文件教程", "evidence_ids": ["action"]}]) is None


def test_previously_unimplemented_csv_request_gets_only_output_core_not_cleanup_or_logs():
    point = "pandas 清洗结果导出CSV与处理日志"
    plan = operations.operation_decomposition(point)
    assert plan["subtopics"] == [
        {"id": "operation_core", "text": "pandas CSV 写出"},
        {"id": "operation_qualification", "text": "清洗结果与处理日志"}]
    result = operations.assess_operation_fallback(point, [{"text": "pandas 读写CSV文件教程", "evidence_ids": ["csv"]}])
    assert result["topic_evidence_status"] == "partial"
    assert result["subtopic_coverage"][1]["status"] == "unknown"
    assert operations.operation_decomposition("pandas 清洗结果导出Parquet与处理日志") is None


@pytest.mark.parametrize("owner,title,allowed", [
    ("pandas", "Python pandas.to_datetime函数方法的使用", True),
    ("pandas", "PANDAS.DataFrame.to_csv函数用法", True),
    ("Matplotlib", "Pandas_Matplotlib完整教程", True),
    ("pandas", "PandasWrapper.to_datetime方法", False),
    ("pandas", "foo.pandas.to_datetime方法", False),
    ("pandas", "foo.pandas方法", False),
    ("pandas", "pandasx.to_datetime方法", False),
    ("pandas", "pandas-to_datetime方法", True),
])
def test_probe_exact_owner_namespace_is_admission_only(owner, title, allowed):
    assert service.JobService._probe_owner_in_title(owner, title) is allowed


def probe(title="Python pandas.to_datetime函数方法的使用", *, confirmed=True, started=0):
    point = {"knowledge_point_id": "p", "text": "pandas 日期列解析与无效行分离"}
    if confirmed:
        point["learning_targets"] = ["pd.to_datetime errors 参数"]
    resource, evidence = record(title)
    evidence[0]["query"] = "pandas pd.to_datetime errors 视频教程"
    state = {"gap_query_history": {"p": {evidence[0]["query"]}},
             "gap_probes_started": {"p": {str(i) for i in range(started)}}}
    return point, resource, evidence, state


def test_namespace_probe_preserves_point_executed_query_identity_type_and_caps():
    args = probe()
    assert service.JobService._targeted_catalog_probe(*args)
    assert service.JobService._gap_catalog_probe(*args)
    for mutation in ("wrong-point", "unexecuted-query", "no-type", "no-video"):
        point, resource, evidence, state = deepcopy(args)
        if mutation == "wrong-point": evidence[0]["knowledge_point_id"] = "other"
        if mutation == "unexecuted-query": evidence[0]["query"] = "not-executed"
        if mutation == "no-type": resource["resource_type"] = "unknown"
        if mutation == "no-video": resource["video_evidence_status"] = "none"
        assert not service.JobService._gap_catalog_probe(point, resource, evidence, state)
    for confirmed, started, gap, targeted in [(True, 2, True, False), (True, 4, False, False),
                                              (False, 1, True, True), (False, 2, False, False)]:
        args = probe(confirmed=confirmed, started=started)
        assert service.JobService._gap_catalog_probe(*args) is gap
        assert service.JobService._targeted_catalog_probe(*args) is targeted
    point, resource, evidence, _ = probe()
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result is None or all(part["status"] == "unknown" for part in result["subtopic_coverage"]
                                 if "errors" in part["text"])


@pytest.mark.parametrize("marker", ["相关视频：", "相关课程:", "相关推荐：", "Related videos:", "Recommended courses:"])
def test_own_page_tail_cannot_donate_a_topic_or_level(marker):
    description = "pandas CSV读取教程。" + marker + "pandas 数据去重零基础教程"
    resource, evidence = lesson("pandas 数据读取", description=description)
    before = deepcopy((resource, evidence))
    topic = {"knowledge_point_id": "point", "text": "pandas 数据去重"}
    assert ranking.rank_resource(topic, resource, evidence, SearchRequest(knowledge_points=[topic["text"]])) is None
    assert ranking.own_video_description(resource, description) == "pandas CSV读取教程。"
    assert ranking.learner_fit("advanced", "pandas 数据读取", ranking.own_video_description(resource, description)) == (0, " 学习门槛未由来源明确确认，请先看课程简介。")
    assert (resource, evidence) == before


def test_confirmed_target_only_in_related_tail_is_unknown_own_prefix_still_supported():
    point = {"knowledge_point_id": "point", "text": "pandas 读取客户 CSV 与审计日志",
             "learning_targets": ["pd.read_csv 参数", "DataFrame.drop_duplicates 用法"]}
    resource, evidence = lesson("pandas 读取CSV文件教程", description=
        "pandas.read_csv('input.csv') 示例。相关视频：pandas DataFrame.drop_duplicates(subset=['id']) 用法")
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result and result["topic_evidence_status"] == "partial"
    assert next(row for row in result["subtopic_coverage"] if row["text"] == "DataFrame.drop_duplicates 用法")["status"] == "unknown"
    assert "page_related_recommendations_excluded" in result["topic_match_rules"]
    assert "longer_course_outline_excluded_from_short_video" not in result["topic_match_rules"]


@pytest.mark.parametrize("tail", ["本课不讲pandas数据去重。", "先修要求：pandas 数据去重。", "TODO pandas 数据去重。"])
def test_related_negative_or_prerequisite_cannot_veto_a_complete_own_teaching_claim(tail):
    point = {"knowledge_point_id": "point", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas 数据去重教程", description="本课教pandas数据去重。相关视频：" + tail)
    original = deepcopy((resource, evidence))
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result and next(row for row in result["subtopic_coverage"] if row["id"] == "learning_target_1")["status"] == "supported"
    observations = ranking.topic_observations(point, resource, evidence)
    page = next(row for row in observations if row.get("field_evidence_ids", {}).get("body"))
    assert tail not in page["raw"] and "相关视频" not in page["raw"]
    assert (resource, evidence) == original


def test_projected_scoring_raw_keeps_own_urls_but_not_related_urls_without_breaking_full_field_binding():
    description = "pandas 数据去重教程 https://own.example.org/method。相关视频：https://other.example.org/extra"
    resource, evidence = lesson("pandas 数据去重教程", description=description)
    point = {"knowledge_point_id": "point", "text": "pandas 数据去重"}
    page = next(row for row in ranking.topic_observations(point, resource, evidence)
                if row.get("field_evidence_ids", {}).get("body"))
    assert "https://own.example.org/method" in page["raw"]
    assert "https://other.example.org/extra" not in page["raw"]
    assert "https://" not in page["body"] and page["field_evidence_ids"]["body"] == ["description"]
    assert resource["description"] == description == next(row["text"] for row in evidence if row.get("field") == "description")


@pytest.mark.parametrize("own", ["本课不讲pandas数据去重。", "先修要求：pandas 数据去重。", "TODO pandas 数据去重。"])
def test_own_negative_or_prerequisite_is_retained_and_never_excluded_as_related(own):
    point = {"knowledge_point_id": "point", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas 数据去重教程", description=own + "相关视频：其他课程。")
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result is None or next(row for row in result["subtopic_coverage"] if row["id"] == "learning_target_1")["status"] == "unknown"
    assert own in next(row for row in ranking.topic_observations(point, resource, evidence)
                       if row.get("field_evidence_ids", {}).get("body"))["raw"]


def test_ordinary_related_video_processing_prose_and_own_stage_are_preserved():
    text = "pandas 入门课程：相关视频处理所需的CSV读取教程。"
    resource, evidence = lesson("pandas课程", description=text)
    assert ranking.own_video_description(resource, text) == text
    assert ranking.learner_fit("advanced", resource["title"], text)[0] != 0
    assert ranking.source_scope_notice(resource, evidence) == ""


def test_global_advanced_tag_does_not_assume_familiarity_with_each_library():
    score, reason = ranking.learner_fit("advanced", "Matplotlib 零基础课程", "")
    assert score == -8  # Existing soft ordering is retained; no eligibility exclusion.
    assert "首次使用该技术可补基础" in reason and "已掌握可跳过" in reason
    assert "低于当前" not in reason


def test_longer_syllabus_guard_still_works_after_prefix_projection():
    resource = {"resource_type": "video", "duration_seconds": 600, "chapters": [{"title": "本课"}]}
    text = "本课简介。课程大纲 课时1 20:00 课时2 30:00 课时3 40:00。相关视频：其他课程"
    assert ranking.own_video_description(resource, text) == "本课简介。"
    resource["duration_seconds"] = 7200
    assert ranking.own_video_description(resource, text) == text.split("相关视频：")[0]


def test_scope_notice_only_uses_exact_own_bound_author_declaration():
    description = "该视频更多是自己自学过程中的分享而非教程。"
    resource, evidence = lesson("Matplotlib 绘制条形图示例", description=description)
    before = deepcopy((resource, evidence))
    assert "作者自述" in ranking.source_scope_notice(resource, evidence)
    assert (resource, evidence) == before
    for mutation in ("wrong-url", "changed-description", "search-source", "related-only", "other-video", "negative"):
        other_resource, other_evidence = deepcopy((resource, evidence))
        if mutation == "wrong-url": other_evidence[-1]["url"] = "https://other.example.org/lesson"
        if mutation == "changed-description": other_resource["description"] += "新字"
        if mutation == "search-source": other_evidence[-1]["kind"] = "search"
        if mutation in {"related-only", "other-video", "negative"}:
            changed = {"related-only": "本课完整教程。相关视频：" + description,
                       "other-video": "另一视频分享而非教程。本视频为完整系统教程。",
                       "negative": "该视频不是分享而非教程，是系统课程。"}[mutation]
            other_resource["description"] = other_evidence[-1]["text"] = changed
        assert ranking.source_scope_notice(other_resource, other_evidence) == ""



@pytest.mark.parametrize("name,core", [("csv_reader_related_tail", "pandas 读取 CSV"),
                                      ("group_count_related_tail", "pandas 分组计数")])
def test_retained_real_description_tail_does_not_label_own_stage(name, core):
    fixture = retained(name)
    resource, evidence, point = fixture["resource"], fixture["evidence"], fixture["point"]
    original = deepcopy((resource, evidence))
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]], **fixture["request"]))
    assert result and result["topic_evidence_status"] == "partial"
    assert "学习门槛未由来源明确确认" in result["recommendation_reason"]
    assert "来源标注为入门" not in result["recommendation_reason"] and "来源标注为进阶" not in result["recommendation_reason"]
    rows = {part["text"]: part for part in result["subtopic_coverage"]}
    assert rows[core]["status"] == "supported"
    assert all(rows[target]["status"] == "unknown" for target in point["learning_targets"])
    assert "page_related_recommendations_excluded" in result["topic_match_rules"]
    assert (resource, evidence) == original


def test_retained_real_self_learning_example_is_kept_with_truthful_scope_and_unknown_concepts():
    fixture = retained("self_learning_bar_example")
    resource, evidence, point = fixture["resource"], fixture["evidence"], fixture["point"]
    original = deepcopy((resource, evidence))
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]], **fixture["request"]))
    assert result and result["topic_evidence_status"] == "partial"
    assert "作者自述：分享或项目示例，非系统教程" in result["recommendation_reason"]
    by_text = {row["text"]: row for row in result["subtopic_coverage"]}
    assert all(by_text[target]["status"] == "unknown" for target in point["learning_targets"])
    assert (resource, evidence) == original


def test_retained_real_read_write_catalog_supports_csv_core_without_other_export_requirements():
    fixture = retained("csv_read_write_catalog")
    resource, evidence, point = fixture["resource"], fixture["evidence"], fixture["point"]
    original = deepcopy((resource, evidence))
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]], **fixture["request"]))
    assert result and result["topic_evidence_status"] == "partial"
    rows = {row["text"]: row for row in result["subtopic_coverage"]}
    assert rows["pandas CSV 写出"]["status"] == "supported"
    assert all(rows[target]["status"] == "unknown" for target in point["learning_targets"])
    assert (resource, evidence) == original


def test_retained_real_explicit_namespace_can_receive_bounded_probe_without_teaching_errors():
    fixture = retained("namespace_datetime_candidate")
    resource, evidence, point = fixture["resource"], fixture["evidence"], fixture["point"]
    state = {"gap_query_history": {point["knowledge_point_id"]: {evidence[0]["query"]}},
             "gap_probes_started": {point["knowledge_point_id"]: set()}}
    before = deepcopy((resource, evidence, state))
    assert resource["fetch_status"] == "not_fetched" and resource["video_evidence_status"] == "search_discovered"
    assert ranking.has_type_evidence(resource, evidence) and ranking.has_video_evidence(resource, evidence)
    assert service.JobService._targeted_catalog_probe(point, resource, evidence, state)
    assert service.JobService._gap_catalog_probe(point, resource, evidence, state)
    assert ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]], **fixture["request"])) is None
    assert (resource, evidence, state) == before
