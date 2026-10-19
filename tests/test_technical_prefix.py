"""Canonical project names and legacy raw-point owner boundaries; zero network."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import technical_prefix as prefix, ranking, service, project_search
from backend.app.models import SearchRequest
from backend.app.models import Query
from backend.app.config import Settings
from tests.test_project_followup_matching import lesson

FIXTURES = Path(__file__).parent / "fixtures/twt_recall"


@pytest.mark.parametrize("raw,canonical,owner", [
    ("Arduino按钮INPUT_PULLUP与串口监视器调试", "Arduino 按钮INPUT_PULLUP与串口监视器调试", "Arduino"),
    ("pandas读取数据与去重", "pandas 读取数据与去重", "pandas"),
    ("C++指针与引用", "C++ 指针与引用", "C++"),
    ("C#表单与校验", "C# 表单与校验", "C#"),
    ("PandasWrapper去重与计数", "PandasWrapper 去重与计数", "PandasWrapper"),
    ("foo.Arduino按钮与串口", "foo.Arduino 按钮与串口", "foo.Arduino"),
    ("ArduinoINPUT_PULLUP按钮与串口", "ArduinoINPUT_PULLUP 按钮与串口", "ArduinoINPUT_PULLUP"),
    ("Arduino 按钮与串口", "Arduino 按钮与串口", "Arduino"),
])
def test_identifier_is_complete_at_ascii_to_cjk_boundary(raw, canonical, owner):
    assert prefix.canonical_search_name(raw) == canonical
    assert prefix.leading_technical_owner(raw) == prefix.leading_technical_owner(canonical) == owner


def test_project_canonical_name_and_target_key_agree_without_rewriting_display_or_raw_concepts():
    point = {"name": "Arduino按钮INPUT_PULLUP与串口监视器调试", "technology": "Arduino",
             "concepts": ["pinMode INPUT_PULLUP", "digitalRead", "Serial.begin与Serial.println", "按钮按下为LOW"]}
    original = deepcopy(point)
    name = project_search.searchable_unit_name(point)
    targets = project_search.searchable_learning_targets({"k": point}, {"k": name})
    assert name == "Arduino 按钮INPUT_PULLUP与串口监视器调试"
    request = SearchRequest(knowledge_points=[name], learning_targets=targets)
    assert request.knowledge_points == [name] and request.learning_targets[name] == point["concepts"]
    assert point == original
    assert project_search.searchable_unit_name({**point, "name": name}) == name


def test_normalized_name_collision_never_silently_overwrites_different_concepts():
    points = {"a": {"name": "Arduino按钮", "concepts": ["digitalRead"]},
              "b": {"name": "Arduino 按钮", "concepts": ["INPUT_PULLUP"]}}
    original = deepcopy(points)
    names = {key: project_search.searchable_unit_name(point) for key, point in points.items()}
    assert names["a"] == names["b"] == "Arduino 按钮"
    with pytest.raises(project_search.SearchTargetCollision):
        project_search.searchable_learning_targets(points, names)
    assert points == original and set(points) == {"a", "b"}


def test_inserted_space_must_not_silently_truncate_a_search_target():
    raw = "Arduino" + "测" * 153
    assert len(raw) == 160
    with pytest.raises(ValueError):
        project_search.searchable_unit_name({"name": raw})


def test_explicit_ascii_api_then_chinese_conjunction_keeps_actual_owner_and_both_parts():
    raw = "Arduino按钮INPUT_PULLUP与串口监视器调试"
    plan = ranking.decompose_topic(raw)
    assert plan == ranking.decompose_topic(prefix.canonical_search_name(raw))
    assert plan["shared_context"] == ["Arduino"]
    assert [part["text"] for part in plan["subtopics"]] == ["按钮INPUT_PULLUP", "串口监视器调试"]
    assert ranking.decompose_topic("PandasWrapper去重与计数")["shared_context"] == ["PandasWrapper"]
    assert ranking.decompose_topic("foo.Arduino按钮与串口")["shared_context"] == ["foo.Arduino"]


@pytest.mark.parametrize("text", ["Arduino 分数及格率与统计", "Arduino 琴键和弦与音量", "Arduino X与门与串口"])
def test_lexical_conjunction_exceptions_are_not_split_inside_words(text):
    plan = ranking.decompose_topic(text)
    assert all(part["text"] not in {"格率", "弦", "门"} for part in plan["subtopics"])


@pytest.mark.parametrize("name", ["arduino_digital_read", "arduino_input_pullup"])
def test_retained_actual_raw_arduino_unit_receives_bounded_probe_without_extra_teaching_claim(name):
    data = json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
    point, resource, evidence = data["point"], data["resource"], data["evidence"]
    original = deepcopy(data)
    query = next(row["query"] for row in evidence if row.get("kind") == "search")
    state = {"gap_query_history": {point["knowledge_point_id"]: {query}}, "gap_probes_started": {}}
    assert resource["fetch_status"] == "not_fetched"
    assert service.JobService._targeted_catalog_probe(point, resource, evidence, state)
    assert service.JobService._gap_catalog_probe(point, resource, evidence, state)
    match = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert match is None or all(part["status"] == "unknown" for part in match["subtopic_coverage"]
                                if part["id"].startswith("learning_target_"))
    assert data == original
    for bad in ("ArduinoWrapper按钮INPUT_PULLUP与串口监视器调试", "foo.Arduino按钮INPUT_PULLUP与串口监视器调试", "Pandas按钮INPUT_PULLUP与串口监视器调试"):
        wrong = {**point, "text": bad}
        assert not service.JobService._targeted_catalog_probe(wrong, resource, evidence, state)
        assert not service.JobService._gap_catalog_probe(wrong, resource, evidence, state)
    unrelated = deepcopy(evidence)
    for row in unrelated:
        if row.get("kind") == "search": row["title"] = "011 输入上拉模式 INPUT_PULLUP"
    assert not service.JobService._targeted_catalog_probe(point, resource, unrelated, state)
    assert not service.JobService._gap_catalog_probe(point, resource, unrelated, state)
    for confirmed, started, expected in [(True, 3, True), (True, 4, False), (False, 1, True), (False, 2, False)]:
        candidate = deepcopy(point)
        if not confirmed: candidate.pop("learning_targets")
        state["gap_probes_started"] = {point["knowledge_point_id"]: set(map(str, range(started)))}
        assert service.JobService._gap_catalog_probe(candidate, resource, evidence, state) is expected


def test_confirmed_owner_is_recognized_without_space_but_not_from_foreign_namespace():
    point = {"knowledge_point_id": "p", "text": "Arduino按钮INPUT_PULLUP与串口监视器调试", "learning_targets": ["digitalRead"]}
    resource, evidence = lesson("Arduino digitalRead 函数用法教程")
    match = ranking.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert match and match["topic_evidence_status"] == "partial"
    assert next(row for row in match["subtopic_coverage"] if row["text"] == "digitalRead")["status"] == "supported"
    for name in ("ArduinoWrapper按钮与串口", "foo.Arduino按钮与串口", "Pandas按钮与串口"):
        wrong = {**point, "text": name}
        result = ranking.rank_resource(wrong, resource, evidence, SearchRequest(knowledge_points=[name]))
        assert result is None or all(row["status"] == "unknown" for row in result["subtopic_coverage"]
                                     if row["id"].startswith("learning_target_"))


@pytest.mark.asyncio
@pytest.mark.parametrize("name,domain", [("techwithtim_catalog", "www.techwithtim.net"), ("public_catalog", "www.freecodecamp.org")])
async def test_real_discover_path_forwards_only_own_confirmed_targets_to_twt_recall(name, domain):
    class RecordingDirectory:
        last_requests, last_dns_requests, last_warnings, last_discovery = [], [], [], {}
        async def search(self, query, language, limit, domains, **options):
            self.options = options
            return []
    class PrimaryTrace:
        pass
    directory = RecordingDirectory()
    directory.name = name
    project_jobs = service.JobService.__new__(service.JobService)
    project_jobs.settings, project_jobs.provider = Settings(), PrimaryTrace()
    project_jobs.public_catalog = directory if name == "public_catalog" else None
    project_jobs.twt_catalog = directory if name == "techwithtim_catalog" else None
    point, other = "pygame 游戏状态", "pygame 移动"
    request = SearchRequest(knowledge_points=[point, other], learning_targets={point: ["pygame.font 渲染文字"], other: ["K_LEFT"]})
    before = request.model_dump()
    query = Query(knowledge_point_id="p", query="pygame state", domain_filters=[domain])
    assert await project_jobs._discover(query, request, point) == []
    if name == "techwithtim_catalog":
        assert directory.options["learning_targets"] == ["pygame.font 渲染文字"]
    else:
        assert "learning_targets" not in directory.options
    assert directory.options["original_point"] == point and request.model_dump() == before
