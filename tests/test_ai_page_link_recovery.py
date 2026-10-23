"""One-hop source navigation requires independent own-video verification."""
import asyncio
from copy import deepcopy
import html
import json
from urllib.parse import urlsplit

import httpx
import pytest

from backend.app.ai_video_service import run_ai_video_fallback, visible_point_ids
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from test_ai_grounded_recovery import organic, recovery_service, visible
from test_ai_retained_recovery import POINT, retain, setup_retained


def video(index):
    return f"https://www.bilibili.com/video/BV{index:010}/"


def page(url, *, title="Streamlit 环境安装", chapters=(), leads=(), paid=False):
    data = {"videoData": {"bvid": urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1],
        "title": title, "desc": "公开来源视频介绍", "is_upower_exclusive": paid,
        "pages": [{"cid": index + 1, "page": index + 1, "part": label, "duration": 120}
                  for index, label in enumerate(chapters)]}}
    anchors = "".join(f'<a href="{html.escape(target, quote=True)}">{html.escape(label)}</a>' for target, label in leads)
    return '<html><head><title>Video page</title></head><body>' + anchors + \
        '<script>window.__INITIAL_STATE__=' + json.dumps(data, ensure_ascii=False) + ';</script></body></html>'


class ObservedPages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def enrich(self, candidate):
        self.calls.append(deepcopy(candidate))
        url = candidate["url"]
        assert url in self.pages, "Unexpected URL; fixture cannot contact the network"
        return MetadataExtractor().extract(self.pages[url], url, now())


async def seed_parent(service, job, state, url, *, point_index=0):
    rid = retain(service, job, state, url, point_index=point_index, title="Streamlit 环境安装")
    key, cached = service._page_cache(state["resources"][rid])
    state["started"].add(rid)
    if not cached:
        state["reserved"] += 1
    await service._enrich_one(job, state, rid, key, cached)
    return rid


async def recover(service, job, state, points=None):
    from backend.app.ai_video_service import _recover_from_page_links
    job.setdefault("ai_video_fallback", {})
    await _recover_from_page_links(service, job, state, points or state["points"])


def change_parent_origin(service, job, rid, kind):
    originals = [row for row in service.store.evidence(job["job_id"], rid) if row.get("kind") == "search"]
    for row in originals:
        service.store.connection.execute("DELETE FROM evidence WHERE job_id=? AND id=?", (job["job_id"], row["evidence_id"]))
        if kind is not None:
            row.update(kind=kind, source="offline-origin")
            service.store.add_evidence(job["job_id"], rid, row["knowledge_point_id"], row)
    service.store.connection.commit()


@pytest.mark.parametrize("origin", ["search", "ai_suggestion"])
@pytest.mark.parametrize("parent_paid", [False, True])
async def test_verified_parent_anchor_recovers_only_after_child_own_page_is_fetched(recovery_service, origin, parent_paid):
    service, searches, _ = recovery_service()
    job, state = setup_retained(service)
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 下载按钮")], paid=parent_paid),
        child: page(child, title="Streamlit 文件下载", chapters=["st.download_button"])})
    rid = await seed_parent(service, job, state, parent)
    if origin != "search": change_parent_origin(service, job, rid, origin)
    service.fetcher.calls.clear()
    assert not visible_point_ids(service, job)
    await recover(service, job, state)
    assert not searches and [row["url"] for row in service.fetcher.calls] == [child]
    candidate = service.fetcher.calls[0]
    assert candidate.get("title") == "" and candidate.get("snippet") == ""
    resource = next(row for row in service.store.resources(job["job_id"]).values() if row["url"] == child)
    evidence = service.store.evidence(job["job_id"], resource["resource_id"], state["points"][0]["knowledge_point_id"])
    origin_rows = [row for row in evidence if row["kind"] == "page_link"]
    assert origin_rows and origin_rows[0]["source_url"] == parent
    assert not any(row["kind"] == "search" for row in evidence)
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    rows = visible(service.results(job["job_id"])["groups"][0])
    assert rows and {row["resource"]["url"] for row in rows} == {child}
    assert rows[0]["reference"]["exact_teaching_verified"] is False


async def test_anchor_label_cannot_supply_missing_child_topic_evidence(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 文件下载 st.download_button")]),
        child: page(child, title="Streamlit 图表展示", chapters=["交互图表"])})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent, child]
    assert not visible_point_ids(service, job)


async def test_unbound_fetcher_page_link_cannot_create_primary_teaching_for_another_point(recovery_service):
    service, _, _ = recovery_service(teaching_match_enabled=True)
    job, state = setup_retained(service, (POINT, "图表展示"))
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 下载按钮")]),
        child: page(child, title="Streamlit 实用控件", chapters=["文件下载", "图表展示"])})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state, [state["points"][0]])
    child_resource = next(r for r in state["resources"].values() if r["canonical_url"] == child)
    service.store.add_evidence(job["job_id"], child_resource["resource_id"], None, {
        "evidence_id": "unbound-fetcher-navigation", "kind": "page_link", "source": "fetched_page_link",
        "url": child, "source_url": parent, "text": "", "observed_at": now()})
    groups = service.results(job["job_id"])["groups"]
    assert {row["resource"]["url"] for row in visible(groups[0])} == {child}
    assert not groups[1]["items"] and not groups[1]["partial_items"]
    # Existing reference policy can reuse genuinely observed own chapters for
    # another concept, without claiming primary or exact teaching support.
    related = groups[1]["related_recommendations"]
    assert related and {row["resource"]["url"] for row in related} == {child}
    assert all(row["reference"]["exact_teaching_verified"] is False for row in related)
    assert all("catalog" in row["reference"]["basis"] for row in related)


async def test_paid_link_does_not_close_gap_and_next_independent_free_page_can(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, paid, free = video(1), video(2), video(3)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(paid, "Streamlit 文件下载"), (free, "Streamlit 下载按钮")]),
        paid: page(paid, title="Streamlit 文件下载", paid=True), free: page(free, title="Streamlit 下载按钮")})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent, paid, free]
    rows = visible(service.results(job["job_id"])["groups"][0])
    assert rows and all(row["resource"]["url"] == free for row in rows)


@pytest.mark.parametrize("invalid", ["foreign-point", "stale-parent", "unverified", "no-discovery", "only-page-link"])
async def test_parent_must_be_fresh_verified_and_have_same_point_original_discovery(recovery_service, invalid):
    service, _, _ = recovery_service()
    job, state = setup_retained(service, (POINT, "图表展示"))
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 下载按钮")]),
        child: page(child, title="Streamlit 下载按钮")})
    rid = await seed_parent(service, job, state, parent, point_index=int(invalid == "foreign-point"))
    if invalid == "foreign-point": state["candidate_groups"][state["points"][0]["knowledge_point_id"]].append(rid)
    elif invalid == "stale-parent": state["resources"][rid]["cache"] = {"hit": True, "stale": True, "cached_at": now()}
    elif invalid == "unverified": state["resources"][rid]["video_evidence_status"] = "none"
    elif invalid == "no-discovery": change_parent_origin(service, job, rid, None)
    else: change_parent_origin(service, job, rid, "page_link")
    service.store.save_resource(job["job_id"], state["resources"][rid])
    service.fetcher.calls.clear()
    await recover(service, job, state, [state["points"][0]])
    assert not service.fetcher.calls


async def test_no_recursive_leads_even_if_child_later_has_independent_search_observation(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, child, grandchild = video(1), video(2), video(3)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 文件下载")]),
        child: page(child, leads=[(grandchild, "Streamlit 下载按钮")]),
        grandchild: page(grandchild, title="Streamlit 下载按钮")})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state)
    child_id = retain(service, job, state, child, title="Streamlit 环境安装")
    assert child_id in state.get("page_link_children", set())
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent, child]
    assert not visible_point_ids(service, job)


async def test_three_child_inspections_per_point_is_cumulative_across_calls(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, children = video(1), [video(index) for index in range(2, 7)]
    service.fetcher = ObservedPages({parent: page(parent, leads=[(url, "Streamlit 下载按钮") for url in children]),
        **{url: page(url) for url in children}})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state)
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent, *children[:3]]
    assert state["reserved"] == job["progress"]["details_attempted"] == 4


async def test_each_point_gets_first_link_before_any_second_link_under_shared_detail_cap(recovery_service):
    points = ["文件下载", "表单输入", "图表展示", "交互控件", "会话状态"]
    service, _, _ = recovery_service(max_detail_pages=10)
    job, state = setup_retained(service, points)
    parents, children, pages = [], [], {}
    for index, point in enumerate(points):
        parent, first, second = video(100 + index), video(200 + index), video(300 + index)
        parents.append(parent)
        children.append(first)
        pages[parent] = page(parent, leads=[(first, "Streamlit " + point), (second, "Streamlit " + point)])
        pages[first] = page(first, title="Streamlit " + point)
        pages[second] = page(second, title="Streamlit " + point)
    service.fetcher = ObservedPages(pages)
    for index, parent in enumerate(parents):
        await seed_parent(service, job, state, parent, point_index=index)
    service.fetcher.calls.clear()
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == children
    assert state["reserved"] == job["progress"]["details_attempted"] == 10
    assert len(visible_point_ids(service, job)) == 5


async def test_invalid_observed_links_never_become_network_targets(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent = video(1)
    bad = ["https://127.0.0.1/video/BV1000000002/", "https://example.org/video/BV1000000002/",
           "https://www.bilibili.com/search?keyword=download", video(2) + "?token=secret", "javascript:alert(1)"]
    service.fetcher = ObservedPages({parent: page(parent, leads=[(url, "Streamlit 下载按钮") for url in bad])})
    await seed_parent(service, job, state, parent)
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent]


async def test_private_lead_cache_is_revalidated_for_source_url_and_target_safety(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent)})
    rid = await seed_parent(service, job, state, parent)
    state["observed_video_leads"][rid] = [
        {"url": child, "title": "Streamlit 下载按钮", "source_url": video(99)},
        {"url": child + "?token=unexpected", "title": "Streamlit 下载按钮", "source_url": parent},
        {"url": "https://127.0.0.1/video/BV0000000002/", "title": "Streamlit 下载按钮", "source_url": parent},
        {"url": child, "title": "Django 下载按钮", "source_url": parent},
        {"url": child, "title": "x" * 301, "source_url": parent},
    ]
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent]


async def test_reserved_detail_limit_prevents_link_fetch_without_increasing_original_budget(recovery_service):
    service, _, _ = recovery_service(max_detail_pages=2)
    job, state = setup_retained(service)
    parent, child = video(1), video(2)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 下载按钮")])})
    await seed_parent(service, job, state, parent)
    state["detail_limit"] = state["reserved"]
    await recover(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent]
    assert state["reserved"] == job["progress"]["details_attempted"] == 1
    assert job["budgets"]["max_detail_pages"] == 2


@pytest.mark.parametrize("slow", [False, True])
async def test_observed_links_preserve_fresh_search_capacity_and_time_with_tiny_total_budget(recovery_service, monkeypatch, slow):
    parent, children, fresh = video(1), [video(index) for index in range(2, 5)], video(10)
    service, searches, _ = recovery_service(max_detail_pages=3,
        plan={POINT: {"urls": [], "queries": ["Streamlit 文件下载"]}},
        respond=lambda *_: httpx.Response(200, json={"organic": [organic("Streamlit 文件下载", fresh)]}))
    job, state = setup_retained(service, stopped=False)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(url, "Streamlit 下载按钮") for url in children]),
        **{url: page(url) for url in children}, fresh: page(fresh, title="Streamlit 文件下载")})
    await seed_parent(service, job, state, parent)
    stopped = asyncio.Event()
    if slow:
        original_enrich = service.fetcher.enrich
        async def slow_child(candidate):
            if candidate["url"] in children:
                service.fetcher.calls.append(deepcopy(candidate))
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            return await original_enrich(candidate)
        service.fetcher.enrich = slow_child
        original_timeout = asyncio.timeout
        monkeypatch.setattr(asyncio, "timeout", lambda delay: original_timeout(min(delay, 0.05)))
    await run_ai_video_fallback(service, job, state)
    assert [row["url"] for row in service.fetcher.calls] == [parent, children[0], fresh]
    assert len(searches) == 1 and visible_point_ids(service, job)
    assert state["reserved"] == job["progress"]["details_attempted"] == 3
    assert job["budgets"]["max_detail_pages"] == 3
    if slow:
        assert stopped.is_set() and job["ai_video_fallback"]["page_link_fetch_timed_out"] is True


async def test_cancellation_during_child_fetch_propagates_without_admission_or_more_children(recovery_service):
    service, _, _ = recovery_service()
    job, state = setup_retained(service)
    parent, child, other = video(1), video(2), video(3)
    service.fetcher = ObservedPages({parent: page(parent, leads=[(child, "Streamlit 下载按钮"), (other, "Streamlit 文件下载")])})
    await seed_parent(service, job, state, parent)
    started, stopped = asyncio.Event(), asyncio.Event()
    calls = []
    async def slow(candidate):
        calls.append(candidate["url"])
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    service.fetcher.enrich = slow
    task = asyncio.create_task(recover(service, job, state))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and len(calls) == 1 and calls[0] in {child, other}
        assert not visible_point_ids(service, job)
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
