"""Terminal snapshot diagnosis; SQLite mode=ro, no HTTP and no application writes."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.ai_video_fallback import direct_video_url
from backend.app.related_concepts import reference_concept_hints, reference_technology_context
from backend.app.service import JobService

JOB = "f24a3b59-87e5-4e24-85e8-8804830d2c96"
connection = sqlite3.connect((ROOT / "data/discovery.sqlite3").as_uri() + "?mode=ro", uri=True)
connection.execute("BEGIN")
job = json.loads(connection.execute("SELECT data FROM jobs WHERE id=?", (JOB,)).fetchone()[0])
point = next(p for p in job["knowledge_points"] if p["text"] == "文件下载")
pid = point["knowledge_point_id"]
resources = {rid: json.loads(raw) for rid, raw in connection.execute("SELECT id,data FROM resources WHERE job_id=?", (JOB,))}
evidence = {rid: [] for rid in resources}
for rid, raw in connection.execute("SELECT resource_id,data FROM evidence WHERE job_id=?", (JOB,)):
    evidence.setdefault(rid, []).append(json.loads(raw))
attempts = [json.loads(row[0]) for row in connection.execute("SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (JOB,))]
bound = {rid: resource for rid, resource in resources.items() if any(e.get("knowledge_point_id") == pid and e.get("kind") in {"search", "ai_suggestion", "page_link"} for e in evidence[rid])}
report = {"observed_at": datetime.now(timezone.utc).isoformat(), "read_only": True, "network_requests": 0,
    "job": {key: job.get(key) for key in ("job_id", "status", "phase", "created_at", "updated_at", "progress", "budgets", "ai_video_fallback")},
    "point": point, "source_attempt_counts": dict(Counter(str(a.get("provider")) + ":" + str(a.get("error_code") or a.get("status")) for a in attempts if a.get("knowledge_point_id") == pid)),
    "page_link_evidence_count": sum(e.get("kind") == "page_link" for rows in evidence.values() for e in rows),
    "bound_fetch_counts": dict(Counter(r["fetch_status"] for r in bound.values())), "recovery_queries": [], "bilibili_sources": []}
for attempt in attempts:
    if attempt.get("knowledge_point_id") != pid or attempt.get("search_phase") != "recovery": continue
    row = {key: attempt.get(key) for key in ("query", "provider", "status", "error_code", "candidate_count", "executed_at")}
    row["requests"] = [{key: request.get(key) for key in ("status", "http_status", "error_code", "elapsed_seconds", "candidate_count")} for request in attempt.get("provider_requests", [])]
    report["recovery_queries"].append(row)
for rid, resource in bound.items():
    if resource["platform"] != "bilibili": continue
    row = {key: resource.get(key) for key in ("resource_id", "title", "canonical_url", "fetch_status", "fetch_error", "fetched_at", "video_evidence_status", "requires_payment", "cache")}
    row["chapters_count"] = len(resource.get("chapters", []))
    row["download_chapters"] = [c["title"] for c in resource.get("chapters", []) if re.search(r"下载|download|导出|export", c.get("title", ""), re.I)]
    own = [e for e in evidence[rid] if e.get("kind") in {"page", "catalog"}]
    row["own_download_excerpts"] = [{"field": e.get("field"), "source": e.get("source"), "text": str(e.get("text") or "")[:1200]} for e in own if re.search(r"下载|download|导出|export", str(e.get("text") or ""), re.I)][:5]
    cached = []
    if resource.get("fetched_at"):
        candidates = connection.execute("SELECT data FROM cache WHERE kind='page' AND json_extract(data,'$.fetched_at')=? ORDER BY created DESC", (resource["fetched_at"],)).fetchall()
        for (raw,) in candidates:
            data = json.loads(raw)
            urls = {e.get("url") for e in data.get("evidence", [])}
            if resource["canonical_url"] in urls:
                cached = data.get("_video_leads", [])
                row["exact_fetch_cache_found"] = True
                break
    row["observed_video_lead_count"] = len(cached)
    row["qualifying_navigation_leads"] = [lead for lead in cached if direct_video_url(lead.get("url"), ["bilibili"])
        and reference_technology_context("Streamlit", lead.get("title") or "")
        and (JobService._point_relevance(point, lead.get("title") or "") or reference_concept_hints(point["text"], lead.get("title") or ""))]
    report["bilibili_sources"].append(row)
connection.close()
report["first_batch_gap_snapshot"] = "live-project-v3-readonly-diagnostic.json"
path = ROOT / "evidence/ai-video-repair-20261021/final-gap-diagnostic.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"fallback": report["job"]["ai_video_fallback"], "bound_fetch_counts": report["bound_fetch_counts"], "page_link_evidence_count": report["page_link_evidence_count"],
    "queries": report["recovery_queries"], "fetched": [{k:r[k] for k in ("canonical_url", "fetch_status", "requires_payment", "chapters_count", "download_chapters", "observed_video_lead_count", "qualifying_navigation_leads")} for r in report["bilibili_sources"] if r["fetch_status"] != "not_fetched"]}, ensure_ascii=True))
