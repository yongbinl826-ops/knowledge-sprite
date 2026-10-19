"""Offline contract tests: confirmed skills are targets, never source evidence."""
import asyncio
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.project_models import AnalysisDocument, ProjectInput
from backend.app.project_search import SearchTargetCollision, searchable_learning_targets, searchable_unit_name
from backend.app.project_service import ProjectError, ProjectService
from backend.app.service import AdmissionRejected


def test_manual_and_persisted_legacy_requests_default_to_no_invented_targets():
    historical = {"knowledge_points": ["pandas 时间列解析"], "student_level": "advanced"}
    assert SearchRequest.model_validate(historical).learning_targets == {}
    request = SearchRequest.model_validate_json(json.dumps(historical))
    assert SearchRequest.model_validate_json(request.model_dump_json()) == request


def test_targets_preserve_exact_text_and_bind_to_cleaned_search_name():
    targets = ["pd.to_datetime(errors)", "布尔条件 end < start", " 相等时间的边界判断 "]
    request = SearchRequest(knowledge_points=[" pandas  时间列解析 "],
                            learning_targets={"pandas 时间列解析": targets})
    assert request.learning_targets == {"pandas 时间列解析": targets}
    assert request.learning_targets["pandas 时间列解析"][-1].startswith(" ")
    assert not hasattr(request, "supported_subtopics")


@pytest.mark.parametrize("targets", [
    {"other": ["未选择的目标"]},
    {" pandas 时间列解析 ": ["非确切 key"]},
    {"pandas 时间列解析": []},
    {"pandas 时间列解析": [""]},
    {"pandas 时间列解析": ["  "]},
    {"pandas 时间列解析": ["文字\n换行"]},
    {"pandas 时间列解析": ["文字\t制表"]},
    {"pandas 时间列解析": ["文字\x00控制"]},
    {"pandas 时间列解析": ["文字\u202e方向控制"]},
    {"pandas 时间列解析": ["x" * 121]},
    {"pandas 时间列解析": [f"技能 {i}" for i in range(9)]},
    {"pandas 时间列解析": ["API", " api "]},
    {"pandas 时间列解析": ["ＡＰＩ", "API"]},
    {"pandas 时间列解析": ("元组不是约定的列表",)},
    {"pandas 时间列解析": [123]},
])
def test_invalid_or_unbounded_targets_are_rejected(targets):
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=["pandas 时间列解析"], learning_targets=targets)


def test_target_count_and_character_upper_bounds_are_accepted_without_splitting():
    names = [f"pandas 子任务{i}" for i in range(5)]
    targets = {name: [str(i) + "学" * 119 for i in range(8)] for name in names}
    request = SearchRequest(knowledge_points=names, learning_targets=targets)
    assert request.learning_targets == targets
    assert len(request.model_dump_json().encode("utf-8")) < 512_000


def test_total_utf8_target_budget_applies_even_with_individually_valid_fields():
    names = [str(i) + "😀" * 159 for i in range(5)]
    targets = {name: [str(i) + "😀" * 119 for i in range(8)] for name in names}
    with pytest.raises(ValidationError, match="UTF-8"):
        SearchRequest(knowledge_points=names, learning_targets=targets)


def test_even_a_selected_target_key_cannot_contain_control_characters():
    name = "pandas\x00时间"
    with pytest.raises(ValidationError, match="控制字符"):
        SearchRequest(knowledge_points=[name], learning_targets={name: ["时间解析"]})


def test_project_mapping_is_verbatim_scoped_and_does_not_mutate_analysis():
    points = {
        "k1": {"name": "真实时间计时与限帧", "technology": "pygame",
               "concepts": ["pygame.time.get_ticks 毫秒", "结束时间减开始时间", "clock.tick 限帧", "重置时更新时间基准"]},
        "k2": {"name": "未勾选单元", "technology": "pygame", "concepts": ["不应传给该批"]},
    }
    original = deepcopy(points)
    names = {"k1": searchable_unit_name(points["k1"], "pygame")}
    result = searchable_learning_targets(points, names)
    assert result == {"pygame 真实时间计时与限帧": points["k1"]["concepts"]}
    result[names["k1"]].append("只改变返回值")
    assert points == original


def test_history_without_concepts_keeps_empty_optional_mapping():
    assert searchable_learning_targets({"k1": {"name": "历史单元"}}, {"k1": "历史单元"}) == {}


def test_equal_search_names_cannot_overwrite_different_concepts():
    points = {"k1": {"concepts": ["KEYDOWN 事件"]}, "k2": {"concepts": ["长按状态"]}}
    with pytest.raises(SearchTargetCollision):
        searchable_learning_targets(points, {"k1": "pygame 输入", "k2": "pygame 输入"})
    points["k2"]["concepts"] = points["k1"]["concepts"][:]
    assert searchable_learning_targets(points, {"k1": "pygame 输入", "k2": "pygame 输入"}) == {"pygame 输入": ["KEYDOWN 事件"]}


def test_nonempty_target_changes_request_cache_identity():
    first = SearchRequest(knowledge_points=["pandas 日期时间"], learning_targets={"pandas 日期时间": ["时间解析"]})
    second = SearchRequest(knowledge_points=["pandas 日期时间"], learning_targets={"pandas 日期时间": ["相等时间边界"]})
    assert Store.cache_key("request", first.model_dump()) != Store.cache_key("request", second.model_dump())


def analysis_document():
    return AnalysisDocument.model_validate({
        "scope": "本地日期列处理", "technical_plan": "pandas 本地脚本", "assumptions": [],
        "functions": [{"id": "f1", "name": "清洗时间列", "original_requirement": "正确保留相等时间", "acceptance_criteria": "相等时间输出零分钟"}],
        "knowledge_points": [{"id": "k1", "name": "时间列解析与无效行分离", "technology": "pandas",
            "description": "区分缺失、负时间差与相等时间", "function_ids": ["f1"], "why_needed": "正确处理有效行边界",
            "learning_goal": "保留相等时间，排除严格负值", "concepts": ["pd.to_datetime(errors)", "isna 与缺失筛选", "布尔条件 end < start", "相等时间的边界判断"],
            "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}],
    })


class OfflineAnalyzer:
    async def analyze(self, request):
        return analysis_document()


class CaptureWithoutSearch:
    def __init__(self):
        self.requests = []

    def create(self, request, **kwargs):
        self.requests.append(request)
        raise AdmissionRejected("offline_capture", "Offline mapping test; no search is submitted")


async def make_project(tmp_path):
    store = Store(str(tmp_path / "targets.sqlite3"))
    jobs = CaptureWithoutSearch()
    projects = ProjectService(Settings(database_path=str(tmp_path / "targets.sqlite3")), store, jobs, analyzer=OfflineAnalyzer())
    view = projects.create(ProjectInput(name="合成时间清洗", requirements="保留相等时间并输出零分钟"))
    projects.analyze(view["project_id"], 0)
    await asyncio.gather(*projects.analysis_tasks.values())
    return store, jobs, projects, view["project_id"]


@pytest.mark.asyncio
async def test_professional_search_keeps_snapshot_name_but_omits_legacy_concepts_and_later_draft(tmp_path):
    store, jobs, projects, pid = await make_project(tmp_path)
    try:
        confirmed = projects.confirm(pid, 1, [])
        snapshot = deepcopy(confirmed["version"]["confirmation"])
        point = snapshot["analysis"]["knowledge_points"][0]
        _, version = projects._version(pid, 1)
        version["analysis"]["knowledge_points"][0]["concepts"].append("确认之后的草稿不得进入该快照")
        version["analysis"]["knowledge_points"][0]["name"] = "尚未确认的新名称"
        projects.db.save(pid, version)
        projects.search(pid, 1)
        await asyncio.gather(*projects.tasks.values())
        assert len(jobs.requests) == 1
        request = jobs.requests[0]
        assert request.learning_targets == request.learning_skills == {}
        assert request.knowledge_points == [point["name"]]
        stored = projects.db.version(pid, 1)["confirmation"]
        assert stored == snapshot and stored["search_mode"] == "professional_terms_v1"
        assert stored["analysis"]["knowledge_points"][0]["concepts"] == point["concepts"]
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_legacy_invalid_hidden_concepts_are_preserved_but_do_not_gate_name_only_search(tmp_path):
    store, jobs, projects, pid = await make_project(tmp_path)
    try:
        _, version = projects._version(pid, 1)
        version["analysis"]["knowledge_points"][0]["concepts"] = ["控制\n字符"]
        projects.db.save(pid, version)
        original = deepcopy(version["analysis"])
        confirmed = projects.confirm(pid, 1, [])
        assert confirmed["version"]["confirmation"]["analysis"] == original
        assert confirmed["version"]["confirmation"]["search_mode"] == "professional_terms_v1"
        assert not jobs.requests  # Confirmation itself never submits a search.
        projects.search(pid, 1)
        await asyncio.gather(*projects.tasks.values())
        assert len(jobs.requests) == 1
        assert jobs.requests[0].knowledge_points == [original["knowledge_points"][0]["name"]]
        assert jobs.requests[0].learning_targets == jobs.requests[0].learning_skills == {}
        assert projects.db.version(pid, 1)["analysis"] == original
        assert projects.db.version(pid, 1)["confirmation"]["analysis"] == original
    finally:
        await projects.stop()
        store.close()
