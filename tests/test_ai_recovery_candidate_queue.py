"""A provider's first three misleading snippets cannot hide its fourth page."""
import httpx
import pytest

from backend.app.ai_video_service import visible_point_ids
from backend.app.models import SearchRequest
from test_ai_grounded_recovery import recovery_service, visible
from test_ai_retained_recovery import CatalogPages


POINT = "文本分段"
URLS = [f"https://www.bilibili.com/video/BV1xx411c7D{letter}/" for letter in "fghijk"]


def misleading_search_rows(urls):
    # All tie in discovery priority. Search claims alone are not page facts.
    return [{"title": "Python 编程课程", "link": url,
             "snippet": "Joining and Splitting a String; Python tutorial"} for url in urls]


async def execute(service, points=(POINT,)):
    identifier = service.create(SearchRequest(knowledge_points=list(points), preferred_platforms=["bilibili"],
        topic_technologies={point: "Python" for point in points}))["job_id"]
    await service.run(identifier)
    return service.store.get_job(identifier), service.results(identifier)


def own_rows(group):
    return [row for row in visible(group) if set(row.get("reference", {}).get("basis", [])) & {"page", "catalog"}
            or row.get("match", {}).get("supporting_evidence_ids")]


@pytest.mark.parametrize("teaching", [False, True])
async def test_fourth_returned_page_recovers_without_another_search_and_stops_after_match(teaching, recovery_service):
    service, searches, _ = recovery_service(plan={POINT: {"urls": [], "queries": []}},
        respond=lambda *_: httpx.Response(200, json={"organic": misleading_search_rows(URLS[:5])}),
        teaching_match_enabled=teaching)
    service.fetcher = CatalogPages({url: ("Python 编程课程", [
        "字符串_split()分割_join()合并" if index == 3 else "列表排序与循环遍历"])
        for index, url in enumerate(URLS[:5])})
    job, result = await execute(service)
    assert searches == ["site:bilibili.com Python 文本分段"]
    assert service.fetcher.calls == URLS[:4]
    assert job["progress"]["details_attempted"] == 4
    assert job["ai_video_fallback"]["remaining_points"] == 0
    rows = own_rows(result["groups"][0])
    assert rows and {row["resource"]["url"] for row in rows} == {URLS[3]}
    assert rows[0]["resource"]["video_evidence_status"] == "page_verified"
    cited = set(rows[0]["reference"]["evidence_ids"])
    evidence = service.store.evidence(job["job_id"], rows[0]["resource"]["resource_id"])
    assert any(row.get("kind") == "catalog" and row.get("field") == "chapters.0"
               and row["evidence_id"] in cited and "split()" in str(row.get("text")) for row in evidence)


async def test_fourth_candidate_does_not_override_original_three_page_budget(recovery_service):
    service, searches, _ = recovery_service(plan={POINT: {"urls": [], "queries": []}}, max_detail_pages=3,
        respond=lambda *_: httpx.Response(200, json={"organic": misleading_search_rows(URLS[:5])}))
    service.fetcher = CatalogPages({url: ("Python 编程课程", [
        "字符串_split()分割" if index == 3 else "列表排序"])
        for index, url in enumerate(URLS[:5])})
    job, result = await execute(service)
    assert service.fetcher.calls == URLS[:3]
    assert len(searches) == 1
    assert job["progress"]["details_attempted"] == 3
    assert job["ai_video_fallback"]["remaining_points"] == 1
    assert not own_rows(result["groups"][0])


async def test_queue_keeps_other_points_first_page_before_fourth_candidate(recovery_service):
    other = "列表排序"
    other_url = URLS[5]

    def respond(query, _count):
        rows = ([{"title": "Python 列表排序教程", "link": other_url, "snippet": "Python 列表排序"}]
                if other in query else misleading_search_rows(URLS[:5]))
        return httpx.Response(200, json={"organic": rows})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": []} for point in (POINT, other)},
        respond=respond, max_detail_pages=5)
    pages = {url: ("Python 编程课程", ["字符串_split()分割" if index == 3 else "文件读取"])
             for index, url in enumerate(URLS[:5])}
    pages[other_url] = ("Python 列表排序教程", ["列表排序"])
    service.fetcher = CatalogPages(pages)
    job, _ = await execute(service, (POINT, other))
    assert set(service.fetcher.calls[:2]) == {URLS[0], other_url}
    assert service.fetcher.calls[2:] == URLS[1:4]
    assert len(searches) == 2
    assert job["progress"]["details_attempted"] == 5
    assert len(visible_point_ids(service, job)) == 2
