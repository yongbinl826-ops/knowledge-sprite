"""Related references need actual Chinese topic text, never a query echo."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation
from test_related_recommendations import candidate


@pytest.mark.parametrize("name,body,expected", [
    ("Streamlit 交互控件", "系统教授丰富UI组件（按钮、滑块、表单）的使用与布局控制。", True),
    ("Streamlit 交互控件", "用户输入控件：按钮、滑块与表单", True),
    ("Streamlit 交互控件", "交互式图表的创建", False),
    ("Streamlit 交互控件", "不包含用户输入控件。", False),
    ("Streamlit 图表展示", "教授如何创建交互式图表。", True),
    ("Streamlit 图表展示", "使用Streamlit进行数据可视化", True),
    ("Streamlit 图表展示", "创建柱状图、交互式条形图。", True),
    ("Streamlit 图表展示", "st.bar_chart提供了简单易用的接口。", True),
    ("Streamlit 图表展示", "使用st.bar_chart提供简单接口。", True),
    ("Streamlit 图表展示", "myst.bar_chart_other仅是一个变量。", False),
    ("Streamlit 图表展示", "常用Streamlit绘制流程示意图。", False),
    ("Streamlit 图表展示", "不讲数据可视化。", False),
    ("CSV 文件导出与下载", "交互式UI组件、图表和数据库集成", False),
])
def test_chinese_streamlit_topics_are_separate(name, body, expected):
    result = related_recommendation(*candidate("Streamlit课程", body, name=name, technology="Streamlit"))
    assert bool(result) is expected
    if result:
        assert result["reference"]["exact_teaching_verified"] is False


@pytest.mark.parametrize("name", ["Streamlit 交互控件", "Streamlit 图表展示"])
def test_retained_native_description_supports_related_reference(name):
    path = Path(__file__).parent / "fixtures/source_scope_r9/streamlit-rerun-runtime-r8.json"
    fixture = json.loads(path.read_text("utf-8"))
    resource, evidence = deepcopy(fixture["resource"]), deepcopy(fixture["evidence"])
    original = deepcopy((resource, evidence))
    point = {"knowledge_point_id": "new-student-point", "text": name, "technology": "Streamlit"}
    request = SearchRequest(knowledge_points=[name], topic_technologies={name: "Streamlit"})
    result = related_recommendation(point, resource, evidence, request)
    assert result
    assert result["reference"]["exact_teaching_verified"] is False
    assert "ev_e6b875f9-66bf-4636-9d4f-afb0632338e0" in result["reference"]["evidence_ids"]
    assert result["resource"]["canonical_url"] == "https://www.bilibili.com/video/BV1DoFDzjEY6/"
    assert (resource, evidence) == original


def test_query_and_foreign_description_cannot_supply_chinese_topic():
    point, resource, evidence, request = candidate("Streamlit课程", name="Streamlit 交互控件", technology="Streamlit")
    evidence[0]["query"] = "Streamlit 用户输入控件 UI组件"
    assert related_recommendation(point, resource, evidence, request) is None
    evidence.append({"evidence_id": "foreign", "kind": "page", "field": "description",
                     "source": "html.description", "url": "https://example.org/other",
                     "text": "Streamlit用户输入控件 UI组件"})
    assert related_recommendation(point, resource, evidence, request) is None


@pytest.mark.parametrize("chapter_url,field,body,expected", [
    ("own", "chapters.2", "用户输入控件", True),
    ("own", "chapters.2", "程序发布与部署", False),
    ("foreign", "chapters.2", "用户输入控件", False),
    ("own", "chapters.related", "用户输入控件", False),
])
def test_indexed_own_chapter_uses_bound_course_context(chapter_url, field, body, expected):
    point, resource, evidence, request = candidate("Streamlit课程", name="Streamlit 交互控件", technology="Streamlit")
    own = resource["canonical_url"]
    evidence.extend([
        {"evidence_id": "own-title", "kind": "page", "field": "title", "source": "html.title",
         "url": own, "text": "Streamlit课程"},
        {"evidence_id": "own-chapter", "kind": "catalog", "field": field, "source": "html.video.pages",
         "url": own if chapter_url == "own" else "https://example.org/other",
         "text": {"title": body, "url": own+"?p=3", "source_url": own}},
    ])
    result = related_recommendation(point, resource, evidence, request)
    assert bool(result) is expected
    if result:
        assert {"own-title", "own-chapter"} <= set(result["reference"]["evidence_ids"])
        assert result["reference"]["exact_teaching_verified"] is False
