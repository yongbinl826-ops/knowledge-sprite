"""AI links are candidates until native facts and video relevance agree."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from backend.app import fast_video_search as fast
from test_fast_video_search import Provider, bindings, factory, settings, video


POINTS = [{"id": "bar", "name": "柱状图与类目轴", "technology": "ECharts",
           "description": "展示就业行业人数"}]
INPUT = {"name": "就业数据可视化大屏", "requirements": "使用 ECharts 展示就业人数",
         "preferred_platforms": ["bilibili"], "language": "zh"}
URL = "https://www.bilibili.com/video/BV1sE411k7Yq"
IMAGE = "https://i0.hdslb.com/bfs/archive/native-offline-cover.jpg"
AI_TITLE = "AI编造的ECharts柱状图教材标题"
AI_SNIPPET = "AI编造的柱状图与类目轴说明"
NATIVE_TITLE = "ECharts 柱状图与类目轴入门"
NATIVE_SNIPPET = "通过柱状图与类目轴展示分类数量"


def suggestions():
    return [{"point_id": "bar", "queries": [], "videos": [{"url": URL,
        "title": AI_TITLE, "snippet": AI_SNIPPET,
        "point_matches": [{"point_id": "bar", "relevance": "targeted", "evidence": AI_SNIPPET,
                           "chapter_ids": ["ai-invented-chapter"]}]}]}]


def native_result(title=NATIVE_TITLE, snippet=NATIVE_SNIPPET):
    return {"status": "accepted", "candidate": {"url": URL, "title": title, "snippet": snippet,
        "thumbnail_url": IMAGE, "requires_payment": False}, "provenance": {
            "source_url": URL, "title_source": "html.bilibili.__INITIAL_STATE__.videoData.title",
            "observed_at": "2026-10-28T04:00:00+00:00"}}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("AI native fallback tests must inject every external operation")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.enrich", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)


class CoverObserver:
    instances = []

    def __init__(self, _settings, _points, *, match, publish, **kwargs):
        assert match is None and kwargs["cover_only"] is True
        assert kwargs["max_semantic_batches"] == 0
        self.resources = []
        self.diagnostics = {}
        self.instances.append(self)

    def enqueue(self, resource, point_ids):
        self.resources.append((resource, point_ids))
        return True

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_verified_ai_native_tutorial_works_when_search_is_empty_and_reuses_its_cover():
    verified = matched = False
    calls, snapshots = [], []

    async def verify(suggestion, *, timeout_seconds):
        nonlocal verified
        assert suggestion["url"] == URL and timeout_seconds > 0
        await asyncio.sleep(.01)
        verified = True
        return native_result()

    async def model(_settings, _prompt, payload, **_kwargs):
        nonlocal matched
        calls.append(deepcopy(payload))
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": suggestions()}
        assert payload["task"] == "match_helpful_videos"
        assert verified
        assert all(row["title"] == NATIVE_TITLE and row["snippet"] == NATIVE_SNIPPET
                   and "chapters" not in row for row in payload["candidates"])
        assert AI_TITLE not in str(payload) and AI_SNIPPET not in str(payload)
        await asyncio.sleep(.01)
        matched = True
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(["bar"], NATIVE_SNIPPET)}
                            for row in payload["candidates"]]}

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["recommendations"]["bar"]:
            assert verified and matched, "Unverified suggestions must never flash as cards"

    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        chapter_enricher_factory=CoverObserver, deadline_seconds=.6, catalog_deadline_seconds=.2)
    rows = result["recommendations"]["bar"]
    assert len(rows) == 1 and rows[0]["origin"] == "ai"
    resource = rows[0]["resource"]
    assert resource["title"] == NATIVE_TITLE and resource["thumbnail_url"] == IMAGE
    assert resource["video_evidence_status"] == "native_page_observed"
    assert resource["native_page_provenance"] == native_result()["provenance"]
    assert rows[0]["matched_chapters"] == []
    assert result["progress"]["catalog_model_calls"] == 0
    assert not CoverObserver.instances[-1].resources, "Native cover is reused without another page read"
    assert all(call["task"] != "match_video_chapters" for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(("title", "snippet"), [
    ("宝可梦历代反派战斗", "Pokémon game battles"),
    ("韩国星巴克两杯饮品一个提拉米苏要多少钱？", "记录咖啡和甜点价格"),
    ("部落冲突元气少女屠龙日常", "游戏日常"),
])
async def test_ai_title_cannot_turn_native_game_or_coffee_page_into_echarts_tutorial(title, snippet):
    native_payloads = []

    async def verify(_suggestion, *, timeout_seconds):
        return native_result(title, snippet)

    async def model(_settings, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": suggestions()}
        assert payload["task"] == "match_helpful_videos"
        native_payloads.extend(payload["candidates"])
        assert all(row["title"] == title and row["snippet"] == snippet for row in payload["candidates"])
        assert AI_TITLE not in str(payload) and AI_SNIPPET not in str(payload)
        return {"matches": []}

    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=.5)
    assert native_payloads, "Actual native facts, rather than AI topic claims, must be judged"
    assert not result["recommendations"]["bar"]
    assert result["progress"]["catalog_model_calls"] == 0


@pytest.mark.asyncio
async def test_unknown_native_page_is_not_a_recommendation_or_a_matching_candidate():
    async def verify(_suggestion, *, timeout_seconds):
        return {"status": "rejected", "reason": "native_title_missing"}

    async def model(_settings, _prompt, payload, **_kwargs):
        assert payload["task"] == "plan_video_discovery", "An unknown source must not enter video matching"
        return {"suggestions": suggestions()}

    snapshots = []
    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=.4)
    assert not any(snapshot["recommendations"]["bar"] for snapshot in snapshots)
    assert result["progress"]["candidates"] == 0


@pytest.mark.asyncio
async def test_wrong_model_match_cannot_use_native_game_text_as_echarts_evidence():
    async def verify(_suggestion, *, timeout_seconds):
        return native_result("部落冲突元气少女屠龙日常", "游戏日常")

    async def model(_settings, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": suggestions()}
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["bar"], "游戏日常"), "score": 1.0}
            for row in payload["candidates"]]}

    snapshots = []
    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=.4)
    assert not result["recommendations"]["bar"]
    assert not any(snapshot["recommendations"]["bar"] for snapshot in snapshots)


@pytest.mark.asyncio
async def test_independent_search_arrival_is_not_overwritten_by_later_ai_claims():
    search_visible = asyncio.Event()
    source_title = "搜索源提供的 ECharts 柱状图与类目轴教程"
    candidate = video(901, title=source_title, snippet=NATIVE_SNIPPET, url=URL).model_copy(update={"thumbnail_url": IMAGE})
    snapshots = []

    async def verify(_suggestion, *, timeout_seconds):
        await asyncio.wait_for(search_visible.wait(), .3)
        return native_result()

    async def model(_settings, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": suggestions()}
        assert AI_TITLE not in str(payload) and AI_SNIPPET not in str(payload)
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(["bar"], NATIVE_SNIPPET)}
                            for row in payload["candidates"]]}

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["recommendations"]["bar"]:
            search_visible.set()

    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        provider_factory=factory(Provider(lambda _: [candidate])), complete=model, verify_ai_video=verify,
        deadline_seconds=.6)
    assert search_visible.is_set()
    rows = result["recommendations"]["bar"]
    assert len(rows) == 1 and rows[0]["origin"] == "search"
    assert rows[0]["resource"]["title"] in {source_title, NATIVE_TITLE}
    assert all(AI_TITLE not in str(snapshot["recommendations"]) and AI_SNIPPET not in str(snapshot["recommendations"])
               for snapshot in snapshots)
    assert rows[0]["matched_chapters"] == []


@pytest.mark.asyncio
async def test_cancellation_drains_inflight_native_verification_without_late_publication():
    entered = asyncio.Event()
    active = 0
    snapshots = []

    async def verify(_suggestion, *, timeout_seconds):
        nonlocal active
        active += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    async def model(_settings, _prompt, payload, **_kwargs):
        assert payload["task"] == "plan_video_discovery"
        return {"suggestions": suggestions()}

    task = asyncio.create_task(fast.run_fast_video_search(settings(), POINTS, INPUT,
        publish=snapshots.append, provider_factory=factory(Provider(lambda _: [])), complete=model,
        verify_ai_video=verify, deadline_seconds=2))
    await asyncio.wait_for(entered.wait(), .5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert active == 0
    assert not any(snapshot["recommendations"]["bar"] for snapshot in snapshots)


# Compact native observations captured in native-link-30s-diagnostic.json on
# 2026-10-28. These replay saved facts; no page is fetched by these tests. The
# recorded ~13-second durations are inputs, never real sleeps or live timings.
OBSERVED_NATIVE_PAGES = [
    {"url": "https://www.bilibili.com/video/BV1R3411J793",
     "title": "echarts图表库快速上手", "snippet": "echarts图表库快速上手",
     "thumbnail_url": "http://i0.hdslb.com/bfs/archive/5e4c3d1c2b53a09a24ef597aad5187327d82fe3a.png",
     "source_url": "https://www.bilibili.com/zh-Hans/video/BV1R3411J793/",
     "observed_at": "2026-10-28T03:48:04.524468+00:00", "observed_duration_seconds": 13.033},
    {"url": "https://www.bilibili.com/video/BV1hE411k7Qn",
     "title": "韩国星巴克两杯饮品一个提拉米苏要多少钱？", "snippet": "-",
     "thumbnail_url": "http://i2.hdslb.com/bfs/archive/45a82aa73bcfe1780b05fdca14b3915a4b3282d7.jpg",
     "source_url": "https://www.bilibili.com/zh-Hans/video/BV1hE411k7Qn/",
     "observed_at": "2026-10-28T03:48:04.809231+00:00", "observed_duration_seconds": 13.07},
]


def observed_outcome(observation):
    return {"status": "accepted", "candidate": {
        key: observation[key] for key in ("url", "title", "snippet", "thumbnail_url")},
        "provenance": {"source_url": observation["source_url"],
            "observed_at": observation["observed_at"], "title": {
                "source": "html.bilibili.video_title", "url": observation["url"] + "/",
                "fetched_at": observation["observed_at"]}}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("deadline_seconds", "expected_upper"), [(110, 30), (20, 16.4)])
async def test_native_identity_budget_fits_observed_thirteen_second_page_and_reserves_matching_time(
        deadline_seconds, expected_upper):
    observation = OBSERVED_NATIVE_PAGES[0]
    allotted = []

    async def verify(suggestion, *, timeout_seconds):
        assert suggestion == {"url": observation["url"]}
        allotted.append(timeout_seconds)
        # Replay the observed duration as an admission requirement. In the old
        # 10-second budget this assertion fails without sleeping for 13 seconds.
        assert observation["observed_duration_seconds"] < timeout_seconds <= expected_upper
        return observed_outcome(observation)

    async def model(_settings, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": [{"point_id": "bar", "queries": [], "videos": [{
                "url": observation["url"], "title": AI_TITLE, "snippet": AI_SNIPPET}]}]}
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["bar"], observation["title"], relevance="general")}
            for row in payload["candidates"]]}

    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=deadline_seconds)
    assert fast.AI_IDENTITY_TIMEOUT_SECONDS == 30
    assert len(allotted) == 1 and allotted[0] > expected_upper - .5
    assert result["recommendations"]["bar"][0]["resource"]["title"] == observation["title"]
    assert result["recommendations"]["bar"][0]["relevance"] == "general"
    assert result["progress"]["catalog_model_calls"] == 0


@pytest.mark.asyncio
async def test_saved_starbucks_native_observation_stays_rejected_despite_forced_echarts_match():
    observation = OBSERVED_NATIVE_PAGES[1]
    judged = []

    async def verify(suggestion, *, timeout_seconds):
        assert suggestion == {"url": observation["url"]}
        return observed_outcome(observation)

    async def model(_settings, _prompt, payload, **_kwargs):
        if payload["task"] == "plan_video_discovery":
            return {"suggestions": [{"point_id": "bar", "queries": [], "videos": [{
                "url": observation["url"], "title": AI_TITLE, "snippet": AI_SNIPPET}]}]}
        judged.extend(payload["candidates"])
        assert all(row["title"] == observation["title"] for row in payload["candidates"])
        return {"matches": [{"candidate_id": row["id"],
            "point_matches": bindings(["bar"], observation["title"]), "score": 1.0}
            for row in payload["candidates"]]}

    snapshots = []
    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=.4)
    assert judged
    assert not result["recommendations"]["bar"]
    assert not any(snapshot["recommendations"]["bar"] for snapshot in snapshots)


@pytest.mark.asyncio
@pytest.mark.parametrize("native_cap", [.02, 30.0])
async def test_native_timeout_is_bounded_by_both_candidate_and_total_deadline_without_late_cards(monkeypatch, native_cap):
    monkeypatch.setattr(fast, "AI_IDENTITY_TIMEOUT_SECONDS", native_cap)
    active = 0
    timed_out = []
    snapshots = []
    deadline = .08

    async def verify(_suggestion, *, timeout_seconds):
        nonlocal active
        assert 0 < timeout_seconds <= min(native_cap, deadline * .82)
        active += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            timed_out.append(True)
            raise
        finally:
            active -= 1

    async def model(_settings, _prompt, payload, **_kwargs):
        assert payload["task"] == "plan_video_discovery"
        return {"suggestions": suggestions()}

    clock = asyncio.get_running_loop()
    started = clock.time()
    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        provider_factory=factory(Provider(lambda _: [])), complete=model, verify_ai_video=verify,
        deadline_seconds=deadline)
    assert clock.time() - started < .3
    assert active == 0 and timed_out == [True]
    assert result["status"] != "running"
    assert not any(snapshot["recommendations"]["bar"] for snapshot in snapshots)
    snapshot_count = len(snapshots)
    await asyncio.sleep(.01)
    assert len(snapshots) == snapshot_count, "Timed out verification must have no detached late publisher"
