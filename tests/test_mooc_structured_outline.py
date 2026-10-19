"""Offline own-page curriculum parsing; no browser, API or network access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.extractor import MetadataExtractor


FIXTURES = Path(__file__).parent / "fixtures/mooc_structure"
URL = "https://www.icourse163.org/course/OWN-123"
SOURCE = "html.icourse163.termDto.outLineDto.outLineStructureDtos"


def extract(markup, url=URL):
    return MetadataExtractor().extract(markup, url, "offline-structured-outline")


def synthetic(rows=None, *, outline="", course_id="123", term_id="456", extra=""):
    rows = [{"name": "Parent chapter", "goals": "Learn the concept", "plan": "First task;;;Second task"}] if rows is None else rows
    term = {"id": term_id, "outLineDto": {"outLine": outline, "outLineStructureDtos": rows}}
    script = "window.termDto = " + json.dumps(term).replace("</", "<\\/") + "; window.courseDto = " + json.dumps({"id": course_id, "name": "Own course"}) + ";" + extra
    return '<html><body><div id="j-course-heading-intro"><div class="course-heading-intro_intro"></div></div><div id="j-course-outline"></div><script>' + script + '</script></body></html>'


@pytest.mark.parametrize("number,count", [("01", 107), ("02", 34), ("03", 43)])
def test_retained_own_course_structures_keep_all_original_titles_and_binding(number, count):
    expected = json.loads((FIXTURES / f"{number}-expected.json").read_text("utf-8"))
    raw = (FIXTURES / f"{number}-own-outline.html").read_bytes()
    manifest = json.loads((FIXTURES / "source-manifest.json").read_text("utf-8"))
    origin = next(row for row in manifest if row["fixture"].endswith(f"{number}-own-outline.html"))
    assert hashlib.sha256(raw).hexdigest() == origin["fixture_sha256"]
    result = extract(raw.decode("utf-8"), expected["url"])
    assert [row["title"] for row in result["chapters"]] == expected["expected_titles"]
    assert len(result["chapters"]) == count
    assert result["resource_type"] == "course" and result["catalog_kind"] == "course_outline"
    source = "html.icourse163.termDto.outLineDto.outLine" if number == "02" else SOURCE
    assert result["field_provenance"]["chapters"]["source"] == source
    evidence = {row["evidence_id"]: row for row in result["evidence"]}
    for index, row in enumerate(result["chapters"]):
        assert row["url"] is None and row["source_url"] == expected["url"]
        assert row["start_seconds"] is None and row["end_seconds"] is None
        ev = evidence[row["evidence_id"]]
        assert ev["source"] == source and ev["url"] == expected["url"]
        assert ev["field"] == f"chapters.{index}" and json.loads(ev["text"])["title"] == row["title"]
    assert result["video_evidence_status"] == "none" and not result.get("playback_verified")
    assert not result.get("requires_payment") and not result.get("requires_login")
    if number == "01":
        assert "9.8 Pandas数据分组与聚合" in expected["expected_titles"]
    if number == "03":
        assert "项目6 使用pandas进行数据分组与聚合" in expected["expected_titles"]
        assert "任务2 分组级apply和transform运算" in expected["expected_titles"]
        assert "项目5 使用pandas进行数据分组与聚合" in raw.decode("utf-8")
        assert not any(row["title"].startswith("项目5 使用pandas进行数据分组与聚合") for row in result["chapters"])


def test_parents_without_child_plan_and_empty_separators_keep_order_without_goals_as_lessons():
    rows = [{"name": "One", "goals": "Not a chapter", "plan": ""}, {"name": "Two"},
            {"name": "Three", "goals": "Goal only", "plan": ";;;A;;;;;;B;;;"}]
    result = extract(synthetic(rows))
    assert [r["title"] for r in result["chapters"]] == ["One", "Two", "Three", "A", "B"]
    assert all(r["duration_seconds"] is None for r in result["chapters"])


def test_nonempty_legacy_outline_has_priority_over_structured_and_other_arrays():
    result = extract(synthetic(outline="<p>Legacy own outline</p>", extra='window.relatedCourses=[{name:"Other course",plan:"Other lesson"}];'))
    assert [r["title"] for r in result["chapters"]] == ["Legacy own outline"]
    assert result["field_provenance"]["chapters"]["source"].endswith(".outLine")


def test_matching_explicit_term_keeps_exact_source_url():
    url = URL + "?tid=456"
    result = extract(synthetic(), url)
    assert [row["title"] for row in result["chapters"]] == ["Parent chapter", "First task", "Second task"]
    assert all(row["source_url"] == url and row["url"] is None for row in result["chapters"])


def test_total_structure_text_budget_rejects_whole_catalog():
    result = extract(synthetic([{"name": f"Chapter {i}", "goals": "x" * 4000, "plan": ""} for i in range(26)]))
    assert result["chapters"] == [] and result["catalog_fetch_status"] == "catalog_payload_invalid"


@pytest.mark.parametrize("damage", ["wrong_course", "wrong_term", "duplicate_term", "foreign_host", "related_only", "outside_dto", "comment", "string", "conditional", "external_script", "duplicate_payload", "call", "concat", "duplicate_key", "template", "depth", "array_bound", "script_bound"])
def test_wrong_owner_ambiguous_or_executable_structures_do_not_become_curriculum(damage):
    markup = synthetic(); url = URL
    if damage == "wrong_course": markup = synthetic(course_id="124")
    elif damage == "wrong_term": url += "?tid=457"
    elif damage == "duplicate_term": url += "?tid=456&tid=456"
    elif damage == "foreign_host": url = URL.replace("www.icourse163.org", "example.org")
    elif damage == "related_only": markup = synthetic([], extra='window.relatedCourses=[{name:"Foreign",plan:"Foreign lesson"}];')
    elif damage == "outside_dto": markup = markup.replace('"outLineStructureDtos":', '"remoteRelatedStructure":')
    elif damage == "comment": markup = markup.replace("<script>", "<script>/*").replace("</script>", "*/</script>")
    elif damage == "string": markup = synthetic([], extra='var telemetry="outLineStructureDtos: [{name: foreign}]";')
    elif damage == "conditional": markup = markup.replace("window.termDto", "if(false) window.termDto")
    elif damage == "external_script": markup = markup.replace("<script>", '<script src="https://example.org/remote.js">')
    elif damage == "duplicate_payload": markup += '<script>window.termDto={};window.courseDto={};</script>'
    elif damage == "call": markup = markup.replace('"plan": "First task;;;Second task"', '"plan": loadOutline()')
    elif damage == "concat": markup = markup.replace('"plan": "First task;;;Second task"', '"plan": "First" + " task"')
    elif damage == "duplicate_key": markup = markup.replace('"name": "Parent chapter"', '"name":"Parent chapter","name":"Other"')
    elif damage == "template": markup = markup.replace('"plan": "First task;;;Second task"', '"plan": `${loadOutline()}`')
    elif damage == "depth": markup = synthetic([{"name": "Parent", "plan": [[[[[[[[[["Too deep"]]]]]]]]]]}])
    elif damage == "array_bound": markup = synthetic([{"name": str(i), "plan": ""} for i in range(201)])
    elif damage == "script_bound": markup = markup.replace("<script>", "<script>" + " " * 250001)
    result = extract(markup, url)
    assert result["chapters"] == [] and "chapters" not in result["field_provenance"]


@pytest.mark.parametrize("bad_rows", ["wrong type", ["wrong entry"], [{"name": 3}], [{"name": ""}],
    [{"name": "Parent", "goals": {"remote": "text"}}], [{"name": "Parent", "plan": ["not literal plan text"]}],
    [{"name": "Parent", "children": [{"name": "foreign"}]}], [{"name": "x" * 301}],
    [{"name": "Parent", "goals": "x" * 4001}], [{"name": "Parent", "plan": "x" * 16001}]])
def test_malformed_structure_is_explicitly_invalid_not_a_truncated_catalog(bad_rows):
    result = extract(synthetic(bad_rows))
    assert result["chapters"] == [] and result["catalog_fetch_status"] == "catalog_payload_invalid"
    assert "chapters" not in result["field_provenance"]


@pytest.mark.parametrize("count", [500, 501])
def test_flattened_total_is_complete_or_explicitly_over_limit(count):
    plan = ";;;".join(f"Task {i}" for i in range(count - 1))
    result = extract(synthetic([{"name": "Parent", "plan": plan}]))
    if count == 500:
        assert len(result["chapters"]) == 500 and result["chapters"][-1]["title"] == "Task 498"
    else:
        assert result["chapters"] == [] and result["catalog_fetch_status"] == "catalog_limit_exceeded"


def test_plan_text_removes_hidden_executable_markup_and_never_adopts_links():
    result = extract(synthetic([{"name": "Parent", "plan": '<a href="/learn/OTHER-2">Visible task</a>;;;<script>loadSecret()</script>;;;Hidden<span hidden> hidden</span>;;; <span style="display:none">Not shown</span>'}]))
    assert [r["title"] for r in result["chapters"]] == ["Parent", "Visible task", "Hidden"]
    assert all(r["url"] is None for r in result["chapters"])
