"""Review or explicitly import public, revalidated MOOC observations offline.

The source and existing target paths are mandatory. Dry runs open both SQLite
files read-only and simulate the two public library tables in memory. --apply
backs up the target to a new external directory, then changes only those two
tables in one transaction. No job, query, cache or refresh record is imported.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.course_library import CourseLibrary, _timestamp, course_entry_key, course_family_key, profile_digest
from backend.app.db import Store
from backend.app.service import JobService
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_split_provider_live import scrub

POINTS = ["pandas 数据分组与聚合", "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
PUBLIC_TABLES = {"shared_mooc_courses", "shared_mooc_terms"}
COLUMNS = ("entry_key", "profile", "observed", "expires", "status", "data")
MAX_SOURCE_ROWS = 10000
MAX_ROW_BYTES = 2 * 1024 * 1024
CHAPTER_FIELDS = {"title", "url", "start_seconds", "end_seconds", "source_url", "duration_seconds",
                  "page_number", "outline_parent_index", "source", "evidence_id"}


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _cell(value):
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, float) and not math.isfinite(value):
        return {"sqlite_float": str(value)}
    return value


def connect_readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def table_names(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def table_audit(connection):
    """Order-independent row hashes and schema hashes, never private values."""
    tables = {}
    for name in sorted(table_names(connection)):
        cursor = connection.execute("SELECT * FROM " + _quoted(name))
        hashes = sorted(_hash([_cell(value) for value in row]) for row in cursor)
        tables[name] = {"row_count": len(hashes), "rows_sha256": _hash(hashes),
                        "columns_sha256": _hash([column[0] for column in cursor.description])}
    objects = {}
    for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"):
        objects[row[0] + ":" + row[1]] = {"table": row[2], "sha256": _hash(list(row))}
    return {"tables": tables, "schema_objects": objects}


def protected_audit(audit):
    return {"tables": {name: row for name, row in audit["tables"].items() if name not in PUBLIC_TABLES},
            "schema_objects": {name: row for name, row in audit["schema_objects"].items()
                               if row["table"] not in PUBLIC_TABLES}}


def contains_credentials(value, secrets):
    text = value if isinstance(value, str) else _json(value)
    return (any(secret and secret in text for secret in secrets)
            or bool(re.search(r"\btvly-[A-Za-z0-9_-]{10,}|\bBearer\s+[A-Za-z0-9._-]{10,}", text, re.I)))


def database_contains_credentials(connection, secrets):
    if any(isinstance(row[0], str) and contains_credentials(row[0], secrets)
           for row in connection.execute("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL")):
        return True
    for name in table_names(connection):
        for row in connection.execute("SELECT * FROM " + _quoted(name)):
            for value in row:
                if isinstance(value, bytes):
                    if any(secret and secret.encode() in value for secret in secrets):
                        return True
                elif isinstance(value, str) and contains_credentials(value, secrets):
                    return True
    return False


def memory_service(configured):
    """Use current service profile logic without building any external client."""
    store = Store(":memory:")
    inert = object()
    sources = {configured.search_provider, *(configured.search_provider_for(name)
                for name in ("bilibili", "icourse163"))}
    try:
        service = JobService(configured, store, provider=inert, fetcher=inert, llm=inert,
                             provider_overrides={name: inert for name in sources})
        if service.course_library is None:
            service.course_library = CourseLibrary(store, configured.shared_course_library_ttl_seconds,
                                                    configured.shared_course_library_max_candidates)
        return service
    except BaseException:
        store.close()
        raise


def _check_course_schema(connection, *, required):
    names = table_names(connection)
    if "shared_mooc_courses" not in names:
        if required:
            raise ValueError("Source has no public MOOC course table")
        # A same-named view must never become a writable library destination.
        if connection.execute("SELECT 1 FROM sqlite_schema WHERE name='shared_mooc_courses'").fetchone():
            raise ValueError("Unsupported public library schema")
        return False
    columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(shared_mooc_courses)"))
    if columns != COLUMNS:
        raise ValueError("Unsupported public library schema")
    return True


def _check_target_schema(connection):
    has_courses = _check_course_schema(connection, required=False)
    has_terms = "shared_mooc_terms" in table_names(connection)
    if has_terms:
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(shared_mooc_terms)"))
        if columns != ("term", "entry_key"):
            raise ValueError("Unsupported public term schema")
    elif connection.execute("SELECT 1 FROM sqlite_schema WHERE name='shared_mooc_terms'").fetchone():
        raise ValueError("Unsupported public term schema")
    # Existing triggers could silently write private tables when we import.
    if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='trigger' AND tbl_name IN (?,?)",
                          tuple(sorted(PUBLIC_TABLES))).fetchone():
        raise ValueError("Public library triggers are not supported")
    return has_courses, has_terms


def _read_source(connection):
    _check_course_schema(connection, required=True)
    rows = [dict(row) for row in connection.execute(
        "SELECT entry_key,profile,observed,expires,status,data FROM shared_mooc_courses ORDER BY entry_key LIMIT ?",
        (MAX_SOURCE_ROWS + 1,))]
    if len(rows) > MAX_SOURCE_ROWS:
        raise ValueError("Source exceeds bounded import size")
    return rows


def validate_rows(service, rows, secrets):
    """Re-run production observe; never trust source index or profile labels."""
    profile = service._course_library_profile()
    expected_profile = profile_digest(profile)
    library = service.course_library
    valid, reasons = [], Counter()
    for row in rows:
        reason = None
        current = time.time()
        observed, expires = _timestamp(row["observed"]), _timestamp(row["expires"])
        if row["status"] != "verified":
            reason = "not_verified"
        elif row["profile"] != expected_profile:
            reason = "profile_mismatch"
        elif (not isinstance(row["observed"], (int, float)) or not isinstance(row["expires"], (int, float))
              or observed is None or expires is None or not observed <= current < expires
              or observed + library.ttl_seconds <= current or expires <= observed
              or expires > observed + library.ttl_seconds):
            reason = "invalid_or_expired_observation"
        elif not isinstance(row["data"], str) or len(row["data"].encode()) > MAX_ROW_BYTES:
            reason = "invalid_payload_size"
        elif contains_credentials(row["data"], secrets):
            reason = "source_contains_credentials"
        else:
            try:
                payload = json.loads(row["data"])
                resource, evidence = dict(payload["resource"]), payload["evidence"]
                # Public evidence bindings use only these chapter fields.
                # Nested job/query annotations must not enter the destination.
                if isinstance(resource.get("chapters"), list):
                    resource["chapters"] = [{key: value for key, value in chapter.items() if key in CHAPTER_FIELDS}
                                            for chapter in resource["chapters"]]
                if course_entry_key(resource.get("url")) != row["entry_key"]:
                    reason = "identity_or_profile_mismatch"
                elif _timestamp(resource.get("fetched_at")) != observed:
                    reason = "fetched_at_mismatch"
                elif not library.observe(resource, evidence, profile):
                    reason = "observation_rejected"
                else:
                    saved = service.store.connection.execute(
                        "SELECT * FROM shared_mooc_courses WHERE entry_key=?", (row["entry_key"],)).fetchone()
                    if saved is None or saved["profile"] != row["profile"] or saved["observed"] != observed:
                        reason = "identity_or_profile_mismatch"
                    elif saved["status"] != "verified":
                        reason = "observation_rejected"
                    else:
                        # observe rebuilds public facts and terms; preserve an earlier
                        # source expiry instead of granting a fresh lifetime.
                        entry = dict(saved)
                        entry["expires"] = expires
                        terms = [item[0] for item in service.store.connection.execute(
                            "SELECT term FROM shared_mooc_terms WHERE entry_key=? ORDER BY term", (row["entry_key"],))]
                        valid.append({"row": entry, "terms": terms})
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                reason = "malformed_observation"
        if reason:
            reasons[reason] += 1
    return valid, dict(reasons), expected_profile


def _create_public_tables(connection):
    # Do not use Store/JobService on the target: their schema migrations can
    # create ownership, queue or refresh tables unrelated to this import.
    statements = (
        "CREATE TABLE IF NOT EXISTS shared_mooc_courses(entry_key TEXT PRIMARY KEY,profile TEXT NOT NULL,observed REAL NOT NULL,expires REAL NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS shared_mooc_fresh ON shared_mooc_courses(profile,status,expires)",
        "CREATE TABLE IF NOT EXISTS shared_mooc_terms(term TEXT NOT NULL,entry_key TEXT NOT NULL REFERENCES shared_mooc_courses(entry_key) ON DELETE CASCADE,PRIMARY KEY(term,entry_key))",
        "CREATE INDEX IF NOT EXISTS shared_mooc_terms_entry ON shared_mooc_terms(entry_key)",
    )
    for statement in statements:
        connection.execute(statement)


def _import_rows(connection, entries):
    imported = skipped = expired = 0
    for entry in entries:
        row = entry["row"]
        if row["expires"] <= time.time():
            expired += 1
            continue
        old = connection.execute("SELECT observed FROM shared_mooc_courses WHERE entry_key=?", (row["entry_key"],)).fetchone()
        if old is not None and old[0] >= row["observed"]:
            skipped += 1
            continue
        cursor = connection.execute("""INSERT INTO shared_mooc_courses VALUES(?,?,?,?,?,?)
            ON CONFLICT(entry_key) DO UPDATE SET profile=excluded.profile,observed=excluded.observed,
            expires=excluded.expires,status=excluded.status,data=excluded.data
            WHERE shared_mooc_courses.observed<excluded.observed""", tuple(row[key] for key in COLUMNS))
        if cursor.rowcount != 1:
            skipped += 1
            continue
        connection.execute("DELETE FROM shared_mooc_terms WHERE entry_key=?", (row["entry_key"],))
        connection.executemany("INSERT INTO shared_mooc_terms VALUES(?,?)", ((term, row["entry_key"]) for term in entry["terms"]))
        imported += 1
    return {"imported": imported, "skipped_newer": skipped, "expired_during_import": expired}


def _load_existing_public(connection, memory):
    present, has_terms = _check_target_schema(connection)
    if present:
        for row in connection.execute("SELECT * FROM shared_mooc_courses"):
            memory.execute("INSERT INTO shared_mooc_courses VALUES(?,?,?,?,?,?)", tuple(row))
    if has_terms:
        for row in connection.execute("SELECT term,entry_key FROM shared_mooc_terms"):
            memory.execute("INSERT INTO shared_mooc_terms VALUES(?,?)", tuple(row))
    memory.commit()


def point_lookup(service, points):
    result = []
    for index, text in enumerate(points):
        hits = service.course_library.lookup({"knowledge_point_id": "import-review-" + str(index), "text": text},
            service._course_library_profile(), limit=service.settings.shared_course_library_max_candidates)
        families, courses = set(), []
        for hit in hits:
            family = course_family_key(hit["resource"]["url"])
            if not family or family in families:
                continue
            families.add(family)
            courses.append({"entry_key": hit["entry_key"], "url": hit["resource"]["url"],
                            "title": hit["resource"]["title"]})
        result.append({"text": text, "qualified_count": len(courses), "courses": courses})
    return result


def apply_entries(target, output, entries, secrets, save):
    connection = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA foreign_keys=ON")
    backup_path = output / "target-before.sqlite3"
    try:
        connection.execute("BEGIN IMMEDIATE")
        _check_target_schema(connection)
        before = table_audit(connection)
        save("audit-before.json", before)
        if database_contains_credentials(connection, secrets):
            raise ValueError("target_contains_credentials")
        # A separate read connection can back up the committed snapshot while
        # this writer lock prevents another process from changing that snapshot.
        reader = connect_readonly(target)
        backup = sqlite3.connect(":memory:")
        try:
            reader.backup(backup)
            if table_audit(backup) != before:
                raise ValueError("backup_snapshot_mismatch")
            # SQLite backups can retain deleted values in unused page space.
            # Screen the complete snapshot before writing a backup file.
            image = backup.serialize()
            if (any(secret.encode() in image for secret in secrets)
                    or re.search(rb"\btvly-[A-Za-z0-9_-]{10,}|\bBearer\s+[A-Za-z0-9._-]{10,}", image, re.I)):
                raise ValueError("target_contains_credentials")
            with backup_path.open("xb") as handle:
                handle.write(image)
        finally:
            backup.close()
            reader.close()
        save("backup.json", {"file": backup_path.name, "sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
                              "scope": "Complete private target backup; never a public source export."})
        if entries:
            _create_public_tables(connection)
        counts = _import_rows(connection, entries)
        after = table_audit(connection)
        if protected_audit(before) != protected_audit(after):
            raise ValueError("protected_tables_changed")
        save("audit-after.json", after)
        connection.commit()
        return {**counts, "target_changed": before != after}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _paths(source, target, output):
    source, target, output = (Path(path).expanduser().resolve() for path in (source, target, output))
    for path in (source, target):
        if not path.is_file():
            raise FileNotFoundError("Source and target must be existing SQLite files")
    if source.samefile(target):
        raise ValueError("Source and target must be distinct databases")
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Output must be outside the repository")
    if output.exists():
        raise FileExistsError("Output must be a new directory")
    output.mkdir(parents=True, exist_ok=False)
    return source, target, output


def run(source, target, output, *, apply=False, configured=None, points=POINTS):
    source, target, output = _paths(source, target, output)
    configured = replace(configured or Settings.from_env(), database_path=str(target)).validate()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)

    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))

    report = {"schema_version": 1, "created_at": now(), "mode": "apply" if apply else "dry_run",
        "source": str(source), "target": str(target), "status": "blocked", "network_requests": 0,
        "llm_calls": 0, "billing_changes": False, "only_writable_tables": sorted(PUBLIC_TABLES),
        "counts": {"source_rows": 0, "validated": 0, "imported": 0, "skipped_newer": 0, "rejected": 0},
        "reasons": {}, "per_point": [], "target_changed": False, "transaction_committed": False,
        "library_active_in_current_settings": configured.shared_course_library_enabled and not configured.teaching_match_enabled,
        "precision": "unknown", "recall": "unknown"}
    save("plan.json", report)
    validator = simulator = None
    try:
        # No live source tables other than the public observation table are read.
        source_connection = connect_readonly(source)
        try:
            source_connection.execute("BEGIN")
            rows = _read_source(source_connection)
        finally:
            source_connection.close()
        validator = memory_service(configured)
        entries, reasons, profile = validate_rows(validator, rows, secrets)
        report.update(reasons=reasons, current_profile_sha256=profile)
        report["counts"].update(source_rows=len(rows), validated=len(entries), rejected=sum(reasons.values()))
        simulator = memory_service(configured)
        target_connection = connect_readonly(target)
        try:
            target_connection.execute("BEGIN")
            before = table_audit(target_connection)
            _load_existing_public(target_connection, simulator.store.connection)
        finally:
            target_connection.close()
        save("audit-before.json", before)
        simulated_counts = _import_rows(simulator.store.connection, entries)
        simulator.store.connection.commit()
        report["counts"].update(simulated_counts)
        if not apply:
            report["counts"]["would_import"] = report["counts"].pop("imported")
            report["counts"]["imported"] = 0
            report.update(status="dry_run", lookup_basis="Simulated post-import public library; target unchanged.")
            report["per_point"] = point_lookup(simulator, points)
            save("audit-after.json", before)
        else:
            applied = apply_entries(target, output, entries, secrets, save)
            report["target_changed"] = applied.pop("target_changed")
            report["counts"].update(applied)
            report.update(status="applied", transaction_committed=True,
                          lookup_basis="Read-only lookup of the committed target public library.")
            # Refresh the isolated lookup view from the committed target, not
            # the preflight simulation (a concurrent newer observation may win).
            simulator.store.connection.execute("DELETE FROM shared_mooc_terms")
            simulator.store.connection.execute("DELETE FROM shared_mooc_courses")
            simulator.store.connection.commit()
            target_connection = connect_readonly(target)
            try:
                target_connection.execute("BEGIN")
                _load_existing_public(target_connection, simulator.store.connection)
            finally:
                target_connection.close()
            report["per_point"] = point_lookup(simulator, points)
    except Exception as exc:
        # Error messages/payloads may contain credentials; only explicit codes
        # and exception types leave this process.
        allowed = {"target_contains_credentials", "backup_snapshot_mismatch", "protected_tables_changed"}
        report.update(status="applied_with_lookup_error" if report["transaction_committed"] else "blocked",
                      reason=str(exc) if str(exc) in allowed else "validation_or_transaction_failed",
                      error_type=type(exc).__name__)
        if not report["transaction_committed"]:
            report["counts"]["imported"] = 0
    finally:
        for service in (validator, simulator):
            if service is not None:
                service.store.close()
        save("summary.json", report)
    return scrub(report, secrets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing public live-test library SQLite")
    parser.add_argument("--target", type=Path, required=True, help="Explicit existing preview database")
    parser.add_argument("--output", type=Path, required=True, help="New report/backup directory outside this repository")
    parser.add_argument("--apply", action="store_true", help="Back up and transactionally import verified public observations")
    args = parser.parse_args()
    try:
        result = run(args.source, args.target, args.output, apply=args.apply)
    except Exception as exc:
        print(_json({"status": "blocked", "error_type": type(exc).__name__}))
        return 2
    print(_json(result))
    return 0 if result["status"] in {"dry_run", "applied"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
