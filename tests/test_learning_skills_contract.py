"""Offline contract slices from three unseen projects, not full live analyses.

The fixtures are hand-authored coherent subtasks. They do not migrate concepts,
certify full project coverage, execute student projects or contact a provider.
"""
from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from backend.app.analysis_review import REVIEW_PROMPT_VERSION, SYSTEM_REVIEW_PROMPT
from backend.app.project_analysis import (
    ANALYSIS_MAX_ATTEMPTS, ANALYSIS_MAX_MODEL_CALLS, ANALYSIS_PROMPT_VERSION,
    AnalysisError, ProjectAnalyzer, SYSTEM_PROMPT, generation_schema, learning_quality_issues,
)
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests.test_project_analysis import response, settings


SLICES = {
    "review_cards": {
        "project": {"name": "离线复习卡网页", "requirements": "12张合成复习卡，用原生JavaScript上一张/下一张浏览，首尾按钮禁用。", "student_level": "beginner", "project_context": "会基础HTML、数组和简单函数，首次把状态与DOM连起来。"},
        "technology": "JavaScript", "name": "卡片索引与按钮状态渲染",
        "task": "用数组索引控制12张卡的显示，并在0与11处禁用对应按钮。",
        "concepts": ["索引0到11", "首尾禁用上一张/下一张"],
        "skills": ["JavaScript 数组索引与边界状态", "JavaScript DOM事件与状态渲染"],
        "check": "首张不能上一张，末张不能下一张，切换时内容与索引对应。",
    },
    "pong": {
        "project": {"name": "pygame双人乒乓球状态片段", "requirements": "3分获胜后暂停比赛，但按R可重开；Esc和关窗始终可退出。", "student_level": "intermediate", "project_context": "会Python函数和pygame绘图，未做过回合与胜利状态。"},
        "technology": "pygame", "name": "胜利状态与持续事件循环",
        "task": "获胜后只暂停运动，继续处理R重置和Esc/关窗事件。",
        "concepts": ["3分胜利阈值", "R重置球、球拍与比分"],
        "skills": ["pygame 状态驱动的更新与绘制", "pygame 持续事件处理与数据重置"],
        "check": "任一玩家到3分后能用R重开，胜利画面仍可关窗。",
    },
    "pot_led": {
        "project": {"name": "Arduino电位器LED调光片段", "requirements": "电位器读数映射到LED亮度，每50ms非阻塞采样并用串口观察，不接市电。", "student_level": "beginner", "project_context": "已点亮过LED，第一次使用模拟输入和PWM。"},
        "technology": "Arduino", "name": "模拟输入到PWM的范围映射",
        "task": "用millis时间差定期读取电位器，把读数映射为受限的PWM值并打印。",
        "concepts": ["50ms采样周期", "模拟读数与PWM输出范围", "LED限流与共地"],
        "skills": ["Arduino 模拟输入与PWM范围映射", "Arduino millis时间差周期采样"],
        "check": "旋钮两端和中间亮度变化单调，串口值与输出对应，loop持续运行。",
    },
}


def document_slice(case="review_cards"):
    item = SLICES[case]
    body = {
        "scope": item["project"]["requirements"],
        "technical_plan": "采用项目已选的本地技术，不添加账号、云端或额外功能。",
        "assumptions": ["项目配置可调整；资料可以用其他业务示例教授同一方法。"],
        "learner_profile": {"student_level": item["project"]["student_level"],
                            "assumed_knowledge": [item["project"]["project_context"]],
                            "adjustment_note": "可修改已有经验、阶段和所需学习项后重新分析。"},
        "functions": [{"id": "f1", "name": item["name"], "original_requirement": item["project"]["requirements"],
                       "acceptance_criteria": item["check"]}],
        "knowledge_points": [{"id": "k1", "name": item["name"], "description": "把相关方法用于这个可单独验证的子任务。",
            "function_ids": ["f1"], "why_needed": "对应项目中明确需要实现的交互或处理。",
            "learning_goal": "理解这里的状态、数据与输入输出如何协作。", "technology": item["technology"],
            "project_task": item["task"], "concepts": list(item["concepts"]),
            "learning_skills": list(item["skills"]), "practice_check": item["check"],
            "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}],
    }
    return body


@pytest.mark.parametrize("case", SLICES)
def test_unseen_subtask_skills_are_transferable_without_erasing_project_checks(case):
    body = document_slice(case)
    before = deepcopy(body)
    doc = AnalysisDocument.model_validate(body, context={"fresh_generation": True})
    assert not learning_quality_issues(ProjectInput(**SLICES[case]["project"]), doc)
    point = doc.knowledge_points[0]
    assert point.learning_skills == SLICES[case]["skills"]
    assert point.concepts == SLICES[case]["concepts"]
    assert point.project_task == SLICES[case]["task"] and point.practice_check == SLICES[case]["check"]
    assert body == before
    assert point.learning_skills != point.concepts


def test_missing_legacy_skills_stay_readable_in_all_contexts_without_invented_migration():
    body = document_slice()
    body["knowledge_points"][0].pop("learning_skills")
    before = deepcopy(body)
    for context in (None, {"fresh_generation": True}):
        saved = AnalysisDocument.model_validate(body, context=context)
        assert saved.knowledge_points[0].learning_skills == []
        assert saved.knowledge_points[0].concepts == before["knowledge_points"][0]["concepts"]
    assert body == before


@pytest.mark.parametrize("count", [0, 1, 5, 6])
def test_optional_legacy_skills_keep_max6_without_a_fresh_two_to_four_minimum(count):
    body = document_slice()
    body["knowledge_points"][0]["learning_skills"] = [f"JavaScript 数组视图的具体技能{i}" for i in range(count)]
    for context in (None, {"fresh_generation": True}):
        assert len(AnalysisDocument.model_validate(body, context=context).knowledge_points[0].learning_skills) == count


@pytest.mark.parametrize("count", [2, 3, 4])
def test_fresh_count_accepts_two_to_four(count):
    body = document_slice()
    body["knowledge_points"][0]["learning_skills"] = [f"JavaScript 数组视图的具体技能{i}" for i in range(count)]
    assert len(AnalysisDocument.model_validate(body, context={"fresh_generation": True}).knowledge_points[0].learning_skills) == count


@pytest.mark.parametrize("skills", [
    ["技能" + "长" * 120, "JavaScript DOM渲染"],
    [f"具体技能{i}" for i in range(7)],
    ["  ", "JavaScript DOM渲染"],
    ["JavaScript https://example.org", "JavaScript DOM渲染"],
    ["JavaScript www.example.org", "JavaScript DOM渲染"],
    ["JavaScript 数组\n索引", "JavaScript DOM渲染"],
    ["JavaScript 数组\x00索引", "JavaScript DOM渲染"],
    ["JavaScript 数组\x7f索引", "JavaScript DOM渲染"],
    ["JavaScript 视图", "  JAVASCRIPT   视图  "],
    ["JavaScript 视图", "ＪａｖａＳｃｒｉｐｔ 视图"],
    [22, "JavaScript DOM渲染"],
    "JavaScript DOM渲染",
])
def test_bounded_safe_distinct_strings_without_silent_normalization(skills):
    body = document_slice()
    body["knowledge_points"][0]["learning_skills"] = skills
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(body)


def test_skill_text_preserves_original_unicode_spacing_and_own_technology():
    body = document_slice("pong")
    body["knowledge_points"][0]["learning_skills"] = ["Python 状态数据初始化", "pygame 状态驱动画面与输入"]
    doc = AnalysisDocument.model_validate(body, context={"fresh_generation": True})
    assert doc.knowledge_points[0].learning_skills == body["knowledge_points"][0]["learning_skills"]
    assert not learning_quality_issues(ProjectInput(**SLICES["pong"]["project"]), doc)


@pytest.mark.parametrize("bad,code", [("Python 基础", "broad_learning_skill"), ("Streamlit 控件", "broad_learning_skill"), ("通用控件族", "broad_learning_skill"), ("变量名", "fragmented_learning_skill")])
def test_specific_unit_does_not_hide_generic_or_syntax_only_learning_skills(bad, code):
    body = document_slice("pong")
    body["knowledge_points"][0]["learning_skills"][0] = bad
    doc = AnalysisDocument.model_validate(body)
    assert code in {issue["code"] for issue in learning_quality_issues(ProjectInput(**SLICES["pong"]["project"]), doc)}


@pytest.mark.parametrize("source,skill,code", [
    ("pygame小游戏，获胜后按R重开并可关窗。", "pygame 获胜后停止游戏循环，再按R重开", "unresponsive_game_restart"),
    ("Arduino机械按钮必须去抖，长按不能重复启动。", "Arduino 按钮去抖只需比较当前和前次电平", "raw_edge_is_not_debounce"),
    ("Arduino采样时仍需非阻塞响应串口输入。", "Arduino 使用Serial.readString等待完整命令", "blocking_input_for_responsive_task"),
])
def test_new_skill_layer_cannot_bypass_existing_behavior_guards(source, skill, code):
    body = document_slice("pot_led")
    body["knowledge_points"][0]["learning_skills"][0] = skill
    project = ProjectInput(name="局部语义护栏回归", requirements=source)
    issues = learning_quality_issues(project, AnalysisDocument.model_validate(body))
    assert code in {issue["code"] for issue in issues}


def test_prompt_schema_omits_expanded_fields_while_storage_keeps_safe_optional_history():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert ANALYSIS_PROMPT_VERSION == "project-analysis-v4.1-coherent-professional-terms"
    assert_simple_generation_schema()
    storage = AnalysisDocument.model_json_schema()["$defs"]["ProjectKnowledgePoint"]
    assert "learning_skills" not in storage.get("required", [])
    assert storage["properties"]["learning_skills"]["maxItems"] == 6
    assert storage["properties"]["learning_skills"]["items"]["maxLength"] == 120
    assert "Do not output project_task, concepts, learning_skills, practice_check or learner_profile" in SYSTEM_PROMPT
    assert ANALYSIS_MAX_ATTEMPTS == 2 and ANALYSIS_MAX_MODEL_CALLS == 2


@pytest.mark.asyncio
async def test_missing_legacy_skills_need_no_repair_or_concept_fallback():
    from tests.professional_contract_support import projected_once
    body = document_slice()
    body["knowledge_points"][0].pop("learning_skills")
    result, calls = await projected_once(body, ProjectInput(**SLICES["review_cards"]["project"]), settings())
    assert len(calls) == 1
    assert result.knowledge_points[0].learning_skills == []
    assert result.knowledge_points[0].concepts == []


@pytest.mark.asyncio
async def test_absent_skills_do_not_spend_an_unnecessary_second_generation():
    from tests.professional_contract_support import projected_once
    body = document_slice()
    body["knowledge_points"][0].pop("learning_skills")
    result, calls = await projected_once(body, ProjectInput(**SLICES["review_cards"]["project"]), settings())
    assert len(calls) == 1 and result.knowledge_points[0].learning_skills == []


def test_professional_term_prompt_is_specific_without_compulsory_skill_or_practice_layers():
    assert "not a conversational task sentence" in SYSTEM_PROMPT
    assert "isolated line of syntax or entire discipline" in SYSTEM_PROMPT
    assert "select terms from the actual requirements" in SYSTEM_PROMPT
    assert "Preserve the requested behavior, numbers and constraints in concise feature criteria" in SYSTEM_PROMPT
    assert "Do not turn these points into a compulsory project-task/skills/practice breakdown" in SYSTEM_PROMPT


def test_concrete_streamlit_controls_are_allowed_instead_of_a_generic_family():
    body = document_slice()
    point = body["knowledge_points"][0]
    point.update(name="日期和分类筛选控件", technology="Streamlit",
                 project_task="用日期输入和品类多选的返回值筛选本地CSV。",
                 concepts=["st.date_input", "st.multiselect", "空选择不展示数据"],
                 learning_skills=["Streamlit 日期输入返回值与默认值", "Streamlit 多选返回值到筛选条件"],
                 practice_check="默认展示有效数据，日期和品类选择改变后结果相应变化。")
    project = ProjectInput(name="本地库存筛选看板", requirements="用Streamlit提供日期输入和品类多选筛选，不选品类时结果为空。")
    assert not learning_quality_issues(project, AnalysisDocument.model_validate(body))


def test_correct_practice_does_not_excuse_wrong_debounce_skill():
    body = document_slice("pot_led")
    point = body["knowledge_points"][0]
    point["project_task"] = "按钮电平持续稳定20ms后才确认新状态，再检测单次按下。"
    point["learning_skills"] = ["Arduino 去抖只需比较当前和前次电平", "Arduino 稳定输入事件处理"]
    project = ProjectInput(name="Arduino按钮", requirements="机械按钮必须去抖且长按只触发一次。")
    assert "raw_edge_is_not_debounce" in {i["code"] for i in learning_quality_issues(project, AnalysisDocument.model_validate(body))}


def test_correct_skill_does_not_excuse_blocking_project_instruction():
    body = document_slice("pot_led")
    point = body["knowledge_points"][0]
    point["project_task"] = "使用Serial.readString等待命令，默认立即响应。"
    point["learning_skills"] = ["Arduino Serial.read逐字缓冲输入", "Arduino millis定时采样"]
    project = ProjectInput(name="Arduino串口采样", requirements="非阻塞采样并同时响应串口输入。")
    assert "blocking_input_for_responsive_task" in {i["code"] for i in learning_quality_issues(project, AnalysisDocument.model_validate(body))}
