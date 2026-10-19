"""Offline import safeguards using temporary databases and synthetic outlines.

These tests never open the local .env, production database, or an HTTP source.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.course_library import CourseLibrary, course_entry_key, profile_digest
from backend.app.db import Store
from scripts import import_verified_mooc_library as importer
from test_course_library import observed


URL = "https://www.icourse163.org/course/OFFLINE-123"
POINT = "pandas 数据分组与聚合"
PUBLIC = {"shared_mooc_courses", "shared_mooc_terms"}


@pytest.fixture(autouse=True)
def forbid_external_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline import must not read environment credentials or send HTTP")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def snapshot(path):
    """Independent row snapshot; intentionally does not use importer auditing."""
    with closing(connect(path)) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        return {name: sorted((tuple(row) for row in connection.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr) for name in names}


def profile(config):
    service = importer.memory_service(config)
    try:
        return service._course_library_profile()
    finally:
        service.store.close()


def seed(path, config, *, timestamp, url=URL, chapters=("pandas 数据分组", "pandas 聚合"),
         title="pandas 数据分析"):
    with closing(Store(str(path))) as store:
        library = CourseLibrary(store, config.shared_course_library_ttl_seconds)
        resource, evidence = observed(chapters=chapters, title=title, url=url, timestamp=timestamp)
        assert library.observe(resource, evidence, profile(config))
        return dict(store.connection.execute("SELECT * FROM shared_mooc_courses WHERE entry_key=?",
                                            (course_entry_key(url),)).fetchone())


@pytest.fixture
def databases(tmp_path):
    config = Settings(database_path=str(tmp_path / "must-not-open-configured.sqlite3"),
        teaching_match_enabled=False, shared_course_library_enabled=True,
        mooc_gap_search_enabled=True, mooc_refresh_enabled=True,
        tavily_api_key="synthetic-tavily-credential", serper_api_key="synthetic-serper-credential",
        llm_api_key="synthetic-model-credential")
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    stamp = time.time() - 100
    source_row = seed(source, config, timestamp=stamp)
    with closing(Store(str(source))) as store:
        store.connection.execute("CREATE TABLE source_only_secret(data TEXT)")
        store.connection.execute("INSERT INTO source_only_secret VALUES('source-private-project-do-not-export')")
        store.connection.commit()
    with closing(Store(str(target))) as store:
        store.connection.execute("INSERT INTO jobs VALUES('existing-job','completed',?)",
                                 ('{"private":"target-private-project-preserve"}',))
        store.connection.execute("CREATE TABLE private_data(id INTEGER PRIMARY KEY,payload TEXT)")
        store.connection.execute("INSERT INTO private_data VALUES(1,'keep-private-data')")
        store.cache_set("existing-cache", "search", {"private": "keep-query-cache"}, 600)
    return config, source, target, source_row


def execute(databases, output, **kwargs):
    config, source, target, _ = databases
    return importer.run(source, target, output, configured=config, **kwargs)


def test_dry_run_preserves_both_database_bytes_and_only_simulates_public_tables(databases, tmp_path):
    config, source, target, _ = databases
    originals = {path: path.read_bytes() for path in (source, target)}
    before = snapshot(target)
    output = tmp_path / "dry"
    result = execute(databases, output)
    assert result["status"] == "dry_run" and result["target_changed"] is False
    assert result["counts"]["source_rows"] == result["counts"]["validated"] == result["counts"]["would_import"] == 1
    assert result["counts"]["imported"] == result["counts"]["rejected"] == 0
    assert result["network_requests"] == result["llm_calls"] == 0 and result["billing_changes"] is False
    assert snapshot(target) == before
    assert all(path.read_bytes() == original for path, original in originals.items())
    assert not Path(config.database_path).exists() and not (output / "target-before.sqlite3").exists()
    qualified = {row["text"]: row["qualified_count"] for row in result["per_point"]}
    assert qualified == {POINT: 1, "SQL 多表连接与分组查询": 0, "HTML 表单与网页结构": 0}
    assert json.loads((output / "audit-before.json").read_text(encoding="utf-8")) == json.loads((output / "audit-after.json").read_text(encoding="utf-8"))
    assert (output / "plan.json").is_file() and (output / "summary.json").is_file()
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    for private in ("source-private-project-do-not-export", "target-private-project-preserve", "keep-query-cache"):
        assert private not in report_text


def test_apply_creates_only_public_tables_preserves_profile_age_expiry_and_rebuilds_terms(databases, tmp_path):
    config, source, target, row = databases
    shorter_expiry = row["observed"] + 1800
    with closing(connect(source)) as connection:
        connection.execute("UPDATE shared_mooc_courses SET expires=?", (shorter_expiry,))
        connection.execute("DELETE FROM shared_mooc_terms")
        connection.execute("INSERT INTO shared_mooc_terms VALUES('untrusted-source-index-token',?)", (row["entry_key"],))
        connection.commit()
    original = snapshot(target)
    source_before = snapshot(source)
    result = execute(databases, tmp_path / "apply", apply=True)
    assert result["status"] == "applied" and result["counts"]["imported"] == 1
    assert result["target_changed"]
    after = snapshot(target)
    assert set(after) - set(original) == PUBLIC
    assert {name: value for name, value in after.items() if name not in PUBLIC} == original
    assert snapshot(source) == source_before
    with closing(connect(target)) as connection:
        saved = dict(connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
        terms = {item[0] for item in connection.execute("SELECT term FROM shared_mooc_terms")}
    assert saved["profile"] == row["profile"] == profile_digest(profile(config))
    assert saved["observed"] == row["observed"] and saved["expires"] == shorter_expiry
    assert saved["entry_key"] == row["entry_key"] and saved["status"] == "verified"
    assert terms and "untrusted-source-index-token" not in terms
    assert json.loads(saved["data"])["resource"]["fetched_at"] == json.loads(row["data"])["resource"]["fetched_at"]
    backup = tmp_path / "apply" / "target-before.sqlite3"
    assert backup.is_file() and snapshot(backup) == original
    digest = json.loads((backup.parent / "backup.json").read_text(encoding="utf-8"))["sha256"]
    assert digest == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert next(point for point in result["per_point"] if point["text"] == POINT)["qualified_count"] == 1


@pytest.mark.parametrize("damage", ["profile", "expired", "extended_expiry", "future", "revoked",
    "fetched_time", "wrong_key", "chapter_hash", "malformed"])
def test_invalid_source_rows_are_reported_without_becoming_fresh_or_rewriting_target(databases, tmp_path, damage):
    _, source, target, row = databases
    with closing(connect(source)) as connection:
        if damage == "profile":
            connection.execute("UPDATE shared_mooc_courses SET profile='obsolete-renderer-profile'")
        elif damage == "expired":
            connection.execute("UPDATE shared_mooc_courses SET expires=?", (time.time() - 1,))
        elif damage == "extended_expiry":
            connection.execute("UPDATE shared_mooc_courses SET expires=observed+604801")
        elif damage == "future":
            connection.execute("UPDATE shared_mooc_courses SET observed=?", (time.time() + 600,))
        elif damage == "revoked":
            connection.execute("UPDATE shared_mooc_courses SET status='revoked'")
        elif damage == "wrong_key":
            connection.execute("UPDATE shared_mooc_courses SET entry_key='mooc_wrong_identity'")
        elif damage == "malformed":
            connection.execute("UPDATE shared_mooc_courses SET data='{'")
        else:
            payload = json.loads(row["data"])
            if damage == "fetched_time":
                payload["resource"]["fetched_at"] = datetime.fromtimestamp(row["observed"] - 10, timezone.utc).isoformat()
            else:
                chapter_id = payload["resource"]["chapters"][0]["evidence_id"]
                next(item for item in payload["evidence"] if item["evidence_id"] == chapter_id)["id"] = "ev_tampered"
            connection.execute("UPDATE shared_mooc_courses SET data=?", (json.dumps(payload),))
        connection.commit()
    before = snapshot(target)
    result = execute(databases, tmp_path / "rejected")
    assert result["status"] == "dry_run"
    assert result["counts"]["rejected"] == 1 and result["counts"]["validated"] == result["counts"]["would_import"] == 0
    assert sum(result["reasons"].values()) == 1
    assert all(point["qualified_count"] == 0 for point in result["per_point"])
    assert snapshot(target) == before


def test_partial_outline_can_be_stored_but_never_qualifies_for_complete_current_point(databases, tmp_path):
    config, source, _, row = databases
    seed(source, config, timestamp=row["observed"] + 10, chapters=("pandas 数据分组",))
    result = execute(databases, tmp_path / "partial")
    assert result["counts"]["validated"] == result["counts"]["would_import"] == 1
    assert all(point["qualified_count"] == 0 for point in result["per_point"])


@pytest.mark.parametrize("revoked", [False, True])
def test_newer_target_observation_including_revocation_is_never_overwritten(databases, tmp_path, revoked):
    config, _, target, row = databases
    seed(target, config, timestamp=row["observed"] + 10, title="pandas 数据分析新观察")
    if revoked:
        with closing(Store(str(target))) as store:
            library = CourseLibrary(store)
            assert not library.observe({"url": URL, "fetch_status": "not_found",
                "fetched_at": datetime.fromtimestamp(row["observed"] + 20, timezone.utc).isoformat()}, [], profile(config))
    before = snapshot(target)
    result = execute(databases, tmp_path / "skip", apply=True)
    assert result["status"] == "applied" and not result["target_changed"]
    assert result["counts"]["imported"] == 0 and result["counts"]["skipped_newer"] == 1
    assert snapshot(target) == before
    assert snapshot(tmp_path / "skip" / "target-before.sqlite3") == before
    assert next(point for point in result["per_point"] if point["text"] == POINT)["qualified_count"] == int(not revoked)


def test_same_timestamp_is_not_reimported_and_cannot_extend_expiry(databases, tmp_path):
    _, _, target, row = databases
    execute(databases, tmp_path / "first", apply=True)
    with closing(connect(target)) as connection:
        connection.execute("UPDATE shared_mooc_courses SET expires=?", (row["observed"] + 1800,))
        connection.commit()
    before = snapshot(target)
    result = execute(databases, tmp_path / "second", apply=True)
    assert result["counts"]["skipped_newer"] == 1 and result["counts"]["imported"] == 0
    assert snapshot(target) == before


@pytest.mark.parametrize("blob", [False, True])
def test_target_credentials_block_apply_before_backup_without_leaking_keys(databases, tmp_path, blob):
    config, _, target, _ = databases
    secret = config.tavily_api_key
    with closing(connect(target)) as connection:
        connection.execute("UPDATE private_data SET payload=?", (secret.encode() if blob else secret,))
        connection.commit()
    before = snapshot(target)
    output = tmp_path / "blocked"
    result = execute(databases, output, apply=True)
    assert result["status"] == "blocked" and result["reason"] == "target_contains_credentials"
    assert result["counts"]["imported"] == 0 and not result["target_changed"]
    assert snapshot(target) == before and not (output / "target-before.sqlite3").exists()
    artifacts = json.dumps(result) + "\n" + "\n".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    for value in (config.tavily_api_key, config.serper_api_key, config.llm_api_key):
        assert value not in artifacts


def test_source_credentials_reject_only_that_row_and_are_not_exported(databases, tmp_path):
    config, source, _, row = databases
    second_url = "https://www.icourse163.org/course/OFFLINE-456"
    seed(source, config, timestamp=row["observed"], url=second_url)
    with closing(connect(source)) as connection:
        payload = json.loads(row["data"])
        payload["private_token"] = config.serper_api_key
        connection.execute("UPDATE shared_mooc_courses SET data=? WHERE entry_key=?",
                           (json.dumps(payload), row["entry_key"]))
        connection.commit()
    output = tmp_path / "mixed"
    result = execute(databases, output, apply=True)
    assert result["status"] == "applied"
    assert result["counts"]["source_rows"] == 2
    assert result["counts"]["imported"] == result["counts"]["rejected"] == 1
    assert result["reasons"] == {"source_contains_credentials": 1}
    assert all(config.serper_api_key not in path.read_text(encoding="utf-8") for path in output.glob("*.json"))


def test_wal_backup_contains_latest_committed_private_rows(databases, tmp_path):
    _, _, target, _ = databases
    with closing(connect(target)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO private_data VALUES(2,'committed-only-in-wal')")
        writer.commit()
        assert Path(str(target) + "-wal").exists()
        before = snapshot(target)
        result = execute(databases, tmp_path / "wal", apply=True)
        assert result["status"] == "applied"
        assert snapshot(tmp_path / "wal" / "target-before.sqlite3") == before
        assert snapshot(target)["private_data"] == before["private_data"]


@pytest.mark.parametrize("failure", ["exception", "protected_write"])
def test_failed_apply_rolls_back_public_and_private_writes_and_keeps_backup(databases, tmp_path, monkeypatch, failure):
    _, _, target, _ = databases
    original = importer._import_rows
    def broken(connection, entries):
        counts = original(connection, entries)
        actual_path = connection.execute("PRAGMA database_list").fetchone()[2]
        if actual_path and Path(actual_path).resolve() == target.resolve():
            connection.execute("UPDATE private_data SET payload='must-rollback'")
            if failure == "exception":
                raise RuntimeError("synthetic transaction failure")
        return counts
    monkeypatch.setattr(importer, "_import_rows", broken)
    before = snapshot(target)
    output = tmp_path / "rollback"
    result = execute(databases, output, apply=True)
    assert result["status"] == "blocked" and result["counts"]["imported"] == 0
    assert not result["target_changed"] and snapshot(target) == before
    assert snapshot(output / "target-before.sqlite3") == before
    if failure == "protected_write":
        assert result["reason"] == "protected_tables_changed"


def test_refuses_same_missing_directory_repository_and_existing_output_paths(databases, tmp_path):
    config, source, target, _ = databases
    output = tmp_path / "unused"
    before = snapshot(target)
    with pytest.raises(ValueError):
        importer.run(source, source, output, configured=config)
    with pytest.raises(FileNotFoundError):
        importer.run(source, tmp_path / "missing.sqlite3", output, configured=config)
    with pytest.raises(FileNotFoundError):
        importer.run(tmp_path, target, output, configured=config)
    with pytest.raises(ValueError):
        importer.run(source, target, importer.ROOT / "forbidden-import-artifacts", configured=config)
    output.mkdir()
    with pytest.raises(FileExistsError):
        importer.run(source, target, output, configured=config)
    assert snapshot(target) == before and not list(output.iterdir())
