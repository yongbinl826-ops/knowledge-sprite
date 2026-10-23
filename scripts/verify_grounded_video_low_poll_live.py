"""Authorized live project replay with lightweight polling and one final projection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import time

import httpx

from verify_grounded_video_live import coverage, save


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    with httpx.Client(base_url=args.base, timeout=60, trust_env=False) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        capabilities = get("/api/capabilities")
        assert capabilities["ai_video_fallback"]["policy_version"] == "grounded-video-v2"
        save(args.output / "capabilities.json", capabilities)
        original = get(f"/api/projects/{args.project}")
        assert original["current_version"] == args.expected_version
        source = get(f"/api/projects/{args.project}?version={args.source_version}")
        save(args.output / "project-before.json", original)
        save(args.output / "project-source.json", source)
        prior = source["version"]
        assert prior["analysis"] and prior["input"] == original["version"]["input"]
        current = post(f"/api/projects/{args.project}/edit", {
            "expected_version": args.expected_version, "input": prior["input"], "analysis": prior["analysis"]})
        version = current["current_version"]
        assert version == args.expected_version + 1
        assert current["version"]["analysis"] == prior["analysis"]
        confirmation = prior.get("confirmation") or {}
        body = {"version": version, "acknowledged_skipped_prerequisites":
                confirmation.get("acknowledged_skipped_prerequisites", [])}
        if confirmation.get("topic_technologies"):
            body["reviewed_topic_technologies"] = confirmation["topic_technologies"]
        post(f"/api/projects/{args.project}/confirm", body)
        created = post(f"/api/projects/{args.project}/search", {"version": version})
        save(args.output / "created.json", created)
        selected = [point for point in prior["analysis"]["knowledge_points"] if point["selection"] == "learn"]
        print(json.dumps({"started": True, "project_id": args.project, "version": version,
                          "expected_points": len(selected), "poll_seconds": args.poll_seconds}, ensure_ascii=False), flush=True)

        # Reading this exact local version obtains new batch IDs without calling
        # the expensive project view. No SQL mutation or network-source request
        # occurs here; job state itself is read through the public API.
        uri = "file:" + args.database.resolve().as_posix() + "?mode=ro"
        observations, previous, start = [], None, time.monotonic()
        while True:
            with sqlite3.connect(uri, uri=True) as connection:
                row = connection.execute("SELECT data FROM project_versions WHERE project_id=? AND version=?",
                                         (args.project, version)).fetchone()
                assert row
                state = json.loads(row[0])
            jobs = []
            for batch in state["batches"]:
                if batch.get("job_id"):
                    job = get(f"/api/search-jobs/{batch['job_id']}")
                    jobs.append(job)
                    save(args.output / f"job-{job['job_id']}.json", job)
            observation = {"seconds": round(time.monotonic() - start), "project_status": state["status"],
                "jobs": [{"job_id": job["job_id"], "status": job["status"], "phase": job.get("phase"),
                          "followup_pending": job.get("platform_search", {}).get("followup_pending"),
                          "fallback": job.get("ai_video_fallback"), "progress": job.get("progress")}
                         for job in jobs]}
            observations.append(observation)
            save(args.output / "observations.json", observations)
            significant = {"project_status": state["status"], "jobs": [
                {key: value for key, value in job.items() if key != "progress"} for job in observation["jobs"]]}
            if significant != previous:
                print(json.dumps({"seconds": observation["seconds"], **significant}, ensure_ascii=False), flush=True)
                previous = significant
            if (state["status"] not in {"running", "analyzing"}
                    and len(jobs) == len(state["batches"])
                    and all(job["status"] not in {"queued", "running"}
                            and not job.get("platform_search", {}).get("followup_pending") for job in jobs)):
                break
            if time.monotonic() - start > 1800:
                raise TimeoutError("Acceptance timed out; live jobs retained, no cancellation")
            time.sleep(args.poll_seconds)

        result_path = f"/api/projects/{args.project}/results?version={version}"
        request_start = time.perf_counter()
        result = get(result_path)
        final_result_seconds = round(time.perf_counter() - request_start, 4)
        save(args.output / "results.json", result)
        groups = coverage(result)
        with sqlite3.connect(uri, uri=True) as connection:
            for job in jobs:
                for table in ("search_attempts", "resources", "evidence"):
                    rows = [json.loads(row[0]) for row in connection.execute(
                        "SELECT data FROM " + table + " WHERE job_id=?", (job["job_id"],))]
                    save(args.output / f"{table}-{job['job_id']}.json", rows)
        report = {"base_url": args.base, "result_path": result_path, "status": result["version"]["status"],
            "scope": "normal live API mutation; existing reviewed analysis; configured sources; no URL injection",
            "polling": "read-only local batch-ID lookup; lightweight job GET every 30 seconds; one final results GET",
            "source_version": args.source_version, "version": version, "expected_points": len(selected),
            "covered_points": sum(bool(group["verified_videos"]) for group in groups), "groups": groups,
            "final_result_seconds": final_result_seconds, "playback_verified_by_this_script": False}
        save(args.output / "report.json", report)
        print(json.dumps({key: value for key, value in report.items() if key != "groups"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--project", required=True)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--source-version", type=int, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=30)
    arguments = parser.parse_args()
    if arguments.poll_seconds < 25:
        parser.error("Live results acceptance polling must be at least 25 seconds")
    main(arguments)
