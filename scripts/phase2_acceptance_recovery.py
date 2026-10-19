"""One explicitly authorized same-project recovery; preserves first-round files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from phase2_acceptance import CASES, ROOT, dump, event_count, input_for, local_url, new_analysis_events, now, observe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--model-events", type=Path, required=True)
    parser.add_argument("--expected-prompt", default="project-analysis-v2.4-explicit-technology")
    parser.add_argument("--directory", type=Path, default=ROOT / "evidence" / "phase2-learning")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(ROOT):
        parser.error("Evidence must stay inside the workspace.")
    case = next(c for c in CASES if c["id"] == args.case)
    original = json.loads((directory / f"{args.case}.json").read_text(encoding="utf-8"))
    output = directory / "maze-recovery"
    path = output / "recovery.json"
    if path.exists():
        parser.error("Recovery was already checkpointed. Inspect it; do not repeat the mutation.")
    if original.get("project_id") != args.project_id or original.get("version") != args.expected_version:
        parser.error("The approved project/version does not match first-round evidence.")
    failures = [e for e in original.get("model_events", []) if e.get("event_type") == "model_call_finished"]
    if not (len(failures) == 1 and failures[0].get("failure_type") == "ConnectTimeout"
            and failures[0].get("http_status") is None and original["status"] == "analysis_failed"):
        parser.error("The preserved first attempt is not the explicitly approved connection failure.")
    record = {"case_id": args.case, "project_id": args.project_id,
              "prior_version": args.expected_version, "input": input_for(case),
              "status": "recovery_preflight", "created_at": now(),
              "authorization": "Parent explicitly authorized one same-input same-project new-version recovery after the first ConnectTimeout; not a first-round success.",
              "first_round_evidence": str(directory / f"{args.case}.json")}
    with httpx.Client(base_url=local_url(args.base_url),timeout=10,follow_redirects=False,trust_env=False) as client:
        capability = client.get("/api/capabilities")
        capability.raise_for_status()
        if capability.json()["project_analysis"]["prompt_version"] != args.expected_prompt:
            raise RuntimeError("Analysis prompt changed; recovery not submitted.")
        response = client.get(f"/api/projects/{args.project_id}")
        response.raise_for_status()
        view = response.json()
        version = view.get("version") or {}
        if not (view["current_version"] == args.expected_version and version.get("status") == "analysis_failed"
                and version.get("input") == record["input"]):
            raise RuntimeError("The project is not the approved failed version with unchanged input; no submission.")
        record["preflight_view"] = view
        offset = event_count(args.model_events)
        record.update(status="analysis_submission_pending",analysis_submission_attempted=True,
                      analysis_submitted_at=now(),model_event_start_line=offset)
        dump(path,record)
        try:
            submitted = client.post(f"/api/projects/{args.project_id}/analyze",json={"expected_version":args.expected_version})
            record["analysis_http_status"] = submitted.status_code
            submitted.raise_for_status()
            record["analysis_submission_response"] = submitted.json()
        except (httpx.HTTPError,ValueError):
            record["submission_outcome_uncertain"] = True
        observe(client,{"records":[record]},record,case,output,150)
        record["model_events"] = new_analysis_events(args.model_events,offset)
        dump(path,record)
        (output / "model-events.jsonl").write_text("".join(json.dumps(e,ensure_ascii=False)+'\n' for e in record['model_events']),encoding='utf-8')
    print(json.dumps({k:record.get(k) for k in ['case_id','project_id','prior_version','version','status','client_analysis_elapsed_seconds']},ensure_ascii=False))
    return 0 if record["status"] == "analyzed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
