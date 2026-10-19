"""Only explicit own-course DTO relations may carry hashed outline parents."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.course_library import CourseLibrary, _snapshot
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.source_adapters.base import SourceFacts
from backend.app.source_adapters.icourse163 import MOOC_STRUCT_SOURCE
from scripts import import_verified_mooc_library as importer
from test_mooc_structured_outline import URL, synthetic


ROWS = [{"name": "Python 数据结构", "goals": "GOAL_ONLY 不应成为章节",
         "plan": "Python 列表;;;Python 字典"},
        {"name": "Second parent", "goals": "ANOTHER_GOAL", "plan": "Last child"}]


@pytest.fixture(autouse=True)
def no_network_or_env(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Hierarchy tests must remain offline")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def observation(rows=ROWS, *, url=URL, **kwargs):
    markup = synthetic(rows, **kwargs).replace('"Own course"', '"Python 程序设计"')
    markup = markup.replace("<body>", "<body><div id='j-rectxt'>spContent=本课程讲授Python程序设计，提供公开的章节大纲。</div>")
    resource = MetadataExtractor().extract(markup, url, now())
    evidence = resource.pop("evidence")
    resource.update(url=url, canonical_url=url, platform="icourse163")
    return resource, evidence


def test_explicit_record_parents_are_zero_based_source_bound_and_in_every_digest():
    resource, evidence = observation()
    chapters = resource["chapters"]
    assert [chapter["title"] for chapter in chapters] == ["Python 数据结构", "Python 列表", "Python 字典", "Second parent", "Last child"]
    assert {i: chapter["outline_parent_index"] for i, chapter in enumerate(chapters)
            if "outline_parent_index" in chapter} == {1: 0, 2: 0, 4: 3}
    records = {row["evidence_id"]: row for row in evidence}
    for i, chapter in enumerate(chapters):
        record = records[chapter["evidence_id"]]
        assert chapter["source"] == record["source"] == MOOC_STRUCT_SOURCE
        assert chapter["source_url"] == record["url"] == URL
        assert json.loads(record["text"]) == {k: v for k, v in chapter.items() if k not in {"source", "evidence_id"}}
        expected = "ev_" + hashlib.sha256(f"{URL}|chapters.{i}|{MOOC_STRUCT_SOURCE}|{record['text']}".encode()).hexdigest()[:20]
        assert record["id"] == record["evidence_id"] == expected
    aggregate = records[resource["field_provenance"]["chapters"]["evidence_id"]]
    assert aggregate["id"] == "ev_" + hashlib.sha256(f"{URL}|chapters|{MOOC_STRUCT_SOURCE}|{chapters}".encode()).hexdigest()[:20]
    assert _snapshot(resource, evidence) is not None


def test_relation_changes_hash_even_when_flattened_titles_stay_identical_and_goals_are_not_lessons():
    nested, nested_evidence = observation([{"name": "Python parent", "plan": "Python child", "goals": "Never a chapter"}])
    flat, _ = observation([{"name": "Python parent"}, {"name": "Python child"}])
    assert [row["title"] for row in nested["chapters"]] == [row["title"] for row in flat["chapters"]]
    assert nested["chapters"][1]["evidence_id"] != flat["chapters"][1]["evidence_id"]
    assert nested["field_provenance"]["chapters"]["evidence_id"] != flat["field_provenance"]["chapters"]["evidence_id"]
    changed_goal, _ = observation([{"name": "Python parent", "plan": "Python child", "goals": "Entirely different teaching goal"}])
    assert changed_goal["chapters"] == nested["chapters"]
    tampered = deepcopy(nested)
    tampered["chapters"][1]["outline_parent_index"] = 1
    assert _snapshot(tampered, nested_evidence) is None


@pytest.mark.parametrize("changes", [{"course_id": "124"}, {"url": URL + "?tid=999"},
                                    {"url": URL.replace("www.icourse163.org", "example.org")}])
def test_hierarchy_does_not_bypass_course_term_or_host_binding(changes):
    resource, _ = observation(**changes)
    assert resource["chapters"] == []


@pytest.mark.parametrize("source", ["html.icourse163.termDto.outLineDto.outLine",
                                   "html.icourse163.course_outline.text", "jsonld.hasPart/syllabusSections",
                                   "html.bilibili.videoData.pages"])
def test_parent_field_is_not_adopted_from_other_catalog_sources(monkeypatch, source):
    from backend.app import extractor
    facts = SourceFacts(chapters=[{"title": "Parent", "source_url": URL},
                                 {"title": "Child", "source_url": URL, "outline_parent_index": 0}],
                        catalog_source=source, catalog_kind="course_outline")
    monkeypatch.setattr(extractor, "extract_source_facts", lambda *args: facts)
    result = MetadataExtractor().extract("<html><body>Local fixture</body></html>", URL, now())
    assert len(result["chapters"]) == 2
    assert all("outline_parent_index" not in row for row in result["chapters"])


@pytest.mark.parametrize("parent", [True, False, "0", -1, 1, 2, None])
def test_structured_parent_must_be_an_earlier_integer_root_index(monkeypatch, parent):
    from backend.app import extractor
    facts = SourceFacts(chapters=[{"title": "Parent", "source_url": URL},
                                 {"title": "Child", "source_url": URL, "outline_parent_index": parent}],
                        catalog_source=MOOC_STRUCT_SOURCE, catalog_kind="course_outline")
    monkeypatch.setattr(extractor, "extract_source_facts", lambda *args: facts)
    result = MetadataExtractor().extract("<html><body>Local fixture</body></html>", URL, now())
    assert "outline_parent_index" not in result["chapters"][1]


def test_paragraph_neighbors_are_not_promoted_to_parent_relations():
    resource, _ = observation(outline="<p>Python 数据结构</p><p>列表</p><p>字典</p>")
    assert len(resource["chapters"]) == 3
    assert all("outline_parent_index" not in row for row in resource["chapters"])


@pytest.mark.parametrize("damage", ["foreign_parent", "foreign_child", "nested_child"])
def test_structured_parent_cannot_cross_page_or_reference_another_child(monkeypatch, damage):
    from backend.app import extractor
    chapters = [{"title": "Parent", "source_url": URL},
                {"title": "Child", "source_url": URL, "outline_parent_index": 0},
                {"title": "Another child", "source_url": URL, "outline_parent_index": 0}]
    if damage == "foreign_parent":
        chapters[0]["source_url"] = URL.replace("123", "124")
    elif damage == "foreign_child":
        chapters[2]["source_url"] = URL.replace("123", "124")
    else:
        chapters[2]["outline_parent_index"] = 1
    facts = SourceFacts(chapters=chapters, catalog_source=MOOC_STRUCT_SOURCE, catalog_kind="course_outline")
    monkeypatch.setattr(extractor, "extract_source_facts", lambda *args: facts)
    result = MetadataExtractor().extract("<html><body>Local fixture</body></html>", URL, now())
    assert "outline_parent_index" not in result["chapters"][2]


def test_library_and_offline_import_preserve_bound_parent_field(tmp_path):
    config = Settings(teaching_match_enabled=False, shared_course_library_enabled=True)
    service = importer.memory_service(config)
    try:
        profile = service._course_library_profile()
    finally:
        service.store.close()
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    resource, evidence = observation()
    with closing(Store(str(source))) as store:
        assert CourseLibrary(store).observe(resource, evidence, profile)
        original = json.loads(store.connection.execute("SELECT data FROM shared_mooc_courses").fetchone()[0])
        assert original["resource"]["chapters"][2]["outline_parent_index"] == 0
    with closing(Store(str(target))):
        pass
    result = importer.run(source, target, tmp_path / "import", configured=config, apply=True,
                          points=["Python 列表与字典"])
    assert result["status"] == "applied" and result["counts"]["imported"] == 1
    with closing(Store(str(target))) as store:
        imported = json.loads(store.connection.execute("SELECT data FROM shared_mooc_courses").fetchone()[0])
        assert imported["resource"]["chapters"] == original["resource"]["chapters"]
        assert _snapshot(imported["resource"], imported["evidence"]) is not None
