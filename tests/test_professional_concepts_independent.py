"""Finite cross-domain oracles, not a vocabulary-based ontology certificate."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys

import httpx
import pytest
from tests.professional_contract_support import flat_proposal

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("PROFESSIONAL_CONCEPT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))
ORACLE = json.loads((Path(__file__).parent / "fixtures/professional_concepts_independent.json").read_text(encoding="utf8"))
CASES = ORACLE["cases"]
ACCEPTED = [point["name"] for case in CASES for point in case["concepts"]] + ORACLE["additional_valid_canonical_names"]


def document(points):
    return {"scope": "A synthetic local learning project", "technical_plan": "Use only the declared local tool",
        "assumptions": ["Existing background remains an explicit editable assumption"],
        "functions": [{"id": "F1", "name": "Requested local behavior", "original_requirement": "Preserve the requested local interaction",
                       "acceptance_criteria": "The requested interaction works"}],
        "knowledge_points": [{"id": "K" + str(i+1), "name": p["name"], "technology": p.get("technology", ""),
            "description": "A reusable professional concept", "why_needed": p.get("serves", "Enables the requested behavior"),
            "learning_goal": "Understand the concept", "function_ids": ["F1"], "necessity": "required",
            "prerequisite_ids": [], "learning_order": i+1, "selection": "learn"} for i, p in enumerate(points)]}


@pytest.mark.parametrize("name", list(dict.fromkeys(ACCEPTED)))
def test_accept_professional_nouns_without_required_tool_prefix(name):
    from backend.app.professional_concepts import concept_name_issues
    assert concept_name_issues(name) == []


@pytest.mark.parametrize("name", ORACLE["invalid_task_names"])
def test_observable_task_bundles_and_chapter_labels_need_repair(name):
    from backend.app.professional_concepts import concept_name_issues
    assert concept_name_issues(name)


@pytest.mark.parametrize("name", [
    "读取CSV、清理数据、绘制看板", "上传文件以及创建图表",
    "测量电压与保存读数", "导入文档以及导出报告",
])
def test_joined_explicit_verb_object_clauses_are_task_recipes(name):
    from backend.app.professional_concepts import concept_name_issues
    assert "task_bundle_name" in {code for code, _ in concept_name_issues(name)}


@pytest.mark.parametrize("name", [
    "文件读取与文件写入", "读取与写入", "数据清洗、图表绘制",
    "文件上传以及图表创建", "上传协议与下载协议", "读取模式与写入模式",
    "数据序列化与反序列化", "异常捕获与异常传播", "超时与异常处理",
    "Error handling and user feedback", "Event capturing and event bubbling",
    "应力张量与应变张量", "读取CSV与缺失值", "JSON 编码与URL解码",
])
def test_conjunctions_without_multiple_clear_action_clauses_still_abstain(name):
    from backend.app.professional_concepts import concept_name_issues
    assert concept_name_issues(name) == []


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_cross_domain_oracles_preserve_requirements_and_detached_context(case):
    from backend.app.project_models import AnalysisDocument, ProjectInput
    from backend.app.professional_concepts import contextual_concept_name, topic_technologies
    from backend.app.models import SearchRequest
    from backend.app.queries import contextual_search_phrase
    from backend.app.platform_search import platform_query
    ProjectInput.model_validate(case["input"])
    source = AnalysisDocument.model_validate(document(case["concepts"]))
    assert source.professional_concept_issues() == []
    assert 1 <= len(source.knowledge_points) <= 6
    # The direct-search API batches at most five points. No new slot/budget is
    # needed to represent a larger project; each existing batch retains its map.
    for offset in range(0, len(source.knowledge_points), 5):
        points = [point.model_dump() for point in source.knowledge_points[offset:offset+5]]
        names = {point["id"]: point["name"] for point in points}
        contexts = topic_technologies(points, names)
        request = SearchRequest(knowledge_points=list(names.values()), topic_technologies=contexts,
                                preferred_platforms=["bilibili", "icourse163"])
        original = deepcopy(request.model_dump())
        for point in points:
            query_point = {"knowledge_point_id": point["id"], "text": point["name"], "technology": point["technology"]}
            target = contextual_concept_name(point["name"], point["technology"])
            assert contextual_search_phrase(point["name"], request) == target
            for platform in request.preferred_platforms:
                for slot in range(4):
                    query = platform_query(query_point, platform, request, round_index=slot)
                    assert point["technology"] in query.query
                    assert query.knowledge_point_id == point["id"]
            assert point["name"] == names[point["id"]]
        assert request.model_dump() == original
    assert not any(point.name in case["not_required_by_default"] for point in source.knowledge_points)


@pytest.mark.parametrize("name", ORACLE["invalid_quality_names"])
def test_generation_rejects_broad_subjects_and_single_statement_fragments(name):
    from backend.app.project_analysis import ProjectAnalyzer, AnalysisError
    from backend.app.project_models import ProjectInput
    from backend.app.config import Settings
    async def execute():
        count = 0
        async def respond(request):
            nonlocal count
            count += 1
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(flat_proposal(document([{"name": name}])), ensure_ascii=False)}}]})
        settings = Settings(llm_provider="openai_compatible", llm_base_url="https://synthetic.invalid/v1",
                            llm_api_key="synthetic-not-a-secret", llm_model="synthetic")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
            with pytest.raises(AnalysisError) as error:
                await ProjectAnalyzer(settings, client).analyze(ProjectInput(name="Local project", requirements="Read local data"))
        assert error.value.code == "quality" and count == 2
    asyncio.run(execute())


def test_schema_does_not_restore_skills_tasks_or_student_order_selection():
    from backend.app.project_analysis import generation_schema, SYSTEM_PROMPT, ANALYSIS_MAX_MODEL_CALLS
    schema = generation_schema()
    props = schema["$defs"]["GeneratedConcept"]["properties"]
    assert not set(props) & {"project_task", "concepts", "learning_skills", "practice_check"}
    assert "learner_profile" not in schema["properties"]
    assert ANALYSIS_MAX_MODEL_CALLS == 2
    assert "Do not output prerequisite_ids, learning_order" in SYSTEM_PROMPT


def test_same_name_different_stack_cannot_share_active_job_or_positive_cache():
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.models import SearchRequest
    from backend.app.service import JobService
    class NoSource:
        async def search(self, *_args, **_kwargs):
            raise AssertionError("no provider calls in identity test")
    store = Store(":memory:")
    try:
        jobs = JobService(Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False), store, provider=NoSource())
        plain = SearchRequest(knowledge_points=["事件"])
        first = jobs.create(plain)
        empty = jobs.create(plain.model_copy(update={"topic_technologies": {}}))
        assert first["job_id"] == empty["job_id"]
        assert "topic_technologies" not in store.get_job(first["job_id"])["request"]
        a = jobs.create(SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "pygame"}))
        b = jobs.create(SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "JavaScript"}))
        assert len({first["job_id"], a["job_id"], b["job_id"]}) == 3
        assert store.get_job(a["job_id"])["knowledge_points"][0]["text"] == "事件"
        assert store.get_job(a["job_id"])["request"]["topic_technologies"] == {"事件": "pygame"}
        assert store.cache_key("positive", {"point": "事件", "request": store.get_job(a["job_id"])["request"]}) != store.cache_key(
            "positive", {"point": "事件", "request": store.get_job(b["job_id"])["request"]})
    finally:
        store.close()
