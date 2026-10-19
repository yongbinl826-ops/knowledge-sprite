"""Independent offline video gates. These synthetic records are not live evidence."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.queries import generate_queries, prioritize_video_entry_query
from backend.app.ranking import compound_english_match, decompose_topic, learner_fit, own_video_description, rank_resource


def record(title, snippet="", *, url="https://www.bilibili.com/video/BV1ab411c7De", **fields):
    resource = {"resource_id": "r", "url": url, "canonical_url": url, "title": title, "resource_type": "video",
                "video_evidence_status": "search_discovered", "metadata_evidence_level": "search", "fetch_status": "search_only_policy",
                "field_provenance": {"title": {"source": "search", "evidence_id": "s"},
                                     "resource_type": {"source": "url_pattern", "evidence_id": "s"},
                                     "video_evidence_status": {"source": "url_pattern", "evidence_id": "s"}}, **fields}
    evidence = [{"evidence_id": "s", "kind": "search", "source": "synthetic-test", "title": title,
                 "snippet": snippet, "url": url, "knowledge_point_id": "p"}]
    return resource, evidence


def evaluate(point, title, snippet="", *, level="beginner", **fields):
    resource, evidence = record(title, snippet, **fields)
    original = deepcopy((resource, evidence))
    match = rank_resource({"knowledge_point_id": "p", "text": point}, resource, evidence,
                          SearchRequest(knowledge_points=[point], student_level=level))
    assert (resource, evidence) == original
    return match


@pytest.mark.parametrize("title,snippet", [
    ("pygame键盘事件——控制小船左右移动", ""),
    ("Pygame 控制角色移动的两种方式｜Python 游戏开发教程",
     "在 Python Pygame 中，实现角色移动可分为两个步骤，首先获取输入设备的状态，比如，键盘的某个按键的按下状态，然后根据状态调整角色的位置。而获取设备状态的方式大致分为两种，实时获取和通过事件获取，本视频将为大家演示这两种方式。"),
    ("【Python编程】Win10系统-Pygame使用键盘控制游戏人物移动",
     "本期视频分享了如何使用键盘事件来控制游戏人物移动"),
])
def test_real_shaped_keyboard_movement_sources_match_project_intent(title, snippet):
    # Text shapes came from retained live search metadata; these are offline
    # fixtures, not additional network observations or playback verification.
    match = evaluate("pygame 键盘控制角色左右移动", title, snippet)
    assert match and match["topic_evidence_status"] == "supported"
    assert "pygame_keyboard_controls_sprite_movement" in match["topic_match_rules"]
    assert match["supporting_evidence_ids"] == ["s"]


@pytest.mark.parametrize("title,snippet,fields", [
    ("Pygame 零基础游戏开发教程", "本库提供键盘输入、图形和音频功能。", {}),
    ("Scratch 键盘控制角色左右移动", "", {}),
    ("Pygame 安装教程。Scratch 键盘控制角色左右移动", "", {}),
    ("Pygame 键盘输入与图像处理", "动画自动控制角色左右移动。", {}),
    ("Pygame 角色移动教程", "本节不讲键盘控制角色左右移动，只演示自动动画。", {}),
    ("Pygame 教程", "需要掌握键盘控制角色左右移动。本节讲碰撞检测。", {}),
    ("Pygame 教程", "未实现键盘控制角色左右移动。", {}),
    ("Pygame 教程", "仅提及键盘控制角色左右移动。", {}),
    ("Pygame key.get_pressed 教程", "介绍 API 名称，不讲角色移动。", {}),
    ("pygame键盘事件——控制小船左右移动", "", {"url": "https://www.bilibili.com.evil.example/video/BV1ab411c7De"}),
])
def test_keyboard_intent_requires_owned_instruction_and_trusted_video_entry(title, snippet, fields):
    assert evaluate("pygame 键盘控制角色左右移动", title, snippet, **fields) is None


def test_keyboard_intent_does_not_discard_unobserved_qualifications():
    assert evaluate("pygame 键盘控制角色左右移动与地图边界检测", "pygame键盘事件——控制小船左右移动")["topic_evidence_status"] == "partial"
    assert evaluate("pygame 键盘控制角色左右移动并防止越过地图边界", "pygame键盘事件——控制小船左右移动") is None


REALTIME_MOVEMENT_TITLE = "Pygame 控制角色移动的两种方式｜Python 游戏开发教程"
REALTIME_MOVEMENT_DESCRIPTION = (
    "在 Python Pygame 中，实现角色移动可分为两个步骤，首先获取输入设备的状态，比如，键盘的某个按键的按下状态，然后根据状态调整角色的位置。"
    "而获取设备状态的方式大致分为两种，实时获取和通过事件获取，本视频将为大家演示这两种方式。"
    "0:00 - 摘要，角色的移动 0:40 - 实时获取设备状态，然后移动角色 2:42 - 通过事件获取设备状态，然后移动角色"
)
REALTIME_SEARCH_SNIPPET = REALTIME_MOVEMENT_DESCRIPTION.split("0:00")[0] + "0:00 - 摘要 ..."
HELD_MOVEMENT_POINT = "pygame 键盘长按移动挡板与边界限制"
CURRENT_PROJECT_MOVEMENT_POINT = "pygame 键盘事件与挡板按键移动"


@pytest.mark.parametrize("source_text", [REALTIME_MOVEMENT_DESCRIPTION, REALTIME_SEARCH_SNIPPET])
def test_real_time_keyboard_state_source_covers_held_movement_but_not_boundary(source_text):
    match = evaluate(HELD_MOVEMENT_POINT, REALTIME_MOVEMENT_TITLE, source_text)
    assert match and match["topic_evidence_status"] == "partial"
    assert {p["text"]: p["status"] for p in match["subtopic_coverage"]} == {
        "键盘长按移动挡板": "supported", "边界限制": "unknown"}
    assert "尚未确认：边界限制" in match["recommendation_reason"]
    assert match["supporting_evidence_ids"] == ["s"]


@pytest.mark.parametrize("title,description", [
    ("pygame键盘事件——控制小船左右移动", "事件循环持续检查用户按键、移动鼠标和关闭窗口等操作。"),
    ("Pygame使用键盘控制游戏人物移动", "本期视频分享如何使用键盘事件控制人物移动。"),
    ("Pygame 实时动画教程", "实时更新画面，通过 KEYDOWN 事件控制人物移动。"),
    (REALTIME_MOVEMENT_TITLE, "只通过事件获取设备状态，然后移动角色。"),
    (REALTIME_MOVEMENT_TITLE, "键盘的某个按键的按下状态，然后根据状态调整角色的位置。实时获取和通过事件获取，本视频不讲这两种方式。"),
    (REALTIME_MOVEMENT_TITLE, "键盘的某个按键的按下状态，然后根据状态调整角色的位置。顺带提及实时获取和通过事件获取，本视频演示这两种方式。"),
    (REALTIME_MOVEMENT_TITLE, "不讲" + REALTIME_MOVEMENT_DESCRIPTION),
    (REALTIME_MOVEMENT_TITLE, "需要掌握键盘的某个按键的按下状态，然后根据状态调整角色的位置。实时获取设备状态，然后移动角色。"),
    ("Pygame 教程", "键盘的某个按键的按下状态，然后根据状态调整角色的位置。课程大纲 课时1实时获取设备状态，然后移动角色。"),
    ("Pygame 教程", "键盘的某个按键的按下状态，然后根据状态调整角色的位置。Scratch 实时获取设备状态，然后移动角色。"),
    ("Pygame 教程", "键盘的某个按键的按下状态，然后根据状态调整角色的位置。未实现实时获取设备状态，然后移动角色。"),
])
def test_single_events_or_other_lessons_do_not_prove_held_movement(title, description):
    match = evaluate(HELD_MOVEMENT_POINT, title, description)
    assert match is None or not any(p["status"] == "supported" for p in match["subtopic_coverage"] if p["text"] == "键盘长按移动挡板")


@pytest.mark.parametrize("description", [
    "Pygame 每帧读取键盘按下状态，然后移动挡板。",
    "Pygame 实时检测按键状态并更新角色位置。",
    "Pygame 按住左右方向键时连续移动人物。",
])
def test_explicit_continuous_input_to_position_remains_partial_without_boundary(description):
    match = evaluate(HELD_MOVEMENT_POINT, "Pygame 连续移动教程", description)
    assert match and match["topic_evidence_status"] == "partial"
    assert match["subtopic_coverage"][1]["status"] == "unknown"


def test_current_real_project_shape_matches_only_the_named_event_and_movement():
    match = evaluate(CURRENT_PROJECT_MOVEMENT_POINT, REALTIME_MOVEMENT_TITLE, REALTIME_SEARCH_SNIPPET)
    assert match and match["topic_evidence_status"] == "supported"
    assert {p["text"]: p["status"] for p in match["subtopic_coverage"]} == {
        "键盘事件": "supported", "挡板按键移动": "supported"}
    event_only = evaluate(CURRENT_PROJECT_MOVEMENT_POINT, "Pygame 键盘事件入门教程", "介绍事件队列。")
    assert event_only and event_only["topic_evidence_status"] == "partial"
    assert event_only["subtopic_coverage"][1]["status"] == "unknown"
    assert evaluate(CURRENT_PROJECT_MOVEMENT_POINT, "Pygame 动画教程", "使用鼠标移动挡板。") is None


@pytest.mark.parametrize("wording", ["文字显示", "文本显示", "字体渲染", "显示文字", "渲染文本"])
def test_pygame_text_display_aliases_do_not_supply_scoring(wording):
    point = "pygame 分数计分与屏幕文字显示"
    match = evaluate(point, "pygame 教程：" + wording, "本节没有教计分。pygame " + wording + "示例。")
    assert match and match["topic_evidence_status"] == "partial"
    assert {p["text"]: p["status"] for p in match["subtopic_coverage"]} == {"分数计分": "unknown", "屏幕文字显示": "supported"}


@pytest.mark.parametrize("title,description", [
    ("Pygame 字体安装教程", "安装字体文件，没有教文字显示。"),
    ("Pygame font API 列表", "本节只列出字体 API，不讲文本显示。"),
    ("Qt 字体渲染教程", "显示文字示例。"),
    ("Pygame 安装教程", "Qt 文本显示教程。"),
    ("Pygame 教程", "需要掌握字体渲染；本节介绍坐标。"),
    ("Pygame 字体安装教程", "相关视频：Pygame 文字显示教程"),
])
def test_text_display_needs_owned_teaching_not_font_install_or_other_video(title, description):
    assert evaluate("pygame 分数计分与屏幕文字显示", title, description) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("point,title,url,covered,unknown", [
    ("pygame 分数计分与屏幕文字显示", "pygame教程------文字显示", "https://www.bilibili.com/video/BV1bv4y1H76D/", "屏幕文字显示", "分数计分"),
    ("pygame 初始化与固定帧率主循环", "游戏初始化 | PyGame练习", "https://www.bilibili.com/video/BV1Kd7MzfE3z/", "初始化", "固定帧率主循环"),
])
async def test_real_source_shapes_search_to_fetched_page_keep_unknown_skill(tmp_path, point, title, url, covered, unknown):
    # Both titles and public-page observations exist in the retained v7 database.
    # This is an offline search/fetch pipeline fixture, not new live verification.
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    fetched = []
    def respond(request):
        return httpx.Response(200, json={"results": [{"title": title, "url": url, "content": title, "template": "videos.html"}]})
    class PageFacts:
        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            return {"title": title, "fetch_status": "fetched", "metadata_evidence_level": "page",
                    "field_provenance": {"title": {"source": "fixture.observed_public_title", "evidence_id": "page-title", "url": url}},
                    "evidence": [{"evidence_id": "page-title", "kind": "page", "field": "title",
                                  "source": "fixture.observed_public_title", "url": url, "text": title}]}
    settings = Settings(database_path=str(tmp_path / "two-real-sources.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("fixture",), max_search_requests=1, max_detail_pages=1, search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=PageFacts())
        try:
            jid = service.create(SearchRequest(knowledge_points=[point]))["job_id"]
            await service.run(jid)
            group = service.results(jid)["groups"][0]
            assert fetched == [url] and store.get_job(jid)["progress"]["details_completed"] == 1
            assert not group["items"] and len(group["partial_items"]) == 1
            item = group["partial_items"][0]
            assert item["resource"]["fetch_status"] == "fetched"
            coverage = {p["text"]: p["status"] for p in item["match"]["subtopic_coverage"]}
            assert coverage[covered] == "supported" and coverage[unknown] == "unknown"
        finally:
            store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("point", [HELD_MOVEMENT_POINT, CURRENT_PROJECT_MOVEMENT_POINT])
async def test_namespaced_project_unit_keeps_only_observed_subtopics_through_job_pipeline(tmp_path, point):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    queries = []
    fetched = []
    def respond(request):
        queries.append(request.url.params["q"])
        return httpx.Response(200, json={"results": [{"title": REALTIME_MOVEMENT_TITLE,
            "content": REALTIME_SEARCH_SNIPPET,
            "url": "https://www.bilibili.com/video/BV1ab411c7De", "template": "videos.html"}]})
    class PageFacts:
        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            return {"fetch_status": "fetched", "metadata_evidence_level": "page",
                    "description": REALTIME_MOVEMENT_DESCRIPTION,
                    "field_provenance": {"description": {"source": "fixture.public_description", "evidence_id": "page-description", "url": candidate["url"]}},
                    "evidence": [{"evidence_id": "page-description", "kind": "page", "field": "description",
                                  "source": "fixture.public_description", "url": candidate["url"], "text": REALTIME_MOVEMENT_DESCRIPTION}]}
    settings = Settings(database_path=str(tmp_path / "namespaced-unit.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("fixture",), max_search_requests=1, max_detail_pages=1,
                        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=PageFacts())
        try:
            job_id = service.create(SearchRequest(knowledge_points=[point],
                project_context="项目还涉及边界钳制、计分和游戏重开；这些要求不能作为来源教学证据。"))["job_id"]
            await service.run(job_id)
            result = service.results(job_id)
            assert all("pygame" in q for q in queries)
            assert len(fetched) == 1
            assert store.get_job(job_id)["progress"]["details_completed"] == 1
            group = result["groups"][0]
            visible = group["partial_items"] if point == HELD_MOVEMENT_POINT else group["items"]
            assert len(visible) == 1
            assert visible[0]["resource"]["fetch_status"] == "fetched"
            assert any(e.get("field") == "description" and e.get("kind") == "page"
                       for e in visible[0]["evidence"])
            coverage = visible[0]["match"]["subtopic_coverage"]
            if point == HELD_MOVEMENT_POINT:
                assert not group["items"] and coverage[0]["status"] == "supported" and coverage[1]["status"] == "unknown"
                assert group["collection_coverage"]["status"] == "some_subtopics_supported"
            else:
                assert {p["text"] for p in coverage} == {"键盘事件", "挡板按键移动"}
                assert all(p["status"] == "supported" for p in coverage)
                assert not any("边界" in p["text"] for p in coverage)
            assert store.get_job(job_id)["knowledge_points"][0]["text"] == point
        finally:
            store.close()


@pytest.mark.parametrize("point,title", [
    ("Pygame 事件处理与碰撞检测", "Python 零基础入门视频教程"),
    ("pandas 分组聚合与图表绘制", "Python 基础课程"),
    ("JavaScript 表单校验与 fetch API 请求", "HTML CSS JavaScript 基础教程"),
    ("Arduino 模拟传感器读取与串口输出", "Arduino 入门介绍"),
])
def test_general_foundations_never_replace_project_skills(point, title):
    assert evaluate(point, title) is None


@pytest.mark.parametrize("point", [
    "Pygame 事件处理与碰撞检测", "pandas 分组聚合与图表绘制",
    "JavaScript 表单校验与 fetch API 请求", "Arduino 模拟传感器读取与串口输出",
])
def test_explicit_project_skills_are_evidenced_and_explained(point):
    match = evaluate(point, point + " 入门视频教程", "本教程通过实际项目练习讲解 " + point)
    assert match and match["topic_evidence_status"] == "supported"
    assert point in match["recommendation_reason"]
    assert "学习阶段相符" in match["recommendation_reason"]
    assert match["supporting_evidence_ids"] == ["s"]


@pytest.mark.parametrize("fields", [
    {"requires_login": True, "fetch_status": "login_required"},
    {"requires_payment": True, "fetch_status": "search_only_policy"},
    {"fetch_status": "access_denied", "access_notice": "地区限制，访问要求未确认"},
])
def test_access_conditions_are_not_invalid_links(fields):
    match = evaluate("Pygame 碰撞检测", "Pygame 碰撞检测 入门视频教程", **fields)
    assert match and match["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,hello", "file:///C:/Windows/win.ini",
    "http://127.0.0.1/video/BV1ab411c7De", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/video/BV1ab411c7De", "https://user:pass@www.bilibili.com/video/BV1ab411c7De",
    "https://www.bilibili.com:8080/video/BV1ab411c7De", "https://www.bilibili.com\\@127.0.0.1/video/BV1ab411c7De",
])
def test_unsafe_stored_link_is_rejected_even_for_relaxed_ranking(url):
    resource, evidence = record("Pygame 碰撞检测视频教程", url=url)
    request = SearchRequest(knowledge_points=["Pygame 碰撞检测"])
    assert rank_resource({"knowledge_point_id": "p", "text": request.knowledge_points[0]}, resource, evidence,
                         request, require_type=False) is None


def test_unsafe_resolved_url_cannot_survive_read_time_guard():
    assert evaluate("Pygame 碰撞检测", "Pygame 碰撞检测教程", resolved_url="http://localhost/admin") is None


def test_student_level_changes_order_with_source_based_reason():
    topic = "Pygame 碰撞检测"
    beginner = evaluate(topic, topic + " 入门教程")
    advanced = evaluate(topic, topic + " 高级教程")
    assert beginner["ranking_score"] > advanced["ranking_score"]
    assert "初学者建议先完成本单元先修" in advanced["recommendation_reason"]
    assert "高级" in advanced["recommendation_reason"]
    assert "学习门槛未由来源明确确认" in evaluate(topic, topic + "视频教程")["recommendation_reason"]


def test_mixed_course_levels_stay_unknown_and_advanced_chapter_is_not_an_entry_level():
    assert learner_fit("beginner", "Pygame 入门到高级", "") == (0, " 学习门槛未由来源明确确认，请先看课程简介。")
    assert learner_fit("any", "Pygame 高级", "") == (0, "")
    assert learner_fit("beginner", "Pygame 入门", "高级课程介绍")[0] > 0


@pytest.mark.parametrize("warning", ["不适合初学者", "not for beginners", "not intended for absolute beginners"])
def test_explicit_beginner_exclusion_is_not_mistaken_for_beginner_fit(warning):
    score, explanation = learner_fit("beginner", "Pygame tutorial", warning)
    assert score < 0 and "不适合初学者" in explanation


def test_unbacked_chapter_cannot_invent_project_skill_support():
    resource, evidence = record("Python 入门教程", chapters=[{"title": "Pygame 事件处理与碰撞检测", "evidence_id": "invented"}])
    request = SearchRequest(knowledge_points=["Pygame 事件处理与碰撞检测"])
    assert rank_resource({"knowledge_point_id": "p", "text": request.knowledge_points[0]}, resource, evidence, request) is None


def test_mixed_language_unit_keeps_only_the_observed_component():
    point = "JavaScript 表单校验与 fetch API 请求"
    plan = decompose_topic(point)
    assert plan["shared_context"] == ["JavaScript"]
    assert [part["text"] for part in plan["subtopics"]] == ["表单校验", "fetch API 请求"]
    match = evaluate(point, "JavaScript fetch API 请求视频教程", "使用 fetch API 发起请求")
    assert match and match["topic_evidence_status"] == "partial"
    assert {row["text"]: row["status"] for row in match["subtopic_coverage"]} == {"表单校验": "unknown", "fetch API 请求": "supported"}
    assert evaluate(point, "Python fetch API 请求教程") is None


def test_course_outline_cannot_stitch_keyboard_events_to_image_processing():
    point = "Pygame 事件处理与碰撞检测"
    match = evaluate(point, "Pygame 碰撞检测视频教程", "课程大纲：使用键盘事件；图像处理；矩形碰撞检测。")
    assert match and match["topic_evidence_status"] == "partial"
    assert {row["text"]: row["status"] for row in match["subtopic_coverage"]} == {"事件处理": "unknown", "碰撞检测": "supported"}
    assert "已有来源证据：碰撞检测" in match["recommendation_reason"]
    assert "尚未确认：事件处理" in match["recommendation_reason"]
    assert evaluate("pandas 分组聚合与图表绘制", "pandas 分组聚合视频教程", "图表展示。绘制圆形。")["topic_evidence_status"] == "partial"
    assert evaluate("Pygame 事件处理", "Pygame 视频教程", "课程大纲：使用键盘事件；图像处理。") is None


@pytest.mark.parametrize("wording", ["Pygame 事件处理", "Pygame 事件的处理", "Pygame 处理事件"])
def test_same_noun_and_action_local_word_order_remains_supported(wording):
    match = evaluate("Pygame 事件处理与碰撞检测", "Pygame 碰撞检测视频教程", wording)
    assert match["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("wording", ["Pygame 不讲事件处理", "Pygame 不涉及事件处理", "Pygame 无法处理事件"])
def test_negative_action_statement_does_not_prove_missing_component(wording):
    match = evaluate("Pygame 事件处理与碰撞检测", "Pygame 碰撞检测视频教程", wording)
    assert match and match["topic_evidence_status"] == "partial"
    assert next(row for row in match["subtopic_coverage"] if row["text"] == "事件处理")["status"] == "unknown"


def test_model_query_expansion_cannot_insert_operators_or_forget_exact_skill():
    topic = "Pygame 事件处理与碰撞检测"
    request = SearchRequest(knowledge_points=[topic])
    queries = generate_queries("p", topic, request, ["site:attacker.example Pygame", "https://attacker.example/video", "Pygame collision event"])
    assert topic in queries[0].query
    assert all("attacker" not in query.query for query in queries)
    assert len(queries) <= 6


def test_preferred_direct_video_query_precedes_open_web_without_dropping_queries():
    topic = "Pygame 事件处理与碰撞检测"
    request = SearchRequest(knowledge_points=[topic])
    queries = generate_queries("p", topic, request)
    scheduled = prioritize_video_entry_query(queries)
    assert scheduled[0].domain_filters == ["bilibili.com"]
    assert topic in scheduled[0].query
    assert set(query.query for query in scheduled) == set(query.query for query in queries)
    assert scheduled[1] == queries[0]
    unscoped = generate_queries("p", topic, SearchRequest(knowledge_points=[topic], preferred_platforms=[]))
    assert prioritize_video_entry_query(unscoped) == unscoped


@pytest.mark.asyncio
async def test_video_first_budget_preserves_all_points_fallback_without_extra_requests(tmp_path):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    points = ["Pygame 碰撞检测", "pandas 分组聚合", "JavaScript 表单校验", "Arduino 串口输出"]
    calls = []
    def respond(request):
        calls.append(request)
        # A permitted empty primary response may use the independently allowed
        # backup; no denial/rate-limit is bypassed by the scheduling change.
        return httpx.Response(200, json={"results": []})
    settings = Settings(database_path=str(tmp_path / "video-budget.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), searxng_fallback_engines=("backup",),
                        max_search_requests=12, max_detail_pages=0, search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        jobs = JobService(settings, store, provider=SearXNGProvider(settings, client))
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=points))["job_id"]
            await jobs.run(job_id)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            first_round = attempts[:len(points)]
            assert [a["knowledge_point_id"] for a in first_round] == [p["knowledge_point_id"] for p in job["knowledge_points"]]
            assert all(a["domain_filters"] == ["bilibili.com"] for a in first_round)
            assert all(len(a["provider_requests"]) == 2 for a in first_round)
            assert job["progress"]["search_requests"] == len(calls) <= 12
            assert all(not group["items"] for group in jobs.results(job_id)["groups"])
        finally:
            store.close()


@pytest.mark.asyncio
async def test_next_query_targets_observed_missing_skill_without_claiming_full_single_video(tmp_path):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    queries = []
    def respond(request):
        queries.append(request.url.params["q"])
        title, url = (("pandas 分组聚合视频教程", "https://www.bilibili.com/video/BV1ab411c7De") if len(queries) == 1
                      else ("pandas 图表绘制视频教程", "https://www.bilibili.com/video/BV1cd411c7Df"))
        return httpx.Response(200, json={"results": [{"title": title, "content": title, "url": url, "template": "videos.html"}]})
    settings = Settings(database_path=str(tmp_path / "missing-skill.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), max_search_requests=2, max_detail_pages=0,
                        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        jobs = JobService(settings, store, provider=SearXNGProvider(settings, client))
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["pandas 分组聚合与图表绘制"]))["job_id"]
            await jobs.run(job_id)
            assert len(queries) == 2
            assert "分组聚合与图表绘制" in queries[0]
            assert "pandas 图表绘制" in queries[1] and "聚合" not in queries[1]
            group = jobs.results(job_id)["groups"][0]
            assert not group["items"] and len(group["partial_items"]) == 2
            assert group["collection_coverage"]["status"] == "all_subtopics_supported"
            assert group["collection_coverage"]["single_resource_full_coverage"] is False
        finally:
            store.close()


@pytest.mark.asyncio
async def test_gap_catalog_probes_are_bounded_and_only_real_page_facts_add_coverage(tmp_path):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    queries, fetched = [], []
    def respond(request):
        queries.append(request.url.params["q"])
        rows = [{"title": "pandas 分组聚合视频教程", "url": "https://www.bilibili.com/video/BV1ab411c7De"}] if len(queries) == 1 else [
            {"title": "pandas 零基础完整课程", "url": f"https://www.bilibili.com/video/BV1cd411c7D{suffix}"} for suffix in "fgh"]
        return httpx.Response(200, json={"results": [dict(row, template="videos.html") for row in rows]})

    class PageFacts:
        async def enrich(self, candidate):
            fetched.append(candidate["title"])
            if "完整课程" not in candidate["title"]:
                return {"fetch_status": "search_only_policy", "metadata_evidence_level": "search", "evidence": []}
            return {"title": "pandas 图表绘制公开课", "fetch_status": "fetched", "metadata_evidence_level": "page",
                    "field_provenance": {"title": {"source": "html.title", "evidence_id": "page-title", "url": candidate["url"]}},
                    "evidence": [{"id": "page-title", "evidence_id": "page-title", "kind": "page", "field": "title",
                                  "source": "html.title", "url": candidate["url"], "text": "pandas 图表绘制公开课"}]}

    settings = Settings(database_path=str(tmp_path / "gap-catalog.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), max_search_requests=2, max_detail_pages=8,
                        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        jobs = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=PageFacts())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["pandas 分组聚合与图表绘制"]))["job_id"]
            await jobs.run(job_id)
            assert sum("完整课程" in title for title in fetched) == 2
            group = jobs.results(job_id)["groups"][0]
            assert not group["items"] and group["collection_coverage"]["status"] == "all_subtopics_supported"
            assert len([r for r in store.resources(job_id).values() if r["fetch_status"] == "not_fetched"]) == 1
            assert all(item["match"]["topic_evidence_status"] == "partial" for item in group["partial_items"])
        finally:
            store.close()


@pytest.mark.asyncio
async def test_later_round_discovers_gap_after_empty_first_round(tmp_path):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    queries = []
    def respond(request):
        queries.append(request.url.params["q"])
        if len(queries) == 1:
            return httpx.Response(200, json={"results": []})
        title, suffix = ("pandas 分组聚合视频教程", "e") if len(queries) == 2 else ("pandas 图表绘制视频教程", "f")
        return httpx.Response(200, json={"results": [{"title": title, "url": f"https://www.bilibili.com/video/BV1ab411c7D{suffix}", "template": "videos.html"}]})
    settings = Settings(database_path=str(tmp_path / "late-gap.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), max_search_requests=3, max_detail_pages=0,
                        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        jobs = JobService(settings, store, provider=SearXNGProvider(settings, client))
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["pandas 分组聚合与图表绘制"]))["job_id"]
            await jobs.run(job_id)
            assert len(queries) == 3 and "pandas 图表绘制" in queries[-1] and "聚合" not in queries[-1]
            assert jobs.results(job_id)["groups"][0]["collection_coverage"]["status"] == "all_subtopics_supported"
        finally:
            store.close()


def test_gap_probe_recognizes_module_separator_without_accepting_identifier_prefix():
    from backend.app.service import JobService
    point = {"knowledge_point_id": "p", "text": "pandas 分组聚合与图表绘制"}
    resource, evidence = record("131.Pandas_Matplotlib模块-绘制图")
    evidence[0]["query"] = "gap-query"
    state = {"gap_queries": {"p": "gap-query"}}
    assert JobService._gap_catalog_probe(point, resource, evidence, state)
    assert not JobService._gap_catalog_probe(point, resource, [dict(evidence[0], title="PandasWrapper 基础课")], state)
    assert not JobService._gap_catalog_probe(point, resource, [dict(evidence[0], query="some other query")], state)
    assert not JobService._gap_catalog_probe(point, resource, evidence, dict(state, gap_probes_started={"p": {"one", "two"}}))


def test_teaching_modifiers_bind_noun_action_without_borrowing_another_topic():
    assert compound_english_match("HTML 表单校验", ["HTML 表单零基础教程：双重校验安全思路"])
    assert compound_english_match("HTML 表单校验", ["HTML5表单可以直接用正则表达式校验啦"])
    assert not compound_english_match("Pygame 事件处理", ["Pygame 事件零基础教程：图像处理"])
    assert not compound_english_match("pandas 图表绘制", ["pandas 图表零基础教程：绘制圆形"])


UNCONFIRMED_LANDING_TITLE = "视频去哪了呢？_哔哩哔哩_bilibili"
UNCONFIRMED_VIDEO_URL = "https://www.bilibili.com/video/BV1e5w9z8Eo9/"


def unconfirmed_landing_html():
    # Reconstructed only from retained v7 og:title/description, not a claimed
    # full HTML capture. No error payload or deletion cause was retained.
    return ('<html><head><title>' + UNCONFIRMED_LANDING_TITLE + '</title>'
            '<meta property="og:title" content="' + UNCONFIRMED_LANDING_TITLE + '">'
            '<meta property="og:type" content="video">'
            '<meta property="og:description" content="{$0}, 视频播放量 undefined、弹幕量 {$1}"></head><body></body></html>')


def test_exact_unconfirmed_bilibili_landing_is_not_fetched_or_declared_deleted():
    from backend.app.extractor import MetadataExtractor
    result = MetadataExtractor().extract(unconfirmed_landing_html(), UNCONFIRMED_VIDEO_URL, "2026-10-18T00:00:00Z")
    assert result["fetch_status"] == "unavailable_unconfirmed"
    assert result["video_evidence_status"] == "none" and result["chapters"] == []
    assert "title" not in result and "description" not in result and "resource_type" not in result
    assert "尚未确认" in result["access_notice"]
    assert "not_a_deletion_or_access_cause_diagnosis" in result["evidence"][0]["text"]
    ordinary = MetadataExtractor().extract(unconfirmed_landing_html().replace(UNCONFIRMED_LANDING_TITLE, "Python 教程：视频去哪了呢？问题排查"), UNCONFIRMED_VIDEO_URL, "2026-10-18T00:00:00Z")
    assert ordinary["fetch_status"] == "fetched"


@pytest.mark.asyncio
async def test_unconfirmed_landing_fetch_preserves_search_title():
    from backend.app.fetcher import Fetcher, HTTPResult
    class ObservedResponseFetcher(Fetcher):
        async def fetch(self, url):
            return HTTPResult(200, {"content-type": "text/html; charset=utf-8"}, unconfirmed_landing_html().encode("utf-8"), url)
    result = await ObservedResponseFetcher().enrich({"url": UNCONFIRMED_VIDEO_URL, "title": "Python 变量视频教程", "source": "offline_test"})
    assert result["fetch_status"] == "unavailable_unconfirmed"
    assert result["title"] == "Python 变量视频教程"
    assert result["chapters"] == [] and "尚未确认" in result["access_notice"]


@pytest.mark.parametrize("status,heading", [("login_required", "请先登录"), ("captcha", "安全验证"), ("access_denied", "Access denied")])
def test_explicit_access_classification_precedes_ambiguous_landing(status, heading):
    from backend.app.extractor import MetadataExtractor
    from backend.app.source_adapters.bilibili import unavailable_video_projection
    html = unconfirmed_landing_html().replace("<body></body>", "<body><h1>" + heading + "</h1></body>")
    result = MetadataExtractor().extract(html, UNCONFIRMED_VIDEO_URL, "2026-10-18T00:00:00Z")
    assert result["fetch_status"] == status
    original = dict(result, url=UNCONFIRMED_VIDEO_URL, title=UNCONFIRMED_LANDING_TITLE)
    assert unavailable_video_projection(original, []) is original


@pytest.mark.parametrize("access_fields", [{"requires_login": True}, {"requires_payment": True}, {"region_restriction": "Observed regional notice"}])
def test_ordinary_access_limitations_are_not_unavailability_or_invalidity(access_fields):
    from backend.app.source_adapters.bilibili import unavailable_video_projection
    resource, evidence = record("Python 变量视频教程", url=UNCONFIRMED_VIDEO_URL, **access_fields)
    assert unavailable_video_projection(resource, evidence) is resource
    assert evaluate("Python 变量", "Python 变量视频教程", **access_fields)


def test_historical_unavailable_projection_is_review_and_keeps_raw_rows(tmp_path):
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.service import JobService
    from backend.app.source_adapters.bilibili import unavailable_video_projection
    store = Store(str(tmp_path / "old-unavailable.sqlite3"))
    service = JobService(Settings(), store)
    try:
        jid = service.create(SearchRequest(knowledge_points=["Python 变量"]))["job_id"]
        pid = store.get_job(jid)["knowledge_points"][0]["knowledge_point_id"]
        resource, evidence = record("Python 变量视频教程", url=UNCONFIRMED_VIDEO_URL)
        resource.update(title=UNCONFIRMED_LANDING_TITLE, platform="bilibili", metadata_evidence_level="page", fetch_status="fetched", description="{$0}, 视频播放量 undefined")
        resource["field_provenance"]["title"] = {"source": "meta.og:title", "evidence_id": "bad-title", "url": UNCONFIRMED_VIDEO_URL}
        resource["field_provenance"]["resource_type"] = {"source": "meta.og:type", "evidence_id": "bad-type", "url": UNCONFIRMED_VIDEO_URL}
        evidence[0]["knowledge_point_id"] = pid
        evidence.append({"evidence_id": "bad-title", "kind": "page", "source": "meta.og:title", "field": "title", "text": UNCONFIRMED_LANDING_TITLE, "url": UNCONFIRMED_VIDEO_URL})
        evidence.append({"evidence_id": "bad-type", "kind": "page", "source": "meta.og:type", "field": "resource_type", "text": "video", "url": UNCONFIRMED_VIDEO_URL})
        store.save_resource(jid, resource)
        for row in evidence:
            store.add_evidence(jid, resource["resource_id"], pid if row["kind"] == "search" else None, row)
        before_rows, before_evidence = deepcopy(store.resources(jid)), deepcopy(store.evidence(jid, resource["resource_id"]))
        group = service.results(jid)["groups"][0]
        assert not group["items"] and not group["partial_items"] and len(group["review_items"]) == 1
        reviewed = group["review_items"][0]
        assert reviewed["resource"]["title"] == "Python 变量视频教程"
        assert reviewed["resource"]["fetch_status"] == "unavailable_unconfirmed"
        assert reviewed["resource"]["video_evidence_status"] == "search_discovered"
        assert reviewed["resource"]["field_provenance"]["resource_type"]["source"] == "url_pattern"
        assert "尚未确认" in reviewed["resource"]["access_notice"]
        assert reviewed["match"]["supporting_evidence_ids"] == []
        assert store.resources(jid) == before_rows and store.evidence(jid, resource["resource_id"]) == before_evidence
        missing_title = unavailable_video_projection(resource, [])
        assert missing_title["title"] == "来源视频页面暂不可见（原因未确认）"
        assert unavailable_video_projection(dict(resource, fetch_status="not_found"), evidence)["fetch_status"] == "not_found"
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_page_cache", [False, True])
async def test_unavailable_new_fetch_and_legacy_cache_pipeline_never_promote_search_proof(tmp_path, old_page_cache):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.fetcher import Fetcher, HTTPResult
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    calls = []
    class ObservedResponseFetcher(Fetcher):
        async def fetch(self, url):
            calls.append(url)
            return HTTPResult(200, {"content-type": "text/html; charset=utf-8"}, unconfirmed_landing_html().encode("utf-8"), url)

    def respond(request):
        return httpx.Response(200, json={"results": [{"title": "Python 变量视频教程", "url": UNCONFIRMED_VIDEO_URL,
                                                    "content": "Python 变量基础教学", "template": "videos.html"}]})

    settings = Settings(database_path=str(tmp_path / "unavailable-pipeline.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), max_search_requests=1, max_detail_pages=1,
                        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=ObservedResponseFetcher())
        try:
            key, _ = service._page_cache({"canonical_url": UNCONFIRMED_VIDEO_URL})
            legacy = {"title": UNCONFIRMED_LANDING_TITLE, "description": "{$0}, 视频播放量 undefined",
                      "resolved_url": UNCONFIRMED_VIDEO_URL, "fetch_status": "fetched", "metadata_evidence_level": "page",
                      "resource_type": "video", "video_evidence_status": "none", "chapters": [],
                      "field_provenance": {"title": {"evidence_id": "old-title", "source": "meta.og:title", "url": UNCONFIRMED_VIDEO_URL},
                                           "resource_type": {"evidence_id": "old-type", "source": "meta.og:type", "url": UNCONFIRMED_VIDEO_URL}},
                      "evidence": [{"evidence_id": "old-title", "kind": "page", "field": "title", "source": "meta.og:title",
                                    "text": UNCONFIRMED_LANDING_TITLE, "url": UNCONFIRMED_VIDEO_URL},
                                   {"evidence_id": "old-type", "kind": "page", "field": "resource_type", "source": "meta.og:type",
                                    "text": "video", "url": UNCONFIRMED_VIDEO_URL}]}
            if old_page_cache:
                store.cache_set(key, "page", legacy, 600)
            jid = service.create(SearchRequest(knowledge_points=["Python 变量"]))["job_id"]
            await service.run(jid)
            group = service.results(jid)["groups"][0]
            assert not group["items"] and not group["partial_items"] and len(group["review_items"]) == 1
            item = group["review_items"][0]
            assert item["resource"]["title"] == "Python 变量视频教程"
            assert item["resource"]["fetch_status"] == "unavailable_unconfirmed"
            assert item["match"]["supporting_evidence_ids"] == []
            assert all(row["status"] == "unknown" for row in item["match"].get("subtopic_coverage", []))
            assert "尚未确认" in item["resource"]["access_notice"]
            assert len(calls) == (0 if old_page_cache else 1)
            assert store.get_job(jid)["progress"]["details_cached"] == int(old_page_cache)
            if old_page_cache:
                assert store.cache_get(key)["data"] == legacy
                assert any(row.get("text") == UNCONFIRMED_LANDING_TITLE for row in item["evidence"])
        finally:
            store.close()


def test_short_collision_video_cannot_teach_other_keyboard_lesson_from_full_course_outline():
    title = "Pygame 碰撞检测视频课程"
    description = title + " 课程大纲 课时1视频键盘事件处理17:30 课时2视频图像处理25:11 课时3视频碰撞检测21:32"
    resource, evidence = record(title)
    resource.update(description=description, fetch_status="fetched", metadata_evidence_level="catalog",
                    chapters=[{"title": title, "duration_seconds": 601, "evidence_id": "chapter"}])
    resource["field_provenance"]["description"] = {"source": "html.description", "evidence_id": "description", "url": resource["url"]}
    evidence.extend([{"evidence_id": "description", "kind": "page", "field": "description", "source": "html.description",
                      "url": resource["url"], "text": description},
                     {"evidence_id": "chapter", "kind": "catalog", "url": resource["url"], "text": title}])
    assert "课程大纲" not in own_video_description(resource, description)
    assert rank_resource({"knowledge_point_id": "p", "text": "Pygame 键盘事件处理"}, resource, evidence,
                         SearchRequest(knowledge_points=["Pygame 键盘事件处理"])) is None
    collision = rank_resource({"knowledge_point_id": "p", "text": "Pygame 碰撞检测"}, resource, evidence,
                              SearchRequest(knowledge_points=["Pygame 碰撞检测"]))
    assert collision and "longer_course_outline_excluded_from_short_video" in collision["topic_match_rules"]
    assert own_video_description(dict(resource, duration_seconds=7200), description) == description
    assert own_video_description(dict(resource, resource_type="course"), description) == description
    assert resource["description"] == description
