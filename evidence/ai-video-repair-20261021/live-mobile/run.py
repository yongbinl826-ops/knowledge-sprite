"""One authorized real mobile recommendation task; capability stays in RAM."""
import hashlib
import json
from pathlib import Path
import secrets
import time
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8017"
task_id = str(uuid4())
token = secrets.token_urlsafe(32)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def request(path, body=None, authenticated=False):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                                 headers=headers, method="POST" if body is not None else "GET")
    with opener.open(req, timeout=30) as response:
        return response.status, json.load(response)


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


payload = {"kind": "direct_search", "request": {
    "knowledge_points": ["pandas分组聚合"], "topic_technologies": {"pandas分组聚合": "Python"},
    "student_level": "any", "language": "zh", "preferred_platforms": ["bilibili"],
    "project_context": "使用 Python 和 pandas 完成数据分析，对分组数据进行聚合统计"}}
save("request.json", {"base": BASE, "path": f"/api/mobile/tasks/{task_id}", "task_id": task_id,
                      "capability": "not_persisted", "payload": payload, "started_at": stamp(),
                      "mocked": False, "injected_urls": False, "budget_overrides": False})
_, capabilities = request("/api/capabilities")
save("capabilities.json", capabilities)
assert capabilities["ai_video_fallback"]["policy_version"] == "grounded-video-v2"
status, view = request(f"/api/mobile/tasks/{task_id}", payload, True)
save("created.json", {"http_status": status, "view": view})
assert status == 202
start = time.monotonic()
last_hash = None
index = 0
while True:
    digest = hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()
    if digest != last_hash:
        index += 1
        save(f"snapshot-{index:03d}.json", view)
        save("latest.json", view)
        result = view.get("result") or {}
        job = result.get("job") or {}
        progress = {"at": stamp(), "elapsed_seconds": round(time.monotonic() - start, 1),
                    "task_id": task_id, "status": view.get("status"), "job_status": job.get("status"),
                    "phase": job.get("phase"), "progress": job.get("progress"),
                    "ai_video_fallback": job.get("ai_video_fallback")}
        with (OUT / "progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(progress, ensure_ascii=False) + "\n")
        print(json.dumps(progress, ensure_ascii=False), flush=True)
        last_hash = digest
    if view.get("status") not in {"queued", "running"}:
        save("final.json", view)
        print(json.dumps({"finished_at": stamp(), "task_id": task_id, "status": view.get("status"),
                          "output": str(OUT / 'final.json'), "playback_verified": False}, ensure_ascii=False), flush=True)
        break
    if time.monotonic() - start > 540:
        save("client-wait-ended.json", {"at": stamp(), "reason": "client_wait_deadline", "task_still_running": True})
        break
    time.sleep(5)
    _, view = request(f"/api/mobile/tasks/{task_id}", authenticated=True)
