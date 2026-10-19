"""Offline, read-only comparison of original and retained-analysis search runs.

Reads terminal exports, SQLite mode=ro and actual HTTP/model journals. Writes
only the new comparison/ledger; never contacts services or reads configuration.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.summarize_project_model_live import (
    EvidenceNotReady, audit_redaction, chapter_record, digest, read_json, summarize,
)

SUSPENDED_TIMEOUT_HASH = hashlib.sha256(b"Suspended: timeout").hexdigest()


def upstream_reason(warning):
    if warning.get("reason_code") == "unknown" and warning.get("reason_sha256") == SUSPENDED_TIMEOUT_HASH:
        return "suspended_timeout_verified_by_hash"
    return warning.get("reason_code") or warning.get("code") or "unknown"


def referenced_evidence_ids(value):
    """Collect references in match reasons, subtopics and field provenance."""
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("evidence_ids") and isinstance(item, list):
                result.update(identifier for identifier in item if isinstance(identifier, str))
            elif key == "evidence_id" and isinstance(item, str):
                result.add(item)
            elif isinstance(item, (dict, list)):
                result.update(referenced_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            result.update(referenced_evidence_ids(item))
    return result


def result_items(group):
    for field in ("items", "partial_items", "review_items"):
        yield from group.get(field, [])
    for field in ("platform_items", "partial_platform_items", "review_platform_items"):
        for items in group.get(field, {}).values():
            yield from items


def inspect_point_evidence(directory: Path):
    exported = read_json(directory / "project-results.json")
    points, ledger, checks, resource_urls, all_evidence_ids = {}, [], {}, set(), set()
    with sqlite3.connect((directory / "live/live.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        jobs = {}
        for batch in exported["version"]["batches"]:
            job_id = batch["job_id"]
            resources = {row["id"]: json.loads(row["data"]) for row in conn.execute(
                "SELECT id,data FROM resources WHERE job_id=?", (job_id,))}
            evidence_rows = list(conn.execute("SELECT id,resource_id,knowledge_point_id,data FROM evidence WHERE job_id=?", (job_id,)))
            evidence = {row["id"]: json.loads(row["data"]) for row in evidence_rows}
            evidence_owners = {row["id"]: (row["resource_id"], row["knowledge_point_id"]) for row in evidence_rows}
            matches = {(row["knowledge_point_id"], row["resource_id"]): json.loads(row["data"]) for row in conn.execute(
                "SELECT knowledge_point_id,resource_id,data FROM matches WHERE job_id=?", (job_id,))}
            attempts = [json.loads(row[0]) for row in conn.execute("SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (job_id,))]
            all_evidence_ids.update(evidence)
            resource_urls.update(item["canonical_url"] for item in resources.values())
            for resource in resources.values():
                own_evidence = {identifier: item for identifier, item in evidence.items()
                    if evidence_owners[identifier][0] == resource["resource_id"]}
                for index, chapter in enumerate(resource.get("chapters", [])):
                    ledger.append(chapter_record(job_id, resource, index, chapter, own_evidence))
                checks[f"{job_id}/{resource['resource_id']}/provenance_references_exist"] = (
                    referenced_evidence_ids(resource.get("field_provenance", {})).issubset(own_evidence))
            audited_results = read_json(directory / "live/jobs" / job_id / "results.json")
            audited_groups = {group["knowledge_point_id"]: group for group in audited_results["groups"]}
            jobs[job_id] = (resources, evidence, evidence_owners, matches, attempts, audited_groups)
        for point in exported["points"]:
            point_id, job_id, search_point_id = point["project_knowledge_point_id"], point["job_id"], point["knowledge_point_id"]
            resources, evidence, owners, matches, attempts, audited_groups = jobs[job_id]
            own_attempts = [item for item in attempts if item["knowledge_point_id"] == search_point_id]
            provider_responses = [record for attempt in own_attempts for record in attempt.get("provider_requests", [])]
            observed_ids = {owners[identifier][0] for identifier, item in evidence.items()
                if owners[identifier][1] == search_point_id and item.get("kind") == "search"}
            observed_resources = [resources[identifier] for identifier in sorted(observed_ids)]
            group = point.get("result") or {}
            checks[f"{point_id}/audited_job_group_equals_project_group"] = audit_redaction(group) == audited_groups.get(search_point_id)
            card_checks, cards = [], []
            seen = set()
            for item in result_items(group):
                resource_id = item["resource"]["resource_id"]
                reference_ids = referenced_evidence_ids(item["match"])
                resource_evidence_ids = {identifier for identifier, (owner_resource, _) in owners.items()
                    if owner_resource == resource_id}
                appropriate_ids = {identifier for identifier, (owner_resource, owner_point) in owners.items()
                    if owner_resource == resource_id and owner_point in {None, search_point_id}}
                saved_match = matches.get((search_point_id, resource_id))
                item_checks = {
                    "resource_fields_equal_database": item["resource"] == resources.get(resource_id),
                    "derived_match_identity_matches_observed_resource": item["match"].get("knowledge_point_id") == search_point_id
                        and item["match"].get("resource_id") == resource_id and resource_id in observed_ids,
                    "match_evidence_ids_exist_for_resource": reference_ids.issubset(resource_evidence_ids),
                    "topic_support_ids_exist_for_point_resource": set(item["match"].get("supporting_evidence_ids", [])).issubset(appropriate_ids),
                    "exported_evidence_fields_equal_database": all(evidence.get(entry.get("evidence_id")) == entry
                        and entry.get("evidence_id") in resource_evidence_ids for entry in item["evidence"]),
                    "matched_evidence_present_in_export": reference_ids.issubset({entry["evidence_id"] for entry in item["evidence"]}),
                }
                card_checks.append(all(item_checks.values()))
                key = resource_id, item["match"].get("topic_evidence_status")
                if key not in seen:
                    seen.add(key)
                    cards.append({"resource_id": resource_id, "title": item["resource"].get("title"),
                        "url": item["resource"]["url"], "topic_evidence_status": key[1],
                        "fetch_status": item["resource"]["fetch_status"], "evidence_ids": sorted(reference_ids),
                        "chapter_count": len(item["resource"].get("chapters", [])), "checks": item_checks,
                        "persisted_match_present": saved_match is not None,
                        "derived_match_changed_fields": [key for key, value in item["match"].items()
                            if saved_match is None or saved_match.get(key) != value]})
            checks[f"{point_id}/all_card_resource_match_evidence_references_consistent"] = all(card_checks)
            default_ids = {item["resource"]["resource_id"] for field in ("items", "partial_items", "review_items") for item in group.get(field, [])}
            points[point_id] = {
                "name": point["name"], "job_id": job_id, "search_knowledge_point_id": search_point_id,
                "logical_query_count": len(own_attempts),
                "logical_query_statuses": dict(Counter(item["status"] for item in own_attempts)),
                "search_requests": len(provider_responses),
                "provider_responses_with_upstream_failures": sum(bool(record.get("upstream_warnings")) for record in provider_responses),
                "provider_responses_without_candidates": sum(record.get("candidate_count") == 0 for record in provider_responses),
                "upstream_reason_counts": dict(Counter(upstream_reason(warning) for record in provider_responses for warning in record.get("upstream_warnings", []))),
                "query_details": [{**{key: item.get(key) for key in ("query", "status", "candidate_count", "cache_hit", "error_code", "priority_request_limit", "priority_query_count")},
                    "provider_responses": [{key: record.get(key) for key in ("provider", "engines_requested", "http_status", "status", "candidate_count", "raw_candidate_count", "topic_signal_count", "error_code", "upstream_warnings")}
                        for record in item.get("provider_requests", [])]} for item in own_attempts],
                "candidate_resource_count": len(observed_ids),
                "candidate_observation_count": sum(item.get("kind") == "search" and owners[identifier][1] == search_point_id for identifier, item in evidence.items()),
                "candidate_fetch_status_counts": dict(Counter(item["fetch_status"] for item in observed_resources)),
                "fetched_candidate_resource_count": sum(item["fetch_status"] == "fetched" for item in observed_resources),
                "candidate_resources": [{key: item.get(key) for key in ("resource_id", "title", "url", "canonical_url", "fetch_status", "cache")} for item in observed_resources],
                "cards_in_default_buckets": [item for item in cards if item["resource_id"] in default_ids],
                "cards_including_platform_buckets": cards,
                "card_evidence_checks_passed": all(card_checks),
            }
        cache_rows = [{"kind": row["kind"], "created_epoch_seconds": row["created"]} for row in conn.execute("SELECT kind,created FROM cache")]
    checks["all_chapter_fields_equal_catalog_evidence"] = all(row["evidence_consistent"] for row in ledger)
    return {"points": points, "checks": checks, "ledger": ledger,
            "evidence_ids": all_evidence_ids, "resource_urls": resource_urls, "cache_rows": cache_rows}


def compare(before_dir: Path, after_dir: Path, *, expected_points=10, expected_batches=2):
    before_file, after_file = before_dir / "project-results.json", after_dir / "project-results.json"
    before_export, after_export = read_json(before_file), read_json(after_file)
    imported = read_json(after_dir / "retained-analysis-import.json")
    # Reuse all previous job/HTTP/DB/chapter/budget checks without rewriting the baseline.
    before = summarize(before_dir, expected_points=expected_points, expected_batches=expected_batches, write_output=False)
    after = summarize(after_dir, expected_points=expected_points, expected_batches=expected_batches, write_output=False)
    before_detail, after_detail = inspect_point_evidence(before_dir), inspect_point_evidence(after_dir)
    provenance = after_export["version"].get("retained_analysis", {})
    before_version, after_version = before_export["version"], after_export["version"]
    source_hash = hashlib.sha256(before_file.read_bytes()).hexdigest()
    retained_tables = {"projects", "project_versions", "project_functions", "project_knowledge_points", "project_prerequisites"}
    imported_at = datetime.fromisoformat(imported["created_at"]).timestamp()
    checks = {
        "baseline_invariants_passed": before["acceptance_invariants_passed"],
        "new_run_invariants_passed": after["acceptance_invariants_passed"],
        "baseline_evidence_checks_passed": all(before_detail["checks"].values()),
        "new_evidence_checks_passed": all(after_detail["checks"].values()),
        "new_project_identity": before["project_id"] != after["project_id"] == imported["project_id"],
        "new_job_identities": set(before["job_ids"]).isdisjoint(after["job_ids"]),
        "new_evidence_identities": before_detail["evidence_ids"].isdisjoint(after_detail["evidence_ids"]),
        "retained_analysis_origin_explicit": after_version.get("origin") == imported.get("origin") == "retained_analysis",
        "same_input_and_analysis": before_version["input"] == after_version["input"] and before_version["analysis"] == after_version["analysis"],
        "same_confirmed_selected_ids": before_version["confirmation"]["selected_ids"] == after_version["confirmation"]["selected_ids"],
        "new_confirmation_after_import": datetime.fromisoformat(after_version["confirmation"]["confirmed_at"]).timestamp() >= imported_at,
        "retained_source_file_hash_matches": provenance.get("source_file_sha256") == source_hash,
        "retained_analysis_hash_matches": provenance.get("source_analysis_sha256") == digest(before_version["analysis"]),
        "provenance_matches_import_manifest": provenance == imported.get("provenance"),
        "retained_source_identity_matches": provenance.get("source_project_id") == before["project_id"] and provenance.get("source_analysis_version") == before["version"],
        "no_new_analysis_model_claim": provenance.get("new_model_analysis_performed") is False and after["model_events"]["by_task"].get("project_analysis", {}).get("started", 0) == 0,
        "no_old_confirmation_or_search_data_imported": provenance.get("source_confirmation_imported") is False and provenance.get("source_search_data_imported") is False,
        "all_tables_empty_before_import": bool(imported.get("before_table_counts")) and not any(imported["before_table_counts"].values()),
        "only_project_draft_rows_after_import": bool(imported.get("after_table_counts")) and not any(count for table, count in imported["after_table_counts"].items() if table not in retained_tables),
        "all_new_cache_rows_created_after_import": all(row["created_epoch_seconds"] >= imported_at for row in after_detail["cache_rows"]),
        "baseline_search_and_detail_cache_hits_zero": before["search_cache_hits"] == before["detail_cache_hits"] == 0,
        "same_budget_configuration": all(before["budgets"].get(key) == after["budgets"].get(key)
            for key in before["budgets"] if not key.startswith("actual_")),
        "same_project_point_ids": set(before_detail["points"]) == set(after_detail["points"]),
    }
    before_points = {point["project_knowledge_point_id"]: point for point in before["points"]}
    after_points = {point["project_knowledge_point_id"]: point for point in after["points"]}
    metric_names = ("supported_matches", "partial_matches", "review_matches", "displayed_supported_cards", "displayed_partial_cards", "displayed_review_cards")
    point_comparison = []
    for point_id in before_version["confirmation"]["selected_ids"]:
        old, new = before_points[point_id], after_points[point_id]
        old_data, new_data = before_detail["points"][point_id], after_detail["points"][point_id]
        point_comparison.append({"project_knowledge_point_id": point_id, "name": old["name"],
            "before": {**old, **old_data}, "after": {**new, **new_data},
            "delta": {key: new[key] - old[key] for key in metric_names},
            "new_default_card_count": sum(new[key] for key in metric_names[3:]),
            "gap": "no_displayable_result" if not sum(new[key] for key in metric_names[3:]) else "teaching_completeness_and_playback_unverified"})
    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison_invariants_passed": all(checks.values()), "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "before": before, "after": after, "points": point_comparison,
        "before_evidence_checks": before_detail["checks"], "after_evidence_checks": after_detail["checks"],
        "retained_analysis_import": imported,
        "upstream_failure_counts": {label: dict(sum((Counter(point["upstream_reason_counts"])
            for point in details["points"].values()), Counter()))
            for label, details in (("before", before_detail), ("after", after_detail))},
        "upstream_unknown_diagnosis": {"original_reason_code_retained": "unknown",
            "known_reason": "Suspended: timeout", "sha256": SUSPENDED_TIMEOUT_HASH,
            "verification": "Exact SHA256 match and read-only current SearXNG source webutils.py:77-79 plus search/processors/abstract.py:239-245. No request, restart, resume, setting or source-pause changes were used to diagnose it.",
            "meaning": "Temporary upstream suspension caused by timeout. HTTP 200 with this warning is not a successful course search."},
        "shared_discovered_urls_count": len(before_detail["resource_urls"] & after_detail["resource_urls"]),
        "shared_discovered_urls_meaning": "The same public URL can be rediscovered; URL-derived resource IDs may repeat. New job/evidence IDs, empty import tables, cache timestamps and new HTTP evidence distinguish a new run.",
        "new_cache_rows": after_detail["cache_rows"],
        "source_hashes": {"before_project_results": source_hash,
            "after_project_results": hashlib.sha256(after_file.read_bytes()).hexdigest(),
            "retained_analysis_import": hashlib.sha256((after_dir / "retained-analysis-import.json").read_bytes()).hexdigest()},
        "limitations": [
            "This is a new search run using a retained real analysis; project analysis was not rerun.",
            "Point candidate fetch counts follow associated search evidence; a shared resource can appear under multiple points. They are not per-point physical request counts.",
            "Resource rows, detail processing, fetched pages, topic support and full teaching coverage are separate measures.",
            "More cards do not by themselves prove correctness. Human relevance review and UI checks remain separate.",
            "Same budgets and selected points do not control changing upstream search results, network responses or model expansion outputs.",
            "Priority query/request coverage does not mean successful candidates or courses; upstream timeouts and suspended responses remain counted separately.",
            "No playback or full teaching completeness is verified. Empty, partial and review-only results remain explicit.",
            "Result matches are derived again when read; persisted reranking bonuses may differ. Full audited result snapshots and all source evidence references are checked, while changed match fields are listed diagnostically.",
        ],
    }
    return comparison, after_detail["ledger"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=ROOT / "reports/project-deepseek-live-20261017")
    parser.add_argument("--after", type=Path, default=ROOT / "reports/project-search-diagnosis-20261018/verified-rerun")
    parser.add_argument("--expected-points", type=int, default=10)
    parser.add_argument("--expected-batches", type=int, default=2)
    args = parser.parse_args()
    before, after = args.before.resolve(), args.after.resolve()
    if before == after:
        parser.error("Before and after directories must differ")
    try:
        comparison, ledger = compare(before, after, expected_points=args.expected_points, expected_batches=args.expected_batches)
    except EvidenceNotReady as error:
        print(json.dumps({"status": "not_ready", "reason": str(error)}))
        return 2
    (after / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    (after / "chapter-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"comparison_invariants_passed": comparison["comparison_invariants_passed"],
        "failed_checks": comparison["failed_checks"], "before_project_id": comparison["before"]["project_id"],
        "after_project_id": comparison["after"]["project_id"], "chapter_rows": len(ledger)}))
    return 0 if comparison["comparison_invariants_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
