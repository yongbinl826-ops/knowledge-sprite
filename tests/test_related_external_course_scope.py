"""External whole-course claims do not become this video's own instruction."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import grounded_related as grounded
from backend.app.models import SearchRequest
from backend.app.ranking import own_resource_snippet, own_video_description
from backend.app.related_recommendations import related_recommendation
from test_grounded_related_review import case, reviewed


def advert(topic="Python 集合差集比对", url="https://course.example/full-download"):
    return f"下载地址：{url} 本教程时长：4小时13分，共24个章节。完整课程学习内容：{topic}。"


def video_args(description, *, topic="集合差集比对", technology="Python", title="Python 视频介绍"):
    args = case(topic=topic, technology=technology, title=title, description=description)
    args[1]["chapters"] = [{"title": title, "duration_seconds": 207}]
    return args


def actual():
    data = json.loads((Path(__file__).parent / "fixtures/external-course-own-scope-actual.json").read_text(encoding="utf-8"))
    return data["point"], data["resource"], data["evidence"], SearchRequest.model_validate(data["request"])


def test_retained_actual_external_whole_course_no_longer_supplies_chat_completion_claim():
    args = actual()
    before = deepcopy(args[:3])
    assert len(args[1]["chapters"]) == 1 and args[1]["chapters"][0]["duration_seconds"] == 207
    assert own_resource_snippet(args[1]["description"]) == args[1]["description"]
    assert own_video_description(args[1], args[1]["description"]) == ""
    assert related_recommendation(*args) is None
    assert args[:3] == before


@pytest.mark.parametrize("topic,technology,url", [
    ("集合差集比对", "Python", "https://lessons.example/complete-course"),
    ("状态管理", "React", "https://archive.example/course.zip"),
    ("对话补全接口调用", "OpenAI API", "https://other.example/training"),
])
def test_foreign_course_block_is_scoped_without_domain_or_topic_rules(topic, technology, url):
    args = video_args(advert(technology + " " + topic, url), topic=topic, technology=technology,
                      title=technology + " 视频介绍")
    before = deepcopy(args[:3])
    assert own_video_description(args[1], args[1]["description"]) == ""
    assert related_recommendation(*args) is None
    assert args[:3] == before


@pytest.mark.parametrize("position", ["before", "after"])
def test_current_video_statement_remains_a_real_contiguous_source_before_or_after_advert(position):
    own = "本视频讲解 Python 集合差集比对。"
    description = own + "\n" + advert() if position == "before" else advert() + "\n" + own
    args = video_args(description)
    projected = own_video_description(args[1], description)
    assert projected == own and projected in description
    result = related_recommendation(*args)
    assert result and "own-description" in result["reference"]["evidence_ids"]
    pair = grounded.prepare_pair(*args)
    source = next(s for s in pair["sources"] if s["basis"] == "description")
    assert source["_projected"] == own


@pytest.mark.parametrize("label", ["源码下载地址", "源代码下载链接", "代码下载地址", "课件下载地址", "资料下载地址", "数据集下载地址"])
def test_supplementary_material_download_does_not_reassign_current_teaching(label):
    description = f"本视频讲解 Python 集合差集比对。{label}：https://files.example/source.zip 本课程时长：4小时13分，共24个章节。"
    args = video_args(description)
    assert own_video_description(args[1], description) == description
    assert related_recommendation(*args)


@pytest.mark.parametrize("change", ["no-download", "no-duration", "unknown-runtime", "full-video", "multi-part", "course-resource"])
def test_a_link_runtime_or_chapter_count_alone_cannot_exclude_description(change):
    args = video_args(advert())
    r = args[1]
    text = r["description"]
    if change == "no-download": text = text.replace("下载地址：https://course.example/full-download ", "")
    elif change == "no-duration": text = text.replace("时长：4小时13分，", "")
    elif change == "unknown-runtime": r["chapters"][0].pop("duration_seconds")
    elif change == "full-video": r["chapters"][0]["duration_seconds"] = 4 * 3600 + 13 * 60
    elif change == "multi-part": r["chapters"] = [{"duration_seconds": 600, "title": str(i)} for i in range(24)]
    else: r["resource_type"] = "course"
    assert own_video_description(r, text) == text


def test_bare_external_documentation_link_stays_available():
    text = "本视频讲解 Python 集合差集比对。参考文档：https://docs.example/sets。"
    args = video_args(text)
    assert own_video_description(args[1], text) == text
    assert related_recommendation(*args)


def test_english_whole_course_advert_and_written_time_precision():
    text = "Full course link: https://courses.example/archive Duration: 2 hours 40 minutes, 12 chapters. Python set difference."
    args = video_args(text)
    assert own_video_description(args[1], text) == ""
    args[1]["chapters"][0]["duration_seconds"] = 2 * 3600 + 39 * 60 + 59
    assert own_video_description(args[1], text) == text


def test_own_title_can_independently_support_topic_even_when_description_is_external():
    args = video_args(advert("JavaScript event handling"), title="Python 集合差集比对")
    result = related_recommendation(*args)
    assert result and "own-title" in result["reference"]["evidence_ids"]
    assert "own-description" not in result["reference"]["evidence_ids"]


def test_external_description_cannot_donate_technology_to_generic_own_title():
    args = video_args(advert(), title="集合差集比对")
    assert related_recommendation(*args) is None


def test_old_review_seal_rebinds_without_external_course_claim(monkeypatch):
    args = video_args(advert())
    with monkeypatch.context() as old_scope:
        old_scope.setattr(grounded, "own_video_description", lambda resource, text: own_resource_snippet(text))
        pair = grounded.prepare_pair(*args)
        sealed, calls = reviewed(old_scope, pair, quote="Python 集合差集比对")
        assert sealed and len(calls) == 2
        assert grounded.project_reference(*args, sealed)
    assert grounded.project_reference(*args, sealed) is None
    assert related_recommendation(*args, grounded_decision=sealed) is None
