"""Offline cross-domain boundaries for literal identity and instruction syntax."""
from copy import deepcopy

import pytest

from backend.app.professional_concepts import (
    concept_name_issues,
    concept_semantic_issues,
    duplicate_concept_issues,
)


def point(name, technology="", **extra):
    return {"name": name, "technology": technology,
            "description": "An application does not change the concept's identity.", **extra}


@pytest.mark.parametrize("name", [
    "创建型设计模式", "让步状语从句", "使役结构", "使动用法",
    "开发环境", "实现继承", "完成体", "添加剂制造", "制作工艺",
    "Build systems", "Write barriers", "Make functions",
    "发布与订阅模式", "逻辑与运算", "应力与应变", "数据序列化与反序列化",
    "C++ 移动语义", ".NET 反射", "C++ 左值与右值引用",
])
def test_professional_nouns_do_not_become_instructions_from_a_prefix(name):
    assert concept_name_issues(name) == []


@pytest.mark.parametrize("name,code", [
    ("请创建窗口", "project_task_name"),
    ("创建一个窗口", "project_task_name"),
    ("编写这段代码", "project_task_name"),
    ("如何测量电压", "project_task_name"),
    ("通过采样来测量电压", "project_task_name"),
    ("用循环来处理数据", "project_task_name"),
    ("create a game window", "project_task_name"),
    ("build the sales dashboard", "project_task_name"),
    ("learn to calibrate a sensor", "project_task_name"),
    ("创建页面与绑定按钮", "project_task_name"),
    ("创建窗口并循环读取事件", "task_bundle_name"),
    ("测量电压与保存读数", "task_bundle_name"),
    ("导入文档以及导出报告", "task_bundle_name"),
    ("读取文件以便生成报表", "project_purpose_name"),
    ("使用millis计时并避免阻塞", "project_purpose_name"),
    ("过滤噪声以避免采样失真", "project_purpose_name"),
    ("第3章 数据校验", "chapter_or_step_label"),
    ("采样然后滤波", "task_bundle_name"),
])
def test_explicit_instruction_purpose_and_step_evidence_is_still_rejected(name, code):
    assert code in {code for code, _ in concept_name_issues(name)}


@pytest.mark.parametrize("technology,prefixed,plain", [
    ("Python", "Python 列表索引", "列表索引"),
    ("pandas", "pandas分组聚合", "分组聚合"),
    ("JavaScript", "JavaScript 事件传播", "事件传播"),
    ("C++", "C++ 移动语义", "移动语义"),
    (".NET", ".NET反射", "反射"),
    ("JSON Schema", "JSON Schema 字段校验", "字段校验"),
    ("NumPy", "  NUMPY   array   indexing  ", "Array indexing"),
    ("MATLAB", "MATLAB 傅里叶变换", "傅里叶变换"),
    ("英语", "英语 让步状语从句", "让步状语从句"),
])
def test_same_explicit_technology_and_literal_concept_report_both_positions(technology, prefixed, plain):
    points = [point(prefixed, technology, id="k1"), point(plain, technology, id="k2")]
    points[1]["description"] = "A different project application still uses this concept."
    before = deepcopy(points)
    issues = duplicate_concept_issues(points)
    assert [(item["code"], item["point_id"], item["location"]) for item in issues] == [
        ("duplicate_concept_name", "k1", ["knowledge_points", 0, "name"]),
        ("duplicate_concept_name", "k2", ["knowledge_points", 1, "name"]),
    ]
    assert points == before


@pytest.mark.parametrize("technology,left,right", [
    ("Java", "JavaScript 事件", "Script 事件"),
    ("Python", "Pythonic 编程", "ic 编程"),
    ("C", "C++ 移动语义", "++ 移动语义"),
    ("C", "C# 类型", "# 类型"),
    (".NET", ".NETCore 反射", "Core 反射"),
    ("Python", "Python.random", "random"),
    ("英语", "英语语法", "语法"),
    ("Python", "Python Python 列表", "列表"),
    ("Python", "JSON Schema 校验", "跨字段业务约束"),
    ("Python", "数据类型校验", "数据范围校验"),
    ("Python", "C++ 类型", "C 类型"),
    ("Python", ".NET 反射", "NET 反射"),
    ("R", "R 树", "树"),
    ("Ｒ", "Ｒ 树", "树"),
    ("C", "C 类型", "类型"),
])
def test_partial_owner_prefixes_and_different_mechanisms_are_not_identity(technology, left, right):
    # Identical descriptions cannot cause semantic or punctuation-based merging.
    assert duplicate_concept_issues([point(left, technology), point(right, technology)]) == []


@pytest.mark.parametrize("left,right", [
    (point("事件", "pygame"), point("事件", "JavaScript")),
    (point("移动语义", "C++"), point("移动语义", "C")),
    (point("类型", "C++"), point("类型", "C#")),
    (point("反射", ".NET"), point("反射", "NET")),
    (point("列表索引", "Python"), point("Python 列表索引")),
    (point("事件"), point("事件")),
    (point("事件", "general"), point("事件", "none")),
    (point("事件", "Python;run"), point("事件", "Python;run")),
])
def test_context_must_be_explicit_safe_nonempty_and_equal(left, right):
    assert duplicate_concept_issues([left, right]) == []


def test_duplicate_groups_report_every_member_once_in_array_order_without_ids():
    points = [point("Python 列表索引", "Python"), point("元组", "Python"),
              point("列表索引", "PYTHON"), point("python列表索引", "Python")]
    issues = duplicate_concept_issues(points)
    assert [item["location"] for item in issues] == [
        ["knowledge_points", index, "name"] for index in (0, 2, 3)]
    assert all("point_id" not in item for item in issues)


def test_single_character_context_still_detects_identical_full_names():
    issues = duplicate_concept_issues([point("R 树", "R"), point("R 树", "R")])
    assert len(issues) == 2


def test_generation_quality_entrypoint_includes_duplicates_without_rewriting_points():
    points = [point("Python 列表索引", "Python", id="k1"),
              point("列表索引", "Python", id="k2")]
    before = deepcopy(points)
    assert concept_semantic_issues(points) == duplicate_concept_issues(points)
    assert points == before
