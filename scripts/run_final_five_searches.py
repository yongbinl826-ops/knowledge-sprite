"""Run the five approved synthetic cases sequentially after reviewed fixes.

Default is a zero-network plan. --live uses the existing checkpointed runner;
any uncertain/nonterminal outcome stops the sequence without resubmission.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TASKS = [
    ("evidence/phase2-search-r7-preparation-data-maze/source_run.json",
     "evidence/phase2-search-r7-preparation-data-maze/manual_review.json",
     "evidence/phase2-search-r7-data-maze", "project-analysis-v2.6-bounded-semantic-review"),
    ("evidence/phase2-search-r7-preparation-web-arduino/source_run.json",
     "evidence/phase2-search-r7-preparation-web-arduino/manual_review.json",
     "evidence/phase2-search-r7-web-arduino", "project-analysis-v2.6.1-review-repair-context"),
    ("evidence/phase2-dashboard-analysis/run.json",
     "evidence/phase2-dashboard-analysis/manual-review.json",
     "evidence/phase2-search-r7-dashboard", "project-analysis-v2.6.1-review-repair-context"),
]
R8_TASKS = [
    ("evidence/phase2-search-r8-preparation-data-maze/source_run.json",
     "evidence/phase2-search-r8-preparation-data-maze/manual_review.json",
     "evidence/phase2-search-r8-data-maze", "project-analysis-v2.6-bounded-semantic-review"),
    ("evidence/phase2-search-r8-preparation-web-arduino/source_run.json",
     "evidence/phase2-search-r8-preparation-web-arduino/manual_review.json",
     "evidence/phase2-search-r8-web-arduino", "project-analysis-v2.6.1-review-repair-context"),
    ("evidence/phase2-search-r8-preparation-dashboard/source_run.json",
     "evidence/phase2-search-r8-preparation-dashboard/manual_review.json",
     "evidence/phase2-search-r8-dashboard", "project-analysis-v2.6.1-review-repair-context"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--campaign", choices=("r7", "r8"), default="r7")
    args = parser.parse_args()
    tasks = R8_TASKS if args.campaign == "r8" else TASKS
    if not args.live:
        print(json.dumps({"mode": "plan_only", "campaign": args.campaign, "cases": 5, "groups": tasks,
                          "http_requests": 0, "analysis_submissions": 0}))
        return 0
    if not args.runtime_manifest or not args.runtime_pid:
        parser.error("Live execution requires the verified current runtime manifest and PID.")
    # Validate all approvals and fresh output folders before the first write.
    sys.path.insert(0, str(ROOT))
    from scripts.phase2_search_acceptance import make_plan
    for source, manual, output, prompt in tasks:
        make_plan(ROOT / source, ROOT / manual, None, prompt)
        if (ROOT / output / "run.json").exists():
            raise ValueError("Existing checkpoint: observe its original runner; never resubmit.")
    shared = ["--live", "--base-url", args.base_url,
        "--runtime-manifest", str(args.runtime_manifest.resolve()),
        "--runtime-pid", str(args.runtime_pid),
        "--runtime-prompt", "project-analysis-v2.6.1-review-repair-context"]
    for index, (source, manual, output, prompt) in enumerate(tasks, 1):
        print(json.dumps({"group": index, "status": "starting_approved_runner"}), flush=True)
        result = subprocess.run([sys.executable, "-X", "utf8",
            str(ROOT / "scripts/phase2_search_acceptance.py"), *shared,
            "--source-run", source, "--manual-review", manual,
            "--output", output, "--expected-prompt", prompt], cwd=ROOT)
        if result.returncode:
            print(json.dumps({"group": index, "status": "stopped_no_resubmission",
                              "returncode": result.returncode}), flush=True)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
