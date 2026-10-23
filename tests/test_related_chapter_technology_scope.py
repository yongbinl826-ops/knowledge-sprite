"""Each cited chapter needs its own technology or an unambiguous parent.

The first fixture is a minimal retained v20 source observation, not invented
coverage. Other cases independently exercise the general inheritance boundary.
"""
from copy import deepcopy
import json

import pytest

from backend.app.models import SearchRequest
from backend.app.related_recommendations import chapter_can_inherit_technology, related_recommendation
from test_related_mechanism_boundaries import page_candidate


ACTUAL_URL = "https://www.bilibili.com/video/BV1jsohBdEUV/"
ACTUAL_CHAPTERS = [
    ("ev_2a7e552e-d254-441c-9bd9-51504b1986ac", 75, 1928,
     "74.最新 Langchain1.0 入门【17】langgraph 状态管理器 checkpointer 详细解析"),
    ("ev_c6a86366-5ece-44d6-884b-d239525b24ec", 54, 943,
     "53.streamlit状态存储session_state介绍"),
    ("ev_b6513fcb-1497-4eae-bd1a-c87ab5cd8704", 55, 885,
     "54.streamlit系统状态显示效果"),
]


def actual_observation():
    point = {"knowledge_point_id": "763f1e50-14d9-47f8-85a2-6f6bdd32d730",
             "text": "会话状态管理", "technology": "Streamlit"}
    resource = {"resource_id": "res_407ed6aa5ac20f03b6d84c33",
                "title": "【全748集】目前B站最全最细的AI大模型零基础全套教程，2026最新版，包含所有干货！七天就能从小白到大神！少走99%的弯路！存下吧！很难找全的！",
                "platform": "bilibili", "url": ACTUAL_URL, "canonical_url": ACTUAL_URL,
                "fetch_status": "fetched", "video_evidence_status": "page_verified",
                "resource_type": "video", "metadata_evidence_level": "catalog",
                "field_provenance": {"resource_type": {
                    "evidence_id": "ev_e5609914-33d8-447a-81de-534b0027759c", "source": "meta.og:type"}}}
    evidence = [{"evidence_id": "ev_e5609914-33d8-447a-81de-534b0027759c", "kind": "page",
                 "field": "resource_type", "source": "meta.og:type", "url": ACTUAL_URL, "text": "video"}]
    for eid, part, duration, title in ACTUAL_CHAPTERS:
        evidence.append({"evidence_id": eid, "kind": "catalog", "field": f"chapters.{part-1}",
                         "source": "html.bilibili.__INITIAL_STATE__.videoData.pages", "url": ACTUAL_URL,
                         "text": json.dumps({"duration_seconds": duration, "end_seconds": None,
                             "page_number": part, "source_url": ACTUAL_URL, "start_seconds": None,
                             "title": title, "url": f"{ACTUAL_URL}?p={part}"}, ensure_ascii=False),
                         "fetched_at": "2026-10-21T06:42:44.663222+00:00",
                         "cache": {"hit": False, "cached_at": None, "stale": False}})
    request = SearchRequest(knowledge_points=[point["text"]], topic_technologies={point["text"]: point["technology"]})
    return point, resource, evidence, request


def add_chapter(args, title, index=0):
    eid = f"chapter-{index}"
    args[2].append({"evidence_id": eid, "kind": "catalog", "field": f"chapters.{index}",
                    "source": "html.video.pages", "url": args[1]["canonical_url"],
                    "text": {"title": title, "page_number": index + 1,
                             "source_url": args[1]["canonical_url"],
                             "url": args[1]["canonical_url"] + f"?p={index+1}"}})
    return eid


def test_actual_mixed_course_keeps_streamlit_parts_without_langgraph_citation():
    args = actual_observation()
    before = deepcopy(args[:3])
    result = related_recommendation(*args)
    assert result
    assert set(result["reference"]["evidence_ids"]) == {chapter[0] for chapter in ACTUAL_CHAPTERS[1:]}
    assert result["reference"]["technical_context"] == "observed"
    assert result["reference"]["exact_teaching_verified"] is False
    assert args[:3] == before


def test_actual_langgraph_part_alone_does_not_supply_streamlit_context():
    point, resource, evidence, request = actual_observation()
    assert related_recommendation(point, resource, evidence[:2], request) is None


@pytest.mark.parametrize("wrong_title", ["LangGraph 状态管理", "Redis 会话状态管理", "会话状态管理"])
def test_uncertain_earlier_part_cannot_borrow_later_parts_framework(wrong_title):
    args = page_candidate("会话状态管理", "Streamlit", "多技术视频课程")
    wrong = add_chapter(args, wrong_title, 0)
    right = add_chapter(args, "Streamlit 会话状态管理", 9)
    result = related_recommendation(*args)
    assert result
    assert right in result["reference"]["evidence_ids"]
    assert wrong not in result["reference"]["evidence_ids"]


def test_own_unambiguous_course_title_supplies_unnamed_chapters_framework():
    args = page_candidate("会话状态管理", "Streamlit", "Streamlit 视频课程")
    chapter = add_chapter(args, "会话状态管理")
    result = related_recommendation(*args)
    assert {chapter, "own-title"} <= set(result["reference"]["evidence_ids"])


@pytest.mark.parametrize("title", [
    "Flet 会话状态管理", "Gradio 会话状态管理", "LangGraph 状态管理",
    "Redis 会话状态管理", "NovaGraph framework 会话状态管理", "Redis.get() 会话状态管理",
])
def test_own_course_context_never_overrides_explicit_competing_chapter(title):
    args = page_candidate("会话状态管理", "Streamlit", "Streamlit 视频课程")
    add_chapter(args, title)
    assert related_recommendation(*args) is None


@pytest.mark.parametrize("title", ["LangGraph 状态管理", "Redis 会话状态管理", "NovaGraph 框架会话状态管理"])
def test_declared_parent_never_overrides_explicit_other_chapter_owner(title):
    args = page_candidate("会话状态管理", "Streamlit", "课程章节")
    add_chapter(args, title)
    parent = "https://www.bilibili.com/video/BV1WKH7zZEEw/"
    args[1]["parent_course_url"] = parent
    args[2].append({"evidence_id": "parent", "kind": "page", "field": "title", "source": "html.title",
                    "url": parent, "text": "Streamlit 视频课程"})
    assert related_recommendation(*args) is None


@pytest.mark.parametrize("title", [
    "1. LangGraph 状态管理", "第2讲 Redis 会话状态管理", "[3] NovaGraph library 会话状态管理",
    "Redis.get() 会话状态管理", "redis.get 会话状态管理",
])
def test_numbered_or_namespaced_other_technology_cannot_inherit(title):
    assert not chapter_can_inherit_technology("Streamlit", title)


@pytest.mark.parametrize("title", [
    "Session state management", "Input widgets and form values", "Retry strategies",
    "Exponential backoff", "Recursion basics", "Download Button", "Downloading Zip Files from AWS S3",
    "export PDF files", "Email Form Using Python", "contact form", "template replacement",
    "self.get() 状态管理", "cls.from_dict() 数据加载", "retry.wait() 调用",
])
def test_unknown_ordinary_english_or_generic_api_is_not_an_external_framework(title):
    assert chapter_can_inherit_technology("Streamlit", title)


@pytest.mark.parametrize("technology,title", [
    ("Pydantic", "BaseModel 字段约束"), ("Python", "ChatPromptTemplate 提示词模板"),
    ("Python", "ThreadPoolExecutor concurrent calls"), ("pandas", "DataFrame methods"),
    ("Python", "RetryPolicy configuration"), ("Streamlit", "NovaGraph 状态管理"),
])
def test_unknown_class_or_api_identifier_alone_is_not_a_framework_declaration(technology, title):
    assert chapter_can_inherit_technology(technology, title)


def test_explicit_cross_library_use_and_host_language_foundations_remain_eligible():
    args = page_candidate("会话状态管理", "Streamlit", "Streamlit 视频课程")
    chapter = add_chapter(args, "Redis 与 Streamlit 会话状态管理")
    assert chapter in related_recommendation(*args)["reference"]["evidence_ids"]
    args = page_candidate("列表增删遍历", "Streamlit", "Streamlit 视频课程")
    chapter = add_chapter(args, "Python list operations")
    assert chapter in related_recommendation(*args)["reference"]["evidence_ids"]


@pytest.mark.parametrize("title", ["LangGraph 状态管理", "Redis 会话状态管理", "Redis.get() 会话状态管理"])
def test_grounded_sources_exclude_other_framework_chapter_before_review(title):
    from backend.app import grounded_related as grounded
    from test_grounded_related_review import case, indexed_chapter

    args = case(topic="会话状态管理", technology="Streamlit", title="Streamlit 视频课程", description="课程介绍")
    wrong = indexed_chapter(args[1], args[2], title)
    right = indexed_chapter(args[1], args[2], "会话状态管理")
    pair = grounded.prepare_pair(*args)
    ids = {source["evidence_id"] for source in pair["sources"]}
    assert wrong["evidence_id"] not in ids
    assert right["evidence_id"] in ids


@pytest.mark.parametrize("title", ["Session state management", "Retry strategies", "Exponential backoff", "Recursion basics"])
def test_grounded_generic_english_chapter_still_inherits_course_context(title):
    from backend.app import grounded_related as grounded
    from test_grounded_related_review import case, indexed_chapter

    args = case(topic=title, technology="Python", title="Python 视频课程", description="课程介绍")
    chapter = indexed_chapter(args[1], args[2], title)
    pair = grounded.prepare_pair(*args)
    source = next(source for source in pair["sources"] if source["evidence_id"] == chapter["evidence_id"])
    assert source["technology_context"] == "Python 视频课程"


@pytest.mark.parametrize("title", ["LangGraph 状态管理", "Redis 会话状态管理"])
def test_old_positive_seal_cannot_bypass_current_chapter_context(monkeypatch, title):
    from backend.app import grounded_related as grounded, related_recommendations as related
    from test_grounded_related_review import case, indexed_chapter, reviewed

    args = case(topic="会话状态管理", technology="Streamlit", title="Streamlit 视频课程", description="课程介绍")
    indexed_chapter(args[1], args[2], title)
    with monkeypatch.context() as old_policy:
        old_policy.setattr(related, "chapter_can_inherit_technology", lambda *_: True)
        pair = grounded.prepare_pair(*args)
        # Offline fake verdicts reproduce a seal created under the old policy.
        sealed, calls = reviewed(old_policy, pair, basis="catalog")
        assert sealed and len(calls) == 2
        assert grounded.project_reference(*args, sealed)
    assert grounded.project_reference(*args, sealed) is None
    assert related_recommendation(*args, grounded_decision=sealed) is None


@pytest.mark.parametrize("parent_title,expected", [("Streamlit 视频课程", True), ("Streamlit 和 Flet 视频课程", False)])
def test_declared_parent_course_can_supply_unnamed_chapter_context(parent_title, expected):
    args = page_candidate("会话状态管理", "Streamlit", "课程章节")
    chapter = add_chapter(args, "会话状态管理")
    parent = "https://www.bilibili.com/video/BV1WKH7zZEEw/"
    args[1]["parent_course_url"] = parent
    args[2].append({"evidence_id": "parent", "kind": "page", "field": "title", "source": "html.title",
                    "url": parent, "text": parent_title})
    result = related_recommendation(*args)
    assert bool(result) is expected
    if result:
        assert {chapter, "parent"} <= set(result["reference"]["evidence_ids"])
        assert result["reference"]["technical_context"] == "parent_course"


def test_mixed_own_course_title_does_not_supply_generic_chapter_context():
    args = page_candidate("会话状态管理", "Streamlit", "Streamlit 和 Flet 视频课程")
    wrong = add_chapter(args, "会话状态管理", 0)
    right = add_chapter(args, "Streamlit 会话状态管理", 1)
    result = related_recommendation(*args)
    assert right in result["reference"]["evidence_ids"]
    assert wrong not in result["reference"]["evidence_ids"]


def test_valid_own_page_proof_remains_while_unqualified_chapter_is_removed():
    args = page_candidate("会话状态管理", "Streamlit", "多技术视频课程", "Streamlit 会话状态管理")
    wrong = add_chapter(args, "LangGraph 状态管理")
    result = related_recommendation(*args)
    assert "own-description" in result["reference"]["evidence_ids"]
    assert wrong not in result["reference"]["evidence_ids"]
    assert result["reference"]["basis"] == ["page"]


def test_query_without_technology_does_not_require_chapter_framework():
    point, resource, evidence, _ = page_candidate("会话状态管理", "Streamlit", "多技术视频课程")
    point.pop("technology")
    args = point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])
    chapter = add_chapter(args, "会话状态管理")
    result = related_recommendation(*args)
    assert chapter in result["reference"]["evidence_ids"]


def test_parent_context_on_different_url_cannot_rescue_generic_chapter():
    args = page_candidate("会话状态管理", "Streamlit", "课程章节")
    add_chapter(args, "会话状态管理")
    args[1]["parent_course_url"] = "https://www.bilibili.com/video/BV1WKH7zZEEw/"
    args[2].append({"evidence_id": "foreign", "kind": "page", "field": "title", "source": "html.title",
                    "url": "https://example.com/another-course", "text": "Streamlit 视频课程"})
    assert related_recommendation(*args) is None
