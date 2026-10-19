"""Source-scoped nonteaching/audience statements, retained real r8 replay."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.ranking import learner_fit, rank_resource, _whole_source_non_teaching
from tests.test_source_scope import lesson


FIXTURE = Path(__file__).parent / "fixtures/source_scope_r9/streamlit-rerun-runtime-r8.json"
UNKNOWN = (0, " 学习门槛未由来源明确确认，请先看课程简介。")


def test_actual_r8_summary_adds_only_confirmed_rerun_and_keeps_audience_unknown():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    before = deepcopy(data)
    result = rank_resource(data["point"], data["resource"], data["evidence"], SearchRequest.model_validate(data["request"]))
    assert result and result["topic_evidence_status"] == "partial"
    rows = {row["id"]: row for row in result["subtopic_coverage"]}
    assert rows["subtopic_2"]["status"] == rows["learning_target_2"]["status"] == "supported"
    assert rows["learning_target_2"]["text"] == "脚本重运行"
    assert all(row["status"] == "unknown" for key, row in rows.items() if key not in {"subtopic_2", "learning_target_2"})
    assert "来源标注为高级" not in result["recommendation_reason"]
    assert "学习门槛未由来源明确确认" in result["recommendation_reason"]
    assert data == before


@pytest.mark.parametrize("description", [
    "4. 高级应用架构与集成。构建多页面应用程序。",
    "模块内容：高级DataFrames与编辑器。",
    "Topics: advanced application architecture and integration.",
    "Chapter 4: Advanced API usage. Chapter 5: Expert tools.",
    "支持初学者示例数据，也展示高级图表；未说明课程受众。",
    "没有要求入门知识；学习门槛仍未说明。",
    "4.高级课程介绍：主要演示窗口布局。",
])
def test_description_topic_words_do_not_declare_course_entry_level(description):
    assert learner_fit("intermediate", "Streamlit 数据应用课程", description) == UNKNOWN


@pytest.mark.parametrize("description,student,expected", [
    ("本课程面向初学者。", "beginner", 8),
    ("适合零基础学员。", "beginner", 8),
    ("课程难度：中级。", "intermediate", 8),
    ("目标受众：高级开发者。", "beginner", -18),
    ("A course designed for beginners.", "beginner", 8),
    ("Course level: advanced.", "beginner", -18),
    ("An intermediate-level course.", "intermediate", 8),
    ("pandas 入门课程：学习读取CSV文件。", "advanced", -8),
])
def test_explicit_audience_difficulty_or_course_level_is_preserved(description, student, expected):
    assert learner_fit(student, "Streamlit 数据应用课程", description)[0] == expected


@pytest.mark.parametrize("title,description", [
    ("Pygame 入门到高级", ""),
    ("Data course", "适合初学者。课程难度：高级。"),
    ("Data course", "Beginner course; advanced course."),
    ("Data course", "not intended for beginners"),
])
def test_mixed_or_negative_audience_cannot_be_invented_as_single_positive_fit(title, description):
    assert learner_fit("intermediate", title, description) == UNKNOWN


def assess(description, *, title="Streamlit 课程", target="脚本重运行"):
    resource, evidence = lesson(title, description=description)
    point = {"knowledge_point_id": "point", "text": "Streamlit 文件上传与脚本重运行", "learning_targets": [target]}
    result = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    rows = {row["id"]: row for row in result["subtopic_coverage"]} if result else {}
    return rows.get("learning_target_1", {"status": "unknown"})["status"]


@pytest.mark.parametrize("unrelated", [
    "学员无需HTML/CSS/JavaScript知识。",
    "本课不讲SQL数据库。",
    "先修要求：Python 列表。",
    "Next lesson: PostgreSQL indexes.",
    "API list: SQLAlchemy symbols.",
])
def test_other_subject_disclaimer_cannot_retract_explicit_own_target(unrelated):
    assert assess("Streamlit 用户交互触发脚本重运行。" + unrelated) == "supported"


@pytest.mark.parametrize("body", [
    "本课不讲Streamlit脚本重运行。",
    "Streamlit does not teach 脚本重运行。",
    "Streamlit not cover 脚本重运行。",
    "Prerequisites: Streamlit 脚本重运行。",
    "TODO: Streamlit 脚本重运行。",
    "Future lesson: Streamlit 脚本重运行。",
    "Next lesson: Streamlit 脚本重运行。",
    "API list: Streamlit 脚本重运行。",
    "本课只提及Streamlit脚本重运行。",
])
def test_target_bound_negation_prerequisite_future_or_reference_still_blocks(body):
    assert assess(body, title="Streamlit 脚本重运行教程") == "unknown"


@pytest.mark.parametrize("disclaimer", [
    "本视频不提供任何教学。",
    "本课不是教程。",
    "本视频仅演示效果。",
    "This video is not a tutorial.",
    "This lesson provides no instruction.",
    "This video does not teach anything.",
    "This video is a demo only.",
    "Not a tutorial.",
])
def test_explicit_whole_source_disclaimer_blocks_even_with_literal_target(disclaimer):
    body = disclaimer + "Streamlit 用户交互触发脚本重运行。"
    assert _whole_source_non_teaching("Streamlit 课程", body)
    assert assess(body) == "unknown"


@pytest.mark.parametrize("heading", ["API list", "Prerequisites", "Next lesson", "TODO", "先修要求"])
def test_standalone_document_or_raw_section_label_is_not_current_teaching(heading):
    body = heading + ":\nStreamlit 脚本重运行。"
    assert assess(body) == "unknown"


def test_related_tail_and_wrong_tool_still_cannot_supply_target():
    assert assess("本课介绍Streamlit窗口布局。相关视频：Streamlit脚本重运行。") == "unknown"
    assert assess("Django 脚本重运行教程。", title="Django教程") == "unknown"
