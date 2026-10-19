"""Explicitly offline project/API tests. Synthetic analysis never enters production."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.main import create_app
from backend.app.models import Candidate, SearchRequest
from backend.app.project_models import AnalysisDocument, ProjectInput
from backend.app.project_service import ProjectError, ProjectService
from backend.app.service import JobService


def document(count=7):
    return AnalysisDocument.model_validate({"scope": "离线测试的本地成绩分析工具", "technical_plan": "Python 本地脚本",
        "assumptions": ["输入已有 Excel 文件"], "functions": [{"id": "f1", "name": "成绩报告",
        "original_requirement": "读取成绩，统计和导出报告", "acceptance_criteria": "输出统计表和图表"}],
        "knowledge_points": [{"id": f"k{i}", "name": f"成绩统计步骤 {i}", "description": "具体步骤",
            "function_ids": ["f1"], "why_needed": "实现统计功能", "learning_goal": "能独立完成示例",
            "necessity": "required", "prerequisite_ids": [], "learning_order": i + 1, "selection": "learn"}
            for i in range(count)]})


class OfflineAnalyzer:
    available = True
    def __init__(self, count=7):
        self.count, self.calls = count, 0
    async def analyze(self, request):
        self.calls += 1
        return document(self.count)


class EmptySearch:
    async def search(self, *args, **kwargs):
        return []


class NoFetch:
    async def enrich(self, candidate):
        raise AssertionError("No network is allowed in offline project tests")


def setup(tmp_path, **options):
    settings = Settings(database_path=str(tmp_path / "projects.sqlite3"), max_search_requests=30,
                        max_detail_pages=1, deadline_seconds=5, project_deadline_seconds=60,
                        search_min_interval_seconds=0, **options)
    store = Store(settings.database_path)
    jobs = JobService(settings, store, provider=EmptySearch(), fetcher=NoFetch())
    projects = ProjectService(settings, store, jobs, analyzer=OfflineAnalyzer())
    return settings, store, jobs, projects


async def analyzed(projects, count=7, **input_data):
    projects.analyzer.count = count
    project = projects.create(ProjectInput(name="  成绩工具  ", requirements="本地读取 Excel\n统计并导出图表", **input_data))
    result = projects.analyze(project["project_id"], 0)
    await asyncio.gather(*projects.analysis_tasks.values())
    return projects.view(result["project_id"])


async def settle(projects):
    await asyncio.wait_for(asyncio.gather(*projects.tasks.values()), 5)


async def wait_for(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("offline state did not settle")


@pytest.mark.asyncio
async def test_seven_points_batch_without_omission_refresh_and_idempotency(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    jobs.start()
    try:
        view = await analyzed(projects, 7, student_level="intermediate", language="en",
                              technical_version="Python 3.13", preferred_platforms=["bilibili"], project_context="离线验收")
        pid = view["project_id"]
        assert view["original_input"]["name"] == "  成绩工具  "
        with pytest.raises(ProjectError) as exc:
            projects.search(pid, 1)
        assert exc.value.code == "confirmation_required" and store.job_counts() == {}
        confirmed = projects.confirm(pid, 1, [])
        assert confirmed["version"]["budgets"]["batch_count"] == 2
        first = projects.search(pid, 1)
        assert [len(batch["project_knowledge_point_ids"]) for batch in first["version"]["batches"]] == [5, 2]
        assert projects.search(pid, 1)["version"]["batches"] == first["version"]["batches"]
        await settle(projects)
        result = projects.results(pid, 1)
        assert result["version"]["status"] == "no_results"
        assert len(result["points"]) == 7
        assert len({point["knowledge_point_id"] for point in result["points"]}) == 7
        assert all(point["status"] == "no_results" for point in result["points"])
        assert len(result["version"]["batches"]) == 2
        assert sum(store.job_counts().values()) == 2
        assert result["version"]["budgets"]["actual_search_requests"] <= 60
        for batch in result["version"]["batches"]:
            request = store.get_job(batch["job_id"])["request"]
            assert request["student_level"] == "intermediate" and request["language"] == "en"
            assert request["technical_version"] == "Python 3.13" and request["preferred_platforms"] == ["bilibili"]
            assert "离线验收" in request["project_context"]
        assert projects.search(pid, 1)["version"]["search_started_at"] == first["version"]["search_started_at"]
        assert len(projects.db.list()) == 1
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_edit_add_delete_rename_and_shared_selection_do_not_inherit_maps(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    jobs.start()
    try:
        view = await analyzed(projects, 3)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await settle(projects)
        edited = deepcopy(view["version"]["analysis"])
        edited["functions"].append({"id": "f2", "name": "显示图表", "original_requirement": "输出图表", "acceptance_criteria": "展示统计图"})
        edited["knowledge_points"].pop(2)
        edited["knowledge_points"][0].update(name="pandas 读取 Excel", function_ids=["f1", "f2"], selection="mastered")
        edited["knowledge_points"][1]["selection"] = "skip"
        added = deepcopy(edited["knowledge_points"][1])
        added.update(id="added", name="matplotlib 绘制柱状图", selection="learn", learning_order=3)
        edited["knowledge_points"].append(added)
        new = projects.edit(pid, 1, AnalysisDocument.model_validate(edited))
        assert new["current_version"] == 2 and new["version"]["confirmation"] is None
        assert new["version"]["batches"] == []
        assert all(point["result"] is None for point in projects.results(pid, 2)["points"])
        assert all(point["knowledge_point_id"] for point in projects.results(pid, 1)["points"])
        with pytest.raises(ProjectError) as exc:
            projects.search(pid, 2)
        assert exc.value.code == "confirmation_required"
        projects.confirm(pid, 2, [])
        projects.search(pid, 2)
        await settle(projects)
        points = projects.results(pid, 2)["points"]
        assert [point["project_knowledge_point_id"] for point in points if point["job_id"]] == ["added"]
        assert len({row["id"] for row in store.connection.execute("SELECT id FROM project_knowledge_points WHERE version=2")}) == 3
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [[], ["k0"]])
async def test_skipped_transitive_prerequisite_keeps_valid_refs_without_mandatory_ack(tmp_path, acknowledged):
    _, store, jobs, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 3)
        analysis = deepcopy(view["version"]["analysis"])
        analysis["knowledge_points"][0]["selection"] = "skip"
        analysis["knowledge_points"][1].update(selection="mastered", prerequisite_ids=["k0"])
        analysis["knowledge_points"][2]["prerequisite_ids"] = ["k1"]
        pid = view["project_id"]
        projects.edit(pid, 1, AnalysisDocument.model_validate(analysis))
        with pytest.raises(ProjectError) as exc:
            projects.confirm(pid, 2, ["missing"])
        assert exc.value.code == "invalid_acknowledgement"
        result = projects.confirm(pid, 2, acknowledged)
        confirmation = deepcopy(result["version"]["confirmation"])
        assert confirmation["selected_ids"] == ["k2"]
        assert confirmation["acknowledged_skipped_prerequisites"] == acknowledged
        assert confirmation["analysis"] == AnalysisDocument.model_validate(analysis).model_dump()
        assert result["version"]["analysis"]["knowledge_points"][0]["selection"] == "skip"
        assert projects.confirm(pid, 2, acknowledged)["version"]["confirmation"] == confirmation
        assert store.job_counts() == {}
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("option", [dict(project_max_batches=1), dict(project_max_search_requests=3), dict(project_max_detail_pages=1)])
async def test_project_budget_rejects_entire_selection_not_truncated(tmp_path, option):
    _, store, _, projects = setup(tmp_path, **option)
    try:
        view = await analyzed(projects, 7)
        with pytest.raises(ProjectError) as exc:
            projects.confirm(view["project_id"], 1, [])
        assert exc.value.code == "project_budget_exceeded"
        assert exc.value.details["budgets"]["selected_count"] == 7
        assert projects.view(view["project_id"])["version"]["confirmation"] is None
        assert store.job_counts() == {}
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_runtime_capacity_lower_than_five_and_all_mastered_no_job(tmp_path):
    _, store, jobs, projects = setup(tmp_path, max_knowledge_points=2)
    jobs.start()
    try:
        view = await analyzed(projects, 5)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        result = projects.search(pid, 1)
        assert [len(batch["project_knowledge_point_ids"]) for batch in result["version"]["batches"]] == [2, 2, 1]
        await settle(projects)
        edited = deepcopy(view["version"]["analysis"])
        for i, point in enumerate(edited["knowledge_points"]):
            point["selection"] = "mastered" if i % 2 else "skip"
        projects.edit(pid, 1, AnalysisDocument.model_validate(edited))
        projects.confirm(pid, 2, [])
        done = projects.search(pid, 2)
        assert done["version"]["status"] == "completed" and done["version"]["batches"] == []
        assert sum(store.job_counts().values()) == 3
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_cancel_pending_batches_does_not_cancel_shared_direct_job(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    try:
        first = await analyzed(projects, 7)
        pid = first["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
        before = projects.view(pid)["version"]
        job_id = before["batches"][0]["job_id"]
        shared = jobs.create(SearchRequest.model_validate(store.get_job(job_id)["request"]))
        assert shared["reused"] is True and shared["job_id"] == job_id
        cancelled = await projects.cancel(pid, 1)
        assert cancelled["version"]["status"] == "cancelled"
        assert cancelled["version"]["batches"][1]["status"] == "cancelled"
        assert store.get_job(job_id)["status"] == "queued"
        await settle(projects)
        assert sum(store.job_counts().values()) == 1
        assert projects.search(pid, 1)["version"]["status"] == "cancelled"
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_restart_recovers_pending_and_never_resubmits_interrupted_batch(tmp_path):
    settings, store, jobs, projects = setup(tmp_path)
    view = await analyzed(projects, 7)
    pid = view["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
    original_job = projects.view(pid)["version"]["batches"][0]["job_id"]
    await projects.stop()
    await jobs.stop()
    store.close()
    reopened = Store(settings.database_path)
    second_jobs = JobService(settings, reopened, provider=EmptySearch(), fetcher=NoFetch())
    second = ProjectService(settings, reopened, second_jobs, analyzer=OfflineAnalyzer())
    second_jobs.start()
    second.start()
    try:
        await settle(second)
        result = second.results(pid)
        assert result["version"]["batches"][0]["job_id"] == original_job
        assert result["version"]["batches"][0]["status"] == "interrupted"
        assert result["version"]["batches"][1]["status"] == "no_results"
        assert sum(reopened.job_counts().values()) == 2
        assert len(result["points"]) == 7
    finally:
        await second.stop()
        await second_jobs.stop()
        reopened.close()


@pytest.mark.asyncio
async def test_current_confirmation_cannot_be_bypassed_using_unstarted_old_version(tmp_path):
    _, store, _, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 2)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.edit(pid, 1, document(2))
        with pytest.raises(ProjectError) as exc:
            projects.search(pid, 1)
        assert exc.value.code == "version_conflict" and store.job_counts() == {}
        new_input = ProjectInput(name="新需求", requirements="本地只读取文件，不需要导出")
        projects.analyze(pid, 2, new_input)
        await asyncio.gather(*projects.analysis_tasks.values())
        assert projects.view(pid)["input"] == new_input.model_dump()
        assert projects.view(pid, 1)["version"]["input"]["name"] == "  成绩工具  "
        assert projects.view(pid)["original_input"]["name"] == "  成绩工具  "
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_deadline_and_changed_runtime_limits_keep_unexecuted_points_visible(tmp_path):
    settings, store, jobs, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 7)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        data = projects.db.version(pid, 1)
        data["search_started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=59)).isoformat()
        projects.db.save(pid, data)
        await settle(projects)
        result = projects.results(pid)
        assert result["version"]["status"] == "failed"
        assert {point["status"] for point in result["points"]} == {"budget_exceeded"}
        assert store.job_counts() == {}
        second = await analyzed(projects, 2)
        pid2 = second["project_id"]
        projects.confirm(pid2, 1, [])
        projects.search(pid2, 1)
        projects.settings = replace(settings, max_search_requests=31)
        await settle(projects)
        assert projects.view(pid2)["version"]["batches"][0]["error"]["code"] == "runtime_limits_changed"
        assert store.job_counts() == {}
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_global_admission_failure_is_not_retried_or_bypassed(tmp_path):
    _, store, jobs, projects = setup(tmp_path, submission_limit_per_minute=1)
    jobs.start()
    try:
        view = await analyzed(projects, 7)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await settle(projects)
        batches = projects.view(pid)["version"]["batches"]
        assert batches[0]["status"] == "no_results"
        assert batches[1]["status"] == "failed"
        assert batches[1]["error"]["code"] == "submission_rate_limited"
        assert sum(store.job_counts().values()) == 1
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_api_no_model_preserves_input_and_manual_search_still_works(tmp_path):
    settings = Settings(database_path=str(tmp_path / "api.sqlite3"), max_search_requests=1, max_detail_pages=0)
    app = create_app(settings, provider=EmptySearch(), fetcher=NoFetch())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            assert (await client.get("/api/capabilities")).json()["project_analysis"]["status"] == "unconfigured"
            for invalid in ({"name": "工具", "requirements": ""}, {"name": "工具", "requirements": "x" * 8001}):
                assert (await client.post("/api/projects", json=invalid)).status_code == 422
            raw = {"name": "成绩工具", "requirements": "本地读取 Excel\n统计并导出"}
            created = await client.post("/api/projects", json=raw)
            assert created.status_code == 201
            pid = created.json()["project_id"]
            response = await client.post(f"/api/projects/{pid}/analyze", json={"expected_version": 0})
            assert response.status_code == 202
            await asyncio.gather(*app.state.projects.analysis_tasks.values())
            result = (await client.get(f"/api/projects/{pid}/results")).json()
            assert result["version"]["status"] == "analysis_failed"
            assert result["version"]["error"]["code"] == "unconfigured"
            assert result["input"]["requirements"] == raw["requirements"] and result["points"] == []
            assert (await client.post(f"/api/projects/{pid}/search", json={"version": 1})).status_code == 409
            assert (await client.post(f"/api/projects/{pid}/edit", json={"expected_version": 1, "analysis": document(1).model_dump()})).status_code == 409
            assert (await client.post("/api/search-jobs", json={"knowledge_points": ["pandas 读取 Excel"]})).status_code == 202
            await asyncio.wait_for(app.state.service.queue.join(), 3)
            assert len((await client.get("/api/projects")).json()["projects"]) == 1


@pytest.mark.asyncio
async def test_analysis_repeated_click_does_not_repeat_model_or_version(tmp_path):
    _, store, _, projects = setup(tmp_path)
    try:
        created = projects.create(ProjectInput(name="成绩", requirements="读取 Excel 文件并计算平均分"))
        pid = created["project_id"]
        first = projects.analyze(pid, 0)
        assert projects.analyze(pid)["current_version"] == 1
        await asyncio.gather(*projects.analysis_tasks.values())
        assert projects.analyzer.calls == 1
        assert first["version"]["status"] == "analyzing"
        assert projects.view(pid)["version"]["status"] == "analyzed"
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_exclusive_queued_cancel_and_shared_project_last_consumer(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    try:
        first = await analyzed(projects, 7)
        pid = first["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
        original = projects.view(pid)["version"]["batches"][0]["job_id"]
        second = await analyzed(projects, 7)
        other_id = second["project_id"]
        projects.confirm(other_id, 1, [])
        projects.search(other_id, 1)
        await wait_for(lambda: projects.view(other_id)["version"]["batches"][0]["job_id"] is not None)
        assert projects.view(other_id)["version"]["batches"][0]["job_id"] == original
        assert projects.view(other_id)["version"]["batches"][0]["reused"] is True
        await projects.cancel(pid, 1)
        assert store.get_job(original)["status"] == "queued"
        await projects.cancel(other_id, 1)
        assert store.get_job(original)["status"] == "cancelled"
        await settle(projects)
        assert sum(store.job_counts().values()) == 1 and jobs.queue.qsize() == 0
        assert not store.release_job_consumer(original, "not-an-owner")
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_exclusive_running_cancel_stops_job_and_next_batch(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()
    class BlockingSearch:
        async def search(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
    jobs.provider = BlockingSearch()
    jobs.start()
    try:
        view = await analyzed(projects, 7)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await asyncio.wait_for(entered.wait(), 2)
        result = await projects.cancel(pid, 1)
        assert result["version"]["status"] == "cancelled" and cancelled.is_set()
        assert result["version"]["batches"][0]["status"] == "cancelled"
        assert result["version"]["batches"][1]["status"] == "cancelled"
        await settle(projects)
        assert sum(store.job_counts().values()) == 1 and jobs.worker and not jobs.worker.done()
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_existing_direct_job_is_shared_when_project_reuses_it(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 2)
        pid = view["project_id"]
        analysis = view["version"]["analysis"]
        source = view["input"]
        request = SearchRequest(knowledge_points=[point["name"] for point in analysis["knowledge_points"]],
            project_context="\n".join(part for part in [source["name"], source.get("project_context", ""), source["requirements"]] if part)[:1000],
            student_level=source["student_level"], language=source["language"],
            technical_version=source["technical_version"], preferred_platforms=source["preferred_platforms"])
        direct = jobs.create(request)
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
        assert projects.view(pid)["version"]["batches"][0]["job_id"] == direct["job_id"]
        assert analysis["technical_plan"] not in store.get_job(direct["job_id"])["request"]["project_context"]
        await projects.cancel(pid, 1)
        assert store.get_job(direct["job_id"])["status"] == "queued"
        assert store.connection.execute("SELECT consumer_key FROM job_consumers WHERE job_id=?", (direct["job_id"],)).fetchone()[0] == "manual"
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_later_batch_failure_retains_earlier_real_pipeline_results(tmp_path):
    _, store, jobs, projects = setup(tmp_path, submission_limit_per_minute=1)
    class SyntheticSearch:
        async def search(self, query, *args):
            return [Candidate(id="offline", title=query + " 视频教程", snippet=query + " 入门课程", source="explicit-offline-test",
                query=query, url="https://example.org/lesson", resource_type_hint="video", type_source="search_template")]
    class SearchOnly:
        async def enrich(self, candidate):
            return {"fetch_status": "search_only_policy", "evidence": []}
    jobs.provider, jobs.fetcher = SyntheticSearch(), SearchOnly()
    jobs.start()
    try:
        view = await analyzed(projects, 7)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await settle(projects)
        result = projects.results(pid)
        assert result["version"]["status"] == "partial"
        assert result["version"]["batches"][1]["status"] == "failed"
        assert any(point["result"] and any(point["result"].get(key) for key in ("items", "partial_items", "review_items")) for point in result["points"][:5])
        assert all(point["status"] == "failed" for point in result["points"][5:])
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_recovery_rejects_tightened_total_budget_and_keeps_all_mappings(tmp_path):
    settings, store, jobs, projects = setup(tmp_path)
    view = await analyzed(projects, 7)
    pid = view["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
    original = projects.view(pid)["version"]["batches"][0]["job_id"]
    await projects.stop()
    await jobs.stop()
    store.close()
    tightened = replace(settings, project_max_search_requests=30)
    store = Store(settings.database_path)
    jobs = JobService(tightened, store, provider=EmptySearch(), fetcher=NoFetch())
    projects = ProjectService(tightened, store, jobs, analyzer=OfflineAnalyzer())
    jobs.start()
    projects.start()
    try:
        await settle(projects)
        result = projects.results(pid)
        assert len(result["points"]) == 7
        assert result["version"]["batches"][0]["job_id"] == original
        assert result["version"]["batches"][1]["status"] == "budget_exceeded"
        assert result["version"]["batches"][1]["error"]["code"] == "project_limits_changed"
        assert sum(store.job_counts().values()) == 1
        assert store.connection.execute("SELECT COUNT(*) FROM project_point_job_mappings").fetchone()[0] == 5
        assert store.connection.execute("SELECT COUNT(*) FROM job_consumers WHERE job_id=?", (original,)).fetchone()[0] == 1
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_crash_between_job_creation_and_project_mapping_uses_persisted_idempotency(tmp_path):
    settings, store, jobs, projects = setup(tmp_path)
    view = await analyzed(projects, 2)
    pid = view["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
    data = projects.db.version(pid, 1)
    original = data["batches"][0]["job_id"]
    await projects.stop()
    # Simulate only the atomic JobService commit surviving a process failure.
    data["batches"][0].update(job_id=None, status="pending", mappings=[], reused=False)
    store.connection.execute("DELETE FROM project_point_job_mappings WHERE project_id=?", (pid,))
    projects.db.save(pid, data)
    await jobs.stop()
    store.close()
    store = Store(settings.database_path)
    jobs = JobService(settings, store, provider=EmptySearch(), fetcher=NoFetch())
    projects = ProjectService(settings, store, jobs, analyzer=OfflineAnalyzer())
    jobs.start()
    projects.start()
    try:
        await settle(projects)
        recovered = projects.view(pid)["version"]["batches"][0]
        assert recovered["job_id"] == original and recovered["reused"] is True
        assert len(recovered["mappings"]) == 2 and recovered["status"] == "interrupted"
        assert sum(store.job_counts().values()) == 1
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_long_context_uses_original_user_background_and_discloses_summary(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 1, project_context="项目背景" * 250)
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await wait_for(lambda: projects.view(pid)["version"]["batches"][0]["job_id"] is not None)
        data = projects.view(pid)["version"]
        context = store.get_job(data["batches"][0]["job_id"])["request"]["project_context"]
        source = data["confirmation"]["input"]
        original = "\n".join(part for part in [source["name"], source.get("project_context", ""), source["requirements"]] if part)
        assert len(context) <= 1000 and context == " ".join(original[:1000].split())
        assert data["analysis"]["technical_plan"] not in context
        assert any("1000" in warning for warning in data["warnings"])
        assert len(data["input"]["project_context"]) == 1000
        assert data["confirmation"]["analysis"] == view["version"]["analysis"]
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("technology,name,concepts", [
    ("pygame", "键盘长按移动挡板与边界限制", ["key.get_pressed 按键状态", "rect.clamp_ip 边界限制"]),
    ("Arduino", "串口命令缓冲", ["逐字符接收", "行结束和缓冲边界"]),
    ("JavaScript", "表单校验与 fetch 请求", ["表单字段校验", "异步请求与失败反馈"]),
])
async def test_literal_professional_name_reaches_search_without_inferred_owner_and_keeps_mapping(tmp_path, technology, name, concepts):
    _, store, jobs, projects = setup(tmp_path)
    jobs.start()
    try:
        view = await analyzed(projects, 1)
        pid = view["project_id"]
        analysis = deepcopy(view["version"]["analysis"])
        analysis["technical_plan"] = "Python + pygame + Arduino + JavaScript"
        analysis["knowledge_points"][0].update(name=name, technology=technology, concepts=concepts)
        edited = projects.edit(pid, 1, AnalysisDocument.model_validate(analysis))
        version = edited["version"]["version"]
        confirmation = projects.confirm(pid, version, [])["version"]["confirmation"]
        projects.search(pid, version)
        await settle(projects)
        result = projects.results(pid, version)
        batch = result["version"]["batches"][0]
        job = store.get_job(batch["job_id"])
        assert job["request"]["knowledge_points"] == [name]
        assert not job["request"].get("learning_targets") and not job["request"].get("learning_skills")
        assert analysis["technical_plan"] not in job["request"]["project_context"]
        assert confirmation["analysis"]["knowledge_points"][0]["technology"] == technology
        assert confirmation["analysis"]["knowledge_points"][0]["concepts"] == concepts
        assert result["points"][0]["name"] == name
        assert result["points"][0]["knowledge_point_id"] == job["knowledge_points"][0]["knowledge_point_id"]
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_hidden_technology_does_not_expand_name_but_real_name_limit_stays_enforced(tmp_path):
    from pydantic import ValidationError
    _, store, jobs, projects = setup(tmp_path)
    try:
        view = await analyzed(projects, 1)
        pid = view["project_id"]
        analysis = deepcopy(view["version"]["analysis"])
        analysis["knowledge_points"][0].update(name="长" * 160, technology="Arduino")
        edited = projects.edit(pid, 1, AnalysisDocument.model_validate(analysis))
        version = edited["version"]["version"]
        confirmed = projects.confirm(pid, version, [])
        assert confirmed["version"]["confirmation"]["search_mode"] == "professional_terms_v1"
        assert confirmed["version"]["confirmation"]["analysis"]["knowledge_points"][0]["name"] == "长" * 160
        assert confirmed["version"]["confirmation"]["analysis"]["knowledge_points"][0]["technology"] == "Arduino"
        assert store.job_counts() == {}
        too_long = deepcopy(analysis)
        too_long["knowledge_points"][0]["name"] = "长" * 161
        with pytest.raises(ValidationError):
            projects.edit(pid, version, AnalysisDocument.model_validate(too_long))
        with pytest.raises(ValidationError):
            SearchRequest(knowledge_points=["长" * 161])
        assert projects.view(pid)["current_version"] == version
        assert projects.view(pid)["version"]["analysis"]["knowledge_points"][0]["name"] == "长" * 160
        assert store.job_counts() == {}
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_api_rejects_boolean_version_and_injected_config_fields(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / "strict.sqlite3")), provider=EmptySearch(), fetcher=NoFetch(), analyzer=OfflineAnalyzer(2))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            pid = (await client.post("/api/projects", json={"name": "工具", "requirements": "读取 Excel 并计算平均分"})).json()["project_id"]
            assert (await client.post(f"/api/projects/{pid}/analyze", json={"expected_version": False})).status_code == 422
            assert (await client.post(f"/api/projects/{pid}/search", json={"version": True})).status_code == 422
            assert (await client.post(f"/api/projects/{pid}/analyze", json={"input": {"name": "工具", "requirements": "做统计", "llm_api_key": "untrusted"}})).status_code == 422
