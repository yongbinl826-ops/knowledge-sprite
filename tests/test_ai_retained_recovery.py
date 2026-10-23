"""Retained real-source leads still require actual parsed own-page evidence.

The source and HTML boundaries are synthetic; catalog parsing, enrichment,
SQLite, ranking and projection use production implementations.
"""
import asyncio
import json
from urllib.parse import urlsplit

import pytest

from backend.app.ai_video_service import _inspect_retained_candidates, run_ai_video_fallback, visible_point_ids
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, Query, SearchRequest, now
from backend.app.providers import SearchError
from test_ai_grounded_recovery import recovery_service, visible


POINT = "文件下载"
URL = "https://www.bilibili.com/video/BV1xx411c7Df/"


class CatalogPages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def enrich(self, candidate):
        url = candidate["url"]
        self.calls.append(url)
        title, chapters = self.pages[url]
        bvid = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        payload = {"videoData": {"bvid": bvid, "title": title, "desc": "公开课程目录",
            "pic": "https://i0.hdslb.com/bfs/archive/fixture.jpg",
            "pages": [{"cid": index + 100, "page": index + 1, "part": chapter, "duration": 120}
                      for index, chapter in enumerate(chapters)]}}
        html = '<html><head><title>Video page</title></head><body><script>window.__INITIAL_STATE__=' \
            + json.dumps(payload, ensure_ascii=False) + ';</script></body></html>'
        return MetadataExtractor().extract(html, url, now())


def setup_retained(service, points=(POINT,), *, stopped=True):
    request = SearchRequest(knowledge_points=list(points), preferred_platforms=["bilibili"],
                            topic_technologies={point: "Streamlit" for point in points})
    job = service.store.get_job(service.create(request)["job_id"])
    job.update(status="running", phase="fetching")
    service._save(job)
    points = job["knowledge_points"]
    state = {"request": request, "points": points,
        "point_map": {point["knowledge_point_id"]: point for point in points},
        "resources": {}, "candidates": {}, "candidate_groups": {point["knowledge_point_id"]: [] for point in points},
        "started": set(), "reserved": 0, "detail_limit": service.settings.max_detail_pages,
        "ready": True, "search_finished": True, "changed": asyncio.Event(),
        "cursor": 0, "network_slots": asyncio.Semaphore(3)}
    if stopped:
        service._ai_search_source = lambda *_args, **_kwargs: (
            "searxng", None, SearchError("source_stopped", "搜索来源暂时受限"))
    return job, state


def retain(service, job, state, url=URL, *, point_index=0, title="Streamlit 完整课程"):
    point = state["points"][point_index]
    row = Candidate(id="retained-" + str(len(state["resources"])), title=title, url=url,
                    source="offline-source", query=point["text"], snippet="Streamlit 入门课程和完整目录")
    service._record_search_candidates(job, state,
        Query(knowledge_point_id=point["knowledge_point_id"], query=point["text"], domain_filters=["bilibili.com"]),
        [row], {"hit": False, "cached_at": None, "stale": False})
    return next(rid for rid, resource in state["resources"].items() if resource["canonical_url"] == url)


async def test_stopped_search_can_recover_existing_point_bound_course_through_own_catalog(recovery_service):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service)
    rid = retain(service, job, state)
    service.fetcher = CatalogPages({URL: ("Streamlit 完整课程", ["环境安装", "文件下载 st.download_button()"] )})
    assert not visible_point_ids(service, job)
    await run_ai_video_fallback(service, job, state)
    assert not searches and service.fetcher.calls == [URL]
    assert job["ai_video_fallback"]["retained_pages_inspected"] == 1
    assert job["ai_video_fallback"]["remaining_points"] == 0
    resource = service.store.resources(job["job_id"])[rid]
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    rows = visible(service.results(job["job_id"])["groups"][0])
    assert rows and rows[0]["reference"]["exact_teaching_verified"] is False
    assert "catalog" in rows[0]["reference"]["basis"]


async def test_retained_foreign_point_observation_cannot_be_scheduled_for_gap(recovery_service):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service, (POINT, "图表展示"))
    rid = retain(service, job, state, point_index=1)
    target = state["points"][0]
    state["candidate_groups"][target["knowledge_point_id"]].append(rid)
    job["ai_video_fallback"] = {}
    service.fetcher = CatalogPages({URL: ("Streamlit 完整课程", ["文件下载 st.download_button()"] )})
    await _inspect_retained_candidates(service, job, state, [target])
    assert not searches and not service.fetcher.calls
    assert not visible_point_ids(service, job)


@pytest.mark.parametrize("chapters", [["环境安装", "交互图表"], ["开始前下载GitHub资料", "file_uploader 上传文件"]])
async def test_generic_or_prerequisite_download_course_is_not_admitted_without_real_topic(chapters, recovery_service):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service)
    retain(service, job, state)
    service.fetcher = CatalogPages({URL: ("Streamlit 完整课程", chapters)})
    await run_ai_video_fallback(service, job, state)
    assert not searches and service.fetcher.calls == [URL]
    assert not visible_point_ids(service, job)
    assert job["ai_video_fallback"]["remaining_points"] == 1


async def test_retained_inspections_allocate_each_point_first_page_within_total_budget(recovery_service):
    points = ["文件下载", "表单输入", "图表展示", "交互控件", "会话状态"]
    service, searches, _ = recovery_service(max_detail_pages=5)
    job, state = setup_retained(service, points)
    pages, first_urls = {}, []
    for index, point in enumerate(points):
        for extra in range(3):
            url = f"https://www.bilibili.com/video/BV1xx411c{index}{extra}f/"
            retain(service, job, state, url, point_index=index)
            pages[url] = ("Streamlit 完整课程", [point])
            if not extra:
                first_urls.append(url)
    service.fetcher = CatalogPages(pages)
    await run_ai_video_fallback(service, job, state)
    assert not searches and service.fetcher.calls == first_urls
    assert job["ai_video_fallback"]["retained_pages_inspected"] == 5
    assert job["progress"]["details_attempted"] == 5 and state["reserved"] == 5
    assert len(visible_point_ids(service, job)) == 5


async def test_retained_inspection_never_exceeds_three_candidates_for_one_gap(recovery_service):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service)
    urls, pages = [], {}
    for index in range(4):
        url = f"https://www.bilibili.com/video/BV1xx411c7D{index}/"
        urls.append(url)
        retain(service, job, state, url)
        pages[url] = ("Streamlit 完整课程", ["文件下载 st.download_button()"] if index == 3 else ["环境安装"])
    service.fetcher = CatalogPages(pages)
    await run_ai_video_fallback(service, job, state)
    assert not searches and service.fetcher.calls == urls[:3]
    assert job["ai_video_fallback"]["retained_pages_inspected"] == 3
    assert job["ai_video_fallback"]["remaining_points"] == 1


async def test_cancellation_during_retained_fetch_stops_work_without_admission(recovery_service):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service)
    retain(service, job, state)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def wait_page(_candidate):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    service.fetcher.enrich = wait_page
    task = asyncio.create_task(run_ai_video_fallback(service, job, state))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and not searches
        assert not visible_point_ids(service, job)
        assert job["ai_video_fallback"]["status"] == "interrupted"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
