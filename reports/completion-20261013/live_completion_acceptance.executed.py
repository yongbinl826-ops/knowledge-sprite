"""Run only the two preregistered held-out jobs once; never replace failed cases."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "reports/completion-20261013"
OUTPUT = FOLDER / "held-out-live.json"
TERMINAL = {"completed", "partial", "failed", "interrupted", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


def hashes():
    paths = [path for folder in (ROOT / "backend/app", ROOT / "frontend/src")
             for path in folder.rglob("*") if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".css"}]
    paths += [ROOT / "uv.lock", ROOT / "frontend/package-lock.json"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def save(report):
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    if OUTPUT.exists():
        raise SystemExit("Refusing to overwrite the held-out run or rerun its cases")
    scope = json.loads((FOLDER / "scope-and-budget.json").read_text(encoding="utf-8-sig"))
    plan = scope["network_plan"]["held_out_acceptance"]
    report = {"started_at": now(), "mode": "live", "plan": plan, "source_hashes_before": hashes(),
              "jobs": [], "errors": [], "boundaries": [
                  "Two frozen cases; no replacement or retry of failed cases",
                  "Real API requests; no fixtures, seeded URLs, browser fallback or media requests",
                  "HTTP counts distinguish search, target HTML/robots, and uncounted DoH",
                  "Course family is source-scoped; unknown identity is not an independent-course claim",
                  "Automated metadata and catalog evidence do not verify playback"]}
    save(report)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) as client:
        try:
            response = await client.get("/api/capabilities")
            response.raise_for_status()
            report["capabilities_before"] = response.json()
            limits = report["capabilities_before"]["limits"]
            assert limits["global_concurrency"] == 1
            assert limits["max_search_requests"] == plan["per_job_max_search_requests"]
            assert limits["max_detail_pages"] == plan["per_job_max_detail_pages"]
            for index, case in enumerate(plan["cases"]):
                payload = {**case, "student_level": "beginner"}
                key = f"heldout-{uuid.uuid4()}"
                entry = {"case_index": index, "request": payload, "submitted_at": now(), "idempotency_key": key, "snapshots": []}
                report["jobs"].append(entry)
                save(report)
                response = await client.post("/api/search-jobs", json=payload, headers={"Idempotency-Key": key})
                response.raise_for_status()
                entry["create_response"] = response.json()
                job_id = entry["job_id"] = entry["create_response"]["job_id"]
                save(report)
                started = asyncio.get_running_loop().time()
                while True:
                    response = await client.get(f"/api/search-jobs/{job_id}")
                    response.raise_for_status()
                    state = response.json()
                    entry["last_job"] = state
                    snapshot = {"observed_at": now(), "status": state["status"], "phase": state.get("phase"), "progress": state.get("progress")}
                    if not entry["snapshots"] or any(snapshot[k] != entry["snapshots"][-1][k] for k in ("status", "phase", "progress")):
                        entry["snapshots"].append(snapshot)
                        print(json.dumps({"case": index, **snapshot}, ensure_ascii=False), flush=True)
                    save(report)
                    if state["status"] in TERMINAL:
                        break
                    if asyncio.get_running_loop().time() - started > plan["per_job_deadline_seconds"] + 25:
                        raise TimeoutError("Local polling deadline exceeded")
                    await asyncio.sleep(2)
                entry["final_job"] = state
                entry["elapsed_seconds"] = round(asyncio.get_running_loop().time() - started, 3)
                response = await client.get(f"/api/search-jobs/{job_id}/results")
                response.raise_for_status()
                entry["results"] = response.json()
                # Lost POST response recovery: same key after terminal must not create another search.
                response = await client.post("/api/search-jobs", json=payload, headers={"Idempotency-Key": key})
                response.raise_for_status()
                entry["terminal_replay_response"] = response.json()
                if response.json()["job_id"] != job_id:
                    raise AssertionError("Idempotency replay unexpectedly created another job")
                save(report)
            response = await client.get("/api/capabilities")
            response.raise_for_status()
            report["capabilities_after"] = response.json()
        except (httpx.HTTPError, TimeoutError, AssertionError, KeyError, ValueError) as exc:
            report["errors"].append({"type": type(exc).__name__, "observed_at": now(), "message": "Stopped; no case rerun. Inspect retained job state."})
    resources = {}
    for entry in report["jobs"]:
        for group in entry.get("results", {}).get("groups", []):
            for item in [*group["items"], *(item for rows in group["platform_items"].values() for item in rows)]:
                resources[item["resource"]["resource_id"]] = item["resource"]
    report["summary"] = {
        "completed_cases": sum("final_job" in j for j in report["jobs"]),
        "actual_search_http": sum(j.get("final_job", {}).get("progress", {}).get("search_requests", 0) for j in report["jobs"]),
        "search_cache_hits": sum(bool(a.get("cache_hit")) for j in report["jobs"] for a in j.get("results", {}).get("search_attempts", [])),
        "displayed_resources_including_platform_filters": len(resources),
        "displayed_fetch_statuses": dict(Counter(r["fetch_status"] for r in resources.values())),
        "displayed_platforms": dict(Counter(r["platform"] for r in resources.values())),
        "displayed_source_families": len({r["course_identity"]["family_id"] for r in resources.values() if r.get("course_identity", {}).get("family_id")}),
        "displayed_identity_unknown_or_partial": sum(r.get("course_identity", {}).get("status") != "identified" for r in resources.values()),
        "displayed_catalog_rows": sum(len(r.get("chapters", [])) for r in resources.values()),
        "playback_verified": False,
    }
    report["source_hashes_after"] = hashes()
    report["source_unchanged_during_run"] = report["source_hashes_after"] == report["source_hashes_before"]
    report["finished_at"] = now()
    save(report)
    print(json.dumps({"report": str(OUTPUT), "summary": report["summary"], "errors": report["errors"]}, ensure_ascii=False), flush=True)
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
