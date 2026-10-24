"""Offline behavior checks for the bounded, helpful-video recommendation policy.

Providers and model completions are synthetic; scheduling, URL checks, matching,
publication, and cancellation use the actual engine. No provider/page HTTP is
permitted from these tests.
"""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import replace
import asyncio
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app import fast_video_search as fast_search
from backend.app.models import Candidate
from backend.app.providers import SearchError
from backend.app.fast_video_search import run_fast_video_search


POINTS = [
    {"id": "keyboard", "name": "键盘按键状态轮询", "technology": "Pygame", "description": "让玩家控制角色移动"},
    {"id": "collision", "name": "轴对齐包围盒碰撞检测", "technology": "Pygame", "description": "判断球和接球板是否相撞"},
]
INPUT = {"name": "用Python做一个接球小游戏", "description": "接住下落的小球并计分",
         "preferred_platforms": ["bilibili", "icourse163", "xuetangx"], "language": "zh"}


def settings(**kwargs):
    return replace(Settings(search_provider="tavily", tavily_api_key="offline-placeholder",
                            llm_provider="openai_compatible", llm_model="offline-model",
                            llm_api_key="offline-placeholder", search_min_interval_seconds=0), **kwargs)


def video(number=1, *, title="Pygame 接球游戏项目实战", snippet="学习键盘移动与矩形碰撞", url=None):
    return Candidate(id=f"source-{number}", title=title, snippet=snippet,
                     url=url or f"https://www.bilibili.com/video/av{100000 + number}",
                     source="offline", query="synthetic")


def rows(result, point_id="keyboard"):
    return result["recommendations"].get(point_id, [])


class Provider:
    name = "offline"

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    async def search(self, query, language, limit, domain_filters):
        call = {"query": query, "language": language, "limit": limit, "domains": domain_filters}
        self.calls.append(call)
        result = self.handler(call)
        return await result if hasattr(result, "__await__") else result


def factory(provider):
    return lambda _settings, provider_name="tavily": provider


def bindings(point_ids, evidence, relevance="targeted"):
    return [{"point_id": point_id, "relevance": relevance, "evidence": evidence, "chapter_ids": []}
            for point_id in point_ids]


def completion(*, suggestions=None, points_by_candidate=None):
    calls = []

    async def complete(_settings, _prompt, data, **_kwargs):
        calls.append(deepcopy(data))
        if data["task"] == "plan_video_discovery":
            return {"suggestions": deepcopy(suggestions or [])}
        assert data["task"] == "match_helpful_videos"
        matches = []
        for item in data["candidates"]:
            bound = points_by_candidate(item, data["points"]) if points_by_candidate else [p["id"] for p in data["points"]]
            matches.append({"candidate_id": item["id"], "point_matches": bindings(bound, item["snippet"]), "score": .9,
                            "requires_payment": None})
        return {"matches": matches}

    complete.calls = calls
    return complete


@pytest.fixture(autouse=True)
def no_network_or_detail_pages(monkeypatch):
    attempts = []

    async def forbidden(*_args, **_kwargs):
        attempts.append(True)
        pytest.fail("Fast recommendations must not fetch detail pages or make uninjected HTTP calls")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.enrich", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.fetch", forbidden)
    yield
    assert not attempts, "No network/detail attempts are allowed, including caught task failures"


async def test_platforms_run_together_and_fast_results_do_not_wait_for_slow_platform():
    platforms_started, snapshots = set(), []
    slow_release = asyncio.Event()
    slow_completed = False
    first_while_slow_pending = False

    async def search(call):
        nonlocal slow_completed
        domains = " ".join(call["domains"])
        platforms_started.add(domains)
        if "bilibili" in domains:
            await asyncio.sleep(.015)
            return [video()]
        await slow_release.wait()
        slow_completed = True
        return []

    def publish(snapshot):
        nonlocal first_while_slow_pending
        snapshots.append(deepcopy(snapshot))
        if rows(snapshot) and not slow_release.is_set():
            first_while_slow_pending = not slow_completed
            slow_release.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, provider_factory=factory(Provider(search)), complete=completion())
    assert any("bilibili" in value for value in platforms_started)
    assert any("icourse163" in value for value in platforms_started)
    assert first_while_slow_pending, "A slow platform must not withhold another platform's ready cards"
    assert rows(result)
    assert any(rows(snapshot) and snapshot["status"] == "running" for snapshot in snapshots)


async def test_total_deadline_cancels_slow_search_and_model_work():
    active, cancelled = 0, 0

    async def wait_forever(*_args, **_kwargs):
        nonlocal active, cancelled
        active += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        finally:
            active -= 1

    before = time.monotonic()
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.12, provider_factory=factory(Provider(wait_forever)), complete=wait_forever)
    elapsed = time.monotonic() - before
    assert elapsed < .7, "One shared wall-clock budget must cover all stages"
    assert active == 0 and cancelled > 0
    assert result["status"] != "running"


async def test_caller_cancellation_leaves_no_running_provider_or_model_children():
    active = 0
    entered = asyncio.Event()

    async def wait_forever(*_args, **_kwargs):
        nonlocal active
        active += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    task = asyncio.create_task(run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=2, provider_factory=factory(Provider(wait_forever)), complete=wait_forever))
    await asyncio.wait_for(entered.wait(), .5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert active == 0


async def test_actual_provider_requests_share_project_budget_including_retries():
    class RetryingProvider:
        name = "offline-retries"
        sent = 0

        @contextmanager
        def query_scope(self, hook):
            self.hook = hook
            yield

        async def search(self, *_args):
            for _ in range(3):
                await self.hook()
                self.sent += 1
                await asyncio.sleep(0)
            return []

    provider = RetryingProvider()
    result = await run_fast_video_search(settings(project_max_search_requests=2), POINTS, INPUT,
        publish=lambda _: None, deadline_seconds=.4, provider_factory=factory(provider), complete=completion())
    assert provider.sent == result["progress"]["search_requests"] == 2
    assert result["diagnostics"]["search_budget_reached"]


async def test_semantic_aliases_reuse_across_points_and_do_not_truncate_at_five():
    # No literal knowledge-point names occur in these titles or summaries.
    candidates = [video(n, title=f"Pygame 从零制作小游戏 第{n}讲", snippet="方向键输入与矩形相交测试") for n in range(1, 8)]
    model = completion()
    result = await run_fast_video_search(settings(max_results_per_point=5), POINTS, INPUT,
        publish=lambda _: None, deadline_seconds=.6,
        provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    assert len(rows(result, "keyboard")) == len(rows(result, "collision")) == 7
    assert {r["resource"]["url"] for r in rows(result, "keyboard")} == {r["resource"]["url"] for r in rows(result, "collision")}
    assert any(call["task"] == "match_helpful_videos" for call in model.calls)
    assert all(row["resource"]["fetch_status"] == "not_fetched" for row in rows(result))
    assert all(row["resource"]["playback_verified"] is False for row in rows(result))


async def test_ai_direct_links_and_rewritten_queries_are_used_before_technology_fallback():
    direct = video(30, title="Pygame 键盘控制教程")
    suggestions = [{"point_id": "keyboard", "queries": ["Pygame move paddle tutorial"],
                    "videos": [{"title": direct.title, "url": direct.url, "snippet": direct.snippet,
                                "point_matches": bindings(["keyboard"], direct.title)}]}]
    provider = Provider(lambda _: [])
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(provider), complete=completion(suggestions=suggestions))
    assert any(row["resource"]["url"].rstrip("/") == direct.url for row in rows(result))
    assert any("move paddle" in call["query"] for call in provider.calls)
    assert all(row["origin"] != "technology" for row in rows(result, "keyboard"))


async def test_technology_fallback_does_not_cross_into_unrelated_technology():
    points = [POINTS[0], {"id": "sql", "name": "关联查询", "technology": "SQL", "description": "连接两张表"}]
    model = completion(points_by_candidate=lambda _candidate, _points: [])
    result = await run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [video(40, title="Pygame 游戏开发入门", snippet="基础项目教程")])), complete=model)
    assert rows(result, "keyboard"), "An empty point can use a same-technology introductory video"
    assert not rows(result, "sql"), "A Pygame tutorial is not a SQL technology fallback"


async def test_explicit_paid_content_is_excluded_unknown_cost_allowed_and_chinese_first():
    candidates = [video(51, title="Pygame paid course", snippet="Purchase course for $49"),
                  video(52, title="Pygame game tutorial", snippet="Keyboard input and collision detection"),
                  video(53, title="Pygame 游戏项目教程", snippet="键盘控制与碰撞检测")]
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: candidates)), complete=completion())
    titles = [row["resource"]["title"] for row in rows(result)]
    assert candidates[0].title not in titles
    assert candidates[1].title in titles and candidates[2].title in titles
    assert titles.index(candidates[2].title) < titles.index(candidates[1].title)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "http://127.0.0.1/private", "https://www.bilibili.com/",
    "https://search.bilibili.com/all?keyword=pygame", "https://www.bilibili.com.evil.example/video/av123456",
    "https://www.bilibili.com:8080/video/av123456",
    "https://user:password@www.bilibili.com/video/av123456", "https://example.com/article/pygame",
])
async def test_unsafe_or_non_video_links_are_never_recommended(url):
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.4, provider_factory=factory(Provider(lambda _: [video(60, url=url)])), complete=completion())
    assert not any(result["recommendations"].values())


async def test_later_clear_payment_evidence_removes_earlier_ai_suggestion():
    candidate = video(70, title="Pygame 键盘控制教程", snippet="方向键输入与矩形相交测试")
    suggestions = [{"point_id": "keyboard", "queries": [],
                    "videos": [{"title": candidate.title, "url": candidate.url,
                                "snippet": candidate.snippet, "point_matches": bindings(["keyboard"], candidate.snippet)}]}]
    seen_before_payment_check = []

    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": suggestions}
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(["keyboard"], row["snippet"]),
                              "score": .9, "requires_payment": True}
                             for row in data["candidates"]]}

    result = await run_fast_video_search(settings(), POINTS, INPUT,
        publish=lambda snapshot: seen_before_payment_check.append(bool(rows(snapshot))),
        deadline_seconds=.5, provider_factory=factory(Provider(lambda _: [candidate])), complete=complete)
    assert any(seen_before_payment_check), "The initial price-unknown AI suggestion may be shown"
    assert not any(result["recommendations"].values()), "A later clear paid classification must remove the suggestion"


async def test_untrusted_malformed_point_ids_do_not_kill_matching_worker():
    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings([{"id": "keyboard"}, [], None, 42, "keyboard"], row["snippet"]),
                              "score": .9, "requires_payment": None}
                             for row in data["candidates"]]}

    # An alias-only resource needs the surviving valid semantic assignment;
    # broad fallback cannot hide a crashed matching worker in this check.
    candidate = video(71, title="玩家控制角色左右移动", snippet="按下方向键控制接球板")
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.4, provider_factory=factory(Provider(lambda _: [candidate])), complete=complete)
    assert rows(result, "keyboard")
    assert not result["diagnostics"]["deadline_reached"]


@pytest.mark.parametrize("model_response", [{"invalid": True}, {"matches": "wrong type"}, None])
async def test_bad_model_output_and_provider_errors_still_finish(model_response):
    async def bad_search(_):
        raise RuntimeError("synthetic supplier failure")

    async def bad_completion(*_args, **_kwargs):
        return deepcopy(model_response)

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.3, provider_factory=factory(Provider(bad_search)), complete=bad_completion)
    assert result["status"] != "running"
    assert not any(result["recommendations"].values())


@pytest.mark.parametrize(("error_code", "stop_flag", "warning", "allow_fallback"), [
    ("search_timeout", None, None, True),
    ("search_unavailable", None, None, True),
    ("search_rate_limited", None, None, False),
    ("search_unavailable", "access_denied", None, False),
    ("search_unavailable", "quota_exhausted", None, False),
    ("search_unavailable", None, {"reason_code": "captcha"}, False),
])
async def test_configured_supplier_failover_preserves_access_and_quota_stops(error_code, stop_flag, warning, allow_fallback):
    async def unavailable(_):
        raise SearchError(error_code, "Synthetic provider state")

    primary, secondary = Provider(unavailable), Provider(lambda _: [video(80)])
    primary.name, secondary.name = "searxng", "tavily"
    if stop_flag:
        setattr(primary, stop_flag, True)
    primary.last_warnings = [warning] if warning else []

    def providers(_settings, provider_name="tavily"):
        return primary if provider_name == "searxng" else secondary

    result = await run_fast_video_search(settings(search_provider="searxng", searxng_failover_provider="tavily",
                                                 ai_video_search_provider="default"),
        POINTS, INPUT, publish=lambda _: None, deadline_seconds=.4,
        provider_factory=providers, complete=completion())
    assert bool(secondary.calls) is allow_fallback
    assert bool(rows(result)) is allow_fallback
    assert result["progress"]["search_requests"] == len(primary.calls) + len(secondary.calls)


async def test_late_candidates_keep_reserved_matching_calls_and_are_not_silently_dropped(monkeypatch):
    # A smaller equivalent budget makes the exhaustion boundary deterministic:
    # one planning call and three early singleton results used to exhaust it.
    monkeypatch.setattr(fast_search, "MAX_MODEL_CALLS", 4)
    monkeypatch.setattr(fast_search, "TAIL_MODEL_CALLS", 2, raising=False)
    points = [{"id": f"point-{n}", "name": f"角色控制知识点{n}", "technology": "Pygame"}
              for n in range(3)]
    start = time.monotonic()
    search_index, searched_urls, judged_urls, first_publication = 0, set(), set(), []
    delays = [.05, .11, .17, .3]

    async def search(_call):
        nonlocal search_index
        index = search_index
        search_index += 1
        await asyncio.sleep(max(0, start + delays[index] - time.monotonic()))
        # No technology token: broad fallback cannot conceal skipped AI work.
        candidate = video(100 + index, title=f"玩家移动教学{index}", snippet="用方向键控制角色")
        searched_urls.add(candidate.url)
        return [candidate]

    async def complete(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        judged_urls.update(row["url"] for row in data["candidates"])
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings([points[0]["id"]], row["snippet"]), "score": .9}
                            for row in data["candidates"]]}

    def publish(snapshot):
        if rows(snapshot, points[0]["id"]) and not first_publication:
            first_publication.append(time.monotonic() - start)

    result = await run_fast_video_search(settings(), points, {**INPUT, "preferred_platforms": ["bilibili"]},
        publish=publish, deadline_seconds=.8, provider_factory=factory(Provider(search)), complete=complete)
    assert len(searched_urls) == 4
    assert judged_urls == searched_urls, "Late source results must still receive semantic matching"
    assert {row["resource"]["url"] for row in rows(result, points[0]["id"])} == searched_urls
    assert first_publication and first_publication[0] < .17, "Reserving the tail must not delay the initial cards"
    assert result["progress"]["model_calls"] <= 4
    assert result["diagnostics"]["matching"]["unjudged_candidates"] == 0
    assert not result["diagnostics"]["deadline_reached"]


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
async def test_waiting_for_reserved_tail_calls_obeys_deadline_and_cancellation(monkeypatch, stop):
    monkeypatch.setattr(fast_search, "MAX_MODEL_CALLS", 4)
    monkeypatch.setattr(fast_search, "TAIL_MODEL_CALLS", 2, raising=False)
    points = [{"id": f"point-{n}", "name": f"角色控制知识点{n}", "technology": "Pygame"}
              for n in range(3)]
    first_matched, second_returned = asyncio.Event(), asyncio.Event()
    search_index, active, model_calls = 0, 0, 0

    async def search(_call):
        nonlocal search_index, active
        index = search_index
        search_index += 1
        active += 1
        try:
            if index == 0:
                return [video(200, title="玩家移动教学", snippet="用方向键控制角色")]
            if index == 1:
                await first_matched.wait()
                second_returned.set()
                return [video(201, title="控制接球板", snippet="响应键盘输入")]
            await asyncio.Event().wait()
        finally:
            active -= 1

    async def complete(_settings, _prompt, data, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        first_matched.set()
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings([points[0]["id"]], row["snippet"]), "score": .9}
                            for row in data["candidates"]]}

    started = time.monotonic()
    task = asyncio.create_task(run_fast_video_search(settings(), points,
        {**INPUT, "preferred_platforms": ["bilibili"]}, publish=lambda _: None,
        deadline_seconds=.18 if stop == "deadline" else 1,
        provider_factory=factory(Provider(search)), complete=complete))
    await asyncio.wait_for(second_returned.wait(), .3)
    if stop == "cancel":
        await asyncio.sleep(.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result["diagnostics"]["deadline_reached"]
        assert result["diagnostics"]["matching"]["unjudged_candidates"] == 1
        assert result["status"] == "partial"
    assert time.monotonic() - started < .6
    assert active == 0
    assert model_calls == 2, "Reserved calls must not be spent on isolated early arrivals"


async def test_candidates_over_tail_capacity_are_reported_as_unjudged_without_more_model_calls(monkeypatch):
    monkeypatch.setattr(fast_search, "MAX_MODEL_CALLS", 3)
    monkeypatch.setattr(fast_search, "TAIL_MODEL_CALLS", 2)
    candidates = [video(300 + index) for index in range(90)]
    model = completion()
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=1.5, provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    matching = result["diagnostics"]["matching"]
    assert result["progress"]["model_calls"] == len(model.calls) == 3
    assert matching["judged_candidates"] == 72
    assert matching["unjudged_candidates"] == matching["budget_skipped_candidates"] == 18
    assert matching["failed_candidates"] == 0
    assert all(result["recommendations"].values())
    assert result["status"] == "partial", "Full point coverage must not disguise unmatched source candidates"


async def test_invalid_matching_shape_counts_failure_instead_of_a_negative_judgment():
    async def invalid_match(_settings, _prompt, data, **_kwargs):
        return {"suggestions": []} if data["task"] == "plan_video_discovery" else {"matches": {}}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.4, provider_factory=factory(Provider(lambda _: [video(500)])), complete=invalid_match)
    matching = result["diagnostics"]["matching"]
    assert matching["judged_candidates"] == 0
    assert matching["unjudged_candidates"] == matching["failed_candidates"] == 1
    assert matching["budget_skipped_candidates"] == 0
    assert all(result["recommendations"].values()), "Same-technology fallback remains available"
    assert result["status"] == "partial"


async def test_targeted_lessons_keep_all_results_and_general_courses_only_fill_empty_points():
    candidates = [video(600, title="Pygame 游戏开发入门", snippet="完整项目课程"),
                  video(601, title="Pygame 键盘输入", snippet="按键状态与方向键轮询"),
                  video(602, title="Pygame 键盘控制", snippet="连续读取键盘输入")]

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": row["id"], "score": .99,
            "point_matches": bindings([p["id"] for p in POINTS], row["title"], "general")
            if "入门" in row["title"] else bindings(["keyboard"], row["snippet"])} for row in data["candidates"]]}

    snapshots = []
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    assert len(rows(result, "keyboard")) == 2
    assert all(row["relevance"] == "targeted" for row in rows(result, "keyboard"))
    assert len(rows(result, "collision")) == 1
    assert rows(result, "collision")[0]["relevance"] == "general"
    first_fallback = next(index for index, snapshot in enumerate(snapshots) if rows(snapshot, "collision"))
    assert all(search["status"] != "running" for search in snapshots[first_fallback]["diagnostics"]["searches"])
    assert result["diagnostics"]["coverage"]["targeted_points"] == 1
    assert result["diagnostics"]["coverage"]["general_fallback_points"] == 1


async def test_empty_points_get_one_diverse_background_course_each_without_flooding():
    points = [*POINTS, {"id": "loop", "name": "游戏循环", "technology": "Pygame"}]
    candidates = [video(610 + n, title=f"Pygame 入门课程 第{n}讲", snippet="从零制作小游戏") for n in range(6)]
    model = completion(points_by_candidate=lambda _row, _points: [])
    result = await run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    assert all(len(result["recommendations"][point["id"]]) == 1 for point in points)
    assert len({row["resource"]["resource_id"] for values in result["recommendations"].values() for row in values}) == 3
    assert result["diagnostics"]["coverage"]["general_fallback_associations"] == 3


@pytest.mark.parametrize("evidence", ["Pygame", "Pygame 游戏开发入门", "不存在的键盘状态轮询教程"])
async def test_generic_or_invented_evidence_never_counts_as_targeted(evidence):
    candidate = video(620, title="Pygame 游戏开发入门", snippet="完整项目课程")

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": row["id"], "score": 1.0,
            "point_matches": bindings(["keyboard", "collision"], evidence)} for row in data["candidates"]]}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [candidate])), complete=model)
    assert result["diagnostics"]["coverage"]["targeted_points"] == 0
    assert result["diagnostics"]["rejections"]["ungrounded_targeted_match"] == 2
    assert all(len(values) == 1 and values[0]["relevance"] == "general" for values in result["recommendations"].values())


@pytest.mark.parametrize("urls, expected", [
    (["https://www.bilibili.com/video/BV1VZ4y1G7YB?p=3", "https://bilibili.com/video/BV1VZ4y1G7YB/?p=8"], 1),
    (["https://www.icourse163.org/course/BIT-1001873001", "https://www.icourse163.org/course/0809BIT021E-1001873001"], 1),
    (["https://www.icourse163.org/course/BIT-1001873001?tid=3", "https://www.icourse163.org/course/BIT-1001873001?tid=4"], 2),
])
async def test_same_course_aliases_merge_topic_evidence_without_merging_different_terms(urls, expected):
    candidates = [video(630, title="键盘输入教程", snippet="键盘状态轮询", url=urls[0]),
                  video(631, title="碰撞检测教程", snippet="轴对齐包围盒相交测试", url=urls[1])]
    seen = []

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        seen.extend(data["candidates"])
        output = []
        for row in data["candidates"]:
            text = row["title"] + " " + row["snippet"]
            assignments = []
            if "键盘状态轮询" in text:
                assignments += bindings(["keyboard"], "键盘状态轮询")
            if "轴对齐包围盒相交测试" in text:
                assignments += bindings(["collision"], "轴对齐包围盒相交测试")
            output.append({"candidate_id": row["id"], "point_matches": assignments})
        return {"matches": output}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    assert result["progress"]["candidates"] == expected
    assert len(rows(result, "keyboard")) == len(rows(result, "collision")) == 1
    assert all(values[0]["relevance"] == "targeted" for values in result["recommendations"].values())
    if expected == 1:
        assert rows(result, "keyboard")[0]["resource"]["resource_id"] == rows(result, "collision")[0]["resource"]["resource_id"]
        assert any("键盘状态轮询" in row["snippet"] and "轴对齐包围盒相交测试" in row["snippet"] for row in seen)


async def test_optional_catalog_arrives_after_first_card_and_adds_real_point_specific_chapters():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    first_card, catalog_visible = asyncio.Event(), asyncio.Event()
    snapshots = []
    search_count = 0
    candidate = video(640, title="Pygame 键盘控制教程", snippet="键盘状态轮询",
                      url="https://www.bilibili.com/video/BV1VZ4y1G7YB")
    points = [{**POINTS[0], "name": "键盘状态轮询"}, {**POINTS[1], "name": "碰撞检测"}]

    async def fetch(resource):
        await asyncio.wait_for(first_card.wait(), .2)
        await asyncio.sleep(.02)
        return {"url": resource["url"], "fetch_status": "fetched", "chapters": [
            {"title": title, "page_number": number, "url": resource["url"] + f"?p={number}",
             "source_url": resource["url"], "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}
            for number, title in [(3, "键盘状态轮询"), (5, "碰撞检测"), (8, "键盘状态轮询与碰撞检测")]]}

    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] in {"plan_video_discovery", "match_video_chapters"}:
            return {"suggestions": []} if data["task"] == "plan_video_discovery" else {"matches": []}
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(["keyboard"], row["snippet"])}
                            for row in data["candidates"]]}

    def publish(snapshot):
        snapshots.append(snapshot)
        if rows(snapshot):
            first_card.set()
        if rows(snapshot, "collision") and rows(snapshot, "collision")[0].get("matched_chapters"):
            catalog_visible.set()

    async def search(_call):
        nonlocal search_count
        search_count += 1
        if search_count == 1:
            return [candidate]
        # A real search remains in flight while optional metadata arrives;
        # metadata is no longer allowed to extend the completed search's tail.
        await catalog_visible.wait()
        return []

    result = await run_fast_video_search(settings(), points, INPUT, publish=publish,
        deadline_seconds=.6, provider_factory=factory(Provider(search)), complete=model,
        chapter_enricher_factory=enricher)
    first = next(snapshot for snapshot in snapshots if rows(snapshot))
    assert rows(first)[0]["matched_chapters"] == []
    assert rows(first)[0]["added_at"] == rows(result)[0]["added_at"]
    assert rows(first)[0]["elapsed_seconds"] == rows(result)[0]["elapsed_seconds"]
    assert [chapter["index"] for chapter in rows(result)[0]["matched_chapters"]] == [3, 8]
    assert [chapter["index"] for chapter in rows(result, "collision")[0]["matched_chapters"]] == [5, 8]
    assert rows(result)[0]["resource"]["title"] == candidate.title
    assert result["diagnostics"]["coverage"]["targeted_points"] == 2
    assert result["diagnostics"]["coverage"]["general_fallback_points"] == 0


async def test_catalog_semantics_has_three_independent_calls_without_spending_video_budget(monkeypatch):
    monkeypatch.setattr(fast_search, "MAX_MODEL_CALLS", 4)
    calls = []

    class Enricher:
        def __init__(self, _settings, _points, **kwargs):
            assert "load_cached_catalog" not in kwargs and "save_catalog" not in kwargs
            self.match = kwargs["match"]
            self.diagnostics = {"catalogs_received": 1, "scheduled_resources": 1}
        def enqueue(self, *_args):
            return True
        async def run_background_match(self, **_kwargs):
            for _ in range(4):
                await self.match("catalog prompt", {"resources": []}, .2)
        async def close(self):
            pass

    async def model(_settings, _prompt, data, **_kwargs):
        calls.append(data["task"])
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        if data["task"] == "match_video_chapters":
            return {"matches": []}
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(["keyboard"], row["snippet"])}
                            for row in data["candidates"]]}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.8, provider_factory=factory(Provider(lambda _: [video(700 + n) for n in range(73)])),
        complete=model, chapter_enricher_factory=Enricher)
    assert len(calls) == result["progress"]["model_calls"] == 7
    assert result["progress"]["recommendation_model_calls"] == 4
    assert calls.count("match_video_chapters") == result["progress"]["catalog_model_calls"] == 3
    assert calls.count("match_helpful_videos") == 3
    assert result["diagnostics"]["matching"]["budget_skipped_candidates"] == 0
    assert result["diagnostics"]["catalog_model_budget_reached"]
    assert result["catalog_enrichment"]["status"] == "partial"


async def test_late_part_evidence_is_rejudged_without_duplicating_or_retimestamping_first_card():
    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    first_visible, late_returned = asyncio.Event(), False
    search_count = 0
    snapshots, judged = [], []

    async def search(_call):
        nonlocal search_count, late_returned
        search_count += 1
        if search_count == 1:
            return [video(800, title="Pygame 键盘输入", snippet="键盘状态轮询", url=url + "?p=3")]
        await first_visible.wait()
        late_returned = True
        return [video(801, title="Pygame 碰撞检测", snippet="轴对齐包围盒相交测试", url=url + "?p=8")]

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        output = []
        for row in data["candidates"]:
            judged.append(row["snippet"])
            assignment = bindings(["keyboard"], "键盘状态轮询")
            if "轴对齐包围盒相交测试" in row["snippet"]:
                assignment += bindings(["collision"], "轴对齐包围盒相交测试")
            output.append({"candidate_id": row["id"], "point_matches": assignment})
        return {"matches": output}

    def publish(snapshot):
        snapshots.append(snapshot)
        if rows(snapshot):
            first_visible.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, provider_factory=factory(Provider(search)), complete=model)
    first = next(snapshot for snapshot in snapshots if rows(snapshot))
    assert late_returned and len(judged) == 2
    assert result["progress"]["candidates"] == 1
    assert len(rows(result)) == len(rows(result, "collision")) == 1
    assert rows(first)[0]["added_at"] == rows(result)[0]["added_at"]
    assert rows(result, "collision")[0]["relevance"] == "targeted"
    assert not result["diagnostics"]["matching"]["unjudged_candidates"]


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
async def test_optional_catalog_is_bounded_and_cancellable_after_recommendation_terminal(stop):
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    entered, terminal = asyncio.Event(), asyncio.Event()
    snapshots = []
    active, cancelled = 0, 0

    async def fetch(_resource):
        nonlocal active, cancelled
        active += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        finally:
            active -= 1

    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    candidate = video(810, url="https://www.bilibili.com/video/BV1VZ4y1G7YB")
    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()

    started = time.monotonic()
    task = asyncio.create_task(run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.15 if stop == "deadline" else 1,
        provider_factory=factory(Provider(lambda _: [candidate])), complete=completion(),
        chapter_enricher_factory=enricher, catalog_deadline_seconds=.08))
    await asyncio.wait_for(entered.wait(), .3)
    await asyncio.wait_for(terminal.wait(), .3)
    first_terminal = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert first_terminal["catalog_enrichment"]["status"] == "running"
    assert not task.done()
    if stop == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert rows(result), "Optional metadata delay must not withhold the ready recommendation"
        assert result["catalog_enrichment"]["status"] == "partial"
        assert result["diagnostics"]["catalog_deadline_reached"]
    assert snapshots[-1]["catalog_enrichment"]["status"] == ("cancelled" if stop == "cancel" else "partial")
    assert {key: snapshots[-1][key] for key in ("status", "finished_at", "elapsed_seconds")} == {
        key: first_terminal[key] for key in ("status", "finished_at", "elapsed_seconds")}
    assert time.monotonic() - started < .5
    assert active == 0 and cancelled == 1


@pytest.mark.parametrize("snippet", [
    "04:32 098-文本编码-03-Python2.x处理中文字符串 04:08 007-游戏窗口-04-创建游戏窗口和游戏循环 10:55 047-碰撞检测-01-子弹摧毁敌机 04:41",
    "本节介绍命令自动补全。 Image 19: 创建游戏窗口和游戏循环 10:55 Image 20: 碰撞检测-01-子弹摧毁敌机 04:41",
    "本节介绍命令自动补全。 相关推荐：创建游戏窗口和游戏循环，碰撞检测-01-子弹摧毁敌机",
])
async def test_search_catalog_and_related_sidebar_cannot_target_unrelated_video(snippet):
    # Reproduces v9's real false positive: a terminal-completion part inherited
    # other parts' timestamps and related-video text from a search extraction.
    candidate = video(820, title="20-文件和目录命令-02-分享自动补全和命令选择技巧_哔哩哔哩_bilibili",
                      snippet=snippet, url="https://www.bilibili.com/video/av14184325?p=20")
    payloads = []

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        payloads.extend(data["candidates"])
        # Even a mistaken model quoting the old contaminated text cannot pass
        # the source guard once catalog/sidebar text has been separated.
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(
            ["keyboard", "collision"], "创建游戏窗口和游戏循环")} for row in data["candidates"]]}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.5, provider_factory=factory(Provider(lambda _: [candidate])), complete=model)
    assert not any(result["recommendations"].values())
    assert all("游戏循环" not in row["snippet"] and "碰撞检测" not in row["snippet"] for row in payloads)


@pytest.mark.parametrize("text, expected", [
    ("本视频讲解键盘轮询与碰撞检测，时长10:55。", "本视频讲解键盘轮询与碰撞检测，时长10:55。"),
    ("本视频讲解碰撞检测。课程目录 1. 矩形相交 10:55 2. 示例 04:41", "本视频讲解碰撞检测。"),
    ("Learn keyboard polling. Related videos: collision detection", "Learn keyboard polling."),
])
def test_genuine_description_is_retained_when_separated_from_catalog_or_sidebar(text, expected):
    assert fast_search._clean_discovery_snippet(text) == expected


async def test_second_match_can_bind_only_observed_chapter_ids_and_preserves_existing_chapters():
    first_visible = asyncio.Event()
    source_count, published_once = 0, False
    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    chapters = [
        {"chapter_id": "native-3", "title": "键盘状态轮询", "index": 3, "url": url + "?p=3"},
        {"chapter_id": "native-8", "title": "矩形相交测试", "index": 8, "url": url + "?p=8"},
    ]

    class Enricher:
        def __init__(self, _settings, _points, **kwargs):
            self.publish = kwargs["publish"]
            self.diagnostics = {"catalogs_received": 1, "scheduled_resources": 1}
        def enqueue(self, resource, _point_ids):
            nonlocal published_once
            if not published_once:
                published_once = True
                self.publish(resource["resource_id"], "keyboard", deepcopy(chapters))
            return True
        async def drain(self, **_kwargs):
            pass
        async def close(self):
            pass

    async def search(_call):
        nonlocal source_count
        source_count += 1
        if source_count == 1:
            return [video(830, title="键盘输入教程", snippet="键盘状态轮询", url=url + "?p=3")]
        await first_visible.wait()
        return [video(831, title="矩形相交教程", snippet="矩形相交测试", url=url + "?p=8")]

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        output = []
        for row in data["candidates"]:
            assignment = bindings(["keyboard"], "键盘状态轮询")
            if row.get("chapters"):
                assignment[0]["chapter_ids"] = ["native-3"]
                assignment += [{"point_id": "collision", "relevance": "targeted", "evidence": "矩形相交测试",
                                "chapter_ids": ["native-8", "invented-99", None, {}]}]
            output.append({"candidate_id": row["id"], "point_matches": assignment})
        return {"matches": output}

    def publish(snapshot):
        if rows(snapshot):
            first_visible.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, provider_factory=factory(Provider(search)), complete=model,
        chapter_enricher_factory=Enricher)
    assert [chapter["chapter_id"] for chapter in rows(result)[0]["matched_chapters"]] == ["native-3", "native-8"]
    assert [chapter["chapter_id"] for chapter in rows(result, "collision")[0]["matched_chapters"]] == ["native-8"]


async def test_catalog_semantics_publishes_during_search_instead_of_waiting_for_a_tail():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    semantic_visible = asyncio.Event()
    searches_started, searches_active = 0, 0
    semantic_calls_during_search = []
    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    candidate = video(850, title="Pygame 键盘输入教程", snippet="读取方向键状态", url=url)

    async def fetch(resource):
        return {"url": resource["url"], "fetch_status": "fetched", "chapters": [
            {"title": "矩形相交测试", "page_number": 8, "url": url + "?p=8",
             "source_url": url, "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}]}

    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    async def search(_call):
        nonlocal searches_started, searches_active
        searches_started += 1
        if searches_started == 1:
            return [candidate]
        searches_active += 1
        try:
            await semantic_visible.wait()
            return []
        finally:
            searches_active -= 1

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        if data["task"] == "match_video_chapters":
            semantic_calls_during_search.append(searches_active > 0)
            return {"matches": [{"resource_id": item["resource_id"], "point_id": "collision",
                "chapter_ids": [chapter["chapter_id"] for chapter in item["chapters"]]}
                for item in data["resources"]]}
        return {"matches": [{"candidate_id": item["id"], "point_matches": bindings(["keyboard"], item["snippet"])}
                            for item in data["candidates"]]}

    def publish(snapshot):
        if rows(snapshot, "collision") and rows(snapshot, "collision")[0].get("matched_chapters"):
            semantic_visible.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.8, provider_factory=factory(Provider(search)), complete=model,
        chapter_enricher_factory=enricher)
    assert semantic_calls_during_search == [True]
    assert semantic_visible.is_set() and searches_active == 0
    assert rows(result, "collision")[0]["matched_chapters"][0]["title"] == "矩形相交测试"
    assert result["progress"]["model_calls"] == 3
    assert not result["diagnostics"]["deadline_reached"]


async def test_slow_metadata_does_not_delay_recommendation_terminal_and_leaves_no_live_children():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    active = 0
    cancelled = 0
    instances = []
    snapshots = []

    async def fetch(_resource):
        nonlocal active, cancelled
        active += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        finally:
            active -= 1

    def enricher(*args, **kwargs):
        instance = HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
        instances.append(instance)
        return instance

    started = time.monotonic()
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=snapshots.append,
        deadline_seconds=10, provider_factory=factory(Provider(lambda _: [video(860)])), complete=completion(),
        chapter_enricher_factory=enricher, catalog_deadline_seconds=.08)
    terminal = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert terminal["elapsed_seconds"] < .5, "Video terminal must be emitted before the catalog wait"
    assert terminal["catalog_enrichment"]["status"] == "running"
    assert result["elapsed_seconds"] == terminal["elapsed_seconds"]
    assert result["catalog_enrichment"]["elapsed_seconds"] > result["elapsed_seconds"]
    assert time.monotonic() - started < 1
    assert rows(result) and result["status"] == "completed"
    assert active == 0 and cancelled == 1
    assert all(task.done() for instance in instances for task in instance._tasks)
    assert result["progress"]["model_calls"] == 2


async def test_catalog_cache_is_injected_only_when_supplied_and_can_fill_chapters_without_fetching():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    called = []

    class Cache:
        def lookup(self, resource):
            called.append(("lookup", resource["url"]))
            return {"url": resource["url"], "fetch_status": "fetched",
                "fetched_at": "2026-10-23T10:00:00+00:00",
                "thumbnail_url": "https://i0.hdslb.com/bfs/archive/cached-cover.jpg",
                "field_provenance": {"thumbnail_url": {
                    "source": "html.bilibili.__INITIAL_STATE__.videoData.pic",
                    "url": url, "fetched_at": "2026-10-23T10:00:00+00:00"}}, "chapters": [
                {"title": POINTS[0]["name"], "page_number": 3, "url": url + "?p=3",
                 "source_url": url, "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}]}
        def observe(self, *args):
            called.append(("observe", args))

    def enricher(*args, **kwargs):
        assert kwargs["load_cached_catalog"].__self__ is cache
        assert kwargs["save_catalog"].__self__ is cache
        return HelpfulVideoChapterEnricher(*args, **kwargs)

    cache = Cache()
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [video(870, url=url)])),
        complete=completion(), chapter_enricher_factory=enricher, catalog_cache=cache)
    assert any(kind == "lookup" for kind, _ in called)
    assert rows(result)[0]["matched_chapters"][0]["title"] == POINTS[0]["name"]
    assert result["diagnostics"]["page_requests"] == 0


async def test_generic_only_catalogs_do_not_reserve_an_unusable_model_call(monkeypatch):
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    monkeypatch.setattr(fast_search, "MAX_MODEL_CALLS", 4)

    async def fetch(resource):
        return {"url": resource["url"], "fetch_status": "fetched", "chapters": [
            {"title": "Pygame编程基础", "page_number": 1, "url": resource["url"],
             "source_url": resource["url"], "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}]}

    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    model = completion()
    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=2, provider_factory=factory(Provider(lambda _: [video(900 + n) for n in range(73)])),
        complete=model, chapter_enricher_factory=enricher)
    assert result["diagnostics"]["chapters"]["catalogs_received"] > 0
    assert result["diagnostics"]["chapters"]["semantic_calls"] == 0
    assert result["progress"]["model_calls"] == len(model.calls) == 4
    assert result["diagnostics"]["matching"]["unjudged_candidates"] == 0
    assert result["diagnostics"]["matching"]["judged_candidates"] == 73


async def test_late_catalog_semantics_updates_only_existing_cards_after_frozen_video_terminal():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    terminal, release = asyncio.Event(), asyncio.Event()
    snapshots, instances, catalog_calls = [], [], []
    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    provider = Provider(lambda _: [video(980, title="键盘输入教程", snippet="读取方向键状态", url=url)])

    async def fetch(resource):
        await release.wait()
        return {"url": resource["url"], "fetch_status": "fetched", "chapters": [
            {"title": title, "page_number": index, "url": url + f"?p={index}",
             "source_url": url, "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}
            for index, title in [(3, "方向键状态采样"), (8, "矩形相交测试")]]}

    def enricher(*args, **kwargs):
        instance = HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
        instances.append(instance)
        return instance

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        if data["task"] == "match_video_chapters":
            catalog_calls.append(terminal.is_set())
            return {"matches": [{"resource_id": resource["resource_id"], "point_id": point_id,
                "chapter_ids": [chapter["chapter_id"] for chapter in resource["chapters"] if chapter["index"] == index]}
                for resource in data["resources"] for point_id, index in [("keyboard", 3), ("collision", 8)]]}
        return {"matches": [{"candidate_id": item["id"], "point_matches": bindings(["keyboard"], item["snippet"])}
                            for item in data["candidates"]]}

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()

    task = asyncio.create_task(run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, catalog_deadline_seconds=.5, provider_factory=factory(provider),
        complete=model, chapter_enricher_factory=enricher))
    await asyncio.wait_for(terminal.wait(), .3)
    first_terminal = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert first_terminal["status"] == "partial" and not rows(first_terminal, "collision")
    assert rows(first_terminal)[0]["matched_chapters"] == []
    assert first_terminal["catalog_enrichment"]["status"] == "running" and not task.done()
    search_calls = len(provider.calls)
    await asyncio.sleep(.03)
    release.set()
    result = await asyncio.wait_for(task, .3)
    assert catalog_calls == [True]
    assert result["catalog_enrichment"]["status"] == "completed"
    assert result["catalog_enrichment"]["elapsed_seconds"] > result["elapsed_seconds"]
    assert len(provider.calls) == search_calls
    assert result["progress"]["recommendation_model_calls"] == 2
    assert result["progress"]["catalog_model_calls"] == 1
    assert result["progress"]["model_calls"] == 3
    frozen = {key: first_terminal[key] for key in ("status", "finished_at", "elapsed_seconds")}
    for snapshot in snapshots[snapshots.index(first_terminal):]:
        assert {key: snapshot[key] for key in frozen} == frozen
        assert not rows(snapshot, "collision"), "Late metadata cannot create another point/resource recommendation"
        assert len(rows(snapshot)) == 1
        def recommendation_identity(row):
            return {**{key: value for key, value in row.items() if key not in {"matched_chapters", "resource"}},
                    "resource": {key: value for key, value in row["resource"].items()
                                 if key not in {"cover_status", "cover_error_code"}}}
        assert recommendation_identity(rows(snapshot)[0]) == recommendation_identity(rows(first_terminal)[0])
    assert [chapter["index"] for chapter in rows(result)[0]["matched_chapters"]] == [3]
    assert all(child.done() for instance in instances for child in instance._tasks)


async def test_confirmed_paid_catalog_can_remove_existing_cards_after_video_terminal():
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    terminal = asyncio.Event()
    snapshots = []

    async def fetch(resource):
        await terminal.wait()
        return {"url": resource["url"], "fetch_status": "fetched", "requires_payment": True}

    def enricher(*args, **kwargs):
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, catalog_deadline_seconds=.5,
        provider_factory=factory(Provider(lambda _: [video(981)])), complete=completion(),
        chapter_enricher_factory=enricher)
    first_terminal = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert rows(first_terminal) and rows(first_terminal, "collision")
    assert not any(result["recommendations"].values())
    assert {key: result[key] for key in ("status", "finished_at", "elapsed_seconds")} == {
        key: first_terminal[key] for key in ("status", "finished_at", "elapsed_seconds")}
    assert result["catalog_enrichment"]["status"] == "completed"


@pytest.mark.parametrize("outcome", ["model_failure", "semantic_budget", "internal_deadline", "background_failure"])
async def test_catalog_terminal_status_reports_partial_or_failed_without_harming_videos(outcome):
    closed = []

    class Enricher:
        def __init__(self, _settings, _points, **kwargs):
            self.match = kwargs["match"]
            self.finished = asyncio.Event()
            self.diagnostics = {}
        def enqueue(self, *_args):
            return True
        def finish_admission(self, **_kwargs):
            self.finished.set()
        async def run_background_match(self, **_kwargs):
            await self.finished.wait()
            if outcome == "model_failure":
                with pytest.raises(RuntimeError, match="Catalog model completion failed"):
                    await self.match("catalog prompt", {"resources": []}, .2)
                self.diagnostics["errors"] = 1
            elif outcome == "semantic_budget":
                self.diagnostics["semantic_budget_reached"] = True
            elif outcome == "internal_deadline":
                self.diagnostics["deadline_reached"] = True
            else:
                raise RuntimeError("synthetic optional catalog failure")
        async def close(self):
            closed.append(True)

    videos = completion()

    async def model(*args, **kwargs):
        if args[2]["task"] == "match_video_chapters":
            raise RuntimeError("synthetic catalog model failure")
        return await videos(*args, **kwargs)

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, catalog_deadline_seconds=.5,
        provider_factory=factory(Provider(lambda _: [video(982)])), complete=model,
        chapter_enricher_factory=Enricher)
    assert result["status"] == "completed" and all(result["recommendations"].values())
    assert result["catalog_enrichment"]["status"] == ("failed" if outcome == "background_failure" else "partial")
    assert closed == [True]
    assert result["progress"]["recommendation_model_calls"] == 2


async def test_accepted_broad_courses_share_same_technology_fallback_without_extra_calls_or_targeted_duplicates(monkeypatch):
    monkeypatch.setattr(fast_search, "MATCH_CONCURRENCY", 1)
    points = [*POINTS, {"id": "text", "name": "文本渲染", "technology": "pygame"},
              {"id": "sql", "name": "关联查询", "technology": "SQL"}]
    # Reproduces v15: the actual teaching library is present in the course's
    # own description, while its broader title names the parent language.
    candidates = [
        video(990, title="Python游戏开发入门_中国大学MOOC(慕课)",
              snippet="本课程介绍Python第三方库Pygame，讲解单机2D游戏设计和实现的基本概念和开发方法。",
              url="https://www.icourse163.org/course/detail.htm?cid=1450456167"),
        video(991, title="二维游戏项目实战", snippet="本课程使用 Pygame，从零完成一个游戏项目。"),
        video(992, title="键盘输入教程", snippet="按键状态与方向键轮询"),
    ]
    calls = []

    async def model(_settings, _prompt, data, **_kwargs):
        calls.append(data["task"])
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": item["id"], "point_matches": bindings(
            ["keyboard"], item["snippet"], "targeted" if item["title"] == "键盘输入教程" else "general")}
            for item in data["candidates"]]}

    result = await run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: candidates)), complete=model)
    assert calls == ["plan_video_discovery", "match_helpful_videos"]
    assert len(rows(result, "keyboard")) == 1 and rows(result)[0]["relevance"] == "targeted"
    assert len(rows(result, "collision")) == len(rows(result, "text")) == 1
    assert rows(result, "collision")[0]["relevance"] == rows(result, "text")[0]["relevance"] == "general"
    assert rows(result, "collision")[0]["resource"]["resource_id"] != rows(result, "text")[0]["resource"]["resource_id"]
    assert not rows(result, "sql")
    assert {row["resource"]["url"] for values in result["recommendations"].values() for row in values} <= {
        item.url for item in candidates}


@pytest.mark.parametrize("title,snippet,relevance,evidence", [
    ("矩形碰撞检测入门教程", "本课讲解 Pygame 的矩形碰撞检测。", "general", "矩形碰撞检测"),
    ("Python游戏开发入门", "本课讲解Python基础。相关推荐：Pygame项目实战教程", "general", "Python基础"),
    ("Python游戏开发入门", "本课程使用其他图形工具。参考资料：Pygame游戏开发教程", "general", "其他图形工具"),
    ("Python游戏开发入门", "本课使用 Pygame 完成一个游戏项目。", "targeted", "Pygame"),
    ("Python游戏开发入门", "本课使用 Pygame 完成一个游戏项目。", "general", "模型编造的教学内容"),
])
async def test_topic_only_or_unaccepted_or_unrelated_mentions_do_not_enter_shared_fallback(title, snippet, relevance, evidence):
    candidate = video(993, title=title, snippet=snippet)

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": item["id"],
            "point_matches": bindings(["keyboard"], evidence, relevance)} for item in data["candidates"]]}

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [candidate])), complete=model)
    assert not rows(result, "collision"), "One point's model binding cannot make a focused or unrelated course universal"


@pytest.mark.parametrize("title", ["Pygame 矩形碰撞检测教程", "Pygame 矩形碰撞检测入门",
                                  "Pygame 游戏开发入门：矩形碰撞检测", "Pygame collision detection tutorial",
                                  "Pygame 游戏开发入门 第7讲 矩形碰撞检测"])
async def test_single_topic_technology_title_cannot_fill_unrelated_empty_points(title):
    candidate = video(994, title=title, snippet="讲解矩形碰撞检测")
    points = [*POINTS, {"id": "text", "name": "文本渲染", "technology": "Pygame"}]
    result = await run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [candidate])),
        complete=completion(points_by_candidate=lambda _candidate, _points: ["collision"]))
    assert len(rows(result, "collision")) == 1 and rows(result, "collision")[0]["relevance"] == "targeted"
    assert not rows(result, "keyboard") and not rows(result, "text")


@pytest.mark.parametrize("title", ["Python入门", "Python 编程基础教程", "Python beginner programming course"])
async def test_plain_technology_introductory_course_still_fills_missing_foundations(title):
    points = [{"id": "variables", "name": "变量与赋值", "technology": "Python"},
              {"id": "branch", "name": "条件分支", "technology": "Python"}]
    result = await run_fast_video_search(settings(), points, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [video(995, title=title, snippet="从零学习编程")])),
        complete=completion(points_by_candidate=lambda _candidate, _points: []))
    assert all(len(values) == 1 and values[0]["relevance"] == "general" for values in result["recommendations"].values())


@pytest.mark.parametrize("with_fallback", [False, True])
async def test_confirmed_missing_catalog_retracts_after_terminal_and_only_reuses_existing_fallback(with_fallback):
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher

    terminal = asyncio.Event()
    snapshots, fetched = [], []
    missing = video(996, title="Pygame 游戏开发入门", snippet="键盘轮询与矩形碰撞检测")
    existing = video(997, title="Pygame 编程基础教程", snippet="从零学习Pygame编程")
    candidates = [missing, existing] if with_fallback else [missing]
    provider = Provider(lambda _: candidates)

    async def fetch(resource):
        fetched.append(resource["url"])
        await terminal.wait()
        return {"url": resource["url"], "fetch_status": "not_found" if resource["url"] == missing.url else "fetched"}

    def enricher(*args, **kwargs):
        assert callable(kwargs["on_unavailable"])
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    async def model(_settings, _prompt, data, **_kwargs):
        if data["task"] == "plan_video_discovery":
            return {"suggestions": []}
        return {"matches": [{"candidate_id": row["id"], "point_matches": bindings(
            [point["id"] for point in POINTS], row["snippet"], "targeted" if row["url"] == missing.url else "general")}
            for row in data["candidates"]]}

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=.6, catalog_deadline_seconds=.5,
        provider_factory=factory(provider), complete=model, chapter_enricher_factory=enricher)
    first_terminal = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert all(values[0]["resource"]["url"] == missing.url for values in first_terminal["recommendations"].values())
    for snapshot in snapshots[snapshots.index(first_terminal):]:
        assert {key: snapshot[key] for key in ("status", "finished_at", "elapsed_seconds")} == {
            key: first_terminal[key] for key in ("status", "finished_at", "elapsed_seconds")}
    assert result["progress"]["search_requests"] == first_terminal["progress"]["search_requests"] == len(provider.calls)
    assert result["progress"]["model_calls"] == first_terminal["progress"]["model_calls"]
    assert missing.url in fetched
    assert result["diagnostics"]["chapters"]["scheduled_resources"] == first_terminal["diagnostics"]["chapters"]["scheduled_resources"], (
        "Retraction must not enqueue another catalog; work already admitted before terminal may finish")
    assert result["diagnostics"]["unavailable_resources"][0]["reason"] == "not_found"
    assert result["diagnostics"]["unavailable_resources"][0]["affected_point_ids"] == ["keyboard", "collision"]
    assert result["progress"]["covered_points"] == (2 if with_fallback else 0)
    if with_fallback:
        assert all(len(values) == 1 and values[0]["resource"]["url"] == existing.url
                   and values[0]["relevance"] == "general" for values in result["recommendations"].values())
    else:
        assert not any(result["recommendations"].values())


async def test_unavailable_course_cannot_be_readded_by_later_source_alias_or_matching():
    unavailable = asyncio.Event()
    url = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    direct = video(998, title="Pygame 游戏开发入门", snippet="键盘轮询与矩形碰撞检测", url=url + "?p=1")
    suggestions = [{"point_id": "keyboard", "queries": [], "videos": [{
        "title": direct.title, "url": direct.url, "snippet": direct.snippet,
        "point_matches": bindings(["keyboard", "collision"], direct.snippet)}]}]

    class Enricher:
        def __init__(self, _settings, _points, **kwargs):
            self.on_unavailable = kwargs["on_unavailable"]
            self.publish = kwargs["publish"]
            self.diagnostics = {}
        def enqueue(self, resource, _point_ids):
            self.on_unavailable(resource["resource_id"])
            # A late annotation must not resurrect the known missing course.
            self.publish(resource["resource_id"], "keyboard", [{"chapter_id": "late", "title": "键盘轮询", "index": 1}])
            unavailable.set()
            return True
        async def close(self):
            pass

    async def search(_call):
        await unavailable.wait()
        return [video(999, title=direct.title, snippet=direct.snippet, url=url.replace("www.", "") + "?p=8")]

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(search)),
        complete=completion(suggestions=suggestions), chapter_enricher_factory=Enricher)
    assert not any(result["recommendations"].values())
    assert result["progress"]["candidates"] == 1
    assert result["diagnostics"]["rejections"]["known_unavailable"] > 0
    assert len(result["diagnostics"]["unavailable_resources"]) == 1


async def test_legacy_catalog_factory_without_unavailable_callback_remains_compatible():
    closed = []

    class LegacyEnricher:
        def __init__(self, _settings, _points, *, match, publish, on_paid, deadline, max_resources):
            self.diagnostics = {}
        def enqueue(self, *_args):
            return True
        async def close(self):
            closed.append(True)

    result = await run_fast_video_search(settings(), POINTS, INPUT, publish=lambda _: None,
        deadline_seconds=.6, provider_factory=factory(Provider(lambda _: [video(1000)])),
        complete=completion(), chapter_enricher_factory=LegacyEnricher)
    assert all(result["recommendations"].values()) and closed == [True]


async def test_background_missing_cover_fetch_precedes_new_covered_catalogs_on_same_host(monkeypatch):
    from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher, MAX_CATALOG_RESOURCES

    # Keep model completion order deterministic; native catalog tasks still use
    # the real concurrent scheduler and its same-host lock.
    monkeypatch.setattr(fast_search, "MATCH_CONCURRENCY", 1)

    # Fill the existing foreground allowance with already illustrated cards.
    # The last two cards are admitted only after expansion, in display order:
    # an illustrated slow directory, then a card still missing its cover.
    initial = [video(2000 + n).model_copy(update={
        "thumbnail_url": f"https://i0.hdslb.com/observed-{n}.jpg"})
        for n in range(MAX_CATALOG_RESOURCES)]
    slow = video(2100).model_copy(update={"thumbnail_url": "https://i0.hdslb.com/observed-slow.jpg"})
    missing = video(2101)
    candidates = [*initial, slow, missing]
    fetched, instances = [], []
    active = peak_active = 0

    async def fetch(resource):
        nonlocal active, peak_active
        fetched.append(resource["url"])
        active += 1
        peak_active = max(peak_active, active)
        try:
            if resource["url"] == slow.url:
                await asyncio.Event().wait()
            observed = {"url": resource["url"], "fetch_status": "fetched", "chapters": [],
                        "fetched_at": "2026-10-24T00:00:00+00:00"}
            if resource["url"] == missing.url:
                observed.update(thumbnail_url="https://i0.hdslb.com/backfilled.jpg",
                    field_provenance={"thumbnail_url": {"source": "html.bilibili.__INITIAL_STATE__.videoData.pic",
                        "url": resource["url"], "fetched_at": observed["fetched_at"]}})
            return observed
        finally:
            active -= 1

    def enricher(*args, **kwargs):
        instance = HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
        instances.append(instance)
        return instance

    provider = Provider(lambda call: candidates if "入门 项目实战 教程" in call["query"] else [])
    result = await run_fast_video_search(settings(), POINTS[:1], {**INPUT, "preferred_platforms": ["bilibili"]},
        publish=lambda _: None, deadline_seconds=2, catalog_deadline_seconds=.1,
        provider_factory=factory(provider), complete=completion(), chapter_enricher_factory=enricher)

    assert fetched[:MAX_CATALOG_RESOURCES] == [item.url for item in initial]
    assert fetched[MAX_CATALOG_RESOURCES:] == [missing.url, slow.url], (
        "A new missing cover must acquire the same-host slot before an already illustrated slow directory")
    assert peak_active == 1 and active == 0
    assert [row["resource"]["url"] for row in rows(result)] == [item.url for item in candidates], (
        "Scheduling priority must not reorder or filter recommendations")
    backfilled = next(row["resource"] for row in rows(result) if row["resource"]["url"] == missing.url)
    assert backfilled["thumbnail_url"] == "https://i0.hdslb.com/backfilled.jpg"
    instance = instances[0]
    assert instance.diagnostics["network_scheduled_resources"] == len(candidates)
    assert instance.max_resources == 96 and instance.max_http_requests == 288
    assert all(task.done() for task in instance._tasks)
