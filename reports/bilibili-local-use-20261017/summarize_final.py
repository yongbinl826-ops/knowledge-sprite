"""Export bounded public chapter evidence from the final live database.

The older generic audit journal strips URL query strings. This ledger retains
only the observed, validated numeric Bilibili p parameter for chapter checks.
No source request, candidate injection, HTML replay or database mutation occurs.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "final-live-run"
JOB = "2d4b4ef1-f94d-49cf-8d33-378e1b861afa"
db = sqlite3.connect((OUT / "live.sqlite3").as_uri() + "?mode=ro", uri=True)
job = json.loads(db.execute("SELECT data FROM jobs WHERE id=?", (JOB,)).fetchone()[0])
assert job["status"] in {"completed", "partial"}
resources = [json.loads(row[0]) for row in db.execute("SELECT data FROM resources WHERE job_id=?", (JOB,))]
evidence = {json.loads(row[0])["evidence_id"]: json.loads(row[0])
            for row in db.execute("SELECT data FROM evidence WHERE job_id=?", (JOB,))}
ledger = []
for resource in resources:
    chapters = []
    for index, chapter in enumerate(resource["chapters"]):
        proof = evidence[chapter["evidence_id"]]
        actual = json.loads(proof["text"])
        assert proof["kind"] == "catalog" and proof["field"] == f"chapters.{index}"
        for field in ("title", "url", "page_number", "duration_seconds"):
            assert actual[field] == chapter[field], (resource["canonical_url"], field)
        assert re.fullmatch(r"https://www\.bilibili\.com/video/BV[0-9A-Za-z]{10}/\?p=[1-9][0-9]*", chapter["url"])
        assert chapter["url"].split("?")[0] == resource["canonical_url"]
        chapters.append({key: chapter.get(key) for key in
                         ("title", "url", "page_number", "duration_seconds", "source", "evidence_id")})
    ledger.append({key: resource.get(key) for key in
                   ("resource_id", "canonical_url", "title", "fetch_status", "fetched_at", "thumbnail_url")}
                  | {"chapters": chapters, "playback_verified": False})

run = json.loads((OUT / "run.json").read_text(encoding="utf-8"))
hash_matches = {path: (ROOT / path).is_file() and hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
                for path, digest in run["source_hashes"].items()}
assert all(hash_matches.values())
events = [json.loads(line) for line in (OUT / "jobs" / JOB / "events.jsonl").read_text(encoding="utf-8").splitlines()]
responses = [{key: event.get(key) for key in
              ("recorded_at", "url", "http_status", "body_bytes", "body_sha256", "request_kind")}
             for event in events if event["event_type"] == "http_response_body"]
audit = json.loads((OUT / "jobs" / JOB / "audit-status.json").read_text(encoding="utf-8"))
summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(), "job_id": JOB,
    "input": job["request"], "status": job["status"], "progress": job["progress"],
    "warnings": job["warnings"], "fetch_status_counts": dict(Counter(r["fetch_status"] for r in resources)),
    "resources_with_catalog": sum(bool(r["chapters"]) for r in resources),
    "catalog_rows": sum(len(r["chapters"]) for r in resources),
    "chapter_rows_match_their_evidence": True,
    "source_hash_count": len(hash_matches), "source_hashes_still_match": all(hash_matches.values()),
    "saved_page_replay": run["saved_page_replay"], "candidate_injection": run["candidate_injection"],
    "audit_status": audit, "http_responses": responses,
    "browser_evidence": ["ui-dom-check.json", "ui-console-errors.json", "final-ui.png",
                         "chapter-destination.json", "chapter-destination.png",
                         "cover-destination.json", "cover-destination.png"],
    "playback_verified": False,
}
for name, data in (("chapter-ledger.json", ledger), ("acceptance-summary.json", summary)):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: summary[key] for key in
                  ("job_id", "status", "fetch_status_counts", "resources_with_catalog", "catalog_rows", "source_hashes_still_match")}, ensure_ascii=True))
