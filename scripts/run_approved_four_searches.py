"""Sequential, checkpointed live acceptance using the existing approved runners.

No analysis is submitted. Existing output checkpoints stop resubmission; inspect
the underlying runner's --observe-only mode after any uncertain interruption.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-manifest", required=True, type=Path)
    parser.add_argument("--runtime-pid", required=True, type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    shared = ["--live", "--base-url", args.base_url, "--runtime-manifest", str(args.runtime_manifest.resolve()),
              "--runtime-pid", str(args.runtime_pid), "--runtime-prompt", "project-analysis-v2.6.1-review-repair-context"]
    tasks = [
        ["--source-run", "evidence/phase2-search-retry-preparation-v4/source_run.json",
         "--manual-review", "evidence/phase2-search-retry-preparation-v4/manual_review.json",
         "--output", "evidence/phase2-search-final-data-maze"],
        ["--source-run", "evidence/phase2-learning-v261/run.json",
         "--manual-review", "evidence/phase2-learning-v261/manual-review.json",
         "--expected-prompt", "project-analysis-v2.6.1-review-repair-context",
         "--output", "evidence/phase2-search-final-web-arduino"],
    ]
    for index, extra in enumerate(tasks, 1):
        print(json.dumps({"group": index, "status": "starting_existing_approved_runner", "analysis_submissions": 0}), flush=True)
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/phase2_search_acceptance.py"), *shared, *extra], cwd=ROOT)
        if result.returncode:
            print(json.dumps({"group": index, "status": "stopped_no_resubmission", "returncode": result.returncode}), flush=True)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
