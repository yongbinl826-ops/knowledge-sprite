"""Offline evidence boundaries for generic concept-name feedback."""
from copy import deepcopy

import pytest

from backend.app.professional_concepts import concept_name_issues, textbook_concept_issues


@pytest.mark.parametrize("name,description", [
    ("设备初始化与信号采样", "说明设备就绪条件、采样频率和信号读取时序。"),
    ("试剂配置与浓度测量", "说明浓度的物理含义以及溶液配制与测量的方法。"),
    ("细胞定位与组织观察", "说明显微成像的空间定位以及组织形态的观察条件。"),
    ("Signal modeling and amplitude limits", "Describe the model and its physical admissibility conditions."),
    ("图结构表示与路径检索", "说明图的顶点和边以及检索所需的数据表示。"),
    ("Time-step-based motion updates", "Explain the integration method and the time units used by it."),
])
def test_name_only_suspicion_is_retained_without_claiming_semantic_proof(name, description):
    points = [{"id": "topic", "name": name, "description": description}]
    before = deepcopy(points)
    issues = textbook_concept_issues(points)
    assert len(issues) == 1
    assert issues[0]["disposition"] == "advisory"
    assert issues[0]["evidence"] == "title_heuristic"
    assert issues[0]["severity"] == "low"
    assert issues[0]["location"] == ["knowledge_points", 0, "name"]
    assert issues[0]["point_id"] == "topic"
    assert issues[0]["message"]
    assert points == before


@pytest.mark.parametrize("name", [
    "计数变量清零", "组件属性更新", "对象的字段赋值", "Score increment",
])
def test_explicit_bookkeeping_labels_still_require_repair(name):
    issues = textbook_concept_issues([{"name": name, "description": "说明其项目用途。"}])
    assert len(issues) == 1
    assert issues[0]["code"] == "textbook_operation_label"
    assert issues[0]["disposition"] == "blocking"
    assert issues[0]["evidence"] == "explicit_bookkeeping_label"
    assert issues[0]["severity"] == "medium"


@pytest.mark.parametrize("name,description", [
    ("重启时的状态重置", "重新开始需要把分数、实体位置、速度和状态全部恢复到初始值。"),
    ("会话恢复", "把对象属性和计数变量恢复到初始值。"),
    ("Application reset", "Restore all mutable state and variables to their initial values."),
])
def test_state_assignment_recipes_use_description_evidence_and_still_block(name, description):
    issue, = textbook_concept_issues([{"name": name, "description": description}])
    assert issue["code"] == "textbook_operation_label"
    assert issue["disposition"] == "blocking"
    assert issue["evidence"] == "state_assignment_description"


@pytest.mark.parametrize("name,description", [
    ("量子状态重置", "研究非幺正量子通道的算子表示与物理实现。"),
    ("寄存器复位", "复位引脚将寄存器置于初始值，分析同步与异步时序要求。"),
    ("约束表示与求解", "说明约束的表示、可行解和求解方法。"),
    ("应力与应变", "说明材料变形和内力之间的关系。"),
])
def test_unfamiliar_or_related_domain_concepts_are_not_renamed_or_blocked(name, description):
    points = [{"name": name, "description": description}]
    original = deepcopy(points)
    assert textbook_concept_issues(points) == []
    assert points == original


def test_title_advisory_does_not_remove_explicit_task_syntax_guard():
    name = "创建窗口与更新坐标"
    assert {code for code, _ in concept_name_issues(name)} >= {
        "task_bundle_name", "project_task_name",
    }


def test_mixed_feedback_retains_each_original_location_and_the_saved_text():
    points = [
        {"id": "k1", "name": "Pygame 初始化与显示表面", "description": "初始化模块后创建窗口显示表面。"},
        {"id": "k2", "name": "游戏主循环", "description": "循环处理事件、更新状态和绘制。"},
        {"id": "k3", "name": "重启时的状态重置", "description": "把实体位置和分数恢复到初始值。"},
    ]
    before = deepcopy(points)
    issues = textbook_concept_issues(points)
    assert [(issue["point_id"], issue["disposition"], issue["location"]) for issue in issues] == [
        ("k1", "advisory", ["knowledge_points", 0, "name"]),
        ("k3", "blocking", ["knowledge_points", 2, "name"]),
    ]
    assert points == before


@pytest.mark.parametrize("hard_index", [24, 29])
def test_earlier_advisories_cannot_hide_a_late_blocking_point(hard_index):
    points = [{"id": f"k{index + 1}", "name": f"设备{index + 1}初始化与信号采样",
               "description": "说明设备就绪条件和信号的采样方法。"} for index in range(30)]
    points[hard_index].update(name="计数变量清零", description="将计数变量设为初始值。")
    original = deepcopy(points)
    issues = textbook_concept_issues(points)
    assert len(issues) == 30
    assert [issue["location"] for issue in issues if issue["disposition"] == "blocking"] == [
        ["knowledge_points", hard_index, "name"],
    ]
    assert sum(issue["disposition"] == "advisory" for issue in issues) == 29
    assert points == original


@pytest.mark.parametrize("name", [
    "计数器累加与标志变量赋值",
    "对象字段赋值以及组件属性更新",
    "当前状态更新与运行时状态重置",
    "Score increment and flag variable reset",
])
def test_joining_only_explicit_bookkeeping_labels_cannot_downgrade_them(name):
    issue, = textbook_concept_issues([{"name": name, "description": "保留原有项目操作。"}])
    assert issue["code"] == "textbook_operation_label"
    assert issue["disposition"] == "blocking"
    assert issue["evidence"] == "explicit_bookkeeping_label"


@pytest.mark.parametrize("name,description", [
    ("数值积分与对象状态更新", "积分方法根据导数和时间步长近似新的状态。"),
    ("量子状态重置与计数变量清零", "说明量子通道的物理机制及实验记录方式。"),
    ("信号测量与标志变量赋值", "说明测量信号及其状态记录的使用条件。"),
    ("Statistical estimation and counter increment", "Explain the estimator and how sample events are counted."),
])
def test_one_operation_beside_a_mechanism_is_not_definite_bookkeeping_bundle(name, description):
    issue, = textbook_concept_issues([{"name": name, "description": description}])
    assert issue["disposition"] == "advisory"
    assert issue["evidence"] == "title_heuristic"
