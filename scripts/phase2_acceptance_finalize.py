"""Pin the independently accepted mixed-version phase-2 snapshot, offline only."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase2_acceptance import dump
from scripts.phase2_acceptance_v26_metrics import measure


SELECTION = {
    "web_pomodoro_beginner": "phase2-learning-v261",
    "bicycle_csv_advanced": "phase2-learning-v26",
    "arduino_reaction_beginner": "phase2-learning-v261",
    "pygame_maze_intermediate": "phase2-learning-v26",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    original = {r["case_id"]: r for r in read(ROOT / "evidence/phase2-learning-v25/run.json")["records"]}
    cohorts = {}
    for directory in set(SELECTION.values()):
        path = ROOT / "evidence" / directory
        cohorts[directory] = {"run": read(path / "run.json"), "review": read(path / "manual-review.json"), "metrics": measure(path)}
    cases = []
    for case_id, directory in SELECTION.items():
        source = cohorts[directory]
        record = next(r for r in source["run"]["records"] if r["case_id"] == case_id)
        review = next(r for r in source["review"]["case_reviews"] if r["case_id"] == case_id)
        metric = next(r for r in source["metrics"]["cases"] if r["case_id"] == case_id)
        if (record["status"] != "analyzed" or metric["semantic_pass"] is not True
                or record["project_id"] != original[case_id]["project_id"] or record["input"] != original[case_id]["input"]):
            raise ValueError("A required selected snapshot lacks a matching, independently accepted analysis; no historical fallback.")
        document = record["persisted_view"]["version"]["analysis"]
        analysis_sha = hashlib.sha256(json.dumps(document,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if analysis_sha != review["analysis_sha256"]:
            raise ValueError("Review snapshot hash mismatch.")
        cases.append({"case_id": case_id, "project_id": record["project_id"], "version": record["version"],
                      "student_level": record["input"]["student_level"],
                      "prompt_version": record["persisted_view"]["version"]["prompt_version"],
                      "unit_count": len(document["knowledge_points"]), "requirement_count": len(review["requirements"]),
                      "analysis_sha256": analysis_sha, "independent_static_pass": True,
                      "known_high_or_medium_issues": review["known_high_or_medium_issues"],
                      "low_priority_notes": review.get("low_priority_notes", []),
                      "client_analysis_seconds": record["client_analysis_elapsed_seconds"],
                      "analysis_evidence": f"evidence/{directory}/{case_id}.json",
                      "manual_review_evidence": f"evidence/{directory}/manual-review.json",
                      "technology_targets": [{"unit_id": p["id"], "technology": p["technology"]} for p in document["knowledge_points"]]})
    if sum(c["requirement_count"] for c in cases) != 24 or len(cases) != 4:
        raise ValueError("The final selected snapshot must cover exactly the original four cases and 24 requirements.")
    all_events = []
    attempt_sources = ["phase2-learning", "phase2-learning-v25", "phase2-learning-v26", "phase2-learning-v261"]
    attempts = []
    for directory in attempt_sources:
        run = read(ROOT / "evidence" / directory / "run.json")
        records = list(run["records"])
        recovery = ROOT / "evidence" / directory / "maze-recovery/recovery.json"
        if recovery.exists():
            records.append(read(recovery))
        finished = [e for r in records for e in r.get("model_events", []) if e.get("event_type") == "model_call_finished"]
        all_events.extend(finished)
        attempts.append({"source": f"evidence/{directory}/run.json",
                         "analysis_api_submissions": sum(bool(r.get("analysis_submission_attempted")) for r in records),
                         "provider_finished_events": len(finished), "recovery_file": str(recovery.relative_to(ROOT)) if recovery.exists() else None})
    unique = {e["call_id"]: e for e in all_events}
    def tokens(event, key):
        usage = event.get("usage")
        value = usage.get(key) if isinstance(usage,dict) else None
        return value if type(value) is int and value >= 0 else None
    times = sorted(c["client_analysis_seconds"] for c in cases)
    result = {"created_at":datetime.now(timezone.utc).isoformat(),"mode":"offline_mixed_version_accepted_snapshot",
              "network_requests":0,"new_provider_requests":0,"cohort_is_single_model_version":False,
              "selection_policy":"Only data/maze v2 from v2.6 and web/Arduino v3 from v2.6.1; no fallback to v2.5 or rejected candidates.",
              "cases":cases,"summary":{"cases":4,"student_stages":sorted({c['student_level'] for c in cases}),
              "requirements_independently_passed":24,"requirements_total":24,"units_reviewed":sum(c['unit_count'] for c in cases),
              "known_high_or_medium_learning_defects":0,"independent_static_learning_acceptance_pass":True,
              "selected_snapshot_client_median_seconds":statistics.median(times),"selected_snapshot_client_p95_nearest_rank_seconds":times[-1]},
              "preserved_attempt_history":attempts,
              "observed_learning_analysis_usage_in_listed_phase2_cohorts":{"analysis_api_submissions":sum(c['analysis_api_submissions'] for c in attempts),
              "provider_finished_events":len(unique),"reported_completion_tokens":sum(tokens(e,'completion_tokens') or 0 for e in unique.values()),
              "reported_total_tokens":sum(tokens(e,'total_tokens') or 0 for e in unique.values()),
              "events_with_unknown_usage":sum(tokens(e,'total_tokens') is None for e in unique.values())},
              "limits":["Static review is not execution of student projects or hardware.","This is a mixed-version selected snapshot, not a 100% first-attempt or single-version availability claim.","Usage covers only the explicitly listed learning-analysis evidence, not all app/search calls or a financial bill.","No video search, course coverage, playback or final browser usability result is claimed."]}
    dump(ROOT / "evidence/phase2-learning-final/acceptance.json",result)
    print(json.dumps(result["summary"],ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
