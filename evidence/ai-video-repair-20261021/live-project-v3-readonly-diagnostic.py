"""Read-only running-job diagnostic; never opens a writable Store or requests HTTP."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation
from backend.app.ranking import has_video_evidence

JOB = "0fb26395-7ae9-4fd5-9d48-2d481407323a"
connection = sqlite3.connect((ROOT / "data/discovery.sqlite3").as_uri() + "?mode=ro", uri=True)
connection.execute("BEGIN")
job = json.loads(connection.execute("SELECT data FROM jobs WHERE id=?", (JOB,)).fetchone()[0])
resources = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT id,data FROM resources WHERE job_id=?", (JOB,))}
evidence = {rid: [] for rid in resources}
for rid, raw in connection.execute("SELECT resource_id,data FROM evidence WHERE job_id=?", (JOB,)):
    evidence.setdefault(rid, []).append(json.loads(raw))
attempts = [json.loads(row[0]) for row in connection.execute("SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (JOB,))]
second = json.loads(connection.execute("SELECT data FROM jobs WHERE id=?", ("f24a3b59-87e5-4e24-85e8-8804830d2c96",)).fetchone()[0])
connection.close()
request = SearchRequest.model_validate(job["request"])

def resource_summary(r):
    return {key: r.get(key) for key in ("resource_id", "title", "canonical_url", "fetch_status", "fetch_error", "fetched_at", "video_evidence_status", "requires_payment", "cache")}

report = {"observed_at": datetime.now(timezone.utc).isoformat(), "read_only": True, "network_requests": 0,
    "job": {key: job.get(key) for key in ("job_id", "status", "phase", "created_at", "updated_at", "progress", "ai_video_fallback")},
    "followup_pending": job.get("platform_search", {}).get("followup_pending"),
    "second_batch": {key: second.get(key) for key in ("job_id", "status", "phase", "progress")}, "points": []}
for point in job["knowledge_points"][1:3]:
    pid = point["knowledge_point_id"]
    bound = [resource for rid, resource in resources.items() if any(row.get("knowledge_point_id") == pid and row.get("kind") in {"search", "ai_suggestion", "page_link"} for row in evidence[rid])]
    usable = []
    for rid, resource in resources.items():
        if resource.get("fetch_status") not in {"fetched", "success"} or resource.get("requires_payment") is True or resource.get("cache", {}).get("stale"):
            continue
        if not has_video_evidence(resource, evidence[rid]):
            continue
        related = related_recommendation(point, resource, evidence[rid], request)
        if related and set(related["reference"]["basis"]) & {"page", "catalog"}:
            usable.append({**resource_summary(resource), "basis": related["reference"]["basis"], "evidence_ids": related["reference"]["evidence_ids"]})
    selected = [a for a in attempts if a.get("knowledge_point_id") == pid]
    records = []
    for attempt in selected[-8:]:
        row = {key: attempt.get(key) for key in ("executed_at", "query", "provider", "search_phase", "status", "error_code", "candidate_count", "cache_hit", "network_attempted")}
        row["provider_requests"] = [{key: request.get(key) for key in ("status", "http_status", "error_code", "elapsed_seconds", "candidate_count")} for request in attempt.get("provider_requests", [])]
        records.append(row)
    report["points"].append({"point": point, "bound_resource_count": len(bound), "fetch_counts": dict(Counter(row["fetch_status"] for row in bound)),
        "attempted_resources": [resource_summary(r) for r in bound if r["fetch_status"] != "not_fetched"],
        "unfetched_examples": [resource_summary(r) for r in bound if r["fetch_status"] == "not_fetched"][:6],
        "own_page_references_now": usable, "attempt_status_counts": dict(Counter((str(a.get("provider")) + ":" + str(a.get("error_code") or a.get("status"))) for a in selected)),
        "last_attempts": records})
output = ROOT / "evidence/ai-video-repair-20261021/live-project-v3-readonly-diagnostic.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"job_status": job["status"], "phase": job["phase"], "fallback": job.get("ai_video_fallback"),
    "points": [{"text": p["point"]["text"], "fetch_counts": p["fetch_counts"], "usable_now": len(p["own_page_references_now"]),
                "attempt_status_counts": p["attempt_status_counts"], "last_attempts": p["last_attempts"][-3:]} for p in report["points"]]}, ensure_ascii=True))
