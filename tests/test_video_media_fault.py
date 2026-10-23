"""Only explicit current source declarations establish known media damage."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.video_availability import has_known_media_fault


URL = "https://www.bilibili.com/video/BV1ab411C7xy/"
STAMP = "2026-10-21T01:41:24+00:00"


def own_page(description="音频坏了，不想重新录了。", *, field="description"):
    resource = {"url": URL, "canonical_url": URL, "title": "编程教程", "description": "",
                "fetch_status": "fetched", "fetched_at": STAMP}
    resource[field] = description
    row = {"evidence_id": "own-field", "kind": "page", "field": field,
           "url": URL, "source": "html.description", "text": description, "fetched_at": STAMP}
    return resource, [row]


def test_saved_actual_author_description_is_bound_and_reported_without_mutation():
    fixture = json.loads((Path(__file__).parent / "fixtures/video-author-audio-fault-actual.json").read_text(encoding="utf-8"))
    resource, evidence = fixture["resource"], fixture["evidence"]
    assert resource["description"] == "音频坏了 不想录了 就这样吧 后面应该会有完整版"
    before = deepcopy((resource, evidence))
    assert has_known_media_fault(resource, evidence) is True
    assert (resource, evidence) == before


@pytest.mark.parametrize("text", [
    "音频坏了", "录音损坏", "本期视频的音轨损坏了。", "抱歉，音频坏掉了。",
    "音频坏了，尚未修复。", "音频坏了，后续会重新录制。",
    "This video's audio is broken.", "This video’s audio is corrupted.",
    "My recording's audio track is damaged.", "The audio in this video is broken.",
])
@pytest.mark.parametrize("field", ["title", "description"])
def test_explicit_present_audio_faults(text, field):
    assert has_known_media_fault(*own_page(text, field=field)) is True


@pytest.mark.parametrize("text", [
    "音频没坏", "音频没有坏", "音频未损坏", "不是音频坏了", "并非音频坏了",
    "音频坏了吗？没有，调大音量就好。", "音频坏了怎么办", "如何修复损坏的录音",
    "音频坏了，教大家修复录音。", "音频坏了的修复教程", "音频坏了？修复方法演示",
    "如果音频坏了，请试试这些方法。", "例如音频坏了，可以修复。",
    "以前音频坏了，现在已修复。", "音频坏了，已重新录制。", "音频坏了，音频已经恢复正常。",
    "音频坏了，尚未修复的说法不准确；现已修好。", "上一期音频坏了，本期正常。",
    "纯字幕，无配音", "无声演示", "静音视频，没有旁白", "不含音轨，纯视觉演示",
    "This video's audio is not broken.", "If this video's audio is broken, try this tutorial.",
    "How to fix this video's audio is broken errors", "This video's audio is broken? No.",
    "This video's audio is broken. It is now fixed.", "This video's audio is broken. Audio has been repaired.",
    "Silent tutorial; no narration.", "Video playback has not been tested.",
])
def test_negated_repaired_tutorial_hypothetical_and_silent_are_not_faults(text):
    assert has_known_media_fault(*own_page(text)) is False


@pytest.mark.parametrize("change", [
    {"kind": "search"}, {"kind": "page_link"}, {"kind": "catalog"}, {"field": "chapters.0"},
    {"source": ""}, {"source": " "}, {"source": 1}, {"evidence_id": ""}, {"evidence_id": 1},
    {"url": "https://example.org/neighbor"},
    {"url": URL + "?p=2"}, {"cache": {"stale": True}}, {"stale": True},
    {"fetched_at": "2025-01-01T00:00:00+00:00"}, {"fetched_at": None},
    {"text": "音频坏了"}, {"text": None},
])
def test_unbound_old_discovery_or_mismatched_field_evidence_is_ignored(change):
    resource, evidence = own_page()
    evidence[0].update(change)
    assert has_known_media_fault(resource, evidence) is False


@pytest.mark.parametrize("change", [
    {"fetch_status": "pending"}, {"fetch_status": "javascript_required"}, {"fetch_status": "failed"},
    {"cache": {"stale": True}}, {"stale": True}, {"url": "https://example.org/neighbor"},
    {"canonical_url": "http://127.0.0.1/"}, {"description": "正常教程"},
])
def test_resource_must_still_be_current_successfully_fetched_own_page(change):
    resource, evidence = own_page()
    resource.update(change)
    assert has_known_media_fault(resource, evidence) is False


def test_current_description_correction_overrides_older_wording_in_current_title():
    resource, evidence = own_page("音频坏了", field="title")
    resource["description"] = "现已修复，声音正常。"
    evidence.append({**evidence[0], "evidence_id": "description", "field": "description", "text": resource["description"]})
    assert has_known_media_fault(resource, evidence) is False
    evidence[1]["url"] = "https://example.org/neighbor"
    assert has_known_media_fault(resource, evidence) is True


def test_only_current_field_provenance_can_supply_explicit_fault():
    resource, evidence = own_page()
    row = evidence[0]
    resource["field_provenance"] = {"description": {key: row[key] for key in ("evidence_id", "source", "url")}}
    assert has_known_media_fault(resource, evidence) is True
    resource["field_provenance"]["description"]["evidence_id"] = "replacement-page"
    assert has_known_media_fault(resource, evidence) is False


@pytest.mark.parametrize("title", ["音频修复教程", "How to repair corrupted recordings"])
def test_own_tutorial_title_disambiguates_its_example_description(title):
    resource, evidence = own_page("音频坏了")
    resource["title"] = title
    evidence.append({**evidence[0], "evidence_id": "own-title", "field": "title", "text": title})
    assert has_known_media_fault(resource, evidence) is False
    evidence[1]["url"] = "https://example.org/neighbor"
    assert has_known_media_fault(resource, evidence) is True


@pytest.mark.parametrize("title", ["Python tutorial: how to use input widgets", "Streamlit 文件下载教程"])
def test_ordinary_tutorial_title_does_not_negate_own_audio_fault_description(title):
    resource, evidence = own_page("This video's audio is broken.")
    resource["title"] = title
    evidence.append({**evidence[0], "evidence_id": "own-title", "field": "title", "text": resource["title"]})
    assert has_known_media_fault(resource, evidence) is True


def test_success_status_and_safe_same_video_trailing_slash_are_supported():
    resource, evidence = own_page()
    resource["fetch_status"] = "success"
    evidence[0]["url"] = URL.rstrip("/")
    assert has_known_media_fault(resource, evidence) is True


def test_unverified_fault_text_outside_own_page_fields_cannot_create_fault():
    resource, evidence = own_page("正常视频")
    resource["snippet"] = "音频坏了"
    evidence.extend([None, {"kind": "search", "title": "音频坏了", "snippet": "录音损坏", "url": URL}])
    assert has_known_media_fault(resource, evidence) is False
