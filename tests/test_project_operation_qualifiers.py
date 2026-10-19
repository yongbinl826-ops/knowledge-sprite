"""Synthetic grammar/owner guards only; retained real evidence is replayed separately."""
from copy import deepcopy

import pytest

from backend.app.topic_operations import assess_operation_fallback, operation_decomposition


def observed(text, identifier="own-evidence"):
    return {"text": text, "evidence_ids": [identifier]}


@pytest.mark.parametrize("point,text,core,residual", [
    ("pandas 读取医疗 CSV 与字段检查", "pandas 读取CSV格式文件教程", "pandas 读取 CSV", ["医疗", "字段检查"]),
    ("pandas 读取仓储 Excel 与列类型检查", "pandas.read_excel('input.xlsx') 示例", "pandas 读取 Excel", ["仓储", "列类型检查"]),
    ("JavaScript 读取气象 JSON 并检查结构", "JavaScript读取JSON文件教程", "JavaScript 读取 JSON", ["气象", "检查结构"]),
    ("pandas 读取实验 TSV 并处理缺失列", "pandas read_table('measurements.tsv') 示例", "pandas 读取 TSV", ["实验", "处理缺失列"]),
    ("pandas order_code 去重与审计统计", "pandas 数据去重教程", "pandas 数据去重", ["order_code", "审计统计"]),
    ("pandas 学籍字段删除重复记录与保留规则", "pandas DataFrame.drop_duplicates(subset=['code']) 示例", "pandas 数据去重", ["学籍字段", "保留规则"]),
    ("pandas 日期列解析与无效数据隔离", "pandas 日期时间转换教程", "pandas 日期时间转换", ["日期列", "无效数据隔离"]),
    ("pandas 时间字段转换与错误日志", "pandas.to_datetime(values) 示例", "pandas 日期时间转换", ["时间字段", "错误日志"]),
    ("pandas 按设备分组计数", "pandas 分组计数教程", "pandas 分组计数", ["按设备"]),
    ("pandas 按医院分组后统计数量", "pandas DataFrame.groupby('hospital').size() 示例", "pandas 分组计数", ["按医院"]),
    ("Matplotlib 区域 Top5 条形图", "matplotlib 绘制条形图教程", "Matplotlib 条形图绘制", ["区域", "Top5"]),
    ("Matplotlib 订单数量柱状图绘制与标签", "matplotlib.pyplot.bar(labels, values) 示例", "Matplotlib 条形图绘制", ["订单数量", "标签"]),
])
def test_explicit_five_cores_remain_partial_and_preserve_every_business_or_extra_action(point, text, core, residual):
    observations = [observed(text)]
    before = deepcopy(observations)
    plan = operation_decomposition(point)
    assessment = assess_operation_fallback(point, observations)
    assert plan and assessment and assessment["topic_evidence_status"] == "partial"
    assert plan["subtopics"] == [{"id": part["id"], "text": part["text"]} for part in assessment["subtopic_coverage"]]
    assert assessment["subtopic_coverage"][0]["text"] == core
    assert assessment["subtopic_coverage"][0]["status"] == "supported"
    assert assessment["subtopic_coverage"][1]["status"] == "unknown"
    assert assessment["subtopic_coverage"][1]["evidence_ids"] == []
    assert all(term in assessment["subtopic_coverage"][1]["text"] for term in residual)
    assert assessment["supporting_evidence_ids"] == ["own-evidence"] and observations == before


@pytest.mark.parametrize("point,text", [
    ("pandas 读取医疗 CSV 与字段检查", "pandas 数据分析基础教程"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas 导出CSV教程"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas 读取Excel后导出CSV"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas 导入数据到CSV"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas read_excel('records.xlsx') 示例"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas to_csv('records.csv') 示例"),
    ("pandas 读取医疗 CSV 与字段检查", "polars 读取CSV教程"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas基础，polars读取CSV教程"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas简介 openpyxl读取CSV教程"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas helper.read_csv('records.csv')"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas API列表 read_csv, read_excel, to_csv"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas read_csv"),
    ("pandas 读取医疗 CSV 与字段检查", "先修：pandas读取CSV教程"),
    ("pandas 读取医疗 CSV 与字段检查", "本课不讲pandas读取CSV"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas 不支持读取CSV"),
    ("pandas 读取医疗 CSV 与字段检查", "Prerequisites: pandas.read_csv('records.csv')"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas API list: pandas.read_csv('records.csv')"),
    ("pandas 读取医疗 CSV 与字段检查", "pandas https://example.org/pandas/read_csv/tutorial"),
    ("pandas 读取实验 TSV 与列检查", "pandas read_csv('records.csv') 示例"),
    ("pandas 读取实验 TSV 与列检查", "pandas read_table('records.csv', sep=',') 示例"),
    ("pandas 读取实验 CSV 与列检查", r"pandas read_csv('records.tsv', sep='\t') 示例"),
    ("pandas order_code 去重与审计统计", "pandas 数据清洗教程"),
    ("pandas order_code 去重与审计统计", "pandas dropna() 处理缺失值"),
    ("pandas order_code 去重与审计统计", "pandas helper.drop_duplicates(values)"),
    ("pandas order_code 去重与审计统计", "pandas API列表 DataFrame.drop_duplicates(subset=['code'])"),
    ("pandas order_code 去重与审计统计", "pandas介绍，NumPy 数据去重"),
    ("pandas order_code 去重与审计统计", "pandas 数据去重是先修知识"),
    ("pandas 时间字段转换与错误日志", "pandas 时间数据处理"),
    ("pandas 时间字段转换与错误日志", "pandas Timestamp('2025-01-01') 示例"),
    ("pandas 时间字段转换与错误日志", "pandas to_numeric(values) 示例"),
    ("pandas 时间字段转换与错误日志", "pandas helper.to_datetime(values) 示例"),
    ("pandas 时间字段转换与错误日志", "pandas介绍，numpy.to_datetime(values)"),
    ("pandas 时间字段转换与错误日志", "pandas简介 import numpy as pd; pd.to_datetime(values)"),
    ("pandas 按设备分组计数", "pandas groupby('device').sum() 示例"),
    ("pandas 按设备分组计数", "pandas groupby count size API列表"),
    ("pandas 按设备分组计数", "pandas 分组求和教程"),
    ("pandas 按设备分组计数", "pandas helper.groupby('device').count()"),
    ("pandas 按设备分组计数", "pandas DataFrame.groupby('device').sum(); DataFrame.count()"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib 图表显示教程"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib 绘制折线图"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib 截图条形图教程"),
    ("Matplotlib 区域 Top5 条形图", "Matplotlib简介 Pillow绘制条形图教程"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib helper.bar(labels, values)"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib.bar(labels, values)"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib API清单 pyplot.bar(labels, values)"),
])
def test_partial_does_not_borrow_generic_owner_wrong_direction_api_lists_prerequisites_or_negation(point, text):
    assert assess_operation_fallback(point, [observed(text)]) is None


@pytest.mark.parametrize("point", ["pandas 时间差与分钟换算", "pandas 清洗结果导出Parquet与处理日志", "pandas 高级数据分析",
    "Python 客户数据去重与日志", "pandas 区域 Top5 条形图", "读取客户 CSV 与列检查", "pandas 不读取客户 CSV 与列检查",
    "pandas 读取CSV", "pandas 数据去重", "pandas 分组计数", "matplotlib 绘制条形图"])
def test_five_operation_grammar_does_not_infer_unrequested_actions_or_demote_an_unqualified_whole_topic(point):
    assert operation_decomposition(point) is None


def test_api_owner_alias_must_be_local_or_explicitly_imported_and_never_reassigned():
    point = "pandas 日期字段转换与异常行隔离"
    assert assess_operation_fallback(point, [observed("pandas tutorial: pd.to_datetime(values) 示例")])
    assert assess_operation_fallback(point, [observed("import pandas as pd; pd.to_datetime(values) 示例")])
    assert assess_operation_fallback(point, [observed("pandas tutorial: pd = helper; pd.to_datetime(values)")]) is None
    assert assess_operation_fallback(point, [observed("pandas教程。polars教程。pd.to_datetime(values) 示例")]) is None
    assert assess_operation_fallback(point, [observed("pd.to_datetime(values) 示例")]) is None


def test_context_action_and_ids_cannot_be_stitched_between_observations():
    point = "pandas 读取医疗 CSV 与字段检查"
    assert assess_operation_fallback(point, [observed("pandas基础", "owner"), observed("读取CSV教程", "action")]) is None
    assert assess_operation_fallback(point, [{"text": "pandas读取CSV教程", "evidence_ids": []}]) is None
    result = assess_operation_fallback(point, [observed("pandas读取CSV教程", "right"), observed("pandas导出CSV", "wrong")])
    assert result["supporting_evidence_ids"] == ["right"]


def test_decomposition_is_only_a_target_without_evidence_or_supported_status():
    target = operation_decomposition("pandas 读取任意业务 CSV 与结构校验")
    assert target["subtopics"][0]["id"] == "operation_core"
    assert target["subtopics"][1]["id"] == "operation_qualification"
    assert all("status" not in part and "evidence_ids" not in part for part in target["subtopics"])
    assert assess_operation_fallback("pandas 读取任意业务 CSV 与结构校验", []) is None


@pytest.mark.parametrize("point,text", [
    ("pandas 按设备分组计数", "pandas 不分组计数"),
    ("pandas 读取医疗 CSV 与结构检查", "pandas禁止读取CSV"),
    ("pandas 编号去重与审计", "pandas 无需去重，重复行全部保留"),
    ("pandas 日期列解析与日志", "pandas 不解析日期，保留原字符串"),
    ("Matplotlib 区域 Top5 条形图", "matplotlib 不绘制条形图"),
])
def test_each_core_action_has_a_scoped_negation_guard(point, text):
    assert assess_operation_fallback(point, [observed(text)]) is None


@pytest.mark.parametrize("point", ["pandas 禁止读取医疗CSV与结构检查", "pandas 不分组计数与审计", "pandas 无需去重与计数",
                                  "pandas 不解析时间列与日志", "Matplotlib 不绘制条形图与标签"])
def test_a_forbidden_source_requirement_never_requests_the_positive_core(point):
    assert operation_decomposition(point) is None
