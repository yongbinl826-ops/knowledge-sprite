"""Actual SQLite/idempotency boundaries for the optional confirmed targets."""
import json
import sqlite3

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import IdempotencyConflict, JobService


def offline_service(path, store):
    # Admission/persistence only: no worker is started and no provider is called.
    settings = Settings(database_path=str(path), fetch_enabled=False,
                        official_sitemap_fallback=False, public_catalog_fallback=False,
                        shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False)
    return JobService(settings, store, provider=object(), fetcher=object(), llm=object())


def test_legacy_sqlite_request_and_hash_are_reused_for_omitted_or_explicitly_empty_targets(tmp_path):
    path = tmp_path / "pre-target-contract.sqlite3"
    original_request = {
        "knowledge_points": ["pandas 时间列解析"], "student_level": "beginner", "language": "zh",
        "project_context": "old context", "technical_version": "",
        "preferred_platforms": ["bilibili", "icourse163", "xuetangx"],
    }
    original_job = {"job_id": "old-job", "status": "completed", "phase": "done",
                    "request": original_request, "knowledge_points": [
                        {"knowledge_point_id": "old-point", "text": "pandas 时间列解析"}],
                    "warnings": []}
    original_hash = Store.cache_key("request", original_request)
    # Use an actual old schema without the later job_consumers table.
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE knowledge_points(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), text TEXT NOT NULL);
            CREATE TABLE idempotency_keys(key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id));
        """)
        connection.execute("INSERT INTO jobs VALUES(?,?,?)", ("old-job", "completed", json.dumps(original_job)))
        connection.execute("INSERT INTO knowledge_points VALUES(?,?,?)", ("old-point", "old-job", "pandas 时间列解析"))
        connection.execute("INSERT INTO idempotency_keys VALUES(?,?,?)", ("legacy-key", original_hash, "old-job"))
    store = Store(str(path))
    try:
        service = offline_service(path, store)
        for extra in ({}, {"learning_targets": {}}):
            request = SearchRequest(**{**original_request, "project_context": " old   context ", **extra})
            result = service.create(request, "legacy-key")
            assert result == {"job_id": "old-job", "status": "completed", "reused": True}
        assert store.get_job("old-job") == original_job
        assert store.idempotent_request("legacy-key")["request_hash"] == original_hash
        assert store.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert store.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_nonempty_targets_affect_actual_admission_hash_and_survive_reopen_and_interrupted_recovery(tmp_path):
    path = tmp_path / "target-contract.sqlite3"
    title = "pandas 时间列解析"
    targets = {title: ["pd.to_datetime(errors)", " 相等时长 >= 0 的边界 "]}
    request = SearchRequest(knowledge_points=[title], learning_targets=targets)
    store = Store(str(path))
    try:
        service = offline_service(path, store)
        first = service.create(request, "targets-key")
        job_id = first["job_id"]
        job = store.get_job(job_id)
        original_hash = store.idempotent_request("targets-key")["request_hash"]
        assert job["request"]["learning_targets"] == targets
        assert job["knowledge_points"][0]["learning_targets"] == targets[title]
        assert original_hash == Store.cache_key("request", job["request"])
        assert service.create(request, "targets-key")["job_id"] == job_id
        changed = SearchRequest(knowledge_points=[title], learning_targets={title: ["严格负值 < 0 的边界"]})
        with pytest.raises(IdempotencyConflict):
            service.create(changed, "targets-key")
        other = service.create(changed)
        assert other["job_id"] != job_id
        assert store.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    finally:
        store.close()
    # New targets live in existing job JSON; no lossy three-column point-table migration is needed.
    reopened = Store(str(path))
    try:
        reopened.recover()
        saved = reopened.get_job(job_id)
        assert saved["status"] == "interrupted"
        assert SearchRequest.model_validate(saved["request"]).learning_targets == targets
        assert saved["knowledge_points"][0]["learning_targets"] == targets[title]
        assert reopened.idempotent_request("targets-key")["request_hash"] == original_hash
        assert reopened.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert reopened.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()
