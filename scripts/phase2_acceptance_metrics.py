"""Summarize saved phase-2 evidence; never sends network requests.

Manual semantic judgments must already be recorded in manual-review.json.
Missing reviews are pending, not a semantic pass. Cross-check all unit mappings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def ratio(passed: int, total: int) -> dict:
    return {"passed": passed, "total": total, "ratio": passed / total if total else None}


def aggregate(run: dict, reviews: dict, recoveries: list[dict] | None = None) -> dict:
    by_case = {r["case_id"]: r for r in reviews.get("case_reviews", [])}
    originals = run["records"]
    recoveries = recoveries or []
    latest = {r["case_id"]: r for r in originals}
    for record in recoveries:
        if record.get("status") == "analyzed":
            latest[record["case_id"]] = record
    records = list(latest.values())
    summary = []
    for record in records:
        case = record["case_id"]
        review = by_case.get(case)
        version = record.get("persisted_view", {}).get("version") or {}
        analysis = version.get("analysis") or {}
        point_ids = {p["id"] for p in analysis.get("knowledge_points", [])}
        function_ids = {f["id"] for f in analysis.get("functions", [])}
        requirements = review.get("requirements", []) if review else []
        units = review.get("unit_reviews", []) if review else []
        invalid_mappings = []
        for requirement in requirements:
            if (not set(requirement.get("unit_ids", [])) <= point_ids
                    or not set(requirement.get("function_ids", [])) <= function_ids
                    or not requirement.get("unit_ids")):
                invalid_mappings.append(requirement["id"])
        matching_hash = bool(review and review.get("analysis_sha256") == record.get("observations", {}).get("analysis_sha256"))
        full_units = set(u["id"] for u in units) == point_ids and len(units) == len(point_ids)
        background = review.get("background", {}).get("passed") if review else None
        prerequisites = review.get("prerequisites", {}).get("passed") if review else None
        technical = review.get("technical_correctness", {}).get("passed") if review else None
        coverage = ratio(sum(r.get("passed") is True for r in requirements), len(requirements))
        relevant = ratio(sum(u.get("project_relevant") is True for u in units), len(units))
        granular = ratio(sum(u.get("appropriate_granularity") is True for u in units), len(units))
        manual_complete = bool(review and matching_hash and full_units and requirements and not invalid_mappings
                               and isinstance(background, bool) and isinstance(prerequisites, bool) and isinstance(technical, bool))
        semantic_pass = bool(manual_complete and coverage["ratio"] == 1 and relevant["ratio"] == 1
                             and granular["ratio"] == 1 and background and prerequisites and technical
                             and not review.get("known_high_or_medium_issues")) if manual_complete else None
        summary.append({
            "case_id": case, "project_id": record.get("project_id"), "version": record.get("version"),
            "student_level": record["input"]["student_level"], "api_status": record["status"],
            "manual_review_complete": manual_complete, "review_hash_matches": matching_hash,
            "reviewed_all_units": full_units, "invalid_requirement_mappings": invalid_mappings,
            "manual_requirement_coverage": coverage, "manual_unit_relevance": relevant,
            "manual_unit_granularity": granular, "background_pass": background,
            "prerequisite_pass": prerequisites, "technical_pass": technical,
            "semantic_pass": semantic_pass,
            "client_analysis_seconds": record.get("client_analysis_elapsed_seconds"),
            "guard_issues": record.get("observations", {}).get("quality_guard_issues"),
            "latency_goal_met": record.get("observations", {}).get("latency_goal_met"),
            "latency_hard_limit_met": record.get("observations", {}).get("latency_hard_limit_met"),
            "known_high_or_medium_issues": review.get("known_high_or_medium_issues", []) if review else [],
        })
    finished = {e["call_id"]: e for r in [*originals, *recoveries] for e in r.get("model_events", []) if e.get("event_type") == "model_call_finished"}
    times = sorted(r["client_analysis_elapsed_seconds"] for r in records if r.get("status") == "analyzed")
    expected = run.get("max_analysis_submissions", 4)
    all_complete = len(summary) == expected and all(c["manual_review_complete"] for c in summary)
    all_semantic = all(c["semantic_pass"] is True for c in summary) if all_complete else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "saved_evidence_metrics",
        "network_requests": 0, "new_provider_requests": 0,
        "cases": summary,
        "summary": {
            "expected_cases": expected, "observed_cases": len(summary),
            "analyzed_cases": sum(r.get("status") == "analyzed" for r in records),
            "first_round_analyzed": sum(r.get("status") == "analyzed" for r in originals),
            "first_round_failed": sum(r.get("status") == "analysis_failed" for r in originals),
            "explicit_recovery_submissions": len(recoveries),
            "analysis_api_submissions_including_recovery": sum(bool(r.get("analysis_submission_attempted")) for r in [*originals, *recoveries]),
            "student_stages": sorted({r["input"]["student_level"] for r in records}),
            "manual_review_complete": all_complete, "semantic_acceptance_pass": all_semantic,
            "latency_acceptance_pass": bool(len(times) == expected and all(t <= 90 for t in times)),
            "client_median_seconds": statistics.median(times) if times else None,
            "client_p95_nearest_rank_seconds": times[math.ceil(.95 * len(times)) - 1] if times else None,
            "client_goal_60s_misses": sum(t > 60 for t in times),
            "model_finished_calls": len(finished),
            "model_completion_tokens": sum(e.get("usage", {}).get("completion_tokens", 0) for e in finished.values()),
            "model_total_tokens": sum(e.get("usage", {}).get("total_tokens", 0) for e in finished.values()),
            "model_calls_with_reported_usage": sum("total_tokens" in e.get("usage", {}) for e in finished.values()),
            "model_calls_without_reported_usage": sum("total_tokens" not in e.get("usage", {}) for e in finished.values()),
            "model_wall_seconds": sum(e.get("elapsed_seconds", 0) for e in finished.values()),
            "search_api_submissions_by_this_runner": 0,
        },
        "limitations": [
            "Manual static judgments are not execution of the student projects or hardware.",
            "Tool targets and keyword observations do not prove video relevance or coverage.",
            "Four examples do not estimate production-wide success rates or statistically stable latency percentiles.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "evidence" / "phase2-learning")
    parser.add_argument("--recovery", type=Path, action="append", default=[])
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(ROOT):
        parser.error("Evidence must stay within the workspace.")
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    path = directory / "manual-review.json"
    reviews = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if any(not p.resolve().is_relative_to(ROOT) for p in args.recovery):
        parser.error("Recovery evidence must stay within the workspace.")
    recoveries = [json.loads(p.read_text(encoding="utf-8")) for p in args.recovery]
    result = aggregate(run, reviews, recoveries)
    result["source_sha256"] = {
        "run.json": hashlib.sha256((directory / "run.json").read_bytes()).hexdigest(),
        "manual-review.json": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        **{str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.recovery},
    }
    (directory / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["semantic_acceptance_pass"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
