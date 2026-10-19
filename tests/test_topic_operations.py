"""Offline synthetic observations for the bounded operation fallback."""
from copy import deepcopy

import pytest

from backend.app.models import TopicEvidenceAssessment
from backend.app.topic_operations import assess_operation_fallback


def observation(text, identifier="evidence-1"):
    return {"text": text, "evidence_ids": [identifier]}


@pytest.mark.parametrize(("point", "text", "qualification"), [
    ("Python 本地文件路径处理", "Python 文件路径处理教程", "本地"),
    ("matplotlib 图表保存为图片", "Matplotlib 保存图片", "图表"),
    ("pandas 统计结果导出 Excel", "Pandas导出数据到EXCEL", "统计结果"),
    ("Python 本地目录处理", "Python 目录处理", "本地"),
    ("NumPy 数组保存到 CSV", "NumPy 保存数组到CSV", "数组"),
    ("Julia 实验结果写入 JSON", "Julia 写入JSON文件", "实验结果"),
    ("C++ 本地文件处理", "C++ 文件处理入门", "本地"),
    ("pandas 表格导出为 CSV", "pandas 导出CSV", "表格"),
    ("matplotlib 图表保存为图片", "Matplotlib 保存图片教程", "图表"),
    ("pandas 统计结果导出 Excel", "pandas 读取CSV后导出数据到Excel", "统计结果"),
    ("pandas 统计结果导出 Excel", "pandas 导出统计结果到Excel", "统计结果"),
    ("pandas 统计结果导出 Excel", "pandas 导入CSV；pandas 导出Excel", "统计结果"),
    ("pandas 统计结果导出 Excel", "pandas 导出 Excel 文件教程", "统计结果"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片 文件教程", "图表"),
    ("JavaScript 本地文件处理", "JavaScript基础；JavaScript 文件处理", "本地"),
])
def test_returns_only_partial_with_explicit_unknown_qualification(point, text, qualification):
    rows = [observation(text)]
    before = deepcopy(rows)
    result = assess_operation_fallback(point, rows)
    assert TopicEvidenceAssessment.model_validate(result).topic_evidence_status == "partial"
    assert result["supporting_evidence_ids"] == ["evidence-1"]
    assert result["subtopic_coverage"][0]["status"] == "supported"
    assert result["subtopic_coverage"][1] == {
        "id": "operation_qualification", "text": qualification, "status": "unknown", "evidence_ids": [],
        "reason": f"操作证据不能证明“{qualification}”这一原始限定。",
    }
    assert "仅证明" in result["topic_evidence_reasons"][0]["message"]
    assert "尚未确认" in result["topic_evidence_reasons"][0]["message"]
    assert rows == before


@pytest.mark.parametrize(("point", "text"), [
    ("pandas 统计结果导出 Excel", "pandas 读取Excel教程"),
    ("pandas 统计结果导出 Excel", "pandas 导入Excel"),
    ("pandas 统计结果导出 Excel", "pandas 导出CSV"),
    ("pandas 统计结果导出 Excel", "pandas 导出Excel数据到CSV"),
    ("pandas 统计结果导出 Excel", "pandas 导出Excel到CSV"),
    ("pandas 统计结果导出 Excel", "pandas 导出CSV文件再导入到Excel"),
    ("pandas 统计结果导出 Excel", "pandas 导出CSV并转为Excel"),
    ("pandas 统计结果导出 Excel", "pandas 导出数据再读取文件到Excel"),
    ("pandas 统计结果导出 Excel", "pandas 数据分析入门"),
    ("pandas 统计结果导出 Excel", "openpyxl 导出Excel"),
    ("matplotlib 图表保存为图片", "Pillow 保存图片"),
    ("matplotlib 图表保存为图片", "matplotlib 图表显示"),
    ("matplotlib 图表保存为图片", "matplotlib 网页下载图片"),
    ("matplotlib 图表保存为图片", "matplotlib 从网页下载并保存图片"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片链接"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片分类结果"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片 分类结果"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片\t分类结果"),
    ("matplotlib 图表保存为图片", "matplotlib 保存图片\u3000分类结果"),
    ("matplotlib 图表保存为图片", "matplotlib 截图并保存图片"),
    ("matplotlib 图表保存为图片", "matplotlib 不讲保存图片"),
    ("matplotlib 图表保存为图片", "matplotlib 不会保存图片"),
    ("pandas 统计结果导出 Excel", "pandas 无法导出Excel"),
    ("pandas 统计结果导出 Excel", "pandas 禁止导出Excel"),
    ("pandas 统计结果导出 Excel", "pandas 导出数据到CSV，Excel统计结果"),
    ("Python 本地文件路径处理", "文件路径处理"),
    ("Python 本地文件路径处理", "Python 远程文件路径处理"),
    ("Python 本地文件路径处理", "Python URL路径处理"),
    ("Python 本地文件路径处理", "Python 路径规划处理"),
    ("JavaScript 本地文件处理", "Java 文件处理"),
    ("JavaScript 本地文件处理", "JavaScript基础；Java 文件处理"),
    ("JavaScript 本地文件处理", "JavaScript basics. Java 文件处理"),
    ("JavaScript 本地文件处理", "JavaScript基础\nJava 文件处理"),
    ("pandas 统计结果导出 Excel", "pandas基础；openpyxl 导出Excel"),
    ("Java 本地文件处理", "JavaScript 文件处理"),
    ("C 本地文件处理", "C++ 文件处理"),
    ("C++ 本地文件处理", "C 文件处理"),
    ("pandas 统计结果导出 Excel", "pandas 导出ExcelWriter对象"),
    ("pandas 清洗数据导出 Excel", "pandas 导出Excel"),
    ("pandas 加密数据导出 Excel", "pandas 导出Excel"),
    ("matplotlib 无损图表保存为图片", "matplotlib 保存图片"),
    ("Python 保存图片", "Python 保存图片"),
    ("统计结果导出 Excel", "pandas 导出Excel"),
])
def test_does_not_infer_missing_or_conflicting_core(point, text):
    assert assess_operation_fallback(point, [observation(text)]) is None


@pytest.mark.parametrize("rows", [
    [observation("pandas 数据分析", "e1"), observation("导出Excel", "e2")],
    [observation("pandas 导出", "e1"), observation("Excel", "e2")],
    [{"text": "pandas 导出Excel", "evidence_ids": []}],
    [{"text": "pandas 导出Excel", "evidence_ids": [None, ""]}],
    [{"text": "", "title": "pandas 导出Excel", "evidence_ids": ["e1"]}],
])
def test_needs_complete_single_observation_and_real_evidence_ids(rows):
    assert assess_operation_fallback("pandas 统计结果导出 Excel", rows) is None


def test_only_complete_supporting_observations_contribute_ids():
    result = assess_operation_fallback("pandas 统计结果导出 Excel", [
        observation("pandas 导出CSV", "wrong-format"),
        observation("Excel", "format-only"),
        observation("Pandas 导出数据到Excel", "e1"),
        observation("Pandas 导出Excel", "e1"),
        observation("Pandas 导出表格为Excel", "e2"),
    ])
    assert result["supporting_evidence_ids"] == ["e1", "e2"]
    assert result["subtopic_coverage"][0]["evidence_ids"] == ["e1", "e2"]


def test_title_body_are_one_observation_but_no_raw_evidence_is_used():
    result = assess_operation_fallback("pandas 统计结果导出 Excel", [
        {"title": "Pandas 入门", "body": "导出数据到Excel", "raw": "irrelevant", "evidence_ids": ["e1"]},
    ])
    assert result["topic_evidence_status"] == "partial"
    assert assess_operation_fallback("pandas 统计结果导出 Excel", [
        {"text": "pandas 简介", "raw": "Pandas 导出Excel", "evidence_ids": ["e1"]},
    ]) is None
