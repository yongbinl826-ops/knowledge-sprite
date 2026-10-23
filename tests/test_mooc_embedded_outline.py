"""Offline regression of a freshly captured anonymous HTTP response.

The fixed source is HTTP HTML, not rendered browser DOM. These tests do not make
network requests; the separate live job is required for end-to-end acceptance.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from backend.app.extractor import MetadataExtractor
from backend.app.source_adapters.icourse163 import MOOC_CATALOG_LIMIT


RAW_PATH = Path(__file__).resolve().parents[1] / "tests/fixtures/public_catalog_replays/mooc-public-read-20261017/direct-probe/02-page.body"
RAW_SHA256 = "c492d76ac452b0189057e6d061470b434d14189a6e38931a91a9f2adebf04af4"
URL = "https://www.icourse163.org/course/PKU-1003479006"


def captured_http():
    raw = RAW_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
    return raw.decode("utf-8")


def extract(markup, url=URL):
    return MetadataExtractor().extract(markup, url, "offline-regression")


def synthetic(*, script=None, course_id="1003479006", term_id="1476734461", outline=None):
    # A labelled synthetic boundary fixture, never a substitute for a live page.
    outline = outline or '<p>课程1 Python 列表(12min)</p><p>章节一作业</p>'
    if script is None:
        encoded = json.dumps(outline).replace("</", "<\\/")
        script = f'window.termDto = {{id:"{term_id}",outLineDto:{{outLine:{encoded}}}}}; window.courseDto = {{id:"{course_id}",name:"Python basics"}};'
    return '<html><head><title>Synthetic public course</title></head><body><div id="j-rectxt">spContent=Public course introduction</div><div id="j-course-heading-intro"><div class="course-heading-intro_intro"></div></div><div id="j-course-outline"></div><script>' + script + '</script></body></html>'


def test_current_http_html_contains_literal_curriculum_and_empty_render_targets():
    markup = captured_http()
    soup = BeautifulSoup(markup, "html.parser")
    assert not soup.select_one("#j-course-outline").get_text(strip=True)
    assert not soup.select_one("#j-course-heading-intro .course-heading-intro_intro").get_text(strip=True)
    result = extract(markup)
    assert result["title"] == "Python语言基础与应用"
    assert result["resource_type"] == "course"
    assert result["field_provenance"]["resource_type"]["source"] == "html.icourse163.embedded_course_structure"
    assert result["field_provenance"]["description"]["source"] == "html.icourse163.embedded_introduction"
    assert result["description"].startswith("本课基于主讲教师在北京大学")
    assert "spContent=" not in result["description"]
    assert result["catalog_kind"] == "course_outline"
    chapters = result["chapters"]
    assert len(chapters) == 84
    titles = [row["title"] for row in chapters]
    assert [int(re.match(r"课程(\d+)", title)[1]) for title in titles if re.match(r"课程\d+", title)] == list(range(1, 58))
    assert sum(bool(re.match(r"[一二三四五六七八九十]+、", title)) for title in titles) == 9
    assert sum(title.startswith("视频教程：") for title in titles) == 2
    assert sum(title.startswith("章节") for title in titles) == 16
    assert sum(row["duration_seconds"] is not None for row in chapters) == 41
    assert result["video_evidence_status"] == "none"
    assert not result.get("playback_verified")
    assert not result.get("requires_login") and not result.get("requires_payment")
    assert "access_notice" not in result  # Do not interpret closeVisableStatus as a verified notice.
    evidence = {row["evidence_id"]: row for row in result["evidence"]}
    for index, chapter in enumerate(chapters):
        assert chapter["url"] is None and chapter["start_seconds"] is None and chapter["end_seconds"] is None
        row = evidence[chapter["evidence_id"]]
        assert row["field"] == f"chapters.{index}"
        assert row["url"] == URL and row["source"] == "html.icourse163.termDto.outLineDto.outLine"
        assert json.loads(row["text"])["title"] == chapter["title"]


@pytest.mark.parametrize("url", ["https://example.org/course/PKU-1003479006", "https://www.icourse163.org/learn/PKU-1003479006", URL.replace("1003479006", "1003479007"), URL + "?tid=1476734462", URL + "?tid=1476734461&tid=1476734462", URL + "?tid="])
def test_embedded_outline_requires_course_and_requested_term_identity(url):
    result = extract(captured_http(), url)
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_matching_explicit_term_retains_source_url_without_inventing_lesson_urls():
    url = URL + "?tid=1476734461"
    result = extract(captured_http(), url)
    assert len(result["chapters"]) == 84
    assert all(row["source_url"] == url and row["url"] is None for row in result["chapters"])


@pytest.mark.parametrize("damage", ["wrong_id", "missing_intro_target", "missing_outline_target", "external_script", "duplicate_script", "duplicate_key", "function_call", "concatenation", "conditional_assignment", "comment_only", "string_only", "template_literal", "over_budget"])
def test_unrelated_ambiguous_or_executable_payloads_do_not_become_catalogs(damage):
    markup = synthetic()
    if damage == "wrong_id":
        markup = synthetic(course_id="222")
    elif damage == "missing_intro_target":
        markup = markup.replace('id="j-course-heading-intro"', 'id="unrelated"')
    elif damage == "missing_outline_target":
        markup = markup.replace('id="j-course-outline"', 'id="unrelated"')
    elif damage == "external_script":
        markup = markup.replace("<script>", '<script src="https://example.org/data.js">')
    elif damage == "duplicate_script":
        markup = markup.replace("</body>", '<script>window.courseDto = {id:"222"};</script></body>')
    elif damage == "duplicate_key":
        markup = markup.replace('id:"1003479006"', 'id:"1003479006",id:"222"')
    elif damage == "function_call":
        markup = markup.replace('outLine:', 'outLine:loadOutline() || ')
    elif damage == "concatenation":
        markup = markup.replace('name:"Python basics"', 'name:"Python basics" + " extra"')
    elif damage == "conditional_assignment":
        markup = markup.replace('window.termDto', 'if (false) window.termDto')
    elif damage == "comment_only":
        markup = markup.replace("<script>", "<script>/*").replace("</script>", "*/</script>")
    elif damage == "string_only":
        script = BeautifulSoup(markup, "html.parser").script.get_text()
        markup = synthetic(script="var text=" + json.dumps(script) + ";")
    elif damage == "template_literal":
        markup = markup.replace('name:"Python basics"', 'name:`${loadTitle()}`')
    elif damage == "over_budget":
        markup = markup.replace("<script>", "<script>" + " " * 250_001)
    result = extract(markup)
    assert result["chapters"] == []
    assert "resource_type" not in result


def test_literal_html_removes_hidden_and_executable_text_without_following_links():
    result = extract(synthetic(outline='<p><a href="/learn/OTHER-222">Public item (2min)</a></p><p hidden>Hidden item</p><div style="display:none"><p>Hidden child</p></div><script>ignored()</script><p>Assignment</p>'))
    assert [row["title"] for row in result["chapters"]] == ["Public item (2min)", "Assignment"]
    assert all(row["url"] is None for row in result["chapters"])
    assert result["chapters"][0]["duration_seconds"] == 120


def test_fresh_live_course_all_122_items_survive_schema_sqlite_and_evidence_binding(tmp_path):
    from backend.app.db import Store
    from backend.app.models import Resource

    source = RAW_PATH.parents[1] / "jobs/1e976e58-f094-489b-82db-c43d35bf61e5/public-course-responses/response-0007-d58fa000f67ae9e0.html"
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "d58fa000f67ae9e0df87f88456a6995eea898f18eb2f57c1b85ecb4166d63aa0"
    markup = raw.decode("utf-8")
    # Independent comparison against the exact public literal in this HTTP body.
    values = re.findall(r'\boutLine\s*:\s*("(?:\\.|[^"\\])*")', markup)
    assert len(values) == 1
    outline = BeautifulSoup(json.loads(values[0]), "html.parser")
    titles = [" ".join(node.get_text(" ", strip=True).split()) for node in outline.select("p") if node.get_text(strip=True)]
    assert len(titles) == 122
    url = "https://www.icourse163.org/course/PKU-1206307812"
    result = extract(markup, url)
    assert [row["title"] for row in result["chapters"]] == titles
    assert titles[0] == "一、概述" and titles[-1] == "第十二周作业"
    assert result.get("catalog_fetch_status") is None
    resource = Resource.model_validate(dict(result, resource_id="actual-122", url=url, canonical_url=url,
                                           discovered_at="offline-regression")).model_dump()
    store = Store(str(tmp_path / "catalog.sqlite3"))
    try:
        store.save_job({"job_id": "test", "status": "complete"})
        store.save_resource("test", resource)
        for row in result["evidence"]:
            store.add_evidence("test", "actual-122", None, row)
        restored = store.resources("test")["actual-122"]
        evidence = {row["evidence_id"]: row for row in store.evidence("test", "actual-122")}
        assert [row["title"] for row in restored["chapters"]] == titles
        for index, chapter in enumerate(restored["chapters"]):
            row = evidence[chapter["evidence_id"]]
            assert row["field"] == f"chapters.{index}"
            assert json.loads(row["text"])["title"] == titles[index]
    finally:
        store.close()


@pytest.mark.parametrize("surface", ["embedded", "visible"])
@pytest.mark.parametrize("count", [122, MOOC_CATALOG_LIMIT, MOOC_CATALOG_LIMIT + 1])
def test_mooc_catalog_limit_is_complete_or_explicitly_empty(surface, count):
    from backend.app.models import Resource

    outline = "".join(f"<p>Course item {index}</p>" for index in range(1, count + 1))
    markup = synthetic(outline=outline)
    if surface == "visible":
        soup = BeautifulSoup(markup, "html.parser")
        soup.script.decompose()
        soup.select_one(".course-heading-intro_intro").string = "Visible public introduction"
        soup.select_one("#j-course-outline").append(BeautifulSoup('<div class="f-richEditorText">' + outline + '</div>', "html.parser"))
        markup = str(soup)
    result = extract(markup)
    resource = Resource.model_validate(dict(result, resource_id="limit", url=URL, canonical_url=URL,
                                           discovered_at="offline-regression"))
    assert result["resource_type"] == "course"
    if count <= MOOC_CATALOG_LIMIT:
        assert len(result["chapters"]) == count
        assert result["chapters"][-1]["title"] == f"Course item {count}"
        assert result.get("catalog_fetch_status") is None
        assert len(resource.chapters) == count
    else:
        assert result["chapters"] == [] and resource.chapters == []
        assert result["metadata_evidence_level"] == "page"
        assert "catalog_kind" not in result
        assert resource.catalog_fetch_status == "catalog_limit_exceeded"
        provenance = result["field_provenance"]["catalog_fetch_status"]
        row = next(row for row in result["evidence"] if row["evidence_id"] == provenance["evidence_id"])
        assert f"{count} nonempty entries" in row["text"] and f"{MOOC_CATALOG_LIMIT}-entry limit" in row["text"]
        assert "no truncated catalog" in row["text"]


@pytest.mark.parametrize("preview_source", ["visible", "jsonld"])
def test_oversized_mooc_payload_cannot_be_replaced_by_another_sources_short_preview(preview_source):
    outline = "".join(f"<p>Full course item {index}</p>" for index in range(MOOC_CATALOG_LIMIT + 1))
    soup = BeautifulSoup(synthetic(outline=outline), "html.parser")
    if preview_source == "visible":
        soup.select_one(".course-heading-intro_intro").string = "Visible introduction"
        soup.select_one("#j-course-outline").append(BeautifulSoup('<div class="f-richEditorText"><p>Short visible preview</p></div>', "html.parser"))
    else:
        preview = soup.new_tag("script", type="application/ld+json")
        preview.string = json.dumps({"@type": "Course", "name": "Public course", "hasPart": [{"name": "Short JSON-LD preview"}]})
        soup.body.append(preview)
    result = extract(str(soup))
    assert result["catalog_fetch_status"] == "catalog_limit_exceeded"
    assert result["chapters"] == []
    assert "catalog_kind" not in result
    assert "chapters" not in result["field_provenance"]
    assert not any(row["kind"] == "catalog" or row["field"].startswith("chapters") for row in result["evidence"])
    assert result["metadata_evidence_level"] == "page"
    assert result["resource_type"] == "course"
    assert "catalog_fetch_status" in result["field_provenance"]
