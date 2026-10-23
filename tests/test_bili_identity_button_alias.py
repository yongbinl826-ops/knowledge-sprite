"""Retained public metadata and pure URL/concept controls. No provider calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.ranking import compound_english_match, rank_resource
from backend.app.video_availability import _bound_page_video, _same_url, is_unconfirmed_fetched_media

DATA = json.loads((Path(__file__).parent / "fixtures/bili_identity_button/retained.json").read_text(encoding="utf-8"))["cases"]
BASE = "https://www.bilibili.com/video/BV1SL4y1i7ZL"


def test_retained_javascript_same_video_page_identity_survives_terminal_slash():
    c = DATA["browser_flashcards_intermediate"]
    before = deepcopy(c)
    assert _bound_page_video(c["resource"], c["evidence"])
    assert not is_unconfirmed_fetched_media(c["resource"], c["evidence"])
    m = rank_resource(c["point"], c["resource"], c["evidence"], SearchRequest.model_validate(c["request"]))
    assert m["topic_evidence_status"] == "supported"
    assert "media_identity_unconfirmed" not in {r["code"] for r in m["topic_evidence_reasons"]}
    assert c == before


def test_retained_arduino_key_debounce_is_same_professional_concept_as_button_debounce():
    c = DATA["arduino_pot_button_beginner"]
    before = deepcopy(c)
    m = rank_resource(c["point"], c["resource"], c["evidence"], SearchRequest.model_validate(c["request"]))
    assert m is not None and m["topic_evidence_status"] == "supported"
    assert set(m["supporting_evidence_ids"]) <= {e["evidence_id"] for e in c["evidence"]}
    assert c["resource"]["fetch_status"] == "not_fetched"
    assert "页面详情及完整教学覆盖尚未核验" in m["recommendation_reason"]
    assert c == before


@pytest.mark.parametrize("suffix", ["", "?p=1", "?p=28"])
def test_native_same_bvid_same_explicit_part_slash_only(suffix):
    assert _same_url(BASE + "/" + suffix, BASE + suffix)
    assert _same_url(BASE + suffix, BASE + "/" + suffix)


@pytest.mark.parametrize("left,right", [
    (BASE + "/?p=2", BASE + "?p=3"),
    (BASE + "/?p=1", BASE),
    (BASE.replace("BV1SL4y1i7ZL", "BV1cJ411h7kU") + "/", BASE),
    (BASE.replace("www.", "m.") + "/", BASE),
    (BASE.replace("www.bilibili.com", "www.bilibili.com.evil.example") + "/", BASE),
    (BASE.replace("www.bilibili.com", "evil.bilibili.com") + "/", BASE.replace("www.bilibili.com", "evil.bilibili.com")),
    (BASE.replace("https:", "http:") + "/", BASE),
    (BASE.replace(".com/", ".com:80/") + "/", BASE),
    (BASE.replace(".com/", ".com:444/") + "/", BASE),
    (BASE + "/#part", BASE),
    (BASE + "/?p=0", BASE + "?p=0"),
    (BASE + "/?p=-1", BASE + "?p=-1"),
    (BASE + "/?p=01", BASE + "?p=01"),
    (BASE + "/?p=2&p=2", BASE + "?p=2&p=2"),
    (BASE + "/?%70=2", BASE + "?p=2"),
    (BASE + "/?p=2&redirect=https://other.example/", BASE + "?p=2&redirect=https://other.example/"),
    ("https://example.com/video/BV1SL4y1i7ZL/", "https://example.com/video/BV1SL4y1i7ZL"),
    ("https://www.bilibili.com/list/ml123/", "https://www.bilibili.com/list/ml123"),
])
def test_native_identity_extension_rejects_other_parts_hosts_or_query(left, right):
    assert not _same_url(left, right)


@pytest.mark.parametrize("mutation", ["different_bvid", "different_part", "foreign_host", "wrong_id", "wrong_source", "wrong_field"])
def test_bound_page_proof_does_not_borrow_other_video_or_part(mutation):
    c = deepcopy(DATA["browser_flashcards_intermediate"])
    origin = c["resource"]["field_provenance"]["video_evidence_status"]
    row = next(e for e in c["evidence"] if e.get("evidence_id") == origin["evidence_id"])
    if mutation == "different_bvid": row["url"] = row["url"].replace("BV1SL4y1i7ZL", "BV1cJ411h7kU")
    if mutation == "different_part": row["url"] += "?p=2"
    if mutation == "foreign_host": row["url"] = row["url"].replace("www.bilibili.com", "example.com")
    if mutation == "wrong_id": row["evidence_id"] = "wrong"
    if mutation == "wrong_source": row["source"] = "search"
    if mutation == "wrong_field": row["field"] = "title"
    assert not _bound_page_video(c["resource"], c["evidence"])


@pytest.mark.parametrize("wanted,observed", [
    ("Arduino 按钮消抖", "Arduino 按键消抖教程"),
    ("Arduino 按键去抖", "Arduino 按钮消抖实验"),
    ("Arduino 按钮去抖", "Arduino 按键的消抖"),
    ("STM32 按钮去抖", "STM32 按键消抖教学"),
])
def test_complete_button_debounce_concept_alias(wanted, observed):
    assert compound_english_match(wanted, [observed])


@pytest.mark.parametrize("observed", [
    "ESP32 GPIO 按键消抖教程",
    "ArduinoWrapper 按键消抖教程",
    "Arduino PWM信号的抖动消除",
    "Arduino 按钮输入与信号抖动",
    "Arduino GPIO\nESP32 按键消抖教程",
    "Arduino 本课不讲按键消抖",
    "Arduino 预备知识：按键消抖",
    "Arduino 下节课讲解按键消抖",
    "Arduino 相关API列表：按键消抖",
])
def test_alias_preserves_owner_object_and_teaching_scope(observed):
    assert not compound_english_match("Arduino 按钮消抖", [observed])


def test_alias_does_not_fill_nonblocking_board_or_project_requirements():
    observed = "Arduino 按键消抖教程"
    assert not compound_english_match("Arduino Uno 按钮消抖", [observed])
    assert not compound_english_match("Arduino 非阻塞按钮消抖", [observed])
    assert not compound_english_match("Arduino 按钮消抖与亮度映射", [observed])


def test_retained_other_point_search_cannot_support_debounce_alias():
    c = deepcopy(DATA["arduino_pot_button_beginner"])
    for e in c["evidence"]:
        if e.get("kind") == "search": e["knowledge_point_id"] = "other-point"
    assert rank_resource(c["point"], c["resource"], c["evidence"], SearchRequest.model_validate(c["request"])) is None
