import importlib.util
import json
from pathlib import Path

import pytest

from backend.app import probe_priority as MOD


def point(targets):
    return {"knowledge_point_id": "unit", "learning_targets": targets}


def score(title, targets, *, owner="tool", **fields):
    return MOD.probe_api_priority(point(targets), [{"kind": "search", "knowledge_point_id": "unit", "title": title, **fields}], owner=owner, owner_gate_passed=True)


def test_actual_retained_r7_gap_trace_prioritizes_literal_operation_within_same_budget():
    fixture = json.loads((Path(__file__).parent / "fixtures/probe_priority_r7.json").read_text(encoding="utf-8"))
    candidates = fixture["candidate_trace_first6"]
    p = fixture["point"]
    original_targets = list(p["learning_targets"])
    scores = [(x["title"], MOD.probe_api_priority(p, [{"kind": "search", "knowledge_point_id": p["knowledge_point_id"], "title": x["title"]}], owner="pandas", owner_gate_passed=True)) for x in candidates]
    ranked = sorted(scores, key=lambda x: (-x[1][0], -x[1][1]))
    assert ranked[0][0] == "Python pandas.to_datetime函数方法的使用"
    assert ranked[0][1] == (0, 1)  # operation spelling, not a pd/pandas teaching alias
    assert all(value == (0, 0) for title, value in scores if title != ranked[0][0])
    assert len(ranked[:2]) == 2  # can keep the same two remaining probe slots
    assert p["learning_targets"] == original_targets


@pytest.mark.parametrize("title", ["pandas syntax errors", "Pandas Tutorial DataFrames in Python", "pandas.to_datetime_extra", "pandas fake_to_datetime", "Pandas numpy.to_datetime", "tool foo.to_datetime"])
def test_broad_or_different_identifier_does_not_receive_target_priority(title):
    assert score(title, ["pd.to_datetime(errors)"], owner="pandas") == (0, 0)


@pytest.mark.parametrize("title,targets,owner", [
    ("Arduino digitalRead 函数", ["digitalRead"], "Arduino"),
    ("JavaScript Date.now() 时间戳", ["Date.now() 与绝对截止时间"], "JavaScript"),
    ("pygame time.get_ticks", ["pygame.time.get_ticks 毫秒"], "pygame"),
    ("Arduino millis()", ["millis()非阻塞定时采样"], "Arduino"),
])
def test_multiple_tools_literal_api_spelling(title, targets, owner):
    assert score(title, targets, owner=owner) > (0, 0)


def test_query_snippet_other_point_page_and_unpassed_gate_cannot_supply_priority():
    p = point(["tool.method()"])
    e = [{"kind": "search", "knowledge_point_id": "unit", "title": "tool course", "query": "tool.method", "snippet": "tool.method"}]
    assert MOD.probe_api_priority(p, e, owner="tool", owner_gate_passed=True) == (0, 0)
    assert MOD.probe_api_priority(p, [{**e[0], "title": "tool.method", "knowledge_point_id": "other"}], owner="tool", owner_gate_passed=True) == (0, 0)
    assert MOD.probe_api_priority(p, [{**e[0], "title": "tool.method", "kind": "page"}], owner="tool", owner_gate_passed=True) == (0, 0)
    assert MOD.probe_api_priority(p, [{**e[0], "title": "tool.method"}], owner="tool", owner_gate_passed=False) == (0, 0)


def test_index_false_parameters_and_numbers_are_not_coverage_outputs():
    p = point(["DataFrame.to_csv(index=False)", "random(2000, 5001)范围"])
    original = json.dumps(p, sort_keys=True)
    e = [{"kind": "search", "knowledge_point_id": "unit", "title": "tool to_csv and random"}]
    result = MOD.probe_api_priority(p, e, owner="tool", owner_gate_passed=True)
    assert result == (1, 1)
    assert json.dumps(p, sort_keys=True) == original
    assert isinstance(result, tuple)  # no supported/index/2000..5001 claim returned


def test_legacy_empty_targets_and_generic_prose_do_not_change_order():
    assert score("CSV HTML 文件读写", ["CSV 导出", "HTML 页面结构"]) == (0, 0)
    assert MOD.probe_api_priority({"knowledge_point_id": "unit"}, [], owner="tool", owner_gate_passed=True) == (0, 0)
