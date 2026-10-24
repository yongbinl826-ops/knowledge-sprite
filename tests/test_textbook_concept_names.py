"""Generation-only textbook naming checks; all cases are synthetic and offline."""
from copy import deepcopy

import pytest

from backend.app.professional_concepts import (
    concept_name_issues,
    textbook_concept_issues,
    textbook_concept_name_issues,
)
from backend.app.project_models import AnalysisDocument


@pytest.mark.parametrize("name", [
    "线性表", "栈", "队列", "二叉树", "图", "内部排序", "索引",
    "事件循环", "有限状态机", "碰撞检测", "二维坐标系", "数值积分",
    "帧率控制", "文本渲染", "坐标限幅", "随机数生成", "计数器", "累加器", "评分算法",
    "分数阶微积分", "分数表示", "得分函数", "Accumulator", "Scoring algorithms",
    "创建型设计模式", "发布与订阅模式", "逻辑与运算", "初始化与析构",
    "数据序列化与反序列化", "JSON 编码与解码", "文件读取与文件写入",
    "线性表插入与删除", "异常捕获与异常传播", "事件捕获与事件冒泡",
    "应力与应变", "自旋霍尔磁阻", "让步状语从句", "创建性表达",
    "C++ 左值与右值引用", "Python 列表与循环的游戏状态建模",
    "React useState 状态管理", "pygame.Rect", "变量赋值", "对象生命周期",
    "状态转移", "状态空间模型", "可变状态封装", "当前状态观测",
    "同步复位", "异步复位", "复位电路", "寄存器复位", "状态恢复",
    "基于多版本并发控制的可串行化快照隔离", "计数器电路", "向量累加",
    "Error handling and user feedback", "Event capturing and event bubbling",
    "Read and write locks", "Counter circuits", "Object lifecycle",
    "Mutable state encapsulation", "State transitions", "Synchronous reset",
    "变量", "数据类型", "条件分支", "循环", "函数", "赋值语句", "比较运算",
    "笛卡尔坐标系", "欧拉法", "数值积分", "运动学", "轴对齐包围盒", "约束满足问题",
    "知识表示与推理", "约束表示与求解", "特征表示与度量学习",
    "基于内容的图像检索", "基于密度的聚类", "基于时间步长的数值积分",
    "时间差定位", "Representation learning", "Constraint satisfaction",
    "Knowledge representation and reasoning", "Constraint representation and solving",
    "事件队列", "事件处理", "键盘输入", "轴对齐矩形碰撞检测", "文本渲染",
    "量子状态重置", "协议状态复位",
    "变量与赋值", "数值积分与微分", "旋转与平移", "内存分配与释放",
])
def test_names_are_not_rejected_for_length_conjunction_prefix_or_unfamiliar_domain(name):
    assert textbook_concept_name_issues(name) == []


@pytest.mark.parametrize("name", [
    "图形窗口初始化与显示表面创建",
    "速度积分与位置更新",
    "矩形创建与定位",
    "字体渲染与文本表面绘制",
    "绘图表面绘制与显示刷新",
    "窗口创建与键盘处理",
    "表单配置与组件属性更新",
    "传感器校准与采样值刷新",
    "事务提交以及页面刷新",
    "Window initialization and display surface creation",
    "Numerical integration and position update",
    "计数器与累加", "缓冲区与清零", "渲染器与绘制", "Counter and increment",
])
def test_operation_bundles_need_a_concept_name_without_prescribing_a_replacement(name):
    issues = textbook_concept_name_issues(name)
    assert [code for code, _ in issues] == ["textbook_operation_bundle"]
    assert "description" in issues[0][1]


@pytest.mark.parametrize("name", [
    "计数器累加", "计数变量清零", "标志变量赋值", "累计值更新",
    "运行时对象状态重置", "组件属性更新", "对象的字段赋值",
    "实例状态初始化", "Counter increment", "flag variable reset",
    "runtime object state reset", "Component property update",
    "可变状态重置", "运行时状态初始化", "当前状态更新", "初始状态复位",
    "当前的状态重置", "可变 状态 重置", "mutable state reset",
    "runtime state initialization", "Current state update", "initial state assignment",
    "分数累计", "分数累加", "得分积累", "得分递增", "得分更新", "分数清零",
    "Score accumulation", "score increment", "scores update",
])
def test_bookkeeping_operations_are_feedback_not_independent_learning_topics(name):
    assert [code for code, _ in textbook_concept_name_issues(name)] == ["textbook_operation_label"]


@pytest.mark.parametrize("name", [
    "基于时间增量的运动", "根据采样间隔的位移", "按照数值变化量的更新",
    "利用坐标差值的位置更新", "基于每帧时间差的运动", "时间增量驱动的运动",
    "帧间隔驱动的位置更新", "Time-delta-based motion", "Sampling-interval-driven updates",
    "Motion based on elapsed time", "Movement based on time delta",
    "基于时间步长的运动更新", "基于采样间隔的位移计算", "根据速度差值的运动模拟",
    "时间增量驱动的移动控制", "Time-step-based motion updates", "Frame-interval-driven movement simulation",
])
def test_runtime_quantity_action_is_a_description_not_a_textbook_name(name):
    issues = textbook_concept_name_issues(name)
    assert [code for code, _ in issues] == ["textbook_descriptive_name"]
    assert "description" in issues[0][1] and "definition" in issues[0][1]


@pytest.mark.parametrize("name", [
    "矩形区域表示与坐标约束", "几何形状建模与位置限制", "信号表示以及振幅限幅",
    "图结构表征与容量约束", "Region representation and coordinate constraints",
    "Signal modeling and amplitude limits",
])
def test_representation_and_separate_constraint_requires_semantic_repair(name):
    issues = textbook_concept_name_issues(name)
    assert [code for code, _ in issues] == ["textbook_representation_constraint_bundle"]
    assert "independent" in issues[0][1] and "required" in issues[0][1]


@pytest.mark.parametrize("name", [
    "事件队列与键盘输入", "矩形表示与矩形碰撞检测", "文本渲染与分数显示",
    "图结构表示与路径检索", "特征表征与样本匹配", "缓冲区与串口输入",
    "消息队列与传感器数据收集", "三维投影与模型显示", "哈希校验与上传结果显示",
    "Rectangle representation and collision detection", "Text rendering and score display",
    "矩形表示与绘制", "树形结构表示与检索", "信号表征与转换", "Shape representation and drawing",
])
def test_mechanism_and_application_tail_requires_standard_concept_review(name):
    issues = textbook_concept_name_issues(name)
    assert [code for code, _ in issues] == ["textbook_mechanism_application_bundle"]
    assert "description" in issues[0][1] and "independent" in issues[0][1]


@pytest.mark.parametrize("name,description", [
    ("游戏状态重置", "重置是把一组相关对象与计数恢复到确定的初始值，使新一局从一致起点开始。"),
    ("会话状态重置", "把表单变量恢复到初始值并清零计数。"),
    ("设备状态更新", "把对象字段设为默认值，再开始下一次采集。"),
    ("Checkout state reset", "Restore related variables and counters to their initial values."),
    ("游戏重置", "将可变状态恢复到初始值并开始新一轮。"),
    ("表单恢复", "将各字段恢复到默认值。"),
    ("流程复位", "把对象属性和计数器恢复到初始值。"),
    ("Application reset", "Restore all mutable state and variables to their initial values."),
    ("状态重置", "重置是把参与运行的可变数据恢复为初始值以重新开始。本项目在按下重新开始键时把分数清零。"),
    ("状态重置", "将运行时的值恢复为初始值。"),
    ("流程恢复", "把应用的数据恢复到默认值。"),
    ("流程复位", "将业务的值恢复为初始值。"),
    ("State reset", "Restore application data to initial values."),
    ("Application reset", "Restore runtime values to initial values."),
])
def test_domain_state_action_uses_description_evidence_not_domain_word_lists(name, description):
    points = [{"id": "k1", "name": name, "description": description}]
    before = deepcopy(points)
    assert [(issue["code"], issue["location"]) for issue in textbook_concept_issues(points)] == [
        ("textbook_operation_label", ["knowledge_points", 0, "name"])]
    assert points == before


@pytest.mark.parametrize("name,description", [
    ("量子状态重置", "研究非幺正量子通道的算子表示与物理实现。"),
    ("协议状态复位", "研究通信协议在复位信号后的合法状态转换规则。"),
    ("寄存器复位", "复位引脚将寄存器置于初始值，分析其同步与异步时序要求。"),
    ("状态重置", "研究非幺正量子通道的算子表示与物理实现。"),
])
def test_true_state_mechanisms_are_not_rejected_by_the_word_state_or_reset(name, description):
    assert textbook_concept_issues([{"name": name, "description": description}]) == []


def test_feedback_has_original_point_paths_and_never_mutates_or_renames_points():
    points = [
        {"id": "k1", "name": "计数器累加", "technology": "Python", "description": "每次交互后加一。"},
        {"id": "k2", "name": "有限状态机", "technology": "Python", "description": "理解状态和转移。"},
        {"id": "k3", "name": "速度积分与位置更新", "technology": "pygame", "description": "保持原始用途。"},
    ]
    before = deepcopy(points)
    issues = textbook_concept_issues(points)
    assert [(issue["code"], issue["point_id"], issue["location"]) for issue in issues] == [
        ("textbook_operation_label", "k1", ["knowledge_points", 0, "name"]),
        ("textbook_operation_bundle", "k3", ["knowledge_points", 2, "name"]),
    ]
    assert points == before


def test_feedback_accepts_flat_generated_points_without_internal_ids():
    issues = textbook_concept_issues([{"name": "计数器累加"}])
    assert issues[0]["location"] == ["knowledge_points", 0, "name"]
    assert "point_id" not in issues[0]


def test_observed_state_reset_label_is_feedback_without_auto_merging_the_mechanisms():
    # Shape of the live naming gap, represented here as offline test data.
    points = [
        {"id": "k1", "name": "有限状态机", "description": "状态及转移条件。"},
        {"id": "k2", "name": "可变状态重置", "description": "把当前运行数据变量恢复到初始值。"},
        {"id": "k3", "name": "计数器", "description": "计数和初值。"},
    ]
    before = deepcopy(points)
    issues = textbook_concept_issues(points)
    assert [(item["code"], item["point_id"]) for item in issues] == [("textbook_operation_label", "k2")]
    assert points == before


@pytest.mark.parametrize("name", [
    "图形窗口初始化与显示表面创建", "计数器累加", "运行时对象状态重置", "可变状态重置", "分数累计",
    "基于时间增量的运动", "矩形区域表示与坐标约束",
    "基于时间步长的运动更新", "事件队列与键盘输入", "矩形表示与矩形碰撞检测", "文本渲染与分数显示",
])
def test_new_generation_policy_does_not_reject_or_rewrite_saved_history(name):
    assert concept_name_issues(name) == []
    payload = {
        "scope": "历史保存的接球项目", "technical_plan": "使用已有方案。", "assumptions": [],
        "functions": [{"id": "f1", "name": "交互", "original_requirement": "实现交互", "acceptance_criteria": "响应输入"}],
        "knowledge_points": [{
            "id": "k1", "name": name, "technology": "pygame", "description": "已保存的项目用途。",
            "why_needed": "项目需要。", "learning_goal": "理解相关机制。", "function_ids": ["f1"],
            "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn",
        }],
    }
    document = AnalysisDocument.model_validate(payload)
    assert document.knowledge_points[0].name == name
    assert not document.professional_concept_issues()
    assert textbook_concept_issues(document.model_dump()["knowledge_points"])
