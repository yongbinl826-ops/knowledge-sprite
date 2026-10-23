"""Mechanism qualifiers and source-bound technology, without full-course proof."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation
from test_related_recommendations import candidate


def page_candidate(name, technology, title, description="", *, search_title=None):
    point, resource, evidence, request = candidate(
        search_title or title, name=name, technology=technology)
    resource.update(title=title, fetch_status="fetched", video_evidence_status="page_verified")
    evidence.append({"evidence_id": "own-title", "kind": "page", "field": "title",
                     "source": "html.title", "url": resource["canonical_url"], "text": title})
    if description:
        evidence.append({"evidence_id": "own-description", "kind": "page", "field": "description",
                         "source": "html.description", "url": resource["canonical_url"], "text": description})
    return point, resource, evidence, request


@pytest.mark.parametrize("name,technology,title,expected", [
    ("跨字段业务规则校验", "Pydantic", "Pydantic Field 字段校验规则", False),
    ("跨字段业务规则校验", "Pydantic", "Pydantic field_validator 单字段校验", False),
    ("跨字段业务规则校验", "Pydantic", "Pydantic 跨字段验证 model_validator", True),
    ("跨字段业务规则校验", "Pydantic", "Pydantic @model_validator(mode='after')", True),
    ("跨字段业务规则校验", "Pydantic", "Pydantic @root_validator", True),
    ("跨字段业务规则校验", "Pydantic", "Pydantic cross-field validation", True),
    ("跨字段业务规则校验", "Pydantic", "Pydantic my_model_validator_helper", False),
    ("跨字段业务规则校验", "Pydantic", "Pydantic root_validator is not covered", False),
    ("多字段联合验证", "JavaScript", "JavaScript cross-field validation", True),
    ("多字段联合验证", "JavaScript", "JavaScript 单字段验证", False),
    ("字段校验", "Pydantic", "Pydantic Field 字段校验规则", True),
    ("异步事件处理", "Python", "Python 同步事件处理", False),
    ("异步事件处理", "Python", "Python asyncio 事件处理", True),
    ("异步事件处理", "Python", "Python asyncio 环境安装", False),
    ("同步事件处理", "Python", "Python 异步事件处理", False),
    ("异步请求处理", "JavaScript", "JavaScript await 请求处理", True),
    ("异步请求处理", "JavaScript", "JavaScript 同步请求处理", False),
    ("矩形碰撞检测", "pygame", "Pygame 碰撞检测", True),
    ("CSV 文件导出与下载", "Streamlit", "Streamlit download buttons", True),
])
def test_distinguishing_qualifier_cannot_be_replaced_by_suffix_overlap(name, technology, title, expected):
    args = page_candidate(name, technology, title)
    before = deepcopy(args[:3])
    result = related_recommendation(*args)
    assert bool(result) is expected
    assert args[:3] == before
    if result:
        assert result["reference"]["exact_teaching_verified"] is False


@pytest.mark.parametrize("name,technology,title,expected", [
    ("参数化提示词模板", "Python", "Python LangChain PromptTemplate", True),
    ("参数化提示词模板", "Python", "Python ChatPromptTemplate.from_template", True),
    ("参数化提示词模板", "Python", "Python prompt templates", True),
    ("参数化提示词模板", "Python", "Python Jinja2 templates", False),
    ("参数化提示词模板", "Python", "Python myPromptTemplate_helper", False),
    ("参数化提示词模板", "Python", "Python PromptTemplate is not covered", False),
    ("对话补全接口调用", "OpenAI API", "OpenAI Chat Completions", True),
    ("对话补全接口调用", "OpenAI API", "OpenAI client.chat.completions.create", True),
    ("对话补全接口调用", "OpenAI API", "OpenAI ChatCompletion.create", True),
    ("对话补全接口调用", "OpenAI API", "OpenAI responses.create", False),
    ("对话补全接口调用", "OpenAI API", "OpenAI Chat Completions is not covered", False),
])
def test_mechanism_aliases_are_general_terms_not_project_answers(name, technology, title, expected):
    result = related_recommendation(*page_candidate(name, technology, title))
    assert bool(result) is expected
    if result:
        assert result["reference"]["technical_context"] == "observed"
        assert result["reference"]["exact_teaching_verified"] is False


@pytest.mark.parametrize("title", ["会话状态管理", "Flask 会话状态管理"])
def test_read_page_cannot_borrow_technology_from_search_excerpt(title):
    args = page_candidate("会话状态管理", "Streamlit", title, search_title="Streamlit 会话状态管理")
    assert related_recommendation(*args) is None


def test_search_only_reference_with_observed_technology_remains_a_lead():
    result = related_recommendation(*candidate("Streamlit 会话状态管理", name="会话状态管理", technology="Streamlit"))
    assert result["reference"]["technical_context"] == "observed"
    assert result["reference"]["basis"] == ["search"]


def test_declared_technology_without_any_source_context_is_not_recommended():
    assert related_recommendation(*candidate("会话状态管理", name="会话状态管理", technology="Streamlit")) is None


@pytest.mark.parametrize("title,description", [
    ("Streamlit 视频课程", "会话状态管理"),
    ("会话状态管理", "使用 Streamlit 进行开发"),
])
def test_own_page_fields_can_jointly_supply_topic_and_technology(title, description):
    result = related_recommendation(*page_candidate("会话状态管理", "Streamlit", title, description))
    assert result["reference"]["technical_context"] == "observed"
    assert {"own-title", "own-description"} <= set(result["reference"]["evidence_ids"])


@pytest.mark.parametrize("mode", ["foreign", "missing-source", "mixed", "stale"])
def test_unqualified_context_donor_cannot_fill_page_technology(mode):
    args = page_candidate("会话状态管理", "Streamlit", "会话状态管理", "Streamlit 视频课程")
    donor = args[2][-1]
    if mode == "foreign":
        donor["url"] = "https://example.com/another-course"
    elif mode == "missing-source":
        donor["source"] = ""
    elif mode == "mixed":
        donor["text"] = "Streamlit 和 Flet 视频课程"
    else:
        donor["cache"] = {"stale": True}
    assert related_recommendation(*args) is None


def test_safe_python_library_context_is_recorded_as_observed():
    result = related_recommendation(*page_candidate("列表增删遍历", "Python", "Pygame list operations"))
    assert result["reference"]["technical_context"] == "observed"


def test_declared_parent_must_be_bound_unambiguous_and_sourced():
    args = page_candidate("会话状态管理", "Streamlit", "会话状态管理")
    parent = "https://www.bilibili.com/video/BV1WKH7zZEEw/"
    args[1]["parent_course_url"] = parent
    row = {"evidence_id": "parent", "kind": "page", "field": "title", "source": "html.title",
           "url": parent, "text": "Streamlit 视频课程"}
    args[2].append(row)
    assert related_recommendation(*args)["reference"]["technical_context"] == "parent_course"
    row["text"] = "Streamlit 和 Flet 视频课程"
    assert related_recommendation(*args) is None
    row.update(text="Streamlit 视频课程", source="")
    assert related_recommendation(*args) is None


def test_topic_without_declared_technology_keeps_loose_relevance():
    point, resource, evidence, _ = page_candidate("会话状态管理", "Streamlit", "会话状态管理")
    point.pop("technology")
    request = SearchRequest(knowledge_points=[point["text"]])
    result = related_recommendation(point, resource, evidence, request)
    assert result and result["reference"]["exact_teaching_verified"] is False


def test_sibling_chapter_never_donates_its_technology():
    args = page_candidate("会话状态管理", "Streamlit", "Python 多框架视频课程")
    for index, title in enumerate(["Streamlit 图表展示", "会话状态管理"]):
        args[2].append({"evidence_id": f"chapter-{index}", "kind": "catalog", "field": f"chapters.{index}",
                        "source": "html.video.pages", "url": args[1]["canonical_url"], "text": {"title": title}})
    assert related_recommendation(*args) is None
