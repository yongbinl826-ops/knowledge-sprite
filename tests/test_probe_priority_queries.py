from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.probe_priority import has_literal_identifier, probe_api_priority
from backend.app.queries import gap_query_candidates


def request(text, targets):
    return SearchRequest(knowledge_points=[text], learning_targets={text: targets}, preferred_platforms=["bilibili"], language="zh")


def test_actual_web_focus_target_moves_before_generic_tab_enter_with_same_budget():
    fixture = json.loads((Path(__file__).parent / "fixtures/probe_priority_web_r7.json").read_text(encoding="utf-8"))
    point = fixture["point"]
    req = request(point["text"], point["learning_targets"])
    original = deepcopy(req.model_dump())
    queries = gap_query_candidates(point["knowledge_point_id"], point["text"], req, point["learning_targets"])
    assert queries[0].query == "CSS focus visible 样式 视频教程"
    assert "Tab 聚焦顺序" in queries[1].query
    assert "Enter 空格触发原生按钮" in queries[2].query
    assert len(queries) <= 6
    assert req.model_dump() == original
    title = fixture["candidate_trace_first6"][0]["title"]
    evidence = [{"kind": "search", "source": "searxng", "knowledge_point_id": point["knowledge_point_id"], "title": title}]
    assert probe_api_priority(point, evidence, owner="CSS", owner_gate_passed=True) == (1, 0)
    assert "Tab" not in title and "Enter" not in title  # never claim those targets from focus spelling


@pytest.mark.parametrize("identifier", ["lib.method() 参数", "millis() 定时", "value_counts 去重", "digitalRead 输入", "focus-visible 样式", "custom-pseudo 技能"])
def test_generic_identifier_shapes_get_stable_first_slice_without_api_vocabulary(identifier):
    text = "UnseenKit 项目任务"
    targets = ["先了解任务", identifier, "后续验证"]
    queries = gap_query_candidates("unit", text, request(text, targets), targets)
    assert has_literal_identifier(identifier)
    first = queries[0].query
    assert "先了解任务" not in first and "后续验证" not in first
    assert len(queries) <= 6


def test_no_specific_identifier_keeps_original_part_order():
    text = "Tool 项目任务"
    targets = ["先检查显示", "再观察结果", "最后记录现象"]
    queries = gap_query_candidates("unit", text, request(text, targets), targets)
    assert [q.query for q in queries[:3]] == ["Tool " + x + " 视频教程" for x in targets]


def test_only_exact_confirmed_raw_target_gets_priority_before_safe_part():
    text = "Tool 项目任务"
    targets = ["普通检查", "exact.method() 参数"]
    missing = ["普通检查", "unknown.method() 参数", "Exact.method 参数"]
    queries = gap_query_candidates("unit", text, request(text, targets), missing)
    assert queries[0].query == "Tool 普通检查 视频教程"
    assert not any("unknown.method" in q.query for q in queries)


def test_url_engine_filters_remain_effective_after_identifier_sorting():
    text = "Tool 项目任务"
    targets = ["正常观察", "https://evil.invalid/api.method", "site:evil.invalid method()", "filetype:pdf api.method()", "method() !bang"]
    queries = gap_query_candidates("unit", text, request(text, targets), targets)
    assert queries
    assert all("evil.invalid" not in q.query and "filetype:pdf" not in q.query and "!bang" not in q.query for q in queries)
    assert all("正常观察" in q.query for q in queries)


def test_four_parts_six_queries_caps_and_original_target_unknown_contract_unchanged():
    text = "Tool 项目任务"
    targets = [f"method_{i}() 参数" for i in range(6)]
    req = request(text, targets)
    before = deepcopy(req.model_dump())
    queries = gap_query_candidates("unit", text, req, targets)
    assert len(queries) <= 6
    assert all(not any(f"method_{i}" in q.query for i in (4, 5)) for q in queries)
    assert req.model_dump() == before
    assert all("status" not in q.model_dump() and "evidence_ids" not in q.model_dump() for q in queries)


def test_identifier_title_not_foreign_namespace_or_public_directory_hint():
    point = {"knowledge_point_id": "unit", "learning_targets": ["lib.method() 参数", "focus-visible 样式"]}
    for title in ["tool other.method", "tool focus-visible-extra", "tool notfocus-visible"]:
        ev = [{"kind": "search", "knowledge_point_id": "unit", "source": "searxng", "title": title}]
        assert probe_api_priority(point, ev, owner="tool", owner_gate_passed=True) == (0, 0)
    ev = [{"kind": "search", "knowledge_point_id": "unit", "source": "techwithtim_catalog", "title": "tool focus-visible"}]
    assert probe_api_priority(point, ev, owner="tool", owner_gate_passed=True) == (0, 0)
