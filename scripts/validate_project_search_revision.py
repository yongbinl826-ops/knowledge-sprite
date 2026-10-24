"""Import a retained, previously confirmed analysis into an EMPTY acceptance DB.

This does not invoke any model, HTTP request, confirmation or search. Start the
fresh acceptance runner first, then run this script against its new database.
The imported version is an unconfirmed draft; use the normal API afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.models import now
from backend.app.project_db import ProjectStore
from backend.app.project_models import AnalysisDocument, ProjectInput


class _ImportConnection(sqlite3.Connection):
    """Keep ProjectStore's nested contexts inside the one import transaction."""
    defer_context_commit = False

    def __exit__(self, *args):
        if self.defer_context_commit:
            return False
        return super().__exit__(*args)


REQUIRED_TABLES = {
    "jobs", "knowledge_points", "resources", "matches", "evidence", "search_attempts",
    "cache", "idempotency_keys", "job_consumers", "projects", "project_versions",
    "project_functions", "project_knowledge_points", "project_prerequisites",
    "project_batches", "project_point_job_mappings",
}
PROJECT_ONLY_TABLES = {
    "projects", "project_versions", "project_version_summaries", "project_functions", "project_knowledge_points", "project_prerequisites",
}


def table_counts(connection):
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    if not REQUIRED_TABLES.issubset(tables):
        raise ValueError("Target must already be initialized by the fresh acceptance runner")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", table) for table in tables):
        raise ValueError("Unexpected table name")
    return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}


def validate_source(source: Path, expected_points: int):
    raw = source.read_bytes()
    document = json.loads(raw)
    version = document["version"]
    confirmation = version["confirmation"]
    number = version["version"]
    if type(number) is not int or number < 1 or not confirmation:
        raise ValueError("Source needs a successful analysis with a confirmation snapshot")
    if confirmation["confirmation_version"] != number or document["current_version"] != number:
        raise ValueError("Source analysis and confirmation versions differ")
    input_data = ProjectInput.model_validate(version["input"]).model_dump()
    analysis = AnalysisDocument.model_validate(version["analysis"]).model_dump()
    if (confirmation["input"] != version["input"] or document["input"] != version["input"]
            or confirmation["analysis"] != version["analysis"]):
        raise ValueError("Source analysis/input differs from its immutable confirmation snapshot")
    points = analysis["knowledge_points"]
    point_ids = [point["id"] for point in points]
    selections = {point["id"]: point["selection"] for point in points}
    if len(points) != expected_points or any(value != "learn" for value in selections.values()):
        raise ValueError("This controlled search revision requires every original point to remain selected")
    if confirmation["selected_ids"] != point_ids or confirmation["selections"] != selections:
        raise ValueError("Source selection snapshot differs from the analysis")
    if not version.get("model") or not version.get("prompt_version"):
        raise ValueError("Source model and prompt provenance are required")
    return input_data, analysis, {
        "source_file": str(source.resolve()),
        "source_file_sha256": hashlib.sha256(raw).hexdigest(),
        "source_project_id": document["project_id"], "source_analysis_version": number,
        "source_confirmation_version": confirmation["confirmation_version"],
        "source_confirmed_at": confirmation["confirmed_at"],
        "source_model": version["model"], "source_prompt_version": version["prompt_version"],
        "source_analysis_sha256": hashlib.sha256(json.dumps(analysis, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "source_point_ids": point_ids,
        "analysis_reused": True, "new_model_analysis_performed": False,
        "source_confirmation_imported": False, "source_search_data_imported": False,
    }


def import_retained_analysis(source: Path, database: Path, expected_points: int = 10):
    """Write only project draft data through ProjectStore, atomically and offline."""
    source, database = source.resolve(strict=True), database.resolve(strict=True)
    if expected_points < 1 or expected_points > 24:
        raise ValueError("Expected point count must be between 1 and 24")
    input_data, analysis, provenance = validate_source(source, expected_points)
    project_id = str(uuid4())
    version = {
        "version": 1, "input": input_data, "status": "analyzed", "analysis": analysis,
        "confirmation": None, "batches": [], "budgets": None, "error": None,
        "warnings": ["本次搜课复验沿用上一轮真实模型分析；尚未确认，且本轮未重新调用项目分析模型。"],
        "created_at": now(), "model": provenance["source_model"],
        "prompt_version": provenance["source_prompt_version"], "origin": "retained_analysis",
        "search_started_at": None, "cancel_requested": False, "retained_analysis": provenance,
    }
    connection = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=10,
                                  factory=_ImportConnection)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        # Refuse a nonempty or uninitialized target before invoking persistence.
        if any(table_counts(connection).values()):
            raise ValueError("Target must be empty: no projects, jobs, results, caches or other table rows")
        persistence = ProjectStore(SimpleNamespace(connection=connection))
        connection.execute("BEGIN IMMEDIATE")
        connection.defer_context_commit = True
        try:
            before = table_counts(connection)
            if any(before.values()):
                raise ValueError("Target changed before the import transaction; import refused")
            persistence.create(project_id, input_data)
            persistence.save(project_id, version, new=True)
            restored = persistence.version(project_id, 1)
            after = table_counts(connection)
            if (restored != version or restored["confirmation"] is not None
                    or any(count for table, count in after.items() if table not in PROJECT_ONLY_TABLES)
                    or after["projects"] != 1 or after["project_versions"] != 1
                    or after["project_knowledge_points"] != expected_points):
                raise ValueError("Imported draft failed read-back or isolation checks")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Imported draft failed foreign-key integrity validation")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.defer_context_commit = False
    finally:
        connection.close()
    return {"status": "imported_unconfirmed_draft", "created_at": now(),
        "database": str(database), "project_id": project_id, "version": 1,
        "origin": "retained_analysis", "provenance": provenance,
        "before_table_counts": before, "after_table_counts": after,
        "next_step": "Confirm version 1 and submit search through the normal project API; no HTTP has been performed by this script."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Prior project-results.json export")
    parser.add_argument("--database", type=Path, required=True, help="Fresh runner's already initialized empty SQLite file")
    parser.add_argument("--output", type=Path, required=True, help="New provenance/verification JSON; existing files are refused")
    parser.add_argument("--service-url", default="http://127.0.0.1:18120", help="Recorded for the next manual API step; never contacted")
    parser.add_argument("--expected-points", type=int, default=10)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the output first so an existing report never causes a half-reported import.
    with args.output.open("x", encoding="utf-8") as stream:
        try:
            metadata = import_retained_analysis(args.source, args.database, args.expected_points)
        except Exception as error:
            json.dump({"status": "import_failed", "error_type": type(error).__name__}, stream)
            raise
        metadata["service_url"] = args.service_url.rstrip("/")
        metadata["project_api_url"] = metadata["service_url"] + "/api/projects/" + metadata["project_id"]
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"project_id": metadata["project_id"], "version": 1,
        "status": metadata["status"], "service_url": metadata["service_url"],
        "project_api_url": metadata["project_api_url"], "metadata": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
