"""Offline Store/JobService regression for MOOC outline admission.

Retained HTML is replayed through the actual extractor and enrichment ID
remapping. Small synthetic pages below test boundaries, not real recall quality.
No search, page HTTP request, model call, or production database is used.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.discovery_display import discovered_video, display_discovered_videos
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, Query, SearchRequest
from backend.app.service import JobService


FIXTURES = Path(__file__).parent / "fixtures/mooc_structure"
STAMP = "offline-mooc-service-regression"
POINT = "Python 列表与字典"


class FixtureFetcher:
    def __init__(self):
        self.documents = {}
        self.calls = []

    async def enrich(self, candidate):
        url = candidate["url"]
        self.calls.append(url)
        if url not in self.documents:
            return {"fetch_status": "policy_unreviewed", "evidence": []}
        return MetadataExtractor().extract(self.documents[url], url, STAMP)


def setup(points=(POINT,), *, detail_budget=6):
    fetcher = FixtureFetcher()
    service = JobService(Settings(teaching_match_enabled=False, max_detail_pages=detail_budget,
                                  global_concurrency=1), Store(":memory:"), fetcher=fetcher)
    request = SearchRequest(knowledge_points=list(points), preferred_platforms=["bilibili", "icourse163"])
    job = service.store.get_job(service.create(request)["job_id"])
    points = job["knowledge_points"]
    state = {"request": request, "points": points,
             "point_map": {point["knowledge_point_id"]: point for point in points},
             "resources": {}, "candidates": {},
             "candidate_groups": {point["knowledge_point_id"]: [] for point in points},
             "ready": True, "search_finished": True, "changed": asyncio.Event(),
             "started": set(), "reserved": 0, "cursor": 0, "network_slots": asyncio.Semaphore(1)}
    return service, job, state, fetcher


def discover(service, job, state, url, *, title=POINT, snippet=POINT + " 教学课程", point_index=0):
    point = state["points"][point_index]
    candidate = Candidate(id=f"test-{len(state['candidates'])}", url=url, title=title, snippet=snippet,
                          source="offline-fixture-search", query=point["text"])
    service._record_search_candidates(job, state,
        Query(knowledge_point_id=point["knowledge_point_id"], query=point["text"]),
        [candidate], {"hit": False, "cached_at": None, "stale": False})
    return next(rid for rid, resource in state["resources"].items() if resource["url"] == url)


async def enrich(service, job, state, rid):
    state["started"].add(rid)
    state["reserved"] += 1
    await service._enrich_one(job, state, rid, "offline-page-" + rid, None)


def synthetic_outline(*, course_id="123", term_id="456", chapters=("列表", "字典")):
    """Extractable synthetic page with literal own-course and term identifiers."""
    term = {"id": term_id, "outLineDto": {"outLine": "",
             "outLineStructureDtos": [{"name": title, "plan": "", "goals": ""} for title in chapters]}}
    course = {"id": course_id, "name": "Python程序设计"}
    return ("<html><body><div id='j-course-heading-intro'><div class='course-heading-intro_intro'></div></div>"
            "<div id='j-rectxt'>spContent=本课程讲授Python程序设计，包含循序渐进的课程内容和练习。</div>"
            "<div id='j-course-outline'></div><script>window.termDto = " + json.dumps(term)
            + "; window.courseDto = " + json.dumps(course) + ";</script></body></html>")


def diagnostic(group, rid):
    return next(row["assessment"] for row in group["mooc_relevance"]["candidates"] if row["resource_id"] == rid)


@pytest.mark.asyncio
async def test_retained_outline_support_survives_real_enrichment_and_preserves_bilibili_cards_and_store():
    service, job, state, fetcher = setup((POINT, "Python 不相关目标"))
    expected = json.loads((FIXTURES / "01-expected.json").read_text("utf-8"))
    url = expected["url"]
    fetcher.documents[url] = (FIXTURES / "01-own-outline.html").read_text("utf-8")
    mooc_id = discover(service, job, state, url, title=expected["title"])
    # These are ordinary unverified Bilibili search cards, including a broad
    # title. MOOC-specific admission must not strengthen their old display gate.
    bili_ids = [discover(service, job, state, f"https://www.bilibili.com/video/{bv}/", title=title)
                for bv, title in [("BV1VZ4y1G7YB", POINT), ("BV1Ab4y1W7xT", "Python综合课程")]]
    await enrich(service, job, state, mooc_id)
    resources = service.store.resources(job["job_id"])
    before_evidence = {rid: service.store.evidence(job["job_id"], rid) for rid in resources}
    point = state["points"][0]
    baseline = display_discovered_videos([discovered_video(point, resources[rid], before_evidence[rid])
                                         for rid in bili_ids])[0]
    before_changes = service.store.connection.total_changes
    result = service.results(job["job_id"])
    assert service.results(job["job_id"]) == result
    group = result["groups"][0]
    assert group["discovery_platform_items"]["bilibili"] == baseline
    mooc = group["discovery_platform_items"]["icourse163"]
    assert len(mooc) == 1 and mooc[0]["resource"]["resource_id"] == mooc_id
    assessment = mooc[0]["mooc_relevance"]
    assert assessment["status"] == "outline_supported"
    assert {row["text"] for row in assessment["subtopics"] if row["status"] == "supported"} == {"列表", "字典"}
    catalog_ids = {row["evidence_id"] for row in before_evidence[mooc_id] if row["kind"] == "catalog"}
    assert set(assessment["evidence_ids"]) <= {row["evidence_id"] for row in before_evidence[mooc_id]}
    assert {chapter["evidence_id"] for chapter in assessment["matched_chapters"]} <= catalog_ids
    assert all(set(part["evidence_ids"]) & catalog_ids for part in assessment["subtopics"])
    assert {row["title"] for row in assessment["matched_chapters"]} >= {"3.3 列表", "3.6 字典"}
    assert all(row["source_url"] == url for row in assessment["matched_chapters"])
    # Production enrichment replaces the evidence UUID while retaining the
    # extractor's content-bound id, rather than weakening the hash check.
    chapters = resources[mooc_id]["chapters"]
    catalog = {row["evidence_id"]: row for row in before_evidence[mooc_id] if row["kind"] == "catalog"}
    assert all(catalog[chapter["evidence_id"]]["id"] != chapter["evidence_id"] for chapter in chapters)
    assert group["items"] == group["partial_items"] == group["review_items"] == []
    assert not mooc[0]["resource"].get("playback_verified")
    other_group = result["groups"][1]
    assert other_group["discovery_items"] == [] and other_group["mooc_relevance"]["candidate_count"] == 0
    assert service.store.connection.total_changes == before_changes
    assert service.store.resources(job["job_id"]) == resources
    assert {rid: service.store.evidence(job["job_id"], rid) for rid in resources} == before_evidence
    service.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected_status", [
    ("unrelated", "rejected"), ("prerequisite", "rejected"),
    ("pending", "search_candidate"), ("partial", "outline_partial"),
])
async def test_unrelated_prerequisite_pending_and_partial_mooc_are_diagnostics_not_recommendations(case, expected_status):
    service, job, state, fetcher = setup()
    url = "https://www.icourse163.org/course/OWN-123"
    title, snippet = POINT, POINT + " 课程"
    if case == "unrelated":
        title, snippet = "高等数学", "极限、导数、积分的课程"
    elif case == "prerequisite":
        title, snippet = "Python数据分析", "预备知识：学习者需要预先掌握Python列表与字典。课程讲授可视化。"
    rid = discover(service, job, state, url, title=title, snippet=snippet)
    if case == "partial":
        fetcher.documents[url] = synthetic_outline(chapters=("列表", "程序安装"))
        await enrich(service, job, state, rid)
    group = service.results(job["job_id"])["groups"][0]
    assert group["discovery_items"] == []
    assert group["mooc_relevance"]["recommended_count"] == 0
    assert diagnostic(group, rid)["status"] == expected_status
    assert len(service.store.resources(job["job_id"])) == 1
    if case == "partial":
        assessment = diagnostic(group, rid)
        assert [(row["text"], row["status"]) for row in assessment["subtopics"]] == [("列表", "supported"), ("字典", "not_observed")]
    service.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("damage,reason", [
    ("resource_text", "outline_chapter_text_mismatch"),
    ("source_hash", "outline_chapter_hash_mismatch"),
])
async def test_resource_chapter_edit_or_source_hash_damage_cannot_reuse_catalog_evidence(damage, reason):
    service, job, state, fetcher = setup()
    url = "https://www.icourse163.org/course/OWN-123"
    fetcher.documents[url] = synthetic_outline(chapters=("列表", "程序安装"))
    rid = discover(service, job, state, url)
    await enrich(service, job, state, rid)
    resource = service.store.resources(job["job_id"])[rid]
    if damage == "resource_text":
        resource["chapters"][1]["title"] = "字典"
        service.store.save_resource(job["job_id"], resource)
    else:
        eid = resource["chapters"][1]["evidence_id"]
        row = next(row for row in service.store.evidence(job["job_id"], rid) if row["evidence_id"] == eid)
        row["id"] = "ev_damaged_original_source_hash"
        service.store.connection.execute("UPDATE evidence SET data=? WHERE id=?", (json.dumps(row), eid))
        service.store.connection.commit()
    group = service.results(job["job_id"])["groups"][0]
    assert group["discovery_items"] == []
    assert reason in diagnostic(group, rid)["reason_codes"]
    service.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("urls", [
    ["https://www.icourse163.org/course/OWN-123?outVendor=" + value for value in ("first", "second")],
    ["https://www.icourse163.org/course/OWN-123", "https://www.icourse163.org/course/OTHER-123"],
    ["https://www.icourse163.org/course/OWN-123", "https://www.icourse163.org/course/detail.htm?cid=123"],
])
async def test_native_aliases_fetch_independently_then_deduplicate_without_rewriting_links(urls):
    service, job, state, fetcher = setup()
    ids = []
    for url in urls:
        fetcher.documents[url] = synthetic_outline()
        rid = discover(service, job, state, url)
        await enrich(service, job, state, rid)
        ids.append(rid)
    group = service.results(job["job_id"])["groups"][0]
    assert fetcher.calls == urls
    assert group["mooc_relevance"]["status_counts"] == {"outline_supported": 2}
    rows = group["discovery_platform_items"]["icourse163"]
    assert len(rows) == 1 and group["mooc_relevance"]["recommended_count"] == 1
    assert rows[0]["resource"]["url"] in urls
    resources = service.store.resources(job["job_id"])
    for rid, url in zip(ids, urls):
        assert resources[rid]["url"] == resources[rid]["canonical_url"] == url
        assert diagnostic(group, rid)["display_eligible"]
        assert {row["source_url"] for row in diagnostic(group, rid)["matched_chapters"]} == {url}
        evidence = service.store.evidence(job["job_id"], rid)
        assert {row["url"] for row in evidence if row["kind"] in {"search", "page", "catalog"}} == {url}
        assert set(diagnostic(group, rid)["evidence_ids"]) <= {row["evidence_id"] for row in evidence}
    service.store.close()


@pytest.mark.asyncio
async def test_trailing_slash_copies_deduplicate_only_after_independent_outline_verification():
    service, job, state, fetcher = setup()
    urls = ["https://www.icourse163.org/course/OWN-123", "https://www.icourse163.org/course/OWN-123/"]
    ids = []
    for url in urls:
        fetcher.documents[url] = synthetic_outline()
        rid = discover(service, job, state, url)
        await enrich(service, job, state, rid)
        ids.append(rid)
    group = service.results(job["job_id"])["groups"][0]
    assert group["mooc_relevance"]["status_counts"] == {"outline_supported": 2}
    rows = group["discovery_platform_items"]["icourse163"]
    assert len(rows) == 1 and group["mooc_relevance"]["recommended_count"] == 1
    assert rows[0]["resource"]["url"] in urls
    source_ids = {row["evidence_id"] for row in service.store.evidence(job["job_id"], rows[0]["resource"]["resource_id"])}
    assert set(rows[0]["mooc_relevance"]["evidence_ids"]) <= source_ids
    assert all(diagnostic(group, rid)["display_eligible"] for rid in ids)
    service.store.close()


@pytest.mark.asyncio
async def test_distinct_verified_terms_count_once_without_transferring_outline():
    service, job, state, fetcher = setup()
    urls = ["https://www.icourse163.org/course/OWN-123?tid=" + term for term in ("456", "789")]
    for url, term in zip(urls, ("456", "789")):
        fetcher.documents[url] = synthetic_outline(term_id=term)
        rid = discover(service, job, state, url)
        await enrich(service, job, state, rid)
    pending_url = "https://www.icourse163.org/course/OWN-123?tid=999"
    pending = discover(service, job, state, pending_url)
    group = service.results(job["job_id"])["groups"][0]
    rows = group["discovery_platform_items"]["icourse163"]
    assert len(rows) == 1 and rows[0]["resource"]["url"] in urls
    assert diagnostic(group, pending)["status"] == "search_candidate"
    verified = [row for row in group["mooc_relevance"]["candidates"] if row["url"] in urls]
    assert len(verified) == 2
    for row in verified:
        assert row["assessment"]["display_eligible"]
        assert {chapter["source_url"] for chapter in row["assessment"]["matched_chapters"]} == {row["url"]}
    for row in rows:
        assert {chapter["source_url"] for chapter in row["mooc_relevance"]["matched_chapters"]} == {row["resource"]["url"]}
    service.store.close()


def test_detail_queue_alternates_across_rebuilds_and_preserves_legacy_bilibili_order():
    service, job, state, _ = setup()
    bili = [discover(service, job, state, f"https://www.bilibili.com/video/{bv}/")
            for bv in ("BV1VZ4y1G7YB", "BV1Ab4y1W7xT", "BV1CS4y1G7xQ")]
    pid = state["points"][0]["knowledge_point_id"]
    baseline = service._detail_queues(job, state)[pid]
    assert set(baseline) == set(bili)
    service.settings = replace(service.settings, teaching_match_enabled=True)
    assert service._detail_queues(job, state)[pid] == baseline
    service.settings = replace(service.settings, teaching_match_enabled=False)
    mooc = [discover(service, job, state, f"https://www.icourse163.org/course/OWN-{number}") for number in (123, 124, 125)]
    unrelated = discover(service, job, state, "https://www.icourse163.org/course/OWN-999", title="高等数学", snippet="导数与积分")
    first = service._detail_queues(job, state)[pid]
    assert [rid for rid in first if rid in bili] == baseline
    assert unrelated not in first and set(first) == set(bili + mooc)
    assert first[0] in bili and first[1] in mooc
    state["started"].add(first[0])
    second = service._detail_queues(job, state)[pid]
    assert second[0] in mooc
    state["started"].add(second[0])
    third = service._detail_queues(job, state)[pid]
    assert third[0] == baseline[1]
    assert state["reserved"] == 0 and not job.get("budget_limited")
    service.store.close()


@pytest.mark.asyncio
async def test_real_detail_scheduler_keeps_existing_budget_and_spends_it_on_both_platforms():
    service, job, state, fetcher = setup(detail_budget=2)
    bili = [discover(service, job, state, f"https://www.bilibili.com/video/{bv}/")
            for bv in ("BV1VZ4y1G7YB", "BV1Ab4y1W7xT")]
    mooc = []
    for number in (123, 124):
        url = f"https://www.icourse163.org/course/OWN-{number}"
        fetcher.documents[url] = synthetic_outline(course_id=str(number))
        mooc.append(discover(service, job, state, url))
    unrelated = discover(service, job, state, "https://www.icourse163.org/course/OWN-999", title="高等数学", snippet="导数与积分")
    await asyncio.wait_for(service._run_details(job, state), timeout=5)
    assert len(fetcher.calls) == state["reserved"] == job["progress"]["details_attempted"] == 2
    assert job["progress"]["details_completed"] == 2
    assert {urlsplit(url).hostname for url in fetcher.calls} == {"www.bilibili.com", "www.icourse163.org"}
    assert len(set(bili) & state["started"]) == len(set(mooc) & state["started"]) == 1
    assert unrelated not in state["started"] and job["budget_limited"] is True
    group = service.results(job["job_id"])["groups"][0]
    assert len(group["discovery_platform_items"]["bilibili"]) == 2
    assert len(group["discovery_platform_items"]["icourse163"]) == 1
    service.store.close()
