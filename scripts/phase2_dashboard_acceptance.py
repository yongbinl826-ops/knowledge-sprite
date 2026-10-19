"""One predeclared synthetic dashboard analysis; no confirm/search endpoints.

Reuse the checkpointed analysis harness. The fixed rubric precedes generation;
keyword observations remain heuristics requiring independent manual review.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import phase2_acceptance as harness
from scripts.phase2_acceptance_v26 import runtime_binding, sha


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case-file", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    known, remaining = parser.parse_known_args()
    case_path = known.case_file.resolve()
    if not case_path.is_relative_to(ROOT / "evidence"):
        raise ValueError("Predeclared synthetic case must be workspace evidence.")
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if case.get("synthetic_input") is not True or case.get("case_id") != "study_room_streamlit_intermediate":
        raise ValueError("Only the predeclared synthetic dashboard case is allowed.")
    control = argparse.ArgumentParser(add_help=False)
    control.add_argument("--live", action="store_true")
    control.add_argument("--observe-only", action="store_true")
    control.add_argument("--base-url")
    control.add_argument("--runtime-pid", type=int)
    control.add_argument("--max-analyses", type=int, required=True)
    control.add_argument("--output", type=Path, required=True)
    args, _ = control.parse_known_args(remaining)
    if args.max_analyses != 1:
        raise ValueError("Exactly one analysis submission is allowed.")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "evidence"):
        raise ValueError("Evidence output must stay in the workspace evidence folder.")
    if (output / "run.json").exists() and not args.observe_only:
        raise ValueError("Existing checkpoint permits observation only; never resubmit.")
    binding = runtime_binding(known.runtime_manifest.resolve(), args.base_url, args.runtime_pid)
    harness.CASES = [{"id": case["case_id"], "input": case["input"],
        "coverage": [("Streamlit upload", r"streamlit|file_uploader"),
                     ("Validation", r"to_datetime|to_numeric|校验|验证|清洗"),
                     ("Filtering", r"date_input|multiselect|筛选"),
                     ("Weighted metrics", r"metric|加权|分子"),
                     ("Grouped bar", r"bar_chart|条形|分组"),
                     ("Recoverable empty state", r"st\.stop|空|无结果|零")],
        "manual_checks": [row["requirement"] for row in case["independent_rubric"]]}]
    sys.argv = [str(Path(__file__)), *remaining]
    result = harness.main()
    if (output / "run.json").exists():
        run = json.loads((output / "run.json").read_text(encoding="utf-8"))
        run.update(runtime_binding=binding, predeclared_case=str(case_path),
                   predeclared_case_sha256=sha(case_path),
                   confirm_submissions=0, search_submissions=0,
                   keyword_observations_are_manual_acceptance=False)
        harness.dump(output / "run.json", run)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
