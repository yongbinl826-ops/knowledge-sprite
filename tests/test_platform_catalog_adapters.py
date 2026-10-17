"""Real saved browser DOM replay plus labelled, synthetic boundary mutations.

No test fetches a page or verifies playback. The original captures are immutable.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from backend.app.extractor import MetadataExtractor
from backend.app.source_adapters.bilibili import part_duration_seconds
from backend.app.source_adapters.icourse163 import outline_duration_seconds


CAPTURES = Path(__file__).resolve().parents[1] / "reports/platform-catalog-20261017/browser"
BILIBILI = "https://www.bilibili.com/video/BV1VZ4y1G7YB/"
MOOC = "https://www.icourse163.org/course/PKU-1003479006"
AT = "2026-10-17T03:58:05.372Z"
HASHES = {
    "bilibili-dom.html": "bb146089cf493d9691223e436a9088b8f01b425e45a761af51c00696b303d58f",
    "mooc-dom.html": "369d4b630f1d6e37ced51c8eaf5f58d8893b0cbc94005fbe345cd61f9a12e374",
    "mooc-term-dom.html": "f6cda65c32614de79ebcb2edbd7572cb4123bb4d17a0451894f08193e89091a8",
}


def capture(name: str) -> str:
    raw = (CAPTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES[name], "Keep the original real browser capture unchanged"
    return raw.decode("utf-8")


def extract(markup: str, url: str) -> dict:
    return MetadataExtractor().extract(markup, url, AT)


def assert_individual_evidence(result: dict, source_url: str):
    evidence = {item["evidence_id"]: item for item in result["evidence"]}
    for index, chapter in enumerate(result["chapters"]):
        entry = evidence[chapter["evidence_id"]]
        assert entry["kind"] == "catalog"
        assert entry["field"] == f"chapters.{index}"
        assert entry["url"] == source_url
        assert entry["source"] == chapter["source"]
        assert json.loads(entry["text"]) == {key: chapter[key] for key in (
            "title", "url", "source_url", "start_seconds", "end_seconds", "duration_seconds"
        )}


def test_real_bilibili_capture_has_fifteen_ordered_parts_not_timeline_chapters():
    result = extract(capture("bilibili-dom.html"), BILIBILI)
    assert result["resource_type"] == "video"
    assert result["catalog_kind"] == "video_parts"
    assert result["title"] == "2020年最新Python零基础教程——第5章 列表、元组和字典"
    assert result["field_provenance"]["title"]["source"] == "html.bilibili.video_title"
    assert len(result["chapters"]) == 15
    assert [int(chapter["title"].split(".")[0]) for chapter in result["chapters"]] == list(range(1, 16))
    assert [chapter["duration_seconds"] for chapter in result["chapters"]] == [
        155, 261, 399, 764, 725, 736, 2317, 623, 486, 1127, 1790, 719, 399, 1016, 1192
    ]
    for chapter in result["chapters"]:
        assert chapter["url"] is None  # No href in the actual part nodes.
        assert chapter["start_seconds"] is None and chapter["end_seconds"] is None
    assert "duration_seconds" not in result  # Never sum durations into the current video's length.
    assert result["video_evidence_status"] == "page_verified"
    status = next(entry for entry in result["evidence"] if entry["field"] == "video_evidence_status")
    assert "playback was not tested" in status["text"]
    assert not result.get("playback_verified")
    assert_individual_evidence(result, BILIBILI)


@pytest.mark.parametrize("url", [
    "https://example.org/video/BV1VZ4y1G7YB/",
    "https://www.bilibili.com.evil.org/video/BV1VZ4y1G7YB/",
    "https://www.bilibili.com/read/cv1234/",
    "https://user:secret@www.bilibili.com/video/BV1VZ4y1G7YB/",
])
def test_bilibili_structure_is_not_promoted_on_another_host_or_route(url):
    result = extract(capture("bilibili-dom.html"), url)
    assert result["chapters"] == []
    assert result["video_evidence_status"] == "none"
    assert "resource_type" not in result


def test_bilibili_recommendations_outside_multipart_selector_do_not_join_catalog():
    soup = BeautifulSoup(capture("bilibili-dom.html"), "html.parser")
    recommendations = BeautifulSoup('''<aside class="recommend-list"><div class="video-pod__item">
      <div class="title-txt">Recommended unrelated video</div><div class="stats"><span class="duration">09:59</span></div>
      </div></aside>''', "html.parser")
    soup.body.append(recommendations)
    result = extract(str(soup), BILIBILI)
    assert len(result["chapters"]) == 15
    assert all("Recommended" not in item["title"] for item in result["chapters"])


def test_bilibili_wrong_selector_label_is_not_a_multipart_catalog():
    soup = BeautifulSoup(capture("bilibili-dom.html"), "html.parser")
    soup.select_one(".video-pod__header .title").string = "推荐视频"
    result = extract(str(soup), BILIBILI)
    assert result["chapters"] == []
    assert result["video_evidence_status"] == "none"


def test_bilibili_missing_title_is_skipped_and_missing_duration_stays_unknown():
    soup = BeautifulSoup(capture("bilibili-dom.html"), "html.parser")
    parts = soup.select(".video-pod__list.multip > .video-pod__item")
    parts[0].select_one(".title").decompose()
    parts[1].select_one(".duration").decompose()
    parts[2].select_one(".duration").string = "unknown"
    result = extract(str(soup), BILIBILI)
    assert len(result["chapters"]) == 14
    assert result["chapters"][0]["title"] == "2. 为什么需要列表"
    assert result["chapters"][0]["duration_seconds"] is None
    assert result["chapters"][1]["duration_seconds"] is None
    assert_individual_evidence(result, BILIBILI)


def test_bilibili_hidden_part_is_not_visible_catalog_evidence():
    soup = BeautifulSoup(capture("bilibili-dom.html"), "html.parser")
    soup.select_one(".multip > .video-pod__item")["hidden"] = ""
    result = extract(str(soup), BILIBILI)
    assert len(result["chapters"]) == 14
    assert result["chapters"][0]["title"] == "2. 为什么需要列表"


@pytest.mark.parametrize(("value", "expected"), [
    ("02:35", 155), ("1:02:03", 3723), ("00:00", None), ("1:60", None),
    ("-1:30", None), ("NaN", None), ("直播", None), (None, None), ("9", None),
])
def test_bilibili_duration_grammar(value, expected):
    assert part_duration_seconds(value) == expected


def test_real_mooc_capture_is_text_curriculum_and_preserves_nonvideo_entries():
    result = extract(capture("mooc-dom.html"), MOOC)
    assert result["resource_type"] == "course"
    assert result["catalog_kind"] == "course_outline"
    assert result["video_evidence_status"] == "none"
    assert not result.get("playback_verified")
    assert "本课基于主讲教师在北京大学" in result["description"]
    assert "spContent=" not in result["description"]
    assert len(result["chapters"]) == 84
    titles = [item["title"] for item in result["chapters"]]
    assert [int(re.match(r"课程(\d+)", title)[1]) for title in titles if re.match(r"课程\d+", title)] == list(range(1, 58))
    assert sum(bool(re.match(r"[一二三四五六七八九十]+、", title)) for title in titles) == 9
    assert sum(title.startswith("视频教程：") for title in titles) == 2
    assert sum("测验" in title or "作业" in title for title in titles if title.startswith("章节")) == 16
    assert sum(item["duration_seconds"] is not None for item in result["chapters"]) == 41
    assert all(item["url"] is None and item["start_seconds"] is None and item["end_seconds"] is None for item in result["chapters"])
    assert "duration_seconds" not in result
    assert_individual_evidence(result, MOOC)


@pytest.mark.parametrize("url", [
    "https://example.org/course/PKU-1003479006",
    "https://icourse163.org.evil.org/course/PKU-1003479006",
    "https://www.icourse163.org/learn/PKU-1003479006",
    "https://www.icourse163.org/course/not-a-course",
])
def test_mooc_structure_requires_exact_host_and_course_route(url):
    result = extract(capture("mooc-dom.html"), url)
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_empty_mooc_outline_keeps_course_but_does_not_invent_a_catalog():
    soup = BeautifulSoup(capture("mooc-dom.html"), "html.parser")
    soup.select_one("#j-course-outline").clear()
    result = extract(str(soup), MOOC)
    assert result["resource_type"] == "course"
    assert result["chapters"] == []
    assert "catalog_kind" not in result
    assert result["metadata_evidence_level"] == "page"
    assert result["video_evidence_status"] == "none"


def test_mooc_unrelated_text_and_recommended_links_do_not_enter_outline():
    soup = BeautifulSoup(capture("mooc-dom.html"), "html.parser")
    unrelated = BeautifulSoup('''<div class="f-richEditorText"><p>推荐课程 Other topic (45min)</p>
      <a href="/course/OTHER-123">Other course</a></div>''', "html.parser")
    soup.body.append(unrelated)
    result = extract(str(soup), MOOC)
    assert len(result["chapters"]) == 84
    assert all("Other" not in item["title"] for item in result["chapters"])


def test_mooc_outline_without_course_introduction_is_not_promoted():
    soup = BeautifulSoup(capture("mooc-dom.html"), "html.parser")
    soup.select_one("#j-course-heading-intro").decompose()
    result = extract(str(soup), MOOC)
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_real_mooc_same_page_term_notice_coexists_with_readable_public_outline():
    # Two separately saved, real DOM fragments from the same URL. This is an
    # explicit test composition, not a claim that either file is full HTTP HTML.
    soup = BeautifulSoup(capture("mooc-dom.html"), "html.parser")
    soup.body.append(BeautifulSoup(capture("mooc-term-dom.html"), "html.parser"))
    result = extract(str(soup), MOOC)
    assert result["access_notice"] == "老师已关闭该学期，无法查看"
    assert result["fetch_status"] == "fetched"
    assert result["resource_type"] == "course"
    assert result["catalog_kind"] == "course_outline"
    assert len(result["chapters"]) == 84
    assert result["video_evidence_status"] == "none"
    assert "requires_login" not in result and "requires_payment" not in result and "requires_enrollment" not in result
    provenance = result["field_provenance"]["access_notice"]
    entry = next(item for item in result["evidence"] if item["evidence_id"] == provenance["evidence_id"])
    assert entry["kind"] == "page" and entry["field"] == "access_notice"
    assert entry["text"] == result["access_notice"] and entry["url"] == MOOC
    assert_individual_evidence(result, MOOC)


@pytest.mark.parametrize("change", ["other_host", "outside_enrollment", "not_closed", "hidden"])
def test_mooc_access_notice_needs_specific_visible_closed_term_observation(change):
    soup = BeautifulSoup(capture("mooc-dom.html"), "html.parser")
    term = BeautifulSoup(capture("mooc-term-dom.html"), "html.parser")
    url = MOOC
    if change == "other_host":
        url = "https://example.org/course/PKU-1003479006"
    elif change == "outside_enrollment":
        term.select_one(".course-enroll-info_course-enroll_buttons")["class"] = ["unrelated-comment"]
    elif change == "not_closed":
        term.select_one(".ux-btn").string = "立即参加"
    elif change == "hidden":
        term.select_one(".course-enroll-info_course-enroll_buttons")["hidden"] = ""
    soup.body.append(term)
    result = extract(str(soup), url)
    assert "access_notice" not in result


def test_access_notice_survives_resource_schema_without_asserting_access_requirements():
    from backend.app.models import Resource
    result = extract(capture("mooc-dom.html") + capture("mooc-term-dom.html"), MOOC)
    resource = Resource.model_validate(dict(result, resource_id="res_fixture", url=MOOC, canonical_url=MOOC, discovered_at=AT))
    assert resource.access_notice == "老师已关闭该学期，无法查看"
    assert resource.requires_login is None and resource.requires_payment is None and resource.requires_enrollment is None
    assert resource.playback_verified is False


@pytest.mark.parametrize(("value", "expected"), [
    ("课程4 环境(9min)", 540), ("课程22 练习（5min）", 300),
    ("课程17 字典（dict）(22min)", 1320), ("练习 (1.5 min)", 90),
    ("无显式时长", None), ("测试 (0min)", None), ("测试 (-1min)", None),
    ("测试 (NaNmin)", None), ("测试 (3min) 后续文字", None),
])
def test_mooc_duration_requires_literal_positive_trailing_minutes(value, expected):
    assert outline_duration_seconds(value) == expected


def test_video_haspart_does_not_label_articles_or_untyped_parts_as_clips():
    document = {"@type": "VideoObject", "name": "Observed video", "hasPart": [
        {"@type": "Article", "name": "Related article", "url": "/article", "startOffset": 12},
        {"name": "Unknown attachment", "startOffset": 15},
        {"@type": "VideoObject", "name": "Another entire video", "url": "/other-video"},
        {"@type": "Clip", "name": "Actual chapter", "startOffset": 0, "endOffset": 12},
    ]}
    result = extract('<script type="application/ld+json">' + json.dumps(document) + '</script>', "https://example.org/video")
    assert [item["title"] for item in result["chapters"]] == ["Actual chapter"]
    assert result["catalog_kind"] == "video_chapters"
    assert result["chapters"][0]["start_seconds"] == 0


def test_course_haspart_still_allows_nonclip_course_outline():
    document = {"@type": "Course", "name": "Observed course", "hasPart": [
        {"@type": "Article", "name": "Required reading", "url": "/reading"},
        {"name": "Exercise"},
    ]}
    result = extract('<script type="application/ld+json">' + json.dumps(document) + '</script>', "https://example.org/course")
    assert len(result["chapters"]) == 2
    assert result["catalog_kind"] == "course_outline"
    assert result["video_evidence_status"] == "none"
