"""Import reporting counts courses while retaining every semester observation."""
from copy import deepcopy

import httpx
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.mooc_urls import course_identity_parts
from scripts import import_verified_mooc_library as importer
from test_mooc_relevance_service import synthetic_outline


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Import reporting tests must not access environment credentials or HTTP")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def seed(service, course, term, chapters=("列表", "字典")):
    url = f"https://www.icourse163.org/course/OWN-{course}?tid={term}"
    resource = MetadataExtractor().extract(synthetic_outline(course_id=course, term_id=term,
        chapters=chapters), url, now())
    evidence = resource.pop("evidence")
    resource.update(url=url, canonical_url=url, platform="icourse163")
    assert service.course_library.observe(resource, evidence, service._course_library_profile())
    return url


def test_import_report_counts_three_verified_semesters_as_one_without_mutating_the_library():
    service = importer.memory_service(Settings(teaching_match_enabled=False, shared_course_library_enabled=True))
    try:
        urls = {seed(service, "123", term) for term in ("101", "102", "103")}
        source_rows = [tuple(row) for row in service.store.connection.execute("SELECT * FROM shared_mooc_courses ORDER BY entry_key")]
        assert len(source_rows) == 3
        changes = service.store.connection.total_changes
        report = importer.point_lookup(service, ["Python 列表与字典"])
        assert report[0]["qualified_count"] == len(report[0]["courses"]) == 1
        assert report[0]["courses"][0]["url"] in urls
        assert service.store.connection.total_changes == changes
        assert [tuple(row) for row in service.store.connection.execute("SELECT * FROM shared_mooc_courses ORDER BY entry_key")] == source_rows
    finally:
        service.store.close()


def test_import_report_reads_past_duplicate_terms_and_never_pools_partial_semesters():
    service = importer.memory_service(Settings(teaching_match_enabled=False, shared_course_library_enabled=True))
    try:
        for term in ("101", "102", "103"):
            seed(service, "123", term)
        seed(service, "124", "101", ("列表",))
        seed(service, "124", "102", ("字典",))
        seed(service, "125", "101")
        before = deepcopy(service.course_library.stats())
        report = importer.point_lookup(service, ["Python 列表与字典"])[0]
        assert report["qualified_count"] == len(report["courses"]) == 2
        assert {course_identity_parts(course["url"])["course_id"] for course in report["courses"]} == {"123", "125"}
        assert service.course_library.stats() == before
        assert before["total"] == 6
    finally:
        service.store.close()
