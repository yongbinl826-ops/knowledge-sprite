"""Offline regressions for AI search planning versus observed video facts.

AI may suggest search phrases; only actual provider/cache observations may supply
the title, URL, description, and cover of a new recommendation. Every publication
is checked so a fabricated card cannot flash before later verification removes it.
"""
from copy import deepcopy
import asyncio
import json

import httpx
import pytest

from backend.app.fast_video_search import run_fast_video_search
from backend.app.models import Candidate
from test_fast_video_search import Provider, bindings, factory, settings


@pytest.fixture(autouse=True)
def forbid_network_and_detail_pages(monkeypatch):
    attempts = []

    async def forbidden(*_args, **_kwargs):
        attempts.append(True)
        pytest.fail("Grounding regressions must use injected observations only")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.enrich", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.fetch", forbidden)
    yield
    assert not attempts


def all_rows(snapshot):
    return [row for group in snapshot["recommendations"].values() for row in group]


def forged_video(url, title, point_id="concept"):
    return {
        "title": title,
        "url": url,
        "snippet": "AI_ONLY_DESCRIPTION: " + title,
        "thumbnail_url": "https://i0.hdslb.com/bfs/archive/ai-only-cover.jpg",
        "chapters": [{"chapter_id": "ai-chapter", "title": "AI_ONLY_CHAPTER"}],
        "point_matches": bindings([point_id], title),
        "requires_payment": False,
    }


@pytest.mark.parametrize("technology,concept,urls", [
    ("ECharts", "图表配置项", [
        "https://www.bilibili.com/video/BV1mE411J7n7",
        "https://www.bilibili.com/video/BV1sE411k7Yq",
        "https://www.bilibili.com/video/BV1yE411k7Rm",
        "https://www.bilibili.com/video/BV1hE411k7Qn",
    ]),
    ("SQL", "关联查询", ["https://www.bilibili.com/video/av900001"]),
    ("pandas", "分组聚合", ["https://www.bilibili.com/video/av900002"]),
])
async def test_ai_only_video_never_enters_any_published_snapshot(technology, concept, urls):
    point = {"id": "concept", "name": concept, "technology": technology}
    snapshots, calls = [], []
    title = technology + " " + concept + " 专题教程"

    async def complete(_settings, _prompt, data, **_kwargs):
        calls.append(deepcopy(data))
        if data["task"] == "plan_video_discovery":
            # Each suggestion carries one URL, so no old per-suggestion limit
            # could hide the real four-link failure or the cross-domain cases.
            return {"suggestions": [{"point_id": "concept", "queries": [title],
                                     "videos": [forged_video(url, title)]} for url in urls]}
        pytest.fail("AI-only titles must not enter recommendation classification")

    provider = Provider(lambda _: [])
    result = await run_fast_video_search(settings(), [point],
        {"name": "Offline grounding", "preferred_platforms": ["bilibili"]},
        publish=lambda snapshot: snapshots.append(deepcopy(snapshot)), deadline_seconds=.6,
        provider_factory=factory(provider), complete=complete)

    assert snapshots and all(not all_rows(snapshot) for snapshot in snapshots)
    assert not all_rows(result)
    assert result["progress"]["candidates"] == 0
    assert result["diagnostics"]["rejections"].get("ungrounded_ai_video", 0) >= len(urls)
    assert any(technology in call["query"] for call in provider.calls)
    assert {call["task"] for call in calls} == {"plan_video_discovery"}


@pytest.mark.parametrize("from_cache", [False, True], ids=["provider", "search-cache"])
async def test_real_game_observation_for_ai_url_cannot_inherit_fabricated_course_facts(from_cache):
    point = {"id": "concept", "name": "图表配置项", "technology": "ECharts"}
    url = "https://www.bilibili.com/video/BV1mE411J7n7"
    invented = forged_video(url, "ECharts 图表配置项专题教程")
    observed = Candidate(id="native-game", url=url, title="游戏实况：一家三口",
        snippet="游戏角色与地图探索记录", source="offline", query="synthetic",
        thumbnail_url="https://i0.hdslb.com/bfs/archive/observed-game-cover.jpg")
    plan_finished = asyncio.Event()
    snapshots, payloads = [], []

    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            plan_finished.set()
            return {"suggestions": [{"point_id": "concept", "queries": ["ECharts 图表配置项"],
                                     "videos": [invented]}]}
        assert data["task"] == "match_helpful_videos"
        payloads.extend(deepcopy(data["candidates"]))
        # A model must not be able to use the planner's fictional evidence to
        # label the observed game as an ECharts lesson.
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["concept"], invented["title"]), "score": .99}
            for row in data["candidates"]]}

    async def search(_call):
        await plan_finished.wait()
        return [observed]

    class SearchCache:
        def cache_key(self, namespace, value):
            return namespace + ":" + json.dumps(value, sort_keys=True)

        def cache_get(self, _key):
            return {"data": {"candidates": [observed.model_dump()],
                             "observed_at": "2026-10-28T00:00:00+00:00"},
                    "cache": {"stale": False}}

        def cache_set(self, *_args):
            pytest.fail("A cache hit must not be replaced by AI video facts")

    provider = Provider(search)
    result = await run_fast_video_search(settings(), [point],
        {"name": "Offline grounding", "preferred_platforms": ["bilibili"]},
        publish=lambda snapshot: snapshots.append(deepcopy(snapshot)), deadline_seconds=.7,
        provider_factory=factory(provider), complete=complete,
        search_cache=SearchCache() if from_cache else None)

    assert payloads
    assert all(row["title"] == observed.title and row["snippet"] == observed.snippet for row in payloads)
    assert "AI_ONLY" not in json.dumps(payloads, ensure_ascii=False)
    assert not any(row.get("chapters") for row in payloads)
    assert all(not all_rows(snapshot) for snapshot in snapshots)
    assert not all_rows(result)
    if from_cache:
        assert result["diagnostics"]["search_cache_hits"] > 0
        assert not provider.calls


@pytest.mark.parametrize("technology,concept", [("ECharts", "图表配置项"), ("SQL", "关联查询")])
async def test_real_search_tutorial_overlapping_ai_url_keeps_only_observed_facts(technology, concept):
    point = {"id": "concept", "name": concept, "technology": technology}
    url = "https://www.bilibili.com/video/av900010"
    invented = forged_video(url, technology + " AI_ONLY_TITLE")
    observed = Candidate(id="observed-tutorial", url=url, title=technology + " " + concept + " 原课程",
        snippet=concept + " 的实际教学示例", source="offline", query="synthetic",
        thumbnail_url="https://i0.hdslb.com/bfs/archive/observed-tutorial-cover.jpg")
    plan_finished = asyncio.Event()
    snapshots, payloads = [], []

    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            plan_finished.set()
            return {"suggestions": [{"point_id": "concept", "queries": [technology + " " + concept],
                                     "videos": [invented]}]}
        assert data["task"] == "match_helpful_videos"
        payloads.extend(deepcopy(data["candidates"]))
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["concept"], observed.snippet), "score": .9}
            for row in data["candidates"]]}

    async def search(_call):
        await plan_finished.wait()
        return [observed]

    result = await run_fast_video_search(settings(), [point],
        {"name": "Offline grounding", "preferred_platforms": ["bilibili"]},
        publish=lambda snapshot: snapshots.append(deepcopy(snapshot)), deadline_seconds=.7,
        provider_factory=factory(Provider(search)), complete=complete)

    assert all_rows(result)
    assert payloads and "AI_ONLY" not in json.dumps(payloads, ensure_ascii=False)
    for snapshot in [*snapshots, result]:
        for row in all_rows(snapshot):
            resource = row["resource"]
            assert row["origin"] == "search"
            assert resource["video_evidence_status"] == "search_discovered"
            assert resource["title"] == observed.title
            assert resource["snippet"] == observed.snippet
            assert resource["thumbnail_url"] == observed.thumbnail_url
            assert not row.get("matched_chapters")
            assert "AI_ONLY" not in json.dumps(resource, ensure_ascii=False)


async def test_grounding_does_not_truncate_genuinely_observed_tutorials():
    point = {"id": "concept", "name": "关联查询", "technology": "SQL"}
    observations = [Candidate(id=f"observed-{i}",
        url=f"https://www.bilibili.com/video/av{900100 + i}",
        title=f"SQL 关联查询课程 {i}", snippet="关联查询的教学示例", source="offline", query="synthetic")
        for i in range(8)]

    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": [{"point_id": "concept", "queries": ["SQL JOIN 教程"]}]}
        assert data["task"] == "match_helpful_videos"
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["concept"], row["snippet"]), "score": .9}
            for row in data["candidates"]]}

    result = await run_fast_video_search(settings(max_results_per_point=5), [point],
        {"name": "Offline grounding", "preferred_platforms": ["bilibili"]},
        publish=lambda _: None, deadline_seconds=.8,
        provider_factory=factory(Provider(lambda _: observations)), complete=complete)
    assert {row["resource"]["url"] for row in all_rows(result)} == {row.url for row in observations}
