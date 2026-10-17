"""Read-only verification of the single live UI run; never submits a search."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT / "reports/platform-live-chain-20261017"
JOB = "426f60d1-22cf-4b43-89fd-c0d805bfa974"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    db = sqlite3.connect(f"file:{(PHASE / 'live.sqlite3').as_posix()}?mode=ro", uri=True)
    job = json.loads(db.execute("SELECT data FROM jobs WHERE id=?", (JOB,)).fetchone()[0])
    assert job["status"] == "partial"
    resources = [json.loads(row[0]) for row in db.execute("SELECT data FROM resources WHERE job_id=?", (JOB,))]
    attempts = [json.loads(row[0]) for row in db.execute("SELECT data FROM search_attempts WHERE job_id=?", (JOB,))]
    evidence = [json.loads(row[0]) for row in db.execute("SELECT data FROM evidence WHERE job_id=?", (JOB,))]
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert all(not item["cache_hit"] for item in attempts)
    assert not any(item["chapters"] for item in resources)
    assert not any(item["kind"] in {"page", "catalog"} for item in evidence)
    assert job["fetch_diagnostics"]["counts_delta"] == {}
    assert job["progress"]["details_cached"] == 0
    # Exact local API response bytes retain meaningful course/video parameters.
    # This job contains only the public search inputs and search/policy evidence.
    api = {}
    for name, suffix in (("job", ""), ("results", "/results")):
        with urllib.request.urlopen(f"http://127.0.0.1:18018/api/search-jobs/{JOB}{suffix}", timeout=10) as response:
            body = response.read()
            assert response.status == 200
        api[name] = json.loads(body)
        dest = PHASE / f"api-{name}-exact.json"
        if dest.exists():
            assert dest.read_bytes() == body, "Preserve the original live response"
        else:
            dest.write_bytes(body)
    assert api["job"] == job
    resources_by_id = {item["resource_id"]: item for item in resources}
    shown = [item for group in api["results"]["groups"] for key in ("items", "partial_items", "review_items") for item in group[key]]
    assert all(item["resource"]["canonical_url"] == resources_by_id[item["resource"]["resource_id"]]["canonical_url"] for item in shown)
    # Frozen DB copy is evidence, not input to a new search.
    snapshot = PHASE / "completed-live.sqlite3"
    if not snapshot.exists():
        target = sqlite3.connect(snapshot)
        db.backup(target)
        target.close()
    db.close()
    baseline = read_json(PHASE / "baseline/manifest.json")
    prior = ROOT / "reports/platform-catalog-20261017"
    drift = [name for name, value in baseline["prior_artifact_hashes"].items()
             if not (prior / name).exists() or digest(prior / name) != value]
    assert not drift, drift
    policy_capture = read_json(PHASE / "policy-browser-evidence.json")
    for item in policy_capture["platforms"]:
        name = "bilibili-terms-visible.txt" if item["platform"] == "bilibili" else "mooc-terms-visible.txt"
        assert digest(PHASE / name) == item["body_text_sha256"]
    requests = [request for attempt in attempts for request in attempt.get("provider_requests", [])]
    assert len(requests) == job["progress"]["search_requests"] == 12
    summary = {
        "verified_at": datetime.now(timezone.utc).isoformat(), "job_id": JOB,
        "live_acceptance": {"bilibili_catalog": "blocked_by_explicit_permission_requirement",
                            "icourse163_catalog": "unverified_permission_scope_paused_by_application",
                            "catalog_chain_passed": False},
        "input": job["request"], "job_status": job["status"], "progress": job["progress"],
        "provider_http_statuses": dict(Counter(str(item.get("http_status")) for item in requests)),
        "platform_counts": dict(Counter(item["platform"] for item in resources)),
        "platform_fetch_status_counts": dict(Counter(f'{item["platform"]}:{item["fetch_status"]}' for item in resources)),
        "detail_or_catalog_source_http_requests": 0, "catalog_entries": 0,
        "original_urls_preserved_in_sqlite_and_exact_api": True,
        "sanitized_harness_exports": "jobs/* exports remove query strings; do not infer course identities from those exports",
        "prior_artifacts_unchanged": True, "prior_artifact_count": len(baseline["prior_artifact_hashes"]),
        "original_source_archive": "executed-live-source.zip",
        "notes": ["No course-page source HTTP refusal was observed; policy stopped before network.",
                  "Terms were read from the current official browser pages separately from this job.",
                  "Post-run audit/cache/evidence-scope repairs are offline verified; this live job was not rerun."],
    }
    (PHASE / "live-verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
