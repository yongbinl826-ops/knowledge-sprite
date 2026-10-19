"""Offline v2.6+ pipeline/semantic metrics, including rejected outputs.

Keep unreviewable requirements distinct from actual semantic failures. Preserve
all observed generation/review calls and report missing usage as unknown.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase2_acceptance_metrics import aggregate


def token(event: dict, key: str) -> int | None:
    usage = event.get("usage")
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if type(value) is int and value >= 0 else None


def measure(directory: Path) -> dict:
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    path = directory / "manual-review.json"
    reviews = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    by_review = {r["case_id"]: r for r in reviews.get("case_reviews", [])}
    by_rubric = {r["case_id"]: r["requirements"] for r in plan["independent_requirement_rubric"]}
    safe_run = deepcopy(run)
    for record in safe_run["records"]:
        for event in record.get("model_events", []):
            event["usage"] = {k: token(event, k) for k in ("completion_tokens", "total_tokens") if token(event, k) is not None}
    base = aggregate(safe_run, reviews)
    calls = []
    for record in run["records"]:
        finished = [e for e in record.get("model_events", []) if e.get("event_type") == "model_call_finished"]
        for number, event in enumerate(finished, 1):
            calls.append({"case_id": record["case_id"], "sequence": number, "call_id": event["call_id"],
                          "task": event["task"], "outcome": event.get("outcome"),
                          "failure_type": event.get("failure_type"), "http_status": event.get("http_status"),
                          "completion_tokens": token(event, "completion_tokens"), "total_tokens": token(event, "total_tokens"),
                          "elapsed_seconds": event.get("elapsed_seconds"), "finish_reason": event.get("finish_reason")})
    generations = [c for c in calls if c["task"] == "project_analysis"]
    semantic_reviews = [c for c in calls if c["task"] == "project_analysis_review"]
    requirement_counts = {"passed": 0, "failed": 0, "unassessed": 0, "total": 0}
    for case in base["cases"]:
        original = next(r for r in run["records"] if r["case_id"] == case["case_id"])
        review = by_review.get(case["case_id"], {})
        expected = by_rubric[case["case_id"]]
        judged = {r["id"]: r for r in review.get("requirements", [])}
        counts = {"passed": 0, "failed": 0, "unassessed": 0, "total": len(expected)}
        for requirement in expected:
            value = judged.get(requirement["id"], {}).get("passed")
            counts["passed" if value is True else "failed" if value is False else "unassessed"] += 1
        for key in counts:
            requirement_counts[key] += counts[key]
        case["fixed_requirement_counts"] = counts
        case["accepted_analysis_available"] = original["status"] == "analyzed"
        case["pipeline_error"] = original.get("error")
        if original["status"] != "analyzed":
            case.update(review_hash_matches=None, reviewed_all_units=None, semantic_pass=None)
    expected_count = run.get("selected_count", len(run["records"]))
    completed = sum(r["status"] == "analyzed" for r in run["records"])
    failed = sum(r["status"] in {"analysis_failed", "analysis_rejected"} for r in run["records"])
    all_manual = all(c["manual_review_complete"] for c in base["cases"])
    cohort_pass = False if failed else (
        completed == expected_count and requirement_counts["passed"] == requirement_counts["total"]
        and all(c["semantic_pass"] is True for c in base["cases"])) if all_manual else None
    terminal_times = sorted(r["client_analysis_elapsed_seconds"] for r in run["records"] if "client_analysis_elapsed_seconds" in r)
    base["summary"].update({
        "selected_cases": expected_count, "pipeline_analyzed": completed, "pipeline_failed": failed,
        "cohort_acceptance_pass": cohort_pass, "fixed_requirement_counts": requirement_counts,
        "accepted_output_manual_passes": sum(c["semantic_pass"] is True for c in base["cases"]),
        "generation_calls": len(generations), "review_calls": len(semantic_reviews),
        "all_model_calls": len(calls), "calls_with_unknown_usage": sum(c["total_tokens"] is None for c in calls),
        "generation_reported_completion_tokens": sum(c["completion_tokens"] or 0 for c in generations),
        "review_reported_completion_tokens": sum(c["completion_tokens"] or 0 for c in semantic_reviews),
        "reported_total_tokens": sum(c["total_tokens"] or 0 for c in calls),
        "all_terminal_response_median_seconds": statistics.median(terminal_times) if terminal_times else None,
        "all_terminal_response_p95_nearest_rank_seconds": terminal_times[math.ceil(len(terminal_times)*.95)-1] if terminal_times else None,
        "all_terminal_response_within_90_seconds": all(t <= 90 for t in terminal_times) if len(terminal_times) == expected_count else None,
    })
    base["mode"] = "saved_v26_pipeline_and_independent_semantic_metrics"
    base["call_ledger"] = calls
    base["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory / "run.json", directory / "plan.json", path) if p.exists()}
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "evidence/phase2-learning-v26")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(ROOT):
        parser.error("Evidence must stay inside the workspace.")
    result = measure(directory)
    (directory / "metrics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result["summary"],ensure_ascii=False))
    return 0 if result["summary"]["cohort_acceptance_pass"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
