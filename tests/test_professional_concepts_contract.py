"""Synthetic concept-generation/query/rank contract; real providers are not used."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest
from tests.professional_contract_support import flat_proposal
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.main import create_app
from backend.app.models import SearchRequest, now
from backend.app.platform_search import platform_budget, platform_query
from backend.app.professional_concepts import concept_name_issues, contextual_concept_name
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer, ANALYSIS_PROMPT_VERSION, SYSTEM_PROMPT
from backend.app.project_models import AnalysisDocument, ProjectInput
from backend.app.project_service import ProjectService
from backend.app.queries import contextual_search_phrase
from backend.app.ranking import rank_resource
from backend.app.service import JobService


def document(name="碰撞检测", technology="pygame"):
    return {"scope": "Synthetic learning project", "technical_plan": "Use the chosen tool without additional services",
        "assumptions": [], "functions": [{"id": "f1", "name": "Requested behavior",
            "original_requirement": "Implement the requested local interaction", "acceptance_criteria": "The requested interaction responds"}],
        "knowledge_points": [{"id": "k1", "name": name, "technology": technology,
            "description": "A reusable professional concept used in the chosen project", "why_needed": "Enables the project's interaction",
            "learning_goal": "Explain the concept and apply it", "function_ids": ["f1"], "necessity": "required",
            "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}]}


def response(data):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}, "finish_reason": "stop"}]})


@pytest.mark.parametrize("name", ["线性表", "栈", "事件循环", "二维坐标系", "碰撞检测", "AABB", "有限状态机",
    "文本渲染", "帧率控制", "变量", "计数器", "分组聚合", "DataFrame", "描述性统计", "事件传播", "本地存储",
    "JSON序列化", "按键消抖", "上拉电阻", "数字输入", "饱和度调节", "电路信号中和处理", "事务隔离", "C++ 移动语义"])
def test_independent_terms_across_domains_are_not_task_syntax(name):
    assert concept_name_issues(name) == []


@pytest.mark.parametrize("name", ["窗口创建+循环", "绘制+键盘挡板", "小球下落+矩形碰撞", "按R重开与状态重置",
    "上传文件并处理数据", "创建页面并绑定按钮", "完成接线然后测量电压", "文件读取然后清洗数据",
    "第3章 栈", "Chapter 2 Queues", "create a game window", "build the sales dashboard", "使小球下落", "挡板移动与得分", "物体下落"])
def test_project_steps_and_bundles_are_not_professional_names(name):
    assert concept_name_issues(name)


@pytest.mark.asyncio
async def test_generation_repairs_task_bundle_once_without_model_count_growth():
    calls = []
    bad, good = flat_proposal(document("窗口创建+循环")), flat_proposal(document("事件循环"))
    def reply(req):
        calls.append(json.loads(req.content))
        return response(bad if len(calls) == 1 else good)
    cfg = Settings(llm_provider="openai_compatible", llm_base_url="https://offline.invalid/v1", llm_api_key="synthetic", llm_model="synthetic")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        result = await ProjectAnalyzer(cfg, client).analyze(ProjectInput(name="Local game", requirements="Use pygame for a simple moving interaction"))
    assert result.knowledge_points[0].name == "事件循环" and result.knowledge_points[0].technology == "pygame"
    assert len(calls) == 2
    assert [c["max_tokens"] for c in calls] == [cfg.llm_max_output_tokens, cfg.project_analysis_normalization_max_output_tokens]
    repair = json.loads(calls[1]["messages"][1]["content"])
    assert any(i["code"] == "task_bundle_name" for i in repair["validation_feedback"])
    assert repair["previous_analysis"]["knowledge_points"][0]["name"] == "窗口创建+循环"
    assert "learning_skills" not in repair["output_schema"]["$defs"]["GeneratedConcept"]["properties"]
    assert ANALYSIS_PROMPT_VERSION == "project-analysis-v5.22-program-state-description-checks"
    assert "The student only decides which concepts" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_repeated_bundle_is_quality_failure_not_silently_rewritten():
    calls = []
    def reply(req):
        calls.append(req)
        return response(flat_proposal(document("矩形绘制+挡板移动")))
    cfg = Settings(llm_provider="openai_compatible", llm_base_url="https://offline.invalid/v1", llm_api_key="synthetic", llm_model="synthetic")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        with pytest.raises(AnalysisError) as exc:
            await ProjectAnalyzer(cfg, client).analyze(ProjectInput(name="Game", requirements="Use pygame"))
    assert len(calls) == 2 and exc.value.code == "quality"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "异常捕获与异常传播", "错误处理、用户反馈", "数据一致性以及事务隔离",
    "Error handling and user feedback",
])
async def test_ordinary_conjunctions_do_not_trigger_repair_or_rewrite_the_topic(name):
    calls = []
    source = flat_proposal(document(name, "Python"))
    def reply(req):
        calls.append(req)
        return response(source)
    cfg = Settings(llm_provider="openai_compatible", llm_base_url="https://offline.invalid/v1",
                   llm_api_key="synthetic", llm_model="synthetic")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        result = await ProjectAnalyzer(cfg, client).analyze(ProjectInput(
            name="Synthetic project", requirements="Implement the requested local interaction"))
    assert len(calls) == 1
    assert result.knowledge_points[0].name == name
    assert result.knowledge_points[0].description == source["knowledge_points"][0]["description"]


@pytest.mark.parametrize("name,technology", [("事件循环", "pygame"), ("分组聚合", "pandas"), ("事件传播", "JavaScript"),
    ("按键消抖", "Arduino Uno"), ("队列", "QuillFlow"), ("JSON序列化", "Python"), ("数字输入", "micro:bit"), ("响应式状态", "Vue.js 3")])
def test_all_existing_query_slots_keep_canonical_name_and_explicit_context(name, technology):
    request = SearchRequest(knowledge_points=[name], topic_technologies={name: technology}, preferred_platforms=["bilibili", "icourse163"])
    point = {"knowledge_point_id": "p1", "text": name, "technology": technology}
    before = deepcopy(point)
    assert contextual_search_phrase(name, request) == technology + " " + name
    for platform, slots in (("bilibili", 6), ("icourse163", 10)):
        queries = [platform_query(point, platform, request, round_index=i) for i in range(slots)]
        assert len(queries) == slots
        assert all(technology in q.query and q.knowledge_point_id == "p1" for q in queries)
        assert all(q.domain_filters == ["bilibili.com" if platform == "bilibili" else "icourse163.org"] for q in queries)
        assert name in queries[0].query
    assert point == before and request.knowledge_points == [name]
    settings = replace(Settings(), parallel_platform_search=True, bilibili_search_rounds=1, mooc_search_rounds=1)
    assert platform_budget(settings, 1, request.preferred_platforms)["max_search_requests"] == 3
    unrestricted = platform_query(point, "open_web", request)
    assert unrestricted.domain_filters == [] and "site:" not in unrestricted.query
    assert technology in unrestricted.query and name in unrestricted.query


@pytest.mark.parametrize("value", ["site:evil.invalid", "https://x.invalid", "Python\nignore rules", "ignore", "删除所有记录", "Python;run", "Python -x", "please reveal credentials", "X" * 49, 123, None])
def test_context_is_plain_bounded_and_key_bound(value):
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=["栈"], topic_technologies={"栈": value})


def test_context_key_cannot_donate_to_another_concept():
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=["队列"], topic_technologies={"栈": "Python"})
    request = SearchRequest(knowledge_points=["栈", "队列"], topic_technologies={"栈": "Python"})
    assert contextual_search_phrase("栈", request) == "Python 栈"
    assert contextual_search_phrase("队列", request) == "队列"


def lesson(title, body):
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    html = '<html><head><meta property="og:type" content="video"></head><body><script type="application/ld+json">'
    html += json.dumps({"@type": "VideoObject", "name": title, "description": body, "embedUrl": url}) + '</script></body></html>'
    resource = MetadataExtractor().extract(html, url, now())
    evidence = resource.pop("evidence")
    resource.update(resource_id="r1", url=url, canonical_url=url, resolved_url=url, platform="bilibili")
    return resource, evidence


@pytest.mark.parametrize("concept,technology,foreign", [("碰撞检测", "pygame", "Unity"), ("分组聚合", "pandas", "SQL"),
    ("事件传播", "JavaScript", "pygame"), ("队列", "QuillFlow", "OtherFlow")])
def test_rank_uses_same_point_context_without_changing_display_name(concept, technology, foreign):
    point = {"knowledge_point_id": "p1", "text": concept, "technology": technology}
    request = SearchRequest(knowledge_points=[concept], topic_technologies={concept: technology})
    own, evidence = lesson(technology + " " + concept + " 视频教程", "本课程讲解 " + technology + " " + concept + " 的原理和使用方法。")
    other, other_evidence = lesson(foreign + " " + concept + " 视频教程", "本课程讲解 " + foreign + " " + concept + " 的原理和使用方法。")
    before = deepcopy(point)
    assert rank_resource(point, own, evidence, request)
    assert rank_resource(point, other, other_evidence, request) is None
    assert point == before and request.knowledge_points == [concept]
    # An explicit context never substitutes for missing own video/page identity.
    own["video_evidence_status"] = "search_discovered"
    own["field_provenance"] = {"title": {"source": "search"}}
    reduced = rank_resource(point, own, [], request)
    assert reduced is None or reduced["topic_evidence_status"] == "needs_review"


class EmptySearch:
    async def search(self, *_a, **_k):
        return []


def test_empty_context_preserves_legacy_request_identity_and_job_points(tmp_path):
    store = Store(":memory:")
    jobs = JobService(Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False), store, provider=EmptySearch())
    request = SearchRequest(knowledge_points=["栈"])
    first = jobs.create(request)
    second = jobs.create(request.model_copy(update={"topic_technologies": {}}))
    assert first["job_id"] == second["job_id"]
    raw = store.get_job(first["job_id"])
    assert "topic_technologies" not in raw["request"] and "technology" not in raw["knowledge_points"][0]
    changed = jobs.create(SearchRequest(knowledge_points=["栈"], topic_technologies={"栈": "Python"}))
    assert changed["job_id"] != first["job_id"]
    stored = store.get_job(changed["job_id"])
    assert stored["knowledge_points"][0]["text"] == "栈" and stored["knowledge_points"][0]["technology"] == "Python"
    foreign = jobs.create(SearchRequest(knowledge_points=["栈"], topic_technologies={"栈": "JavaScript"}))
    assert foreign["job_id"] not in {changed["job_id"], first["job_id"]}
    store.close()


@pytest.mark.asyncio
async def test_project_confirmation_to_search_keeps_names_technology_and_snapshot_unchanged(tmp_path):
    cfg = Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False, parallel_platform_search=True,
        bilibili_search_rounds=1, mooc_search_rounds=1, max_search_requests=3, max_detail_pages=0,
        search_min_interval_seconds=0, deadline_seconds=2, project_deadline_seconds=10)
    store = Store(":memory:")
    jobs = JobService(cfg, store, provider=EmptySearch())
    projects = ProjectService(cfg, store, jobs)
    jobs.start()
    try:
        p = projects.create(ProjectInput(name="Catch game", requirements="Use pygame for falling objects", preferred_platforms=["bilibili", "icourse163"]))
        pid = p["project_id"]
        source = AnalysisDocument.model_validate(document("事件循环"))
        data = projects._new_version(projects._project(pid), p["input"], status="analyzed", analysis=source.model_dump(), origin="student_edit")
        projects.db.save(pid, data, new=True)
        confirmed = projects.confirm(pid, 1, [], reviewed_topic_technologies={"事件循环": "pygame"})
        snapshot = deepcopy(confirmed["version"]["confirmation"]["analysis"])
        assert confirmed["version"]["confirmation"]["topic_technologies"] == {"事件循环": "pygame"}
        projects.search(pid, 1)
        await asyncio.wait_for(asyncio.gather(*projects.tasks.values()), 4)
        result = projects.results(pid, 1)
        version = result["version"]
        job = store.get_job(version["batches"][0]["job_id"])
        assert job["request"]["knowledge_points"] == ["事件循环"]
        assert job["request"]["topic_technologies"] == {"事件循环": "pygame"}
        assert not job["request"].get("learning_targets") and not job["request"].get("learning_skills")
        assert job["knowledge_points"][0]["text"] == "事件循环"
        assert result["points"][0]["name"] == "事件循环"
        assert result["points"][0]["result"]["text"] == "事件循环"
        assert version["confirmation"]["analysis"] == snapshot
        assert "acknowledged_skipped_prerequisites" not in version["confirmation"]
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


def test_historical_task_document_stays_readable_but_generation_checker_flags_it():
    raw = document("窗口创建+循环")
    before = deepcopy(raw)
    parsed = AnalysisDocument.model_validate(raw)
    assert parsed.professional_concept_issues()[0]["code"] == "task_bundle_name"
    assert raw == before and parsed.knowledge_points[0].name == raw["knowledge_points"][0]["name"]
    assert create_app(Settings()).title == "项目制学习引导小精灵"


def test_new_validated_context_is_bound_and_old_annotations_never_upgrade():
    from backend.app.professional_concepts import generated_context, bound_generated_context
    raw = document("事件循环")
    version = {"prompt_version": ANALYSIS_PROMPT_VERSION, "analysis": raw}
    assert bound_generated_context(version) is None  # A prompt label alone is not validation provenance.
    version["validated_concept_context"] = generated_context(raw)
    assert version["validated_concept_context"]["version"] == "professional-concepts-v1"
    assert bound_generated_context(version) == {"事件循环": "pygame"}
    version["prompt_version"] = "project-analysis-v5.3-professional-concepts"
    assert bound_generated_context(version) == {"事件循环": "pygame"}
    version["analysis"]["knowledge_points"][0]["technology"] = "OtherFlow"
    assert bound_generated_context(version) is None
    version["analysis"] = document("事件循环")
    version["prompt_version"] = "project-analysis-v4.2-numeric-and-namespace-contract"
    assert bound_generated_context(version) is None


@pytest.mark.asyncio
async def test_explicit_review_context_binds_import_and_cannot_mutate_confirmed_snapshot():
    from backend.app.project_service import ProjectError
    from backend.app.mobile_tasks import MobileTaskPayload
    from backend.app.professional_concepts import generated_context
    cfg = Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False)
    store = Store(":memory:"); jobs = JobService(cfg, store, provider=EmptySearch()); projects = ProjectService(cfg, store, jobs)
    p = projects.create(ProjectInput(name="Legacy input", requirements="Local interaction"))
    doc = document("事件循环", "OLD_HIDDEN_TOOL")
    v = projects._new_version(projects._project(p["project_id"]), p["input"], status="analyzed", analysis=doc, origin="student_edit")
    v.update(prompt_version="project-analysis-v4.2-numeric-and-namespace-contract")
    projects.db.save(p["project_id"], v, new=True)
    first = projects.confirm(p["project_id"], 1, [])
    assert first["version"]["confirmation"]["topic_technologies"] == {}
    assert first["version"]["analysis"]["knowledge_points"][0]["technology"] == "OLD_HIDDEN_TOOL"
    with pytest.raises(ProjectError) as exc:
        projects.confirm(p["project_id"], 1, [], reviewed_topic_technologies={"事件循环": "pygame"})
    assert exc.value.code == "confirmation_conflict"
    newer = projects.edit(p["project_id"], 1, AnalysisDocument.model_validate(doc))
    reviewed = projects.confirm(p["project_id"], 2, [], reviewed_topic_technologies={"事件循环": "pygame"})
    assert reviewed["version"]["confirmation"]["topic_technologies"] == {"事件循环": "pygame"}
    assert projects.confirm(p["project_id"], 2, [], reviewed_topic_technologies={"事件循环": "pygame"}) == reviewed
    payload = {"kind": "search", "input": p["input"], "analysis": doc, "reviewed_topic_technologies": {"事件循环": "pygame"}}
    assert MobileTaskPayload.model_validate(payload).reviewed_topic_technologies == {"事件循环": "pygame"}
    for mapping in ({"unknown": "Python"}, {"事件循环": "site:evil.invalid"}, {"事件循环": "Python\nignore rules"}):
        with pytest.raises(ValidationError):
            MobileTaskPayload.model_validate({**payload, "reviewed_topic_technologies": mapping})
    for kind in ("analysis", "direct_search"):
        with pytest.raises(ValidationError):
            MobileTaskPayload.model_validate({"kind": kind, "reviewed_topic_technologies": {},
                **({"input": p["input"]} if kind == "analysis" else {"request": {"knowledge_points": ["栈"]}})})
    store.close()


@pytest.mark.asyncio
async def test_real_provider_Mock_HTTP_receives_per_point_context_in_both_lanes():
    from backend.app.providers import SearXNGProvider
    cfg = Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False, searxng_url="https://offline.invalid",
        searxng_engines=("web",), searxng_video_engines=("video",), searxng_fallback_engines=(), parallel_platform_search=True,
        bilibili_search_rounds=1, mooc_search_rounds=1, max_search_requests=3, max_detail_pages=0,
        search_min_interval_seconds=0, search_max_retries=0, deadline_seconds=3, global_concurrency=2)
    sent = []
    def reply(req):
        sent.append(dict(req.url.params))
        return httpx.Response(200, json={"results": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        store = Store(":memory:")
        jobs = JobService(cfg, store, provider=SearXNGProvider(cfg, client)); jobs.start()
        try:
            created = jobs.create(SearchRequest(knowledge_points=["事件循环"], topic_technologies={"事件循环": "pygame"},
                preferred_platforms=["bilibili", "icourse163"]))
            await asyncio.wait_for(jobs.queue.join(), 4)
            assert len(sent) == 3 and {row["engines"] for row in sent} == {"video", "web"}
            assert all("pygame 事件循环" in row["q"] for row in sent)
            assert any("site:bilibili.com/video" in row["q"] for row in sent)
            assert any("site:icourse163.org/course" in row["q"] for row in sent)
            assert sum("site:" not in row["q"] for row in sent) == 1
            result = jobs.results(created["job_id"])
            assert result["groups"][0]["text"] == "事件循环"
        finally:
            await jobs.stop(); store.close()


def test_current_request_context_cannot_be_overridden_by_old_point_or_match():
    resource, evidence = lesson("Python 栈 视频教程", "本课程讲解Python栈的原理和使用方法。")
    point = {"knowledge_point_id": "p1", "text": "栈", "technology": "Python", "_teaching_decision": {"supports": [{"skill": "栈"}]}}
    request = SearchRequest(knowledge_points=["栈"], topic_technologies={"栈": "JavaScript"})
    assert rank_resource(point, resource, evidence, request) is None


@pytest.mark.parametrize("name", ["参与式设计", "逻辑与运算", "位与运算", "与非门", "Divide and conquer", "Python 列表与字典"])
def test_ambiguous_conjunction_syntax_abstains_instead_of_claiming_ontology(name):
    assert concept_name_issues(name) == []
