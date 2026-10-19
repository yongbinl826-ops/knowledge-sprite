"""Final same-project v2.6 cohort; default is an offline plan, not a model call.

One analysis POST per existing project. A checkpoint precedes each POST. A lost
response is reconciled by reading the expected new version, never by POSTing
again. The separate --observe-only mode also cannot create or analyze anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase2_acceptance import CASES, dump, input_for, local_url, now, observations


EXPECTED_PROMPT = "project-analysis-v2.6-bounded-semantic-review"
REQUIRED_RUNTIME_FILES = (
    "backend/app/analysis_review.py", "backend/app/project_analysis.py",
    "backend/app/config.py", "backend/app/llm.py",
)
TERMINAL = {"analyzed", "analysis_failed", "analysis_rejected"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_plan(source: Path, selected_ids: list[str] | None = None,
              expected_prompt: str = EXPECTED_PROMPT) -> dict:
    prior = json.loads(source.read_text(encoding="utf-8"))
    prior_cases = {r["case_id"]: r for r in prior["records"]}
    records = []
    for case in CASES:
        saved = prior_cases[case["id"]]
        if saved.get("status") != "analyzed" or saved["input"] != input_for(case):
            raise ValueError("The v2.5 source must be completed and match the original synthetic input exactly.")
        records.append({"case_id": case["id"], "project_id": saved["project_id"],
                        "source_version": saved["version"], "input": saved["input"], "status": "not_submitted"})
    if len(records) != 4 or len({r["project_id"] for r in records}) != 4:
        raise ValueError("Four distinct existing projects are required.")
    rubric_source = source.parent / "manual-review-before-duration-fix.json"
    rubric = json.loads(rubric_source.read_text(encoding="utf-8"))
    requirements = [{"case_id": c["case_id"], "requirements": [
        {"id": r["id"], "requirement": r["requirement"]} for r in c["requirements"]]}
        for c in rubric["case_reviews"]]
    if sum(len(c["requirements"]) for c in requirements) != 24:
        raise ValueError("The fixed independent 24-requirement rubric is missing or changed.")
    original_ids = {r["case_id"] for r in records}
    selected = set(selected_ids) if selected_ids else original_ids
    if not selected or not selected <= original_ids:
        raise ValueError("Select only the original synthetic cases.")
    records = [r for r in records if r["case_id"] in selected]
    requirements = [r for r in requirements if r["case_id"] in selected]
    return {"mode": "offline_plan", "created_at": now(), "source_run": str(source), "source_run_sha256": sha(source),
            "expected_prompt": expected_prompt, "classification": "same_synthetic_non_sensitive_inputs",
            "selected_count": len(records), "selected_cases": [r["case_id"] for r in records],
            "original_cohort_requirement_total": 24,
            "selected_requirement_total": sum(len(r["requirements"]) for r in requirements),
            "limits": {"max_analysis_api_submissions": len(records), "per_analysis_max_model_calls": 4,
                       "max_generation_calls": 2, "max_semantic_review_calls": 2,
                       "review_completion_token_cap": 1500, "server_total_budget_seconds": 120,
                       "client_observation_deadline_seconds": 150, "search_submissions": 0},
            "semantic_acceptance": "Independently review the selected cases from the fixed original 24-requirement rubric; preserve source numeric/equality boundaries, concrete tasks, prerequisites, tool relevance, debounce and persistent post-win events. Model review success alone is insufficient.",
            "rubric_source": str(rubric_source), "rubric_source_sha256": sha(rubric_source),
            "independent_requirement_rubric": requirements,
            "numeric_boundary_probes": [probe for probe in [
                {"case_id": "bicycle_csv_advanced", "probe": "Equal nonmissing start/end timestamps", "expected": "Valid under the stated end<start invalidity rule; duration_min=0 is retained, not required to be strictly positive."},
                {"case_id": "bicycle_csv_advanced", "probe": "End before start, missing or unparseable timestamp", "expected": "Excluded from valid aggregates and recorded under the stated invalid reason."},
                {"case_id": "web_pomodoro_beginner", "probe": "Remaining time reaches exactly zero", "expected": "Transition once, pause the next fixed 25/5-minute stage, and increment only completed focus."},
                {"case_id": "arduino_reaction_beginner", "probe": "Active-low input, random 2-5-second window and repeated raw bounce", "expected": "LOW means pressed; a real stable-input condition precedes press edges, timing remains responsive and within the requested range."},
                {"case_id": "pygame_maze_intermediate", "probe": "Candidate row/column is -1 or 8 in an 8x8 map", "expected": "Reject before list access; valid indices remain 0-7, and won state still processes reset/quit."},
            ] if probe["case_id"] in selected],
            "records": records}


def runtime_binding(path: Path, base_url: str, expected_pid: int | None) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = {k.replace("\\", "/"): v for k, v in manifest.get("files", {}).items()}
    checks = {}
    backend_files = {name for name in files if name.startswith("backend/app/")}
    for relative in sorted(set(REQUIRED_RUNTIME_FILES) | backend_files):
        current = ROOT / relative
        if (not current.resolve().is_relative_to(ROOT) or relative not in files
                or not current.is_file() or sha(current) != files[relative]):
            raise ValueError(f"The confirmed runtime manifest does not match {relative}; no analysis submitted.")
        checks[relative] = files[relative]
    port = urlsplit(base_url).port or (443 if base_url.startswith("https:") else 80)
    if (manifest.get("port") != port or Path(manifest.get("root", "")).resolve() != ROOT
            or (expected_pid is not None and manifest.get("pid") != expected_pid)):
        raise ValueError("The manifest does not match the confirmed local runtime.")
    return {"source": str(path), "source_sha256": sha(path), "pid": manifest.get("pid"),
            "root": manifest.get("root"), "port": manifest.get("port"), "files": checks}


def nested(value: dict, path: str):
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def event_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def collect_events(path: Path, offset: int) -> list[dict]:
    result = []
    for line in event_lines(path)[offset:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(event.get("task", "")).startswith("project_analysis"):
            result.append(event)
    return result


def poll(client: httpx.Client, record: dict, deadline: float, checkpoint) -> None:
    started = time.monotonic()
    expected = record["expected_new_version"]
    while time.monotonic() - started < deadline:
        try:
            response = client.get(f"/api/projects/{record['project_id']}", params={"version": expected})
            if response.status_code == 404:
                record["last_read_status"] = "expected_version_not_observed"
                # Read current state for evidence; absence is never permission to POST again.
                current = client.get(f"/api/projects/{record['project_id']}")
                if current.is_success:
                    record["current_after_uncertain_submission"] = current.json()
                checkpoint()
                time.sleep(1)
                continue
            response.raise_for_status()
            view = response.json()
            version = view.get("version") or {}
            if version.get("version") != expected or version.get("input") != record["input"]:
                record.update(status="unexpected_version_or_input", note="Observed data does not match the exact submitted cohort; no repeat submission.")
                return
            record["last_observed_status"] = version.get("status")
            if version.get("status") in {"analyzed", "analysis_failed"}:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(record["analysis_submitted_at"])).total_seconds()
                record.update(status=version["status"], version=expected, persisted_view=view,
                              completed_at=now(), client_analysis_elapsed_seconds=round(elapsed, 6), error=version.get("error"))
                case = next(c for c in CASES if c["id"] == record["case_id"])
                record["observations"] = observations(case, view, elapsed)
                return
        except (httpx.HTTPError, ValueError):
            record["last_read_status"] = "local_api_read_failed"
        checkpoint()
        time.sleep(1)
    record.update(status="observation_deadline_pending", note="No automatic retry. Read this exact known project/version before any further action.")


def summary(run: dict) -> dict:
    records = run["records"]
    finished = [e for r in records for e in r.get("model_events", []) if e.get("event_type") == "model_call_finished"]
    reviews = [e for e in finished if e.get("task") == "project_analysis_review"]
    configured_review_cap = run.get("analysis_capability", {}).get("review_max_output_tokens", 1500)
    def tokens(event: dict, field: str) -> int | None:
        usage = event.get("usage")
        value = usage.get(field) if isinstance(usage, dict) else None
        return value if type(value) is int and value >= 0 else None
    review_usage_known = bool(reviews) and all(tokens(e, "completion_tokens") is not None for e in reviews)
    return {"expected_selected_count": run.get("selected_count", len(records)),
            "analysis_api_submissions": sum(bool(r.get("analysis_submission_attempted")) for r in records),
            "completed_analyses": sum(r["status"] == "analyzed" for r in records),
            "failed_analyses": sum(r["status"] == "analysis_failed" for r in records),
            "pending_or_unsubmitted": sum(r["status"] not in TERMINAL for r in records),
            "generation_model_events": sum(e.get("task") == "project_analysis" for e in finished),
            "review_model_events": len(reviews), "all_model_finished_events": len(finished),
            "reported_completion_tokens": sum(tokens(e, "completion_tokens") or 0 for e in finished),
            "reported_total_tokens": sum(tokens(e, "total_tokens") or 0 for e in finished),
            "model_calls_with_unknown_usage": sum(tokens(e, "total_tokens") is None for e in finished),
            "per_case_max4_model_events_met": all(sum(e.get("event_type") == "model_call_finished" for e in r.get("model_events", [])) <= 4 for r in records),
            "configured_review_completion_cap": configured_review_cap,
            "review_1500_completion_cap_observed": all(tokens(e, "completion_tokens") <= 1500 for e in reviews) if review_usage_known else None,
            "review_operator_completion_cap_observed": all(tokens(e, "completion_tokens") <= configured_review_cap for e in reviews) if review_usage_known else None,
            "successful_cases_have_observed_review_call": all(any(e.get("event_type") == "model_call_finished" and e.get("task") == "project_analysis_review" for e in r.get("model_events", [])) for r in records if r["status"] == "analyzed"),
            "search_submissions": 0, "manual_semantic_acceptance_pass": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--observe-only", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--case", action="append", choices=[c["id"] for c in CASES])
    scope.add_argument("--cases", nargs="+", choices=[c["id"] for c in CASES])
    parser.add_argument("--source", type=Path, default=ROOT / "evidence/phase2-learning-v25/run.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/phase2-learning-v26")
    parser.add_argument("--base-url")
    parser.add_argument("--expected-prompt", default=EXPECTED_PROMPT)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--model-events", type=Path)
    parser.add_argument("--deadline", type=float, default=150)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or not args.source.resolve().is_relative_to(ROOT) or not 1 <= args.deadline <= 180:
        parser.error("Evidence/source paths must stay in the workspace; the observation deadline must be 1-180 seconds.")
    path = output / "run.json"
    requested_cases = args.case or args.cases
    existing_run = None
    if args.live and path.exists():
        parser.error("run.json already exists; inspect it with --observe-only. Never repeat an uncertain POST.")
    if args.observe_only:
        if not path.exists():
            parser.error("No existing run checkpoint to observe.")
        existing_run = json.loads(path.read_text(encoding="utf-8"))
        existing_cases = [r["case_id"] for r in existing_run["records"]]
        if requested_cases and set(requested_cases) != set(existing_cases):
            parser.error("Read-only observation must retain the existing selected cases.")
        requested_cases = existing_cases
    plan = make_plan(args.source, requested_cases, args.expected_prompt)
    dump(output / "plan.json", plan)
    if not args.live and not args.observe_only:
        print(json.dumps({"mode": "offline_plan", "network_requests": 0, "analysis_api_submissions": 0,
                          "selected_count": len(plan["records"]),
                          "existing_projects": [r["project_id"] for r in plan["records"]]}))
        return 0
    if not args.base_url or not args.runtime_manifest or not args.model_events:
        parser.error("Live/read-only observation requires the explicitly confirmed local runtime, manifest and model-event file.")
    base = local_url(args.base_url)
    binding = runtime_binding(args.runtime_manifest, base, args.runtime_pid)
    run = existing_run if args.observe_only else {
        **plan, "mode": "live_same_project_regression", "started_at": now(), "base_url": base,
        "max_analysis_submissions": len(plan["records"]), "runtime_binding": binding, "model_events_source": str(args.model_events)}
    with httpx.Client(base_url=base,timeout=10,follow_redirects=False,trust_env=False) as client:
        capability = client.get("/api/capabilities")
        capability.raise_for_status()
        caps = capability.json()
        analysis_caps = caps.get("project_analysis", {})
        if (nested(caps,"project_analysis.prompt_version") != args.expected_prompt
                or nested(caps,"project_analysis.status") != "configured"
                or analysis_caps.get("semantic_review_enabled") is not True
                or analysis_caps.get("max_model_calls") != 4
                or type(analysis_caps.get("review_max_output_tokens")) is not int
                or not 1 <= analysis_caps["review_max_output_tokens"] <= 1500):
            raise ValueError("The configured prompt or explicitly enabled semantic review does not match; no POST submitted.")
        run["analysis_capability"] = caps["project_analysis"]
        if args.live:
            # Verify every existing project before spending a single model call.
            for record in run["records"]:
                response = client.get(f"/api/projects/{record['project_id']}")
                response.raise_for_status()
                view = response.json()
                version = view.get("version") or {}
                if (view.get("original_input") != record["input"] or version.get("input") != record["input"]
                        or view["current_version"] < record["source_version"] or version.get("status") == "analyzing"):
                    raise ValueError("Existing project input/version is changed or still analyzing; no cohort submitted.")
                record.update(preflight_view=view, expected_version=view["current_version"],
                              expected_new_version=view["current_version"] + 1)
        dump(path,run)
        for record in run["records"]:
            if record["status"] in TERMINAL or (args.observe_only and not record.get("analysis_submission_attempted")):
                continue
            if args.live:
                offset = len(event_lines(args.model_events))
                record.update(status="analysis_submission_pending",analysis_submission_attempted=True,
                              analysis_submitted_at=now(),model_event_start_line=offset)
                dump(path,run)
                try:
                    response = client.post(f"/api/projects/{record['project_id']}/analyze",json={"expected_version":record["expected_version"]})
                    record["analysis_http_status"] = response.status_code
                    if 400 <= response.status_code < 500:
                        record.update(status="analysis_rejected",note="Known HTTP rejection; not retried.")
                        dump(path,run)
                        continue
                    response.raise_for_status()
                    record["analysis_submission_response"] = response.json()
                except (httpx.HTTPError,ValueError):
                    record["submission_outcome_uncertain"] = True
            poll(client,record,args.deadline,lambda:dump(path,run))
            record["model_events"] = collect_events(args.model_events,record["model_event_start_line"])
            dump(output / f"{record['case_id']}.json",record)
            run["summary"] = summary(run)
            dump(path,run)
            print(json.dumps({k:record.get(k) for k in ["case_id","project_id","expected_version","version","status","client_analysis_elapsed_seconds"]}),flush=True)
            if record["status"] not in TERMINAL:
                break
    run["last_observed_at"] = now()
    run["summary"] = summary(run)
    dump(path,run)
    events = [e for r in run["records"] for e in r.get("model_events",[])]
    (output / "model-events.jsonl").write_text("".join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
    print(json.dumps(run["summary"],ensure_ascii=False))
    return 0 if run["summary"]["completed_analyses"] == len(run["records"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
