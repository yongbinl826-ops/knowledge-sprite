"""Offline public-course scope and identity boundaries, with synthetic HTML."""
from __future__ import annotations

import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.mooc_urls import course_identity_parts, public_course_url


@pytest.mark.parametrize("url,course,term", [
    ("https://www.icourse163.org/course/PKU-123", "123", None),
    ("https://icourse163.org/course/-123/", "123", None),
    ("https://www.icourse163.org/course/CAVTC--1206997801", "1206997801", None),
    ("https://www.icourse163.org/course/A-B_C-123?tid=456", "123", "456"),
    ("https://www.icourse163.org/course/detail.htm?cid=123", "123", None),
    ("https://www.icourse163.org/course/detail.htm?tid=456&cid=123", "123", "456"),
    ("https://www.icourse163.org/course/detail.htm?cid=123&tid=456&outVendor=zw_mooc_pclszykctj_", "123", "456"),
    ("https://www.icourse163.org/course/PKU-123?outVendor=zw_mooc_pclszykctj_&tid=456", "123", "456"),
])
def test_public_route_keeps_its_observed_path_and_query(url, course, term):
    assert public_course_url(url) == url
    assert course_identity_parts(url) == {"course_id": course, "term_id": term}


@pytest.mark.parametrize("suffix", [
    "?cid=", "?cid=x", "?cid=-1", "?cid=1.5", "?cid=123&cid=124",
    "?cid=123&tid=", "?cid=123&tid=456&tid=457", "?cid=123&tid=x",
    "?cid=123&outVendor=", "?cid=123&outVendor=x&outVendor=y",
    "?cid=123&outVendor=https://example.com", "?cid=123&outVendor=x%2Fy",
    "?cid=123&outVendor=" + "x" * 129,
    "?cid=123&redirect=https://example.com", "?cid=123&utm_source=x",
    "?%63id=123", "?cid=%31%32%33", "?cid=123&", "?cid=123#learn",
    "?cid=123;tid=456", "?CID=123", "?cid=123&foo", "",
])
def test_detail_route_rejects_unknown_ambiguous_and_nonliteral_identity(suffix):
    url = "https://www.icourse163.org/course/detail.htm" + suffix
    assert public_course_url(url) is None
    assert course_identity_parts(url) is None


@pytest.mark.parametrize("url", [
    None, "", " https://www.icourse163.org/course/PKU-123",
    "http://www.icourse163.org/course/PKU-123",
    "https://kaoyan.icourse163.org/course/PKU-123",
    "https://www.icourse163.org.evil.example/course/PKU-123",
    "https://user@www.icourse163.org/course/PKU-123",
    "https://www.icourse163.org:444/course/PKU-123",
    "https://www.icourse163.org/course/PKU-123?cid=123",
    "https://www.icourse163.org/course/PKU-123?unknown=1",
    "https://www.icourse163.org/course/PKU-123?tid=456&tid=456",
    "https://www.icourse163.org/course/PKU-123#/learn/content",
    "https://www.icourse163.org/learn/PKU-123",
    "https://www.icourse163.org/spoc/course/PKU-123",
    "https://www.icourse163.org/course/123.htm",
    "https://www.icourse163.org/course/detail.htm/123?cid=123",
    "https://www.icourse163.org/course/detail.htm/?cid=123",
    "https://www.icourse163.org/course/%50KU-123",
    "https://www.icourse163.org/course/PKU-123\n?tid=456",
])
def test_unverified_surfaces_are_not_expanded_to_public_scope(url):
    assert public_course_url(url) is None
    assert course_identity_parts(url) is None


def synthetic(*, course_id="123", term_id="456", script=True, visible=False):
    """Deliberately fabricated fixture: validates binding, not live coverage."""
    payload = ("window.termDto = " + json.dumps({"id": term_id, "outLineDto": {
        "outLine": "<p>SQL 多表连接</p><p>SQL 分组查询</p>"}}) +
        "; window.courseDto = " + json.dumps({"id": course_id, "name": "SQL 课程"}) + ";")
    outline = '<div class="f-richEditorText"><p>SQL 多表连接</p><p>SQL 分组查询</p></div>' if visible else ""
    return ('<html><head><title>SQL 课程</title></head><body>'
            '<div id="j-course-heading-intro"><div class="course-heading-intro_intro">'
            + ("课程介绍" if visible else "") + '</div></div>'
            '<div id="j-course-outline">' + outline + '</div>'
            + ("<script>" + payload + "</script>" if script else "") + '</body></html>')


@pytest.mark.parametrize("url", [
    "https://www.icourse163.org/course/detail.htm?cid=123",
    "https://www.icourse163.org/course/detail.htm?cid=123&tid=456",
    "https://www.icourse163.org/course/detail.htm?cid=123&outVendor=zw_mooc_pclszykctj_",
    "https://www.icourse163.org/course/CAVTC--123?tid=456&outVendor=zw_mooc_pclszykctj_",
])
def test_matching_dto_binds_curriculum_to_exact_observed_native_url(url):
    result = MetadataExtractor().extract(synthetic(), url, "offline-binding-test")
    assert result["resource_type"] == "course"
    assert [c["title"] for c in result["chapters"]] == ["SQL 多表连接", "SQL 分组查询"]
    assert all(c["source_url"] == url and c["url"] is None for c in result["chapters"])
    assert all(e["url"] == url for e in result["evidence"])
    assert not result.get("playback_verified")


@pytest.mark.parametrize("course_id,term_id,url", [
    ("999", "456", "https://www.icourse163.org/course/detail.htm?cid=123"),
    ("123", "999", "https://www.icourse163.org/course/detail.htm?cid=123&tid=456"),
    (True, "456", "https://www.icourse163.org/course/detail.htm?cid=123"),
    ("123", True, "https://www.icourse163.org/course/detail.htm?cid=123&tid=456"),
])
def test_wrong_detail_course_or_term_cannot_fall_back_to_visible_containers(course_id, term_id, url):
    result = MetadataExtractor().extract(synthetic(course_id=course_id, term_id=term_id, visible=True), url, "offline")
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_legacy_detail_containers_without_course_identity_are_not_outline_evidence():
    url = "https://www.icourse163.org/course/detail.htm?cid=123"
    result = MetadataExtractor().extract(synthetic(script=False, visible=True), url, "offline")
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_legacy_slug_visible_outline_behavior_remains_available():
    result = MetadataExtractor().extract(synthetic(script=False, visible=True),
        "https://www.icourse163.org/course/OWN-123", "offline")
    assert result["resource_type"] == "course"
    assert len(result["chapters"]) == 2
