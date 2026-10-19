"""Request-local projection reuse; actual historical replay is recorded separately."""
from copy import deepcopy
import json

import pytest

from backend.app import project_service as stage




def encoded(value):
    # No timestamp or data field is removed from the byte comparison.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ProjectRows:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.project_row = {"project_id": "p", "current_version": 1, "created_at": "fixed", "updated_at": "fixed"}

    def project(self, project_id):
        return deepcopy(self.project_row) if project_id == "p" else None

    def version(self, project_id, version):
        return deepcopy(self.data) if project_id == "p" and version == 1 else None

    def versions(self, project_id):
        return [{"version": 1, "status": self.data["status"], "created_at": "fixed"}]


class JobRows:
    def __init__(self, rows):
        self.rows, self.reads = deepcopy(rows), []

    def get_job(self, job_id):
        self.reads.append(job_id)
        return deepcopy(self.rows.get(job_id))


class CountingJobs:
    def __init__(self, results):
        self.rows, self.calls = deepcopy(results), []

    def results(self, job_id):
        self.calls.append(job_id)
        return deepcopy(self.rows.get(job_id))


def fixture(module, statuses=("completed",), *, same_job=False, result_kind="items"):
    points, batches, jobs, results = [], [], {}, {}
    for index, status in enumerate(statuses):
        pid, kid, jid = f"unit-{index}", f"point-{index}", "shared" if same_job else f"job-{index}"
        points.append({"id": pid, "name": "Knowledge unit " + str(index), "selection": "learn"})
        batches.append({"batch_id": f"batch-{index}", "project_knowledge_point_ids": [pid], "job_id": jid,
                        "status": "submitted", "mappings": [{"project_knowledge_point_id": pid, "knowledge_point_id": kid}]})
        if status is not None:
            jobs[jid] = {"job_id": jid, "status": status, "progress": {"search_requests": 2, "details_attempted": 1},
                         "warnings": ["retained"], "errors": []}
        result = results.setdefault(jid, {"job_id": jid, "groups": []})
        result["groups"].append({"knowledge_point_id": kid, "items": [], "partial_items": [], "review_items": []})
        if result_kind:
            result["groups"][-1][result_kind] = [{"resource": {"resource_id": "retained-" + kid}}]
    data = {"version": 1, "status": "running", "analysis": {"knowledge_points": points, "functions": []},
            "batches": batches, "budgets": {"reserved_detail_pages": 80}}
    project = module.ProjectService.__new__(module.ProjectService)
    project.db, project.store, project.jobs = ProjectRows(data), JobRows(jobs), CountingJobs(results)
    return project



@pytest.mark.parametrize("status,kind,expected", [("completed", "items", "completed"), ("completed", None, "no_results"),
    ("partial", "partial_items", "partial"), ("failed", None, "failed"), ("cancelled", "review_items", "partial"),
    ("timeout", "partial_items", "partial"), ("running", "partial_items", "submitted"), ("queued", None, "submitted"), (None, None, "failed")])
def test_results_reads_status_and_projects_each_job_only_once(status, kind, expected):
    project = fixture(stage, (status,), result_kind=kind)
    result = project.results("p", 1)
    assert result["points"][0]["status"] == expected
    assert project.jobs.calls == project.store.reads == ["job-0"]


@pytest.mark.parametrize("shared", [False, True])
def test_shared_or_distinct_jobs_reused_in_one_synchronous_response(shared):
    project = fixture(stage, ("partial", "partial"), same_job=shared, result_kind="partial_items")
    result = project.results("p")
    assert len(project.jobs.calls) == (1 if shared else 2) and len(project.store.reads) == 2
    assert len(result["points"]) == 2 and all(point["status"] == "partial" for point in result["points"])


def test_none_terminal_result_is_not_recomputed():
    project = fixture(stage)
    project.jobs.rows["job-0"] = None
    assert project.results("p")["points"][0]["result"] is None
    assert project.jobs.calls == ["job-0"]


def test_subsequent_request_has_fresh_status_and_content_and_independent_objects():
    project = fixture(stage, ("running",), result_kind=None)
    first = project.results("p")
    project.store.rows["job-0"]["status"] = "completed"
    project.jobs.rows["job-0"]["groups"][0]["items"] = [{"resource": {"resource_id": "new"}}]
    second = project.results("p")
    assert second["points"][0]["status"] == "completed" and first["points"][0]["status"] == "submitted"
    assert first["points"][0]["result"]["items"] == []
    assert project.jobs.calls == project.store.reads == ["job-0", "job-0"]
    assert not any("job_results" in key for key in project.__dict__)


def test_external_view_signature_and_standalone_refresh_remain_compatible():
    project = fixture(stage)
    assert encoded(project.view("p", 1)) == encoded(project.view("p"))
    data = deepcopy(project.db.data)
    project._refresh_batches(data)
    project._refresh_batches(data)
    assert project.jobs.calls == ["job-0"] * 4


def test_pending_unanalysed_and_missing_versions_keep_original_contract():
    project = fixture(stage)
    project.db.data["batches"][0].update(job_id=None, status="pending")
    assert project.results("p")["points"][0]["status"] == "pending"
    assert not project.jobs.calls and not project.store.reads
    project.db.data.update(analysis=None, batches=[])
    assert project.results("p")["points"] == []
    with pytest.raises(stage.ProjectError) as error:
        project.view("p", 99)
    assert error.value.code == "version_not_found"
