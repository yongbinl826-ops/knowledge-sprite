from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app import project_search, project_service, ranking
from backend.app.models import SearchRequest
from backend.app.technical_prefix import leading_technical_owner
from tests.test_project_followup_matching import lesson


FIXTURE = Path(__file__).parent / "fixtures/project_owner/dashboard-v1.json"


def retained():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("technology,name,expected", [
    ("Streamlit", "groupby 汇总与 Streamlit 条形图", "Streamlit groupby 汇总与 Streamlit 条形图"),
    ("pandas", "groupby 汇总与 pandas 数据表", "pandas groupby 汇总与 pandas 数据表"),
    ("Bevy", "render 渲染与 Bevy 场景", "Bevy render 渲染与 Bevy 场景"),
    ("C++", "vector 容器与 C++ 迭代", "C++ vector 容器与 C++ 迭代"),
    ("Streamlit", "Streamlit 条形图", "Streamlit 条形图"),
    ("pandas", "PANDAS 数据表", "PANDAS 数据表"),
    ("Streamlit", "StreamlitWrapper 条形图", "Streamlit StreamlitWrapper 条形图"),
    ("Streamlit", "foo.Streamlit 条形图", "Streamlit foo.Streamlit 条形图"),
    ("Streamlit", "Streamlit.app 条形图", "Streamlit Streamlit.app 条形图"),
])
def test_explicit_single_technology_is_the_exact_leading_owner_without_changing_raw_data(technology, name, expected):
    point = {"name": name, "technology": technology, "concepts": ["原始概念"]}
    before = deepcopy(point)
    actual = project_search.searchable_unit_name(point)
    assert actual == expected and leading_technical_owner(actual).casefold() == technology.casefold()
    assert point == before
    assert project_search.searchable_unit_name({**point, "name": actual}) == actual


def test_actual_foreign_groupby_card_is_withdrawn_by_the_correct_search_owner():
    fixture = retained(); source = fixture["sources"]["foreign_groupby"]
    before = deepcopy(fixture)
    old = source["stored_point"]
    request = SearchRequest.model_validate(source["request"])
    old_match = ranking.rank_resource(old, source["resource"], source["evidence"], request)
    assert old_match and next(row for row in old_match["subtopic_coverage"] if row["text"] == "groupby 聚合")["status"] == "supported"
    point = {**old, "text": project_search.searchable_unit_name(fixture["point"])}
    assert point["text"].startswith("Streamlit ")
    assert ranking.rank_resource(point, source["resource"], source["evidence"], request) is None
    assert fixture == before


@pytest.mark.parametrize("tool,foreign,action", [("Streamlit", "Excel", "groupby 聚合"),
    ("pandas", "Excel", "groupby 聚合"), ("Bevy", "Unity", "render 渲染"),
    ("Streamlit", "pandas", "filter 筛选")])
def test_shared_function_names_never_borrow_a_foreign_tool(tool, foreign, action):
    raw = {"name": action + " 与 " + tool + " 项目", "technology": tool, "concepts": [action]}
    point = {"knowledge_point_id": "p", "text": project_search.searchable_unit_name(raw), "learning_targets": raw["concepts"]}
    resource, evidence = lesson(foreign + " " + action + " 教程")
    result = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result is None or all(row["status"] == "unknown" for row in result["subtopic_coverage"] if row["id"].startswith("learning_target_"))


def service_for(fixture):
    raw = fixture["project_results"]
    groups = {}
    for row in raw["points"]:
        if row.get("result"):
            groups.setdefault(row["job_id"], {"groups": []})["groups"].append(row["result"])
    service = project_service.ProjectService.__new__(project_service.ProjectService)
    service.view = lambda *args, **kwargs: deepcopy(raw)
    service.jobs = SimpleNamespace(results=lambda job_id: groups[job_id])
    return service, groups


def test_actual_saved_dashboard_result_is_a_read_only_idempotent_scope_projection():
    fixture = retained(); service, groups = service_for(fixture)
    before = deepcopy((fixture, groups))
    raw_point = next(row for row in fixture["project_results"]["points"] if row["project_knowledge_point_id"] == "k5")
    assert len(raw_point["result"]["partial_items"]) == 5
    first = service.results(fixture["project_results"]["project_id"], 1)
    second = service.results(fixture["project_results"]["project_id"], 1)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)
    result = next(row for row in first["points"] if row["project_knowledge_point_id"] == "k5")
    assert result["status"] == "scope_mismatch"
    assert result["result"]["scope_status"] == "mismatch"
    assert "重新检索" in result["result"]["scope_notice"]
    for key in ("items", "partial_items", "review_items", "platform_items", "partial_platform_items", "review_platform_items"):
        assert not result["result"][key]
    assert all(row["status"] == "unknown" for row in result["result"]["collection_coverage"]["subtopics"])
    assert (fixture, groups) == before


def test_correct_explicit_scope_remains_unchanged_and_historic_length_failure_does_not_break_reads():
    fixture = retained(); fixed = project_search.searchable_unit_name(fixture["point"])
    raw = fixture["project_results"]
    row = next(row for row in raw["points"] if row["project_knowledge_point_id"] == "k5")
    row["result"]["text"] = fixed
    service, _ = service_for(fixture)
    result = service.results(raw["project_id"], 1)
    observed = next(p for p in result["points"] if p["project_knowledge_point_id"] == "k5")
    assert observed["result"] == row["result"] and observed["status"] != "scope_mismatch"
    assert json.dumps(result, ensure_ascii=False, sort_keys=True) == json.dumps(raw, ensure_ascii=False, sort_keys=True)
    unit = next(p for p in raw["version"]["analysis"]["knowledge_points"] if p["id"] == "k5")
    unit["name"] = "长" * 145 + " Streamlit "
    row["result"]["text"] = "groupby 汇总"
    service, _ = service_for(fixture)
    assert next(p for p in service.results(raw["project_id"], 1)["points"] if p["project_knowledge_point_id"] == "k5")["status"] == "scope_mismatch"


@pytest.mark.parametrize("stored_text", ["Streamlit", "streamlit", " Streamlit "])
def test_complete_single_word_owner_is_a_legal_unchanged_historic_scope(stored_text):
    fixture = retained(); raw = fixture["project_results"]
    unit = next(p for p in raw["version"]["analysis"]["knowledge_points"] if p["id"] == "k5")
    unit["name"] = "Streamlit"
    row = next(p for p in raw["points"] if p["project_knowledge_point_id"] == "k5")
    row["name"] = "Streamlit"
    row["result"]["text"] = stored_text
    service, groups = service_for(fixture)
    before = deepcopy((fixture, groups))
    result = service.results(raw["project_id"], 1)
    assert json.dumps(result, ensure_ascii=False, sort_keys=True) == json.dumps(raw, ensure_ascii=False, sort_keys=True)
    assert (fixture, groups) == before


def test_new_canonical_collision_rejects_distinct_concepts_and_length_guard_is_not_truncated():
    points = {"a": {"name": "groupby 与 Streamlit 图表", "technology": "Streamlit", "concepts": ["groupby"]},
              "b": {"name": "Streamlit groupby 与 Streamlit 图表", "technology": "Streamlit", "concepts": ["bar_chart"]}}
    names = {key: project_search.searchable_unit_name(point) for key, point in points.items()}
    with pytest.raises(project_search.SearchTargetCollision): project_search.searchable_learning_targets(points, names)
    with pytest.raises(ValueError): project_search.searchable_unit_name({"name": "长" * 150 + " Streamlit", "technology": "Streamlit"})


def test_actual_own_audio_self_report_adds_only_a_bound_quality_notice():
    source = retained()["sources"]["own_audio"]
    before = deepcopy(source)
    notice = ranking.source_scope_notice(source["resource"], source["evidence"])
    assert "作者自述" in notice and "音频存在问题" in notice and "未验证播放" in notice
    assert "后续可能提供完整版" in notice and "未核实该版本的发布情况" in notice
    assert "无效" not in notice and source == before
    for mutation in ("wrong-url", "wrong-provenance-url", "tampered-description", "search-kind", "not-page-verified", "related-only", "another-video", "repair-prose", "negative"):
        resource, evidence = deepcopy((source["resource"], source["evidence"]))
        eid = resource["field_provenance"]["description"]["evidence_id"]
        row = next(e for e in evidence if e["evidence_id"] == eid)
        if mutation == "wrong-url": row["url"] = "https://example.org/other"
        elif mutation == "wrong-provenance-url": resource["field_provenance"]["description"]["url"] = "https://example.org/other"
        elif mutation == "tampered-description": resource["description"] += " changed"
        elif mutation == "search-kind": row["kind"] = "search"
        elif mutation == "not-page-verified": resource["video_evidence_status"] = "search_discovered"
        else:
            text = {"related-only": "本课音频正常。相关视频：音频坏了 不想录了", "another-video": "另一个视频音频坏了。",
                    "repair-prose": "音频坏了时如何修复。", "negative": "本视频音频没有损坏。"}[mutation]
            resource["description"] = row["text"] = text
        assert ranking.source_scope_notice(resource, evidence) == ""


def test_real_streamlit_and_pandas_sources_keep_same_owner_partial_support():
    fixture = retained(); streamlit = fixture["sources"]["own_audio"]
    point = streamlit["stored_point"]
    assert leading_technical_owner(point["text"]).casefold() == "streamlit"
    match = ranking.rank_resource(point, streamlit["resource"], streamlit["evidence"], SearchRequest.model_validate(streamlit["request"]))
    assert match and match["topic_evidence_status"] == "partial"

    assert "音频存在问题" in match["recommendation_reason"]
    pandas = json.loads((Path(__file__).parent / "fixtures/project_owner/pandas-group-count.json").read_text(encoding="utf-8"))
    raw = {"name": pandas["point"]["text"], "technology": "pandas", "concepts": pandas["point"].get("learning_targets", [])}
    assert project_search.searchable_unit_name(raw) == pandas["point"]["text"]
    match = ranking.rank_resource(pandas["point"], pandas["resource"], pandas["evidence"], SearchRequest(knowledge_points=[raw["name"]], **pandas["request"]))
    assert match and match["topic_evidence_status"] == "partial"



@pytest.mark.parametrize("technology,name,expected", [
    ("pandas + Streamlit", "pandas + Streamlit 分组与绘图", "pandas + Streamlit 分组与绘图"),
    ("pandas + Streamlit", "分组与 pandas + Streamlit 绘图", "pandas + Streamlit 分组与 pandas + Streamlit 绘图"),
])
def test_existing_explicit_multi_tool_title_contract_is_preserved_without_guessing_one_owner(technology, name, expected):
    assert project_search.searchable_unit_name({"name": name, "technology": technology}) == expected


@pytest.mark.parametrize("text,expected", [
    ("后面应该会有完整版", True), ("后续会提供完整版。", True), ("以后会发布完整版。", True),
    ("后续会扩展功能。", False), ("后面不会有完整版。", False), ("后续不打算提供完整版。", False),
    ("后续会提供完整版，已经完成。", False), ("后续完整版已经发布。", False),
    ("完整版已经发布。后面会有完整版。", False), ("后面不一定会有完整版。", False),
    ("另一个视频后续会提供完整版。", False),
    ("如何在后续上传完整版教程。", False), ("修复音频后后续会提供完整版教程。", False),
    ("本课已经完整。相关视频：后续会提供完整版。", False),
])
def test_future_complete_version_is_only_an_own_bound_source_self_report(text, expected):
    source = retained()["sources"]["own_audio"]
    resource, evidence = deepcopy((source["resource"], source["evidence"]))
    eid = resource["field_provenance"]["description"]["evidence_id"]
    row = next(e for e in evidence if e["evidence_id"] == eid)
    resource["description"] = row["text"] = text
    before = deepcopy((resource, evidence))
    notice = ranking.source_scope_notice(resource, evidence)
    assert ("后续可能提供完整版" in notice) is expected
    assert (resource, evidence) == before

