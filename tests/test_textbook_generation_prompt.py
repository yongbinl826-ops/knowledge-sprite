"""Offline prompt-delivery and single-generation tests, not model-quality claims."""
from copy import deepcopy

import pytest

from backend.app import project_analysis as module
from backend.app.project_models import MAX_PROJECT_KNOWLEDGE_POINTS, ProjectInput
from tests.test_analysis_compact import fake_clock
from tests.test_analysis_naming_v4 import configured


CASES = [
    pytest.param(
        ProjectInput(name="仓库盘点工具", requirements="用 Python 读取盘点条目，按物品统计数量并显示结果。"),
        [
            {"name": "类与对象", "description": "类描述一类对象的数据与行为，实例保留自己的状态。项目用对象组织盘点条目。", "technology": "Python"},
            {"name": "通过类封装盘点条目的信息与操作", "description": "这是一段故意保留的任务式模型原文。它用于验证生成结果不会再进入命名判断或改写。", "technology": "Python"},
        ], id="programming"),
    pytest.param(
        ProjectInput(name="居民支出调查", requirements="抽取社区住户调查月支出，汇总并解释样本平均值。"),
        [
            {"name": "算术平均数", "description": "算术平均数为观测值之和除以观测数量。项目用它汇总受访住户的月支出。", "technology": ""},
            {"name": "汇总每月支出并计算平均值", "description": "保留模型原来的项目用途标题。运行流程不以命名偏好再次判断或修正它。", "technology": ""},
        ], id="statistics"),
    pytest.param(
        ProjectInput(name="社区活动海报", requirements="用手绘完成一张具有空间深度和清晰视觉层次的活动海报。"),
        [
            {"name": "透视", "description": "透视用画面中的大小和汇聚关系表达空间深度。项目用它组织海报场景的前后关系。", "technology": ""},
            {"name": "海报图层顺序与文字位置", "description": "这是故意模拟的任务式标题。原有名称与说明须原样交付，不能自动替换成教材名称。", "technology": ""},
        ], id="visual_design"),
    pytest.param(
        ProjectInput(name="电池指示灯电路", requirements="选择电阻并搭建由电池供电的低压 LED 指示灯电路。"),
        [
            {"name": "欧姆定律", "description": "在适用条件下，电阻两端电压等于通过的电流与电阻的乘积。项目用它确定限流电阻的阻值。", "technology": ""},
            {"name": "计算指示灯限流电阻并接线", "description": "本条模拟未遵循教材命名风格的原始回答。服务只负责结构边界，不进行内容评判或修正。", "technology": ""},
        ], id="electronics"),
]


@pytest.fixture(autouse=True)
def prohibit_external_generation_and_quality_passes(monkeypatch):
    async def external_call_forbidden(*_args, **_kwargs):
        pytest.fail("This offline test must supply its own saved/synthetic response")

    def quality_pass_forbidden(*_args, **_kwargs):
        pytest.fail("Single generation must not invoke content/name judgment or repair")

    monkeypatch.setattr(module, "complete_json", external_call_forbidden)
    for name in ("_local_quality_issues", "_partition_quality_issues", "_name_repair_context",
                 "learning_quality_issues", "textbook_concept_issues", "professional_contract_issues",
                 "apply_name_repairs", "review_analysis"):
        monkeypatch.setattr(module, name, quality_pass_forbidden, raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("project,points", CASES)
async def test_all_domains_receive_the_same_textbook_guidance_without_output_judgment(monkeypatch, project, points):
    response = {"scope": "实现已提供的项目需求。", "technical_plan": "采用项目所需的方法组织输入并完成结果。",
                "assumptions": [], "knowledge_points": deepcopy(points)}
    calls, audits, rejections = [], [], []

    async def complete(settings, prompt, payload, *_args, **options):
        calls.append((settings, prompt, deepcopy(payload), options))
        return deepcopy(response)

    monkeypatch.setattr(module, "complete_json", complete)
    result = await module.ProjectAnalyzer(configured()).analyze(
        project, on_analysis_attempt=audits.append, on_rejected_attempt=rejections.append)

    assert len(calls) == len(audits) == 1
    settings, prompt, payload, options = calls[0]
    assert prompt == module.SYSTEM_PROMPT
    assert "Names are concepts; descriptions carry project applications" in prompt
    assert "style only, never a required syllabus" in prompt
    assert all(example in prompt for example in ("类与对象", "算术平均数", "欧姆定律", "视觉层级"))
    assert project.name not in prompt  # No domain-specific prompt substitution.
    assert payload["project"] == project.model_dump()
    assert payload["limits"] == {"knowledge_points": 30}
    assert payload["output_schema"] == module.generation_schema()
    assert not {"previous_analysis", "repair_targets", "repair_format", "validation_feedback"} & payload.keys()
    assert settings.llm_max_output_tokens == 16000
    assert settings.llm_reasoning_effort == "low"
    assert 0 < options["timeout_seconds"] <= 60
    assert len(result.knowledge_points) == len(points)
    for expected, actual in zip(points, result.knowledge_points):
        serialized = actual.model_dump()
        assert {key: serialized[key] for key in expected} == expected
    assert result.scope == response["scope"] and result.technical_plan == response["technical_plan"]
    assert audits[0]["analysis"] == response
    assert audits[0]["outcome"] == "accepted" and rejections == []
    assert audits[0]["validation_scope"] == "schema_safety_limits"
    assert not {"advisories", "issues", "repair_response", "repair_format"} & audits[0].keys()


def test_prompt_change_retains_structural_contract_and_single_call_budget():
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v9-textbook-single-generation"
    assert module.ANALYSIS_MAX_MODEL_CALLS == module.ANALYSIS_MAX_ATTEMPTS == 1
    assert module.ANALYSIS_TOTAL_TIMEOUT_SECONDS == module.ANALYSIS_TIMEOUT_SECONDS == 60
    assert MAX_PROJECT_KNOWLEDGE_POINTS == 30
    schema = module.generation_schema()
    assert set(schema["properties"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
    assert schema["properties"]["knowledge_points"]["maxItems"] == 30
    assert set(schema["$defs"]["GeneratedConcept"]["properties"]) == {"name", "description", "technology"}
    assert "Do not add a separate review, naming critique, correction round" in module.SYSTEM_PROMPT
    assert "There is no target count or preferred range" in module.SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_concise_writing_guidance_does_not_truncate_or_reject_a_longer_description(monkeypatch):
    description = "采样设计说明观测单位的选择方式与总体的关系。" * 8
    assert 120 < len(description) < 800
    response = {"scope": "调查住户支出。", "technical_plan": "从总体抽取样本并汇总支出。",
                "assumptions": [], "knowledge_points": [{"name": "抽样", "description": description}]}
    calls = []

    async def complete(*_args, **_kwargs):
        calls.append(True)
        return deepcopy(response)

    monkeypatch.setattr(module, "complete_json", complete)
    result = await module.ProjectAnalyzer(configured()).analyze(
        ProjectInput(name="住户支出调查", requirements="抽样调查住户月支出。"))
    assert len(calls) == 1
    assert result.knowledge_points[0].description == description


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [29.9, 40.0])
async def test_thirty_second_goal_does_not_shorten_sixty_second_deadline_or_add_retry(monkeypatch, elapsed):
    clock = fake_clock(monkeypatch)
    calls, audit = [], []
    response = {"scope": "分析一组调查数据。", "technical_plan": "对已采集样本进行描述性统计。",
                "assumptions": [], "knowledge_points": [
                    {"name": "算术平均数", "description": "观测值之和除以数量。项目用它汇总月支出。"}]}

    async def complete(*_args, **options):
        calls.append(options["timeout_seconds"])
        clock.now += elapsed
        return deepcopy(response)

    monkeypatch.setattr(module, "complete_json", complete)
    result = await module.ProjectAnalyzer(configured()).analyze(
        ProjectInput(name="住户月支出汇总", requirements="计算样本住户的平均月支出。"),
        on_analysis_attempt=audit.append)
    assert len(calls) == len(audit) == 1
    assert calls[0] == 60
    assert result.knowledge_points[0].name == "算术平均数"
    assert audit[0]["outcome"] == "accepted"
    assert audit[0]["model_elapsed_seconds"] == pytest.approx(elapsed)
