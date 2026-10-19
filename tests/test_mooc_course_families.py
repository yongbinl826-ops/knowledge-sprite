"""Distinct-course targets never combine semester evidence or inflate recall."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.course_library import CourseLibrary, course_entry_key, course_family_key
from backend.app.discovery_display import discovered_video, display_discovered_videos
from backend.app.extractor import MetadataExtractor
from backend.app.mooc_urls import course_identity_parts
from test_mooc_relevance_service import discover, enrich, setup, synthetic_outline


def url(course="123", term=None):
    return "https://www.icourse163.org/course/OWN-" + course + ("?tid=" + term if term else "")


def test_course_family_ignores_alias_and_term_without_changing_entry_identity():
    entries = [url(), url(term="456"), url(term="789"),
               "https://icourse163.org/course/detail.htm?cid=123&tid=456",
               "https://www.icourse163.org/course/OTHER-123?outVendor=public"]
    assert len({course_family_key(value) for value in entries}) == 1
    assert len({course_entry_key(value) for value in entries}) == 3
    assert course_family_key(url("124")) != course_family_key(url())
    assert course_family_key("https://www.icourse163.org/learn/OWN-123") is None
    assert course_family_key(url() + "?token=private") is None


async def add_course(service, job, state, fetcher, course, term, chapters=("列表", "字典")):
    entry = url(course, term)
    fetcher.documents[entry] = synthetic_outline(course_id=course, term_id=term, chapters=chapters)
    rid = discover(service, job, state, entry)
    await enrich(service, job, state, rid)
    return rid


@pytest.mark.asyncio
async def test_three_semesters_count_as_one_three_course_ids_count_as_three_and_bilibili_unchanged():
    service, job, state, fetcher = setup(detail_budget=8)
    try:
        point = state["points"][0]
        bili = [discover(service, job, state, "https://www.bilibili.com/video/" + bv + "/")
                for bv in ("BV1VZ4y1G7YB", "BV1Ab4y1W7xT")]
        baseline = display_discovered_videos([discovered_video(point, state["resources"][rid],
                    service.store.evidence(job["job_id"], rid)) for rid in bili])[0]
        for term in ("456", "789", "999"):
            await add_course(service, job, state, fetcher, "123", term)
        assert service._mooc_coverage_count(job, point, state) == 1
        assert service.results(job["job_id"])["groups"][0]["mooc_relevance"]["recommended_count"] == 1

        for course in ("124", "125"):
            await add_course(service, job, state, fetcher, course, "456")
        group = service.results(job["job_id"])["groups"][0]
        assert service._mooc_coverage_count(job, point, state) == 3
        assert group["mooc_relevance"]["recommended_count"] == 3
        assert group["discovery_platform_items"]["bilibili"] == baseline
        assert len(group["mooc_relevance"]["candidates"]) == 5
        for diagnostic in group["mooc_relevance"]["candidates"]:
            assert diagnostic["assessment"]["display_eligible"]
            assert {chapter["source_url"] for chapter in diagnostic["assessment"]["matched_chapters"]} == {diagnostic["url"]}
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_complementary_semesters_cannot_pool_chapters_into_a_complete_course():
    service, job, state, fetcher = setup()
    try:
        point = state["points"][0]
        for term, chapters in (("456", ("列表",)), ("789", ("字典",))):
            await add_course(service, job, state, fetcher, "123", term, chapters)
        group = service.results(job["job_id"])["groups"][0]
        assert service._mooc_coverage_count(job, point, state) == 0
        assert not group["discovery_platform_items"].get("icourse163")
        assert {row["assessment"]["status"] for row in group["mooc_relevance"]["candidates"]} == {"outline_partial"}
        await add_course(service, job, state, fetcher, "123", "999")
        group = service.results(job["job_id"])["groups"][0]
        assert service._mooc_coverage_count(job, point, state) == 1
        assert [row["resource"]["url"] for row in group["discovery_platform_items"]["icourse163"]] == [url(term="999")]
        assert sum(row["assessment"]["status"] == "outline_partial" for row in group["mooc_relevance"]["candidates"]) == 2
    finally:
        service.store.close()


def test_library_seed_reads_past_duplicate_terms_and_preserves_all_entry_observations():
    service, job, state, fetcher = setup()
    try:
        service.settings = replace(service.settings, shared_course_library_enabled=True,
            shared_course_library_max_candidates=10, mooc_target_courses_per_point=3)
        service.course_library = CourseLibrary(service.store, max_candidates=10)
        profile = service._course_library_profile()
        entries = [("123", "456"), ("123", "789"), ("123", "999"),
                   ("124", "456"), ("125", "456"), ("126", "456")]
        stamp = datetime.now(timezone.utc) - timedelta(seconds=10)
        for index, (course, term) in enumerate(entries):
            entry = url(course, term)
            resource = MetadataExtractor().extract(synthetic_outline(course_id=course, term_id=term),
                entry, (stamp - timedelta(seconds=index)).isoformat())
            evidence = resource.pop("evidence")
            resource.update(url=entry, canonical_url=entry, platform="icourse163")
            assert service.course_library.observe(resource, evidence, profile)
        before = [tuple(row) for row in service.store.connection.execute("SELECT * FROM shared_mooc_courses ORDER BY entry_key")]
        hits = service.course_library.lookup(state["points"][0], profile, limit=10)
        assert [course_identity_parts(hit["resource"]["url"])["course_id"] for hit in hits[:5]] == ["123", "123", "123", "124", "125"]

        service._seed_course_library(job, state)
        resources = list(state["resources"].values())
        assert {course_identity_parts(resource["url"])["course_id"] for resource in resources} == {"123", "124", "125"}
        assert len(resources) == 3
        assert job["progress"]["library_courses_reused"] == 3
        assert service._mooc_coverage_count(job, state["points"][0], state) == 3
        group = service.results(job["job_id"])["groups"][0]
        assert group["mooc_relevance"]["recommended_count"] == 3
        for row in group["discovery_platform_items"]["icourse163"]:
            assert {chapter["source_url"] for chapter in row["mooc_relevance"]["matched_chapters"]} == {row["resource"]["url"]}
        assert [tuple(row) for row in service.store.connection.execute("SELECT * FROM shared_mooc_courses ORDER BY entry_key")] == before
        assert len(service.course_library.lookup(state["points"][0], profile, limit=10)) == 6
        assert fetcher.calls == []
    finally:
        service.store.close()
