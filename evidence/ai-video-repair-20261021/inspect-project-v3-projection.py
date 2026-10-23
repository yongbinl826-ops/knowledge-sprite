"""Offline related-video projection using a read-only SQLite snapshot.

No application server/model/fetcher is constructed, and no source fact changes.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendations

database = ROOT / "data/discovery.sqlite3"
source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
copy = sqlite3.connect(":memory:")
source.backup(copy)
source.close()
project_id = "fdfd2ce1-c5c7-4119-81ca-924d6c377c93"
project = json.loads(copy.execute("select data from project_versions where project_id=? and version=3", (project_id,)).fetchone()[0])
result = {"observed_at": datetime.now(timezone.utc).isoformat(), "project_id": project_id, "version": 3,
          "project_status": project["status"], "offline_projection": True, "new_network_requests": 0,
          "source_database_open_mode": "read_only_then_memory_snapshot", "source_facts_changed": False,
          "strict_criterion": "fetch_status=fetched AND video_evidence_status=page_verified AND cache.stale!=true",
          "playback_verified": False, "points": []}
for batch in project["batches"]:
    job_id = batch["job_id"]
    job = json.loads(copy.execute("select data from jobs where id=?", (job_id,)).fetchone()[0])
    request = SearchRequest.model_validate(job["request"])
    resources = {json.loads(raw)["resource_id"]: json.loads(raw) for (raw,) in copy.execute(
        "select data from resources where job_id=?", (job_id,))}
    evidence = {rid: [json.loads(raw) for (raw,) in copy.execute(
        "select data from evidence where job_id=? and resource_id=?", (job_id, rid))] for rid in resources}
    for point in job["knowledge_points"]:
        rows, _ = related_recommendations(point, resources, evidence, request, 5)
        strict = []
        for row in rows:
            resource = resources[row["resource"]["resource_id"]]
            if (resource.get("fetch_status") == "fetched" and resource.get("video_evidence_status") == "page_verified"
                    and not resource.get("cache", {}).get("stale")):
                strict.append({"title": resource["title"], "url": resource["canonical_url"],
                               "cache_hit": resource.get("cache", {}).get("hit"),
                               "fetched_at": resource.get("fetched_at"), "reference": row["reference"]})
        result["points"].append({"name": point["text"], "technology": point.get("technology"), "job_id": job_id,
            "strict_verified_count": len(strict), "strict_videos": strict, "all_related_count": len(rows),
            "fallback": job.get("ai_video_fallback")})
result["covered_points"] = sum(point["strict_verified_count"] > 0 for point in result["points"])
result["total_points"] = len(result["points"])
result["related_concepts_sha256"] = hashlib.sha256((ROOT / "backend/app/related_concepts.py").read_bytes()).hexdigest()
OUT = Path(__file__).parent / "project-v3-offline-projection.json"
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"covered": result["covered_points"], "total": result["total_points"],
                  "points": [{"name": point["name"], "strict": point["strict_verified_count"]} for point in result["points"]],
                  "output": str(OUT)}, ensure_ascii=False))
