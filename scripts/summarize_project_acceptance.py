"""Read-only evidence summary for this turn's real, unseeded acceptance run."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/project-analysis-v1-20261017"
LIVE = OUT / "live"


def main():
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    submitted = read(LIVE / "submitted.json")
    job_id = submitted["job_id"]
    job, results = read(LIVE / "manual-job.json"), read(LIVE / "manual-results.json")
    connection = sqlite3.connect((LIVE / "live.sqlite3").as_uri() + "?mode=ro", uri=True)
    resources = [json.loads(row[0]) for row in connection.execute("SELECT data FROM resources WHERE job_id=?", (job_id,))]
    ledger, invalid = [], []
    for resource in resources:
        evidence = {item["evidence_id"]: item for row in connection.execute("SELECT data FROM evidence WHERE job_id=? AND resource_id=?", (job_id, resource["resource_id"])) if (item := json.loads(row[0]))}
        for index, chapter in enumerate(resource["chapters"]):
            source = evidence.get(chapter.get("evidence_id"), {})
            try:
                observed = json.loads(source.get("text", "null"))
            except json.JSONDecodeError:
                observed = None
            consistent = (source.get("kind") == "catalog" and source.get("field") == f"chapters.{index}" and
                          isinstance(observed, dict) and all(chapter.get(field) == observed.get(field)
                          for field in ("title", "url", "start_seconds", "end_seconds", "duration_seconds")))
            record = {"resource_id": resource["resource_id"], "course_title": resource["title"], "course_url": resource["url"],
                      "chapter": chapter, "source_url": source.get("url"), "evidence_consistent": consistent}
            ledger.append(record)
            if not consistent:
                invalid.append(record)
    jobs_count = connection.execute("SELECT count(*) FROM jobs").fetchone()[0]
    project_batches = connection.execute("SELECT count(*) FROM project_batches").fetchone()[0]
    connection.close()
    events = [json.loads(line) for line in (LIVE / "jobs" / job_id / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    responses = [event for event in events if event["event_type"] == "http_response_body"]
    warnings = [warning for attempt in results["search_attempts"] for warning in (attempt.get("upstream_warnings") or [])]
    manifest = read(LIVE / "run.json")
    summary = {
        "scope": "real unavailable-model project persistence plus separate manual live search; not a completed AI project chain",
        "project_id": submitted["project_id"], "job_id": job_id,
        "real_model_analysis": "not_run_unconfigured", "real_project_full_chain": "not_completed",
        "database_job_count": jobs_count, "project_batch_count": project_batches,
        "search_status": job["status"], "search_requests": job["progress"]["search_requests"],
        "logical_query_statuses": dict(Counter(item["status"] for item in results["search_attempts"])),
        "source_warnings": warnings, "candidate_count": job["progress"]["candidates_discovered"],
        "resource_count": len(resources), "details_attempted": job["progress"]["details_attempted"],
        "fetched_resources": sum(item["fetch_status"] == "fetched" for item in resources),
        "recorded_http_response_statuses": dict(Counter(f"{item['request_kind']}:{item['http_status']}" for item in responses)),
        "chapter_count": len(ledger), "chapter_evidence_consistent": not invalid,
        "ui_recommended_count": sum(len(group["items"]) for group in results["groups"]),
        "search_cache_hits": sum(bool(item.get("cache_hit")) for item in results["search_attempts"]),
        "detail_cache_hits": job["progress"]["details_cached"],
        "environment_unchanged": hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest() == manifest["environment_sha256"],
        "http_bodies_saved": False, "http_body_hashes_recorded": True,
        "playback_verified": False, "teaching_coverage_verified": False,
    }
    (LIVE / "chapter-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (LIVE / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "source_warnings"}))
    if invalid or not summary["environment_unchanged"] or jobs_count != 1 or project_batches != 0:
        raise RuntimeError("Acceptance invariants failed")


if __name__ == "__main__":
    main()
