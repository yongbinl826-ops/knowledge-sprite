"""Read-only, offline audit of one real project/model/search acceptance run.

Only exported JSON/JSONL and SQLite mode=ro are read. This script never reads
configuration or credentials, imports production services, or performs HTTP.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports/project-deepseek-live-20261017"
TERMINAL = {"completed", "partial", "failed", "no_results", "cancelled", "interrupted"}


class EvidenceNotReady(Exception):
    pass


def read_json(path: Path):
    if not path.is_file():
        raise EvidenceNotReady(f"Missing evidence file: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(path: Path):
    if not path.is_file():
        raise EvidenceNotReady(f"Missing evidence file: {path.name}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit_url(value):
    """Match audit URLs, whose queries/fragments were intentionally excluded."""
    try:
        parts = urlsplit(value or "")
        host = (parts.hostname or "").lower()
        return urlunsplit((parts.scheme.lower(), host + (f":{parts.port}" if parts.port else ""), parts.path, "", ""))
    except ValueError:
        return ""


def audit_redaction(value):
    """Mirror the existing journal's documented redaction, without importing services."""
    excluded = {"authorization", "proxy-authorization", "cookie", "set-cookie", "headers",
                "api_key", "tavily_api_key", "llm_api_key", "password", "secret", "token"}
    if isinstance(value, dict):
        return {key: audit_redaction(item) for key, item in value.items()
                if str(key).lower() not in excluded and not str(key).lower().endswith("_api_key")}
    if isinstance(value, (list, tuple)):
        return [audit_redaction(item) for item in value]
    if isinstance(value, str):
        text = re.sub(r"https?://[^\s<>\"']+", lambda match: audit_url(match.group()), value)
        text = re.sub(r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*", "[credential redacted]", text)
        return re.sub(r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", "[credential redacted]", text)
    return value


def chapter_record(job_id, resource, index, chapter, evidence_by_id):
    evidence = evidence_by_id.get(chapter.get("evidence_id"), {})
    try:
        observed = json.loads(evidence.get("text", "null"))
    except (TypeError, json.JSONDecodeError):
        observed = None
    observed = observed if isinstance(observed, dict) else {}
    # Every source field is compared, including adapter-specific page_number.
    fields = sorted((set(chapter) | set(observed)) - {"evidence_id", "source"})
    missing = object()
    checks = {field: chapter.get(field, missing) == observed.get(field, missing) for field in fields}
    checks.update(evidence_kind=evidence.get("kind") == "catalog",
                  evidence_field=evidence.get("field") == f"chapters.{index}",
                  evidence_id=bool(chapter.get("evidence_id")) and chapter.get("evidence_id") == evidence.get("evidence_id"),
                  source=chapter.get("source") == evidence.get("source"))
    return {"job_id": job_id, "resource_id": resource["resource_id"], "course_title": resource.get("title"),
            "course_url": resource.get("url"), "chapter_index": index, "chapter": chapter,
            "source_url": evidence.get("url"), "source_observed_at": evidence.get("observed_at"),
            "source_cache": evidence.get("cache"), "observed_fields": observed,
            "field_checks": checks, "evidence_consistent": bool(observed) and all(checks.values())}


def model_summary(events):
    starts = [event for event in events if event.get("event_type") == "model_call_started"]
    finished = [event for event in events if event.get("event_type") == "model_call_finished"]
    start_counts, end_counts = Counter(event["call_id"] for event in starts), Counter(event["call_id"] for event in finished)
    by_task = {}
    for task in sorted({event.get("task", "unknown") for event in events}):
        rows = [event for event in finished if event.get("task") == task]
        by_task[task] = {"started": sum(event.get("task") == task for event in starts), "finished": len(rows),
            "json_returned": sum(event.get("outcome") == "json_returned" for event in rows),
            "failures": dict(Counter(event.get("failure_type") or "unknown" for event in rows if event.get("outcome") != "json_returned")),
            "http_statuses": dict(Counter(str(event.get("http_status")) for event in rows)),
            "finish_reasons": dict(Counter(str(event.get("finish_reason")) for event in rows)),
            "usage": {key: sum(event.get("usage", {}).get(key, 0) for event in rows)
                      for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}}
    return {"call_count": len(starts), "finished_count": len(finished), "by_task": by_task,
            "total_usage": {key: sum(event.get("usage", {}).get(key, 0) for event in finished)
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")},
            "providers_models": sorted({event["provider_model"] for event in finished if event.get("provider_model")}),
            "matched_unique_start_finish": start_counts == end_counts and all(count == 1 for count in start_counts.values()),
            "pending_call_ids": sorted(set(start_counts) - set(end_counts)),
            "metadata_observation_failures": sum(bool(event.get("metadata_observation_failed")) for event in finished),
            "responses_with_body_hash": sum(bool(event.get("response_body_sha256")) for event in finished),
            "responses_with_content_hash": sum(bool(event.get("message_content_sha256")) for event in finished),
            "failures": [{key: event.get(key) for key in ("call_id", "task", "http_status", "failure_type", "finish_reason", "started_at", "finished_at")}
                         for event in finished if event.get("outcome") != "json_returned"],
            "meaning": "json_returned is transport/JSON success only; project analysis schema and human relevance checks are independent"}


def summarize(output: Path, *, expected_points=10, expected_batches=2, write_output=True):
    live = output / "live"
    exported = read_json(output / "project-results.json")
    global_audit = read_json(output / "audit-status.json")
    manifest = read_json(live / "run.json")
    version = exported.get("version") or {}
    if version.get("status") not in TERMINAL:
        raise EvidenceNotReady("Project result is not terminal")
    project_id, version_number = exported["project_id"], version["version"]
    jobs_summary, ledger, checks = [], [], {}
    resources_by_job, evidence_by_job, all_http_responses = {}, {}, []
    evidence_files = [output / "project-results.json", output / "audit-status.json", live / "run.json", live / "model-events.jsonl"]
    with sqlite3.connect((live / "live.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        project_row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        version_row = connection.execute("SELECT data FROM project_versions WHERE project_id=? AND version=?", (project_id, version_number)).fetchone()
        if project_row is None or version_row is None:
            raise EvidenceNotReady("Exported project version is absent from the database")
        saved_version = json.loads(version_row[0])
        if saved_version["status"] not in TERMINAL:
            raise EvidenceNotReady("Database project result is not terminal")
        analysis = saved_version["analysis"]
        confirmation = saved_version["confirmation"]
        project_points = {point["id"]: point for point in analysis["knowledge_points"]}
        mappings = [dict(row) for row in connection.execute("SELECT * FROM project_point_job_mappings WHERE project_id=? AND version=? ORDER BY project_point_id", (project_id, version_number))]
        batches = [json.loads(row[0]) for row in connection.execute("SELECT data FROM project_batches WHERE project_id=? AND version=? ORDER BY ordinal", (project_id, version_number))]
        job_ids = [batch.get("job_id") for batch in batches]
        selected = confirmation["selected_ids"]
        actual_jobs = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        actual_project_points = connection.execute("SELECT COUNT(*) FROM project_knowledge_points WHERE project_id=? AND version=?", (project_id, version_number)).fetchone()[0]
        flat_selected = [point_id for batch in batches for point_id in batch["project_knowledge_point_ids"]]
        checks.update(analysis_confirmation_version_same=confirmation["confirmation_version"] == version_number == exported["current_version"] == project_row["current_version"],
            confirmed_analysis_unchanged=confirmation["analysis"] == analysis == version["analysis"],
            confirmed_input_unchanged=confirmation["input"] == saved_version["input"] == version["input"],
            expected_point_count=len(project_points) == len(selected) == actual_project_points == expected_points,
            only_explicit_learning_selected=set(selected) == {point["id"] for point in analysis["knowledge_points"] if point["selection"] == "learn"},
            expected_batch_count=len(batches) == expected_batches,
            exact_selected_points_partition=sorted(flat_selected) == sorted(selected) and len(flat_selected) == len(set(flat_selected)),
            no_duplicate_actual_jobs=None not in job_ids and len(set(job_ids)) == expected_batches == actual_jobs,
            batch_capacities=all(0 < len(batch["project_knowledge_point_ids"]) <= min(5, saved_version["budgets"]["batch_size"]) for batch in batches),
            all_selected_points_mapped=set(row["project_point_id"] for row in mappings) == set(selected) and len(mappings) == len(selected),
            snapshot_state_matches_export=saved_version["status"] == version["status"],
            fresh_unmocked_manifest=manifest.get("fresh_database") is True and manifest.get("mock_model") is False and manifest.get("candidate_injection") is False and manifest.get("saved_page_replay") is False)
        expected_mapping_rows = {(point_id, batch["batch_id"], batch["job_id"], mapping["knowledge_point_id"])
                                 for batch in batches for mapping in batch["mappings"] if (point_id := mapping["project_knowledge_point_id"])}
        checks["batch_and_database_mapping_consistent"] = expected_mapping_rows == {(row["project_point_id"], row["batch_id"], row["job_id"], row["knowledge_point_id"]) for row in mappings}
        checks["job_point_mapping_consistent"] = True
        for row in mappings:
            search_point = connection.execute("SELECT job_id,text FROM knowledge_points WHERE id=?", (row["knowledge_point_id"],)).fetchone()
            expected_name = " ".join(project_points[row["project_point_id"]]["name"].split())
            checks["job_point_mapping_consistent"] &= bool(search_point and search_point["job_id"] == row["job_id"] and search_point["text"] == expected_name)
        for batch in batches:
            job_id = batch["job_id"]
            row = connection.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise EvidenceNotReady("A mapped job is absent from the database")
            job = json.loads(row[0])
            if job["status"] not in TERMINAL:
                raise EvidenceNotReady("A mapped search job is not terminal")
            folder = live / "jobs" / job_id
            audit_status = read_json(folder / "audit-status.json")
            observed_events = read_events(folder / "events.jsonl")
            audit_job, audit_results = read_json(folder / "job.json"), read_json(folder / "results.json")
            audit_resources = read_json(folder / "resources-and-evidence.json")
            evidence_files.extend(folder / name for name in ("audit-status.json", "events.jsonl", "job.json", "results.json", "resources-and-evidence.json"))
            resources = [json.loads(row[0]) for row in connection.execute("SELECT data FROM resources WHERE job_id=? ORDER BY id", (job_id,))]
            resources_by_job[job_id] = {resource["resource_id"]: resource for resource in resources}
            evidence = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence WHERE job_id=?", (job_id,))]
            evidence_by_job[job_id] = {item["evidence_id"]: item for item in evidence}
            attempts = [json.loads(row[0]) for row in connection.execute("SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (job_id,))]
            http_responses = [event for event in observed_events if event.get("event_type") == "http_response_body"]
            all_http_responses.extend(http_responses)
            successful_page_urls = {audit_url(event["url"]) for event in http_responses if event.get("http_status") == 200 and event.get("request_kind") in {"page", "catalog"}}
            fetched = [resource for resource in resources if resource.get("fetch_status") == "fetched"]
            fresh_backed = []
            for resource in resources:
                resource_evidence = {item["evidence_id"]: item for raw in connection.execute(
                    "SELECT data FROM evidence WHERE job_id=? AND resource_id=?", (job_id, resource["resource_id"])) if (item := json.loads(raw[0]))}
                for index, chapter in enumerate(resource.get("chapters", [])):
                    ledger.append(chapter_record(job_id, resource, index, chapter, resource_evidence))
                related = {audit_url(resource.get(field)) for field in ("url", "canonical_url", "resolved_url")}
                related.update(audit_url(item.get("url")) for item in resource_evidence.values() if item.get("kind") in {"page", "catalog"})
                if resource.get("fetch_status") == "fetched" and not resource.get("cache", {}).get("hit") and related & successful_page_urls:
                    fresh_backed.append(resource)
            progress = job["progress"]
            provider_requests = [record for attempt in attempts for record in attempt.get("provider_requests", [])]
            job_checks = {"audit_valid": audit_status.get("acceptance_valid") is True and not audit_status.get("audit_errors"),
                "terminal_job_snapshot_matches": audit_job == job,
                "resource_export_matches_database_after_documented_redaction": {item["resource"]["resource_id"]: item["resource"] for item in audit_resources} == audit_redaction(resources_by_job[job_id]),
                "single_audited_execution": sum(event.get("event_type") == "job_started" for event in observed_events) == sum(event.get("event_type") == "job_finished" for event in observed_events) == 1,
                "audit_sequence_contiguous": [event.get("sequence") for event in observed_events] == list(range(1, len(observed_events) + 1)),
                "all_http_responses_hashed": all(event.get("body_sha256") and type(event.get("body_bytes")) is int for event in http_responses),
                "search_requests_within_job_budget": progress["search_requests"] <= job["budgets"]["max_search_requests"],
                "detail_pages_within_job_budget": progress["details_attempted"] + progress.get("catalog_pages_attempted", 0) <= job["budgets"]["max_detail_pages"],
                "provider_request_records_match_counter": len(provider_requests) == progress["search_requests"]}
            checks.update({f"job_{job_id}_{name}": value for name, value in job_checks.items()})
            jobs_summary.append({"job_id": job_id, "batch_id": batch["batch_id"], "status": job["status"],
                "point_count": len(job["knowledge_points"]), "search_requests": progress["search_requests"],
                "details_attempted": progress["details_attempted"], "catalog_pages_attempted": progress.get("catalog_pages_attempted", 0),
                "details_completed": progress.get("details_completed", 0),
                "resource_count": len(resources), "fetch_status_counts": dict(Counter(resource.get("fetch_status") for resource in resources)),
                "fetched_resource_rows": len(fetched), "fresh_http_backed_fetched_rows": len(fresh_backed),
                "fetched_canonical_urls": sorted({resource["canonical_url"] for resource in fetched}),
                "fresh_http_backed_fetched_canonical_urls": sorted({resource["canonical_url"] for resource in fresh_backed}),
                "search_cache_hits": sum(bool(attempt.get("cache_hit")) for attempt in attempts), "detail_cache_hits": progress.get("details_cached", 0),
                "logical_query_statuses": dict(Counter(attempt.get("status") for attempt in attempts)),
                "provider_http_statuses": dict(Counter(f"{record.get('provider')}:{record.get('http_status')}" for record in provider_requests)),
                "observed_http_responses": len(http_responses),
                "observed_http_statuses_by_kind": dict(Counter(f"{event.get('request_kind')}:{event.get('http_status')}" for event in http_responses)),
                "successful_page_response_urls": sorted(successful_page_urls),
                "chapter_count": sum(len(resource.get("chapters", [])) for resource in resources),
                "warnings": job.get("warnings", []), "error_codes": [error.get("code") for error in job.get("errors", [])], "checks": job_checks})
        snapshot_digest = digest({"version": saved_version, "mappings": mappings,
                                  "resources_by_job": resources_by_job, "jobs": jobs_summary})
    model = model_summary(read_events(live / "model-events.jsonl"))
    mapping_by_point = {row["project_point_id"]: row for row in mappings}
    point_summaries = []
    checks["exported_points_exactly_match_selected"] = {point["project_knowledge_point_id"] for point in exported["points"]} == set(selected)
    checks["exported_result_mapping_and_chapters_consistent"] = True
    for point in exported["points"]:
        group, point_id = point.get("result"), point["project_knowledge_point_id"]
        mapping = mapping_by_point.get(point_id)
        checks["exported_result_mapping_and_chapters_consistent"] &= bool(mapping and point.get("job_id") == mapping["job_id"] and point.get("knowledge_point_id") == mapping["knowledge_point_id"] and group and group.get("knowledge_point_id") == mapping["knowledge_point_id"])
        group = group or {}
        for item in [*group.get("items", []), *group.get("partial_items", []), *group.get("review_items", []),
                     *(item for field in ("platform_items", "partial_platform_items", "review_platform_items") for items in group.get(field, {}).values() for item in items)]:
            stored_resource = resources_by_job.get(point.get("job_id"), {}).get(item["resource"]["resource_id"])
            checks["exported_result_mapping_and_chapters_consistent"] &= bool(stored_resource and item["resource"].get("chapters", []) == stored_resource.get("chapters", []))
        supported, partial, review = (group.get(field, 0) for field in ("total_matches", "total_partial_matches", "total_review_matches"))
        point_summaries.append({"project_knowledge_point_id": point_id, "name": point["name"], "status": point["status"],
            "job_id": point.get("job_id"), "knowledge_point_id": point.get("knowledge_point_id"),
            "supported_matches": supported, "partial_matches": partial, "review_matches": review,
            "displayed_supported_cards": len(group.get("items", [])), "displayed_partial_cards": len(group.get("partial_items", [])),
            "displayed_review_cards": len(group.get("review_items", [])), "collection_coverage": group.get("collection_coverage"),
            "gap": "no_supported_resource" if not supported else "teaching_completeness_unverified"})
    budget = saved_version["budgets"]
    search_requests = sum(job["search_requests"] for job in jobs_summary)
    detail_pages = sum(job["details_attempted"] + job["catalog_pages_attempted"] for job in jobs_summary)
    checks.update(actual_search_requests_within_project_budget=search_requests <= budget["reserved_search_requests"] <= budget["max_search_requests"],
                  actual_detail_pages_within_project_budget=detail_pages <= budget["reserved_detail_pages"] <= budget["max_detail_pages"],
                  all_chapter_fields_match_source_evidence=all(row["evidence_consistent"] for row in ledger),
                  model_start_finish_pairs=model["matched_unique_start_finish"],
                  observer_metadata_valid=model["metadata_observation_failures"] == 0,
                  global_audit_valid=global_audit.get("acceptance_valid") is True and not global_audit.get("audit_errors"))
    fetched_urls = sorted({url for job in jobs_summary for url in job["fetched_canonical_urls"]})
    fresh_urls = sorted({url for job in jobs_summary for url in job["fresh_http_backed_fetched_canonical_urls"]})
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "project_id": project_id, "version": version_number,
        "project_status": saved_version["status"], "scope": "This run's persisted analysis, explicit confirmation, actual search/fetch and exported project results; UI is audited separately",
        "acceptance_invariants_passed": all(checks.values()), "failed_checks": [name for name, valid in checks.items() if not valid], "checks": checks,
        "analysis_model": saved_version.get("model"), "prompt_version": saved_version.get("prompt_version"),
        "analysis_and_confirmation_version": confirmation["confirmation_version"], "project_point_count": len(project_points),
        "selected_point_count": len(selected), "mapped_point_count": len(mappings), "batch_count": len(batches), "database_job_count": actual_jobs,
        "job_ids": job_ids, "budgets": {**budget, "actual_search_requests": search_requests, "actual_detail_pages": detail_pages},
        "jobs": jobs_summary, "points": point_summaries,
        "resource_rows": sum(job["resource_count"] for job in jobs_summary), "fetched_resource_rows": sum(job["fetched_resource_rows"] for job in jobs_summary),
        "deduplicated_fetched_url_count": len(fetched_urls), "deduplicated_fetched_urls": fetched_urls,
        "fresh_http_backed_fetched_url_count": len(fresh_urls), "fresh_http_backed_fetched_urls": fresh_urls,
        "observed_http_response_count": len(all_http_responses),
        "observed_http_statuses_by_kind": dict(Counter(f"{event.get('request_kind')}:{event.get('http_status')}" for event in all_http_responses)),
        "search_cache_hits": sum(job["search_cache_hits"] for job in jobs_summary), "detail_cache_hits": sum(job["detail_cache_hits"] for job in jobs_summary),
        "catalog_chapter_rows": len(ledger), "catalog_chapter_mismatches": sum(not row["evidence_consistent"] for row in ledger),
        "points_with_supported_resources": sum(point["supported_matches"] > 0 for point in point_summaries),
        "points_with_supported_or_partial_resources": sum(bool(point["supported_matches"] or point["partial_matches"]) for point in point_summaries),
        "displayed_supported_card_count": sum(point["displayed_supported_cards"] for point in point_summaries),
        "displayed_partial_card_count": sum(point["displayed_partial_cards"] for point in point_summaries),
        "displayed_review_card_count": sum(point["displayed_review_cards"] for point in point_summaries),
        "points_without_supported_resources": [point["project_knowledge_point_id"] for point in point_summaries if not point["supported_matches"]],
        "points_with_no_displayable_results": [point["project_knowledge_point_id"] for point in point_summaries if not (point["supported_matches"] or point["partial_matches"] or point["review_matches"])],
        "model_events": model, "database_logical_snapshot_sha256": snapshot_digest,
        "source_files_sha256": {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_files},
        "limitations": ["Resource discovery counts are not page-fetch counts.", "supported topic evidence does not verify full teaching coverage or playback.",
                        "details_completed counts completed processing attempts, including failures/restrictions; fetched_resource_rows is reported separately.",
                        "Audit resource exports remove URL queries; raw database chapter URLs are retained in chapter-ledger.json and checked against raw evidence.",
                        "HTTP/page/catalog observations do not prove login-free or complete video playback.", "Partial jobs and missing topic resources are preserved; no silent rerun or replacement."],
        "playback_verified": False, "complete_teaching_coverage_verified": False, "ui_page_display_verified": "not_assessed_by_this_script"}
    if write_output:
        (output / "chapter-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-points", type=int, default=10)
    parser.add_argument("--expected-batches", type=int, default=2)
    args = parser.parse_args()
    try:
        summary = summarize(args.output.resolve(), expected_points=args.expected_points, expected_batches=args.expected_batches)
    except EvidenceNotReady as exc:
        print(json.dumps({"status": "not_ready", "reason": str(exc)}))
        return 2
    print(json.dumps({key: summary[key] for key in ("project_id", "project_status", "acceptance_invariants_passed", "failed_checks", "resource_rows", "fetched_resource_rows", "deduplicated_fetched_url_count", "catalog_chapter_rows", "points_with_supported_resources")}))
    return 0 if summary["acceptance_invariants_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
