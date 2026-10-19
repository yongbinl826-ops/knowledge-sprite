"""Exercise SQLite backup, restore, additive migration and application restart.

The source is read-only, including when it has a live WAL. Every mutation is in
fresh evidence copies. Recovery scenarios are explicitly synthetic; no external
model, search, fetch or playback success is implied by this drill.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.main import create_app
from backend.app.models import SearchRequest, now
from backend.app.project_db import ProjectStore
from backend.app.project_models import AnalysisDocument, ProjectInput
from backend.app.project_service import ProjectService
from backend.app.service import JobService


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    # Do not use immutable=1: it would ignore the active source's WAL.
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def fingerprints(connection, names=None) -> dict:
    schemas = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    result = {}
    for name in sorted(schemas if names is None else names):
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [list(row) for row in connection.execute(f"SELECT * FROM {quoted}")]
        result[name] = {"schema_sha256": digest(schemas[name]), "row_count": len(rows),
                        "rows_sha256": digest(sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)))}
    return result


def check_integrity(connection) -> dict:
    result = {"integrity_check": [row[0] for row in connection.execute("PRAGMA integrity_check")],
              "foreign_key_errors": [list(row) for row in connection.execute("PRAGMA foreign_key_check")]}
    if result["integrity_check"] != ["ok"] or result["foreign_key_errors"]:
        raise RuntimeError("Copy failed SQLite integrity or foreign key checks")
    return result


def backup(source: Path, target: Path) -> dict:
    if target.exists() or target.with_name(target.name + "-wal").exists():
        raise RuntimeError("Refusing to overwrite an existing recovery database")
    started = time.monotonic()

    def progress(_status, _remaining, _total):
        if time.monotonic() - started > 30:
            raise TimeoutError("SQLite backup exceeded the drill time budget")

    reader = read_only(source)
    writer = sqlite3.connect(target)
    try:
        # One read transaction gives fingerprints and backup the same snapshot,
        # even if the live application commits new data during this operation.
        reader.execute("BEGIN")
        expected = fingerprints(reader)
        reader.backup(writer, pages=64, progress=progress, sleep=0.05)
        actual = fingerprints(writer)
        if expected != actual:
            raise RuntimeError("Backup contents differ from the source read snapshot")
        integrity = check_integrity(writer)
    finally:
        writer.close()
        reader.close()
    return {"method": "sqlite3.Connection.backup", "source_open_mode": "ro",
            "source_read_snapshot_matches_backup": True, "wal_copied_as_raw_file": False,
            "duration_seconds": round(time.monotonic() - started, 3), "tables": expected,
            "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), **integrity}


def active_wal_probe(output: Path) -> dict:
    """Prove committed WAL data is included while a writer stays connected."""
    source, target = output / "wal-probe-source.sqlite3", output / "wal-probe-backup.sqlite3"
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE recovery_probe(id INTEGER PRIMARY KEY, value TEXT)")
        writer.execute("INSERT INTO recovery_probe VALUES(1,'committed-in-wal')")
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO recovery_probe VALUES(2,'uncommitted-excluded')")
        wal = source.with_name(source.name + "-wal")
        assert wal.is_file() and wal.stat().st_size > 0
        result = backup(source, target)
        with closing(read_only(target)) as reader:
            assert reader.execute("SELECT id,value FROM recovery_probe").fetchall() == [(1, "committed-in-wal")]
        return {"fixture": "synthetic_writer_open_with_active_wal_and_uncommitted_transaction",
                "committed_wal_row_restored": True, "uncommitted_row_excluded": True,
                "raw_wal_copy_used": False, **result}
    finally:
        writer.rollback()
        writer.close()


def history(connection) -> dict:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "projects" not in tables:
        return {"projects": {}, "versions": {}}
    projects = {row[0]: {"original_input": json.loads(row[1]), "input": json.loads(row[2]), "current_version": row[3]}
                for row in connection.execute("SELECT id,original_input,input,current_version FROM projects")}
    versions = {}
    for project_id, version, raw in connection.execute("SELECT project_id,version,data FROM project_versions"):
        value = json.loads(raw)
        versions[f"{project_id}:{version}"] = {key: value.get(key) for key in
            ("input", "analysis", "confirmation", "origin", "parent_version", "prompt_version", "model")}
    return {"projects": projects, "versions": versions}


class OfflineSearch:
    """Explicit zero-result fixture; never a real upstream availability claim."""
    calls = 0

    async def search(self, *_args, **_kwargs):
        self.calls += 1
        return []


class NoFetch:
    async def enrich(self, _candidate):
        raise AssertionError("The recovery drill must not fetch network resources")


class NoAnalyzer:
    available = False

    async def analyze(self, _project):
        raise AssertionError("The recovery drill must not call a model")


async def seed_interrupted_work(path: Path) -> dict:
    settings = Settings(database_path=str(path), max_search_requests=1, max_detail_pages=0,
                        deadline_seconds=5, search_min_interval_seconds=0)
    store = Store(str(path))
    jobs = JobService(settings, store, provider=OfflineSearch(), fetcher=NoFetch())
    projects = ProjectService(settings, store, jobs, analyzer=NoAnalyzer())
    try:
        queued = jobs.create(SearchRequest(knowledge_points=["Recovery drill queued CSV input"]))["job_id"]
        running = jobs.create(SearchRequest(knowledge_points=["Recovery drill running row count"]))["job_id"]
        job = store.get_job(running)
        job.update(status="running", phase="searching")
        store.save_job(job)
        waiting = projects.create(ProjectInput(name="Recovery drill pending analysis", requirements="Read a local CSV and count rows"))
        projects.analyze(waiting["project_id"], 0)
        searchable = projects.create(ProjectInput(name="Recovery drill pending search", requirements="Read a local CSV and count rows"))
        document = AnalysisDocument.model_validate({
            "scope": "Recovery drill only", "technical_plan": "Local Python script", "assumptions": [],
            "functions": [{"id": "f1", "name": "Count CSV rows", "original_requirement": "Read a local CSV and count rows",
                           "acceptance_criteria": "Print the row count"}],
            "knowledge_points": [{"id": "k1", "name": "Python CSV file reading and row counting",
                "description": "Read one local file and count its records", "function_ids": ["f1"],
                "why_needed": "Complete the requested count", "learning_goal": "Print the number of CSV records",
                "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}]})
        data = projects._new_version(projects.db.project(searchable["project_id"]), searchable["input"],
                                     status="analyzed", analysis=document.model_dump(), origin="recovery_drill_fixture")
        projects.db.save(searchable["project_id"], data, new=True)
        projects.confirm(searchable["project_id"], 1, [])
        projects.search(searchable["project_id"], 1)
        # Cancel in-memory tasks before their first execution. Persisted states
        # intentionally remain analyzing/running, modeling a process restart.
        await projects.stop()
        expected = {"queued_job_id": queued, "running_job_id": running,
                    "analyzing_project_id": waiting["project_id"], "searching_project_id": searchable["project_id"]}
        assert store.get_job(queued)["status"] == "queued"
        assert store.get_job(running)["status"] == "running"
        assert projects.db.version(waiting["project_id"], 1)["status"] == "analyzing"
        assert projects.db.version(searchable["project_id"], 1)["status"] == "running"
        return expected
    finally:
        store.close()


async def exercise_app(path: Path, expected_history: dict, cases: dict) -> dict:
    settings = Settings(database_path=str(path), max_search_requests=1, max_detail_pages=0,
                        deadline_seconds=5, search_min_interval_seconds=0)
    provider = OfflineSearch()
    app = create_app(settings, provider=provider, fetcher=NoFetch(), analyzer=NoAnalyzer())
    statuses = []
    async with app.router.lifespan_context(app):
        pending = list(app.state.projects.tasks.values())
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 10)
        await asyncio.wait_for(app.state.service.queue.join(), 10)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
                                    base_url="http://127.0.0.1") as client:
            for project_id, old in expected_history["projects"].items():
                view = await client.get(f"/api/projects/{project_id}")
                if view.status_code != 200:
                    raise RuntimeError("Restored source project cannot be read through the API")
                for version in range(1, old["current_version"] + 1):
                    for endpoint in (f"/api/projects/{project_id}?version={version}",
                                     f"/api/projects/{project_id}/results?version={version}"):
                        response = await client.get(endpoint)
                        if response.status_code != 200:
                            raise RuntimeError("Restored historical version or result cannot be read")
                        statuses.append(response.status_code)
            for key in ("queued_job_id", "running_job_id"):
                response = await client.get(f"/api/search-jobs/{cases[key]}")
                assert response.status_code == 200 and response.json()["status"] == "interrupted"
            analysis = (await client.get(f"/api/projects/{cases['analyzing_project_id']}" )).json()["version"]
            assert analysis["status"] == "analysis_failed" and analysis["error"]["code"] == "interrupted"
            search = (await client.get(f"/api/projects/{cases['searching_project_id']}/results")).json()["version"]
            # A single allowed search out of several planned queries must keep
            # the resumed scheduler honest about its intentionally small budget.
            batch = search["batches"][0]
            assert search["status"] == "partial" and batch["status"] == "partial"
            assert batch["job_status"] == "partial" and batch["progress"]["search_requests"] == 1
            assert batch["warnings"] and not batch["errors"]
            assert (await client.get("/health")).status_code == 200
            readiness = await client.get("/health/ready")
            assert readiness.status_code == 503  # No model configured in this offline drill.
        current = history(app.state.store.connection)
        retained = {key: {name: current[key][name] for name in expected_history[key]} for key in expected_history}
        if retained != expected_history:
            raise RuntimeError("Restored source input, analysis or confirmation changed")
        integrity = check_integrity(app.state.store.connection)
    return {"source_projects_read": len(expected_history["projects"]),
            "source_versions_read": len(expected_history["versions"]), "historical_api_reads_200": len(statuses),
            "original_history_preserved": True, "original_history_sha256": digest(expected_history),
            "queued_and_running_jobs": "interrupted", "pending_analysis": "analysis_failed:interrupted",
            "pending_project_scheduler": "partial:one_request_budget_preserved_with_offline_fixture",
            "offline_search_calls": provider.calls, "real_external_calls": 0,
            "readiness_status": readiness.status_code, "process_id": os.getpid(), **integrity}


def restart_in_fresh_process(database: Path, historical: Path, cases: dict, output: Path, ordinal: int) -> dict:
    case_file = output / "synthetic-cases.json"
    if not case_file.exists():
        case_file.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    destination = output / f"restart-{ordinal}.json"
    command = [sys.executable, str(Path(__file__).resolve()), "--restart-worker", "--database", str(database),
               "--history-source", str(historical), "--case-file", str(case_file), "--report", str(destination)]
    # Each invocation exits before the next starts. No running server is stopped;
    # Windows helpers have no visible console and own only this evidence copy.
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=30,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["process_id"] != os.getpid()
    return result


def synthetic_legacy_migration(source: Path, target: Path) -> dict:
    backup(source, target)
    connection = sqlite3.connect(target)
    try:
        # Fixture only: represent a schema before the additive ownership table.
        connection.execute("DROP TABLE job_consumers")
        connection.commit()
        before = fingerprints(connection)
    finally:
        connection.close()
    store = Store(str(target))
    try:
        ProjectStore(store)
        assert fingerprints(store.connection, before) == before
        jobs = store.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        owners = store.connection.execute("SELECT COUNT(*) FROM job_consumers WHERE consumer_key='legacy'").fetchone()[0]
        assert jobs == owners
        integrity = check_integrity(store.connection)
    finally:
        store.close()
    return {"fixture": "synthetic_pre_consumer_schema_on_evidence_copy_only",
            "original_tables_unchanged": True, "legacy_ownership_rows_added": owners, **integrity}


def verify(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    if not source.is_relative_to(ROOT) or not source.is_file():
        raise ValueError("Source must be an existing database inside this workspace")
    if not any(output.is_relative_to(ROOT / folder) for folder in ("evidence", "tmp")) or output.exists():
        raise ValueError("Choose a fresh output folder under workspace evidence or tmp")
    output.mkdir(parents=True)
    report = {"checked_at": now(), "status": "running", "source": str(source.relative_to(ROOT)),
              "source_access": "read_only_sqlite_snapshot", "scope": "offline_recovery_not_upstream_acceptance",
              "files": {name: name + ".sqlite3" for name in ("snapshot", "restored", "exercise", "legacy")}}
    report_path = output / "verification.json"
    try:
        snapshot, restored, exercise, legacy = (output / f"{name}.sqlite3" for name in ("snapshot", "restored", "exercise", "legacy"))
        report["active_wal_probe"] = active_wal_probe(output)
        report["backup"] = backup(source, snapshot)
        report["restore"] = backup(snapshot, restored)
        with closing(read_only(restored)) as reader:
            expected = history(reader)
            before = fingerprints(reader)
        store = Store(str(restored))
        try:
            ProjectStore(store)
            after = fingerprints(store.connection, before)
            assert before == after
            report["restored_migration"] = {"existing_tables_unchanged": True, **check_integrity(store.connection)}
        finally:
            store.close()
        backup(restored, exercise)
        cases = asyncio.run(seed_interrupted_work(exercise))
        report["synthetic_recovery_cases"] = cases
        report["restart_execution"] = "two_separate_python_processes_with_new_application_instances"
        report["first_restart"] = restart_in_fresh_process(exercise, restored, cases, output, 1)
        with closing(read_only(exercise)) as reader:
            stable = fingerprints(reader)
        report["second_restart"] = restart_in_fresh_process(exercise, restored, cases, output, 2)
        with closing(read_only(exercise)) as reader:
            assert stable == fingerprints(reader)
        report["second_restart_idempotent"] = True
        report["legacy_migration"] = synthetic_legacy_migration(exercise, legacy)
        report["status"] = "passed"
        return report
    except Exception as exc:
        report.update(status="failed", failure_type=type(exc).__name__)
        raise
    finally:
        report["finished_at"] = now()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data" / "preview.sqlite3")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--restart-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--database", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--history-source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--case-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.restart_worker:
        paths = (args.database, args.history_source, args.case_file, args.report)
        if any(path is None or not any(path.resolve().is_relative_to(ROOT / folder)
                                      for folder in ("evidence", "tmp")) for path in paths):
            raise ValueError("Restart worker paths must remain under workspace evidence or tmp")
        if args.report.exists():
            raise ValueError("Refusing to overwrite restart evidence")
        with closing(read_only(args.history_source)) as reader:
            expected = history(reader)
        cases = json.loads(args.case_file.read_text(encoding="utf-8"))
        result = asyncio.run(exercise_app(args.database, expected, cases))
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        sys.exit(0)
    if args.output is None:
        parser.error("--output is required for a recovery drill")
    result = verify(args.source, args.output)
    print(json.dumps({"status": result["status"], "report": str(args.output / "verification.json"),
                      "source_projects_read": result["first_restart"]["source_projects_read"],
                      "source_versions_read": result["first_restart"]["source_versions_read"],
                      "second_restart_idempotent": True, "real_external_calls": 0}, ensure_ascii=False))
