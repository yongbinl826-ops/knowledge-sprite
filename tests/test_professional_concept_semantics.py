"""Legacy checker units and single-pass replay; retained v5.2 is not a new pass."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from tests.professional_contract_support import flat_proposal

from backend.app.professional_concepts import concept_name_issues
from backend.app.project_analysis import (
    SYSTEM_PROMPT, generation_schema,
    professional_contract_issues,
)
from backend.app.project_models import AnalysisDocument, ProjectInput


FIXTURE = Path(__file__).parent / "fixtures/related-policy-20261020/pygame-analysis.json"
LIVE_SHA = "6e6f4c69a689bb3952228c342a39a38f1c0ade6d96d6aa40341be69b9f0a6103"


def observed():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def point(identifier, name, *, technology="", prerequisites=(), description=None):
    return {
        "id": identifier, "name": name,
        "description": description or "解释此概念的机制及其在项目中的应用。",
        "why_needed": "项目使用此机制。", "learning_goal": "理解并应用该机制。",
        "function_ids": ["F1"], "technology": technology,
        "necessity": "required", "prerequisite_ids": list(prerequisites),
        "learning_order": 1 if identifier == "P1" else 2, "selection": "learn",
    }


def document(points):
    return AnalysisDocument.model_validate({
        "scope": "本地合成项目，不添加账号或云服务。",
        "technical_plan": "用所选技术实现项目。", "assumptions": [],
        "functions": [{"id": "F1", "name": "合成功能", "original_requirement": "实现功能",
                       "acceptance_criteria": "行为与需求一致。"}],
        "knowledge_points": points,
    })


def issues(doc, *, level="any", context=""):
    return professional_contract_issues(ProjectInput(
        name="合成项目", requirements="实现项目所需功能，不加云服务。",
        student_level=level, project_context=context,
    ), doc)


def synthetic_repair():
    """Test-authored correction, never recorded as an actual model generation."""
    result = deepcopy(observed()["analysis"])
    result["knowledge_points"] = [p for p in result["knowledge_points"] if p["id"] != "K10"]
    for p in result["knowledge_points"]:
        if p["id"] == "K1":
            # Repair only this synthetic response; the retained live bytes and
            # their original frame-duration misconception remain unchanged.
            p["description"] = ("pygame 程序由初始化、事件处理、状态更新、绘制与屏幕刷新组成的主循环驱动，"
                                "并用 Clock.tick 设置帧率上限；处理耗时较短时等待，不保证每帧耗时的上限。")
        if p["id"] == "K7":
            p["prerequisite_ids"] = []
        if p["id"] == "K4":
            p["prerequisite_ids"] = ["K2"]
    return result


def test_retained_live_has_precise_generation_only_findings():
    source = observed()
    doc = AnalysisDocument.model_validate(source["analysis"])
    found = professional_contract_issues(ProjectInput.model_validate(source["input"]), doc)
    details = {(q["code"], tuple(q["location"])) for q in found}
    assert ("implementation_detail_as_concept", ("knowledge_points", 9, "name")) in details
    assert ("implementation_order_prerequisite", ("knowledge_points", 6, "prerequisite_ids", 1)) in details
    assert ("implementation_order_prerequisite", ("knowledge_points", 3, "prerequisite_ids", 1)) in details
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == LIVE_SHA


@pytest.mark.parametrize("level,context", [
    ("any", ""), ("beginner", "第一次编程"),
    ("intermediate", "会Python变量、条件、循环、列表、函数"),
    ("advanced", "熟悉相关技术，但由我自己勾选知识点"),
])
def test_noun_wrapped_bookkeeping_is_not_a_mastery_inference(level, context):
    source = observed()["analysis"]["knowledge_points"][9]
    doc = document([{**source, "id": "P1", "function_ids": ["F1"]}])
    assert any(q["code"] == "implementation_detail_as_concept" for q in issues(doc, level=level, context=context))
    assert doc.knowledge_points[0].selection == "learn"


@pytest.mark.parametrize("name", ["页面点击计数变量", "项目计数变量", "Application counter variables"])
def test_application_qualified_low_level_variable_labels_need_a_real_concept(name):
    p = point("P1", name, technology="Python",
              description="用整型变量维护数值，事件发生时累加，结束时清零。")
    assert any(q["code"] == "implementation_detail_as_concept" for q in issues(document([p])))


@pytest.mark.parametrize("name,technology", [
    ("CSV 文件读取", "pandas"), ("文件上传", "Streamlit"),
    ("数据序列化", "JavaScript"), ("模数转换", "Arduino Uno"),
    ("变量作用域", "Python"), ("环境变量", ""), ("随机变量", ""),
    ("有限状态机", "pygame"), ("计数器电路", ""),
    ("列表操作", "Python"), ("自旋霍尔磁阻", ""),
])
def test_real_concepts_and_unfamiliar_domains_are_not_forced_into_a_template(name, technology):
    assert not issues(document([point("P1", name, technology=technology)]))


@pytest.mark.parametrize("child,parent,technology", [
    ("列表增删遍历", "随机数生成", "Python"),
    ("数组操作", "随机数生成", "JavaScript"),
    ("Python 列表操作", "Python 随机数生成", "Python"),
    ("边界限制", "键盘输入处理", "pygame"),
    ("坐标限幅", "持续按键状态查询", "pygame"),
    ("数值限幅", "按键状态检测", "Arduino Uno"),
    ("List operations", "Random number generation", "Python"),
    ("Coordinate clamping", "Keyboard input handling", "pygame"),
])
def test_observable_implementation_coupling_is_not_a_knowledge_edge(child, parent, technology):
    doc = document([point("P1", parent, technology=technology),
                    point("P2", child, technology=technology, prerequisites=["P1"])])
    found = issues(doc)
    assert [(q["code"], q["location"]) for q in found] == [
        ("implementation_order_prerequisite", ["knowledge_points", 1, "prerequisite_ids", 0])]


@pytest.mark.parametrize("child,parent,technology", [
    ("列表操作", "线性表", "Python"),
    ("边界限制", "二维坐标系", "pygame"),
    ("矩形碰撞检测", "矩形区域表示", "pygame"),
    ("按键消抖", "数字输入", "Arduino Uno"),
    ("DOM事件传播", "DOM树", "JavaScript"),
    ("分组聚合", "DataFrame", "pandas"),
    ("随机列表采样", "随机数生成", "Python"),
    ("键盘位置控制", "键盘输入处理", "pygame"),
    ("自旋霍尔磁阻", "自旋轨道转矩", ""),
])
def test_valid_or_unfamiliar_dependencies_are_not_replaced_by_a_fixed_graph(child, parent, technology):
    doc = document([point("P1", parent, technology=technology),
                    point("P2", child, technology=technology, prerequisites=["P1"])])
    assert not issues(doc)


@pytest.mark.parametrize("name", [
    "数据序列化与反序列化", "JSON 编码与解码", "文件读取与文件写入",
    "事件捕获与事件冒泡", "CSV 文件导出与下载", "线性表插入与删除",
    "反序列化与序列化", "文件写入与文件读取", "事件冒泡与事件捕获",
    "Event capturing and event bubbling",
])
def test_complementary_facets_of_one_technique_can_remain_one_topic(name):
    assert not concept_name_issues(name)


@pytest.mark.parametrize("name", [
    "异常捕获与异常传播", "错误处理、用户反馈", "数据一致性以及事务隔离",
    "应力张量与应变张量", "语言理解、语音生成、视觉表示",
    "Error handling and user feedback", "Input validation and output validation",
    "JSON 编码与URL解码", "文件读取与网络写入", "窗口创建与键盘处理",
])
def test_conjunction_only_names_are_not_semantically_rejected_by_a_structure_check(name):
    # Synthetic examples, including questionable combinations: accepting the
    # syntax does not certify the topic's coherence or require a subject allowlist.
    assert concept_name_issues(name) == []


@pytest.mark.parametrize("name,code", [
    ("创建页面与绑定按钮", "project_task_name"),
    ("第3章 输入处理、输出格式化", "chapter_or_step_label"),
    ("文件读取然后处理数据", "task_bundle_name"),
    ("Validate input and then format output", "task_bundle_name"),
    ("点击按钮与切换页面", "project_interaction_name"),
])
def test_conjunctions_do_not_bypass_explicit_task_or_step_grammar(name, code):
    assert code in {issue_code for issue_code, _ in concept_name_issues(name)}


def test_history_and_student_reordering_remain_lossless_and_independently_selectable():
    source = observed()["analysis"]
    doc = AnalysisDocument.model_validate(source)
    doc.knowledge_points[6].selection = "skip"
    doc.knowledge_points[4].learning_order = 24
    restored = AnalysisDocument.model_validate(doc.model_dump())
    assert restored.knowledge_points[6].prerequisite_ids == ["K1", "K5"]
    assert restored.knowledge_points[6].selection == "skip"
    assert restored.knowledge_points[4].learning_order == 24
    assert restored.knowledge_points[9].name == "游戏计数变量"
    assert "learning_position" not in restored.model_dump()["knowledge_points"][9]


def test_synthetic_correction_does_not_add_scope_or_change_original_requirements():
    repaired = synthetic_repair()
    assert repaired["functions"] == observed()["analysis"]["functions"]
    assert repaired["scope"] == observed()["analysis"]["scope"]
    assert "限制每帧时长" in observed()["analysis"]["knowledge_points"][0]["description"]
    assert "不保证每帧耗时的上限" in repaired["knowledge_points"][0]["description"]
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == LIVE_SHA
    assert not issues(AnalysisDocument.model_validate(repaired))


def test_prompt_is_about_concepts_and_real_dependencies_not_mastery_or_mandatory_skills():
    assert "one point teaches one reusable principle" in SYSTEM_PROMPT
    assert "Do not output graphs, learning order" in SYSTEM_PROMPT
    assert "The server supplies IDs and selection" in SYSTEM_PROMPT
    assert "not requirements or proof of mastery" in SYSTEM_PROMPT
    schema = generation_schema()
    fields = schema["$defs"]["GeneratedConcept"]["properties"]
    assert not {"learning_skills", "project_task", "practice_check", "learning_position", "selection"} & fields.keys()
    assert "learner_profile" not in schema["properties"]


@pytest.mark.asyncio
async def test_actual_old_findings_do_not_trigger_judgement_or_repair(monkeypatch):
    from backend.app import project_analysis as module
    from tests.test_professional_title_quality import generate_once
    source = observed()
    generated = flat_proposal(source["analysis"])
    def forbidden(*_args, **_kwargs):
        pytest.fail("Naming/content judgement must not run")
    monkeypatch.setattr(module, "_local_quality_issues", forbidden)
    result, calls = await generate_once(generated, ProjectInput.model_validate(source["input"]))
    assert len(calls) == 1
    assert result.knowledge_points[9].name == "游戏计数变量"
    assert "限制每帧时长" in result.knowledge_points[0].description
    assert "prerequisite_ids" not in result.model_dump()["knowledge_points"][0]
    assert "functions" not in result.model_dump()
    assert all(p.selection == "learn" for p in result.knowledge_points)
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == LIVE_SHA


@pytest.mark.asyncio
async def test_synthetic_alternative_is_not_needed_to_accept_original_content(monkeypatch):
    from backend.app import project_analysis as module
    from tests.test_professional_title_quality import generate_once
    original = flat_proposal(observed()["analysis"])
    alternative = flat_proposal(synthetic_repair())
    assert original != alternative
    def forbidden(*_args, **_kwargs):
        pytest.fail("Independent semantic or naming checks must not run")
    monkeypatch.setattr(module, "professional_contract_issues", forbidden)
    result, calls = await generate_once(original, ProjectInput.model_validate(observed()["input"]))
    assert len(calls) == 1
    assert len(result.knowledge_points) == len(original["knowledge_points"])
    assert len(result.knowledge_points) != len(alternative["knowledge_points"])
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == LIVE_SHA
