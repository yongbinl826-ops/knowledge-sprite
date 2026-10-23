"""Local-only Android UI fixture. No model/search/network/client database calls.

Run: python fixture_server.py
Bind: 127.0.0.1:18027. Pair with adb reverse tcp:18027 tcp:18027.
All results, references, task IDs and evidence are synthetic QA data.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 18027
TASKS: dict[str, dict] = {}
LOCK = threading.Lock()
STAMP = "2026-10-21T00:00:00Z"
CAPS = {
    "mode": "synthetic-local-android-ui-qa", "teaching_match_enabled": False,
    "project_analysis": {"status": "available", "message": "本地合成 UI 测试", "max_functions": 12, "max_knowledge_points": 24},
    "project_search": {"max_batches": 6, "batch_size": 5, "max_search_requests": 10, "max_detail_pages": 10, "deadline_seconds": 180},
    "limits": {"max_knowledge_points": 5, "max_results_per_point": 5, "max_search_requests": 10, "max_detail_pages": 10},
    "search": {"status": "available", "message": "合成测试", "selected_provider": "local-fixture", "providers": []},
    "llm": {"status": "available", "message": "合成测试"},
    "fetch": {"status": "available", "message": "合成测试", "browser_fallback": False},
    "platforms": [{"id": p, "name": n, "discovery": "synthetic", "metadata": "synthetic", "playback": "not-tested"}
                  for p, n in [("bilibili", "B站"), ("icourse163", "MOOC"), ("xuetangx", "学堂在线")]],
}
INPUT = {"name": "Android QA", "requirements": "Synthetic local UI test", "student_level": "any", "language": "zh",
         "project_context": "", "technical_version": "", "preferred_platforms": ["bilibili", "icourse163"]}
ANALYSIS = {
    "analysis_format": "concept_list_v1", "scope": "仅本地合成 Android 界面验收", "technical_plan": "", "assumptions": [],
    "knowledge_points": [
        {"id": "K1", "name": "表单输入", "description": "合成测试知识点一", "technology": "Streamlit", "selection": "learn"},
        {"id": "K2", "name": "会话状态管理", "description": "合成测试知识点二", "technology": "Streamlit", "selection": "learn"},
    ],
}


def reference(point: dict, platform: str, number: int) -> dict:
    rid = f"qa-{point['id']}-{platform}-{number}"
    eid = f"evidence-{rid}"
    label = "B站" if platform == "bilibili" else "MOOC"
    # Deliberately inert reserved-domain URLs: never real playback evidence.
    url = f"https://example.invalid/android-qa/{rid}"
    title = f"[QA合成] {point['name']} · {label}课程 {number}"
    return {
        "resource": {"resource_id": rid, "title": title, "url": url, "canonical_url": url, "platform": platform,
                     # These page facts are simulated fixtures, never live-page claims.
                     "thumbnail_url": None, "fetch_status": "fetched", "video_evidence_status": "page_verified",
                     "requires_payment": False, "playback_verified": False, "synthetic": True,
                     "cache": {"hit": False, "cached_at": None, "stale": False},
                     "resource_type": "video", "access_notice": "仅本地合成页面状态测试，不代表真实课程或播放结果。"},
        "reference": {"policy": "related-reference-v1", "kind": "related_reference", "knowledge_point_id": point['id'],
                      "ranking_score": 1.0 - number * .01, "reason": "合成测试数据，仅验证界面。", "exact_teaching_verified": False,
                      "basis": ["page", "synthetic-qa"], "evidence_ids": [eid], "technical_context": "unconfirmed"},
        "evidence": [{"evidence_id": eid, "kind": "page", "source": "synthetic-android-ui-fixture", "url": url,
                      "synthetic": True, "cache": {"hit": False, "cached_at": None, "stale": False},
                      "title": title, "text": "合成页面状态测试；未请求真实页面，非真实检索或教学证据。", "observed_at": STAMP}],
    }


def result_view(body: dict, searching: bool) -> dict:
    project_input = copy.deepcopy(body.get("input") or INPUT)
    analysis = copy.deepcopy(body.get("analysis") or ANALYSIS)
    selected = [p for p in analysis["knowledge_points"] if p.get("selection") == "learn"]
    points = []
    count = 0
    if searching:
        for index, point in enumerate(analysis["knowledge_points"]):
            chosen = point.get("selection") == "learn"
            entries = ([reference(point, "bilibili", n) for n in range(1, 3 if index == 0 else 2)]
                       + [reference(point, "icourse163", 1)]) if chosen else []
            count += len(entries)
            group = {"knowledge_point_id": point["id"], "text": point["name"], "total_matches": 0, "items": [], "section_limit": 5,
                     "recommendation_policy": "related-reference-v1", "related_recommendations": entries,
                     "related_platform_recommendations": {p: [r for r in entries if r["resource"]["platform"] == p]
                                                          for p in ["bilibili", "icourse163", "xuetangx"]},
                     "total_related_recommendations": len(entries)} if chosen else None
            points.append({"project_knowledge_point_id": point["id"], "name": point["name"], "selection": point["selection"],
                           "status": "completed" if chosen else "not_selected", "batch_id": None, "job_id": "synthetic-qa-search",
                           "knowledge_point_id": point["id"] if chosen else None, "result": group})
    state = "completed" if searching else "analyzed"
    view = {"project_id": "temporary-synthetic-server-project", "input": project_input, "current_version": 1,
            "versions": [{"version": 1, "status": state, "created_at": STAMP}],
            "version": {"version": 1, "status": state, "input": copy.deepcopy(project_input), "analysis": analysis,
                        "confirmation": {"confirmed_at": STAMP, "selected_ids": [p["id"] for p in selected]} if searching else None,
                        "batches": [], "error": None, "created_at": STAMP, "model": "local-synthetic-fixture"},
            "points": points, "functions": []}
    if searching:
        view["pipeline"] = {"stage": "completed", "search_requests": 0, "search_budget": 10, "candidates": count,
                            "checking": 0, "displayed": count, "filtered": 0, "unknown": 0, "terminal": True, "source_limited": False}
    return view


def response(task: dict, status: str) -> dict:
    kind = task["body"]["kind"]
    payload = {"task_id": task["id"], "kind": kind, "expires_at": task["expires_at"], "status": status, "error": None, "result": None}
    if status == "completed":
        payload["result"] = result_view(task["body"], searching=kind == "search")
    return payload


def record(method: str, path: str, status: int, kind=None) -> None:
    event = {"at": datetime.now(timezone.utc).isoformat(), "method": method,
             "path": re.sub(r"[a-f0-9-]{36}", ":task-id", path), "status": status,
             "kind": kind, "mode": "synthetic-local-android-ui-qa", "real_model_requests": 0, "real_search_requests": 0}
    with LOCK:
        with (ROOT / "fixture-requests.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # Never print credentials or request bodies.

    def reply(self, status: int, value: dict | None, kind=None):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if value is not None else b""
        self.send_response(status)
        origin = self.headers.get("Origin", "")
        if origin in {"https://localhost", "http://localhost"} or re.fullmatch(r"http://127\.0\.0\.1:\d+", origin):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)
        record(self.command, urlsplit(self.path).path, status, kind)

    def do_OPTIONS(self):
        self.reply(204, None)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.reply(200, {"mode": "synthetic-local-android-ui-qa", "bind": f"{HOST}:{PORT}", "tasks": len(TASKS), "real_model_requests": 0, "real_search_requests": 0})
        elif path == "/api/capabilities":
            self.reply(200, CAPS)
        else:
            match = re.fullmatch(r"/api/mobile/tasks/([a-f0-9-]{36})", path)
            task = TASKS.get(match[1]) if match else None
            if not task or self.headers.get("Authorization") != task["authorization"]:
                self.reply(404, {"detail": "Synthetic task not found"})
            else:
                self.reply(200, response(task, "cancelled" if task.get("cancelled") else "completed"), task["body"]["kind"])

    def do_POST(self):
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/mobile/tasks/([a-f0-9-]{36})(/cancel)?", path)
        if not match:
            self.reply(404, {"detail": "Only synthetic mobile task endpoints exist"})
            return
        token = self.headers.get("Authorization", "")
        if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", token):
            self.reply(401, {"detail": "Fixture expects mobile task capability shape"})
            return
        if match[2]:
            task = TASKS.get(match[1])
            if not task or task["authorization"] != token:
                self.reply(404, {"detail": "Synthetic task not found"})
            else:
                task["cancelled"] = True
                self.reply(200, response(task, "cancelled"), task["body"]["kind"])
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 * 1024:
                raise ValueError("Invalid body size")
            body = json.loads(self.rfile.read(length))
            if body.get("kind") not in {"analysis", "search"}:
                raise ValueError("This fixture supports project analysis and search only")
            if body["kind"] == "search" and not body.get("analysis", {}).get("knowledge_points"):
                raise ValueError("Search requires reviewed knowledge points")
        except (ValueError, TypeError, KeyError) as error:
            self.reply(400, {"detail": str(error)})
            return
        if match[1] in TASKS:
            self.reply(409, {"detail": "Duplicate synthetic task POST"}, body["kind"])
            return
        task = {"id": match[1], "body": body, "authorization": token,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}
        TASKS[match[1]] = task
        self.reply(202, response(task, "queued"), body["kind"])


def self_check():
    analyzed = result_view({"kind": "analysis", "input": INPUT}, False)
    completed = result_view({"kind": "search", "input": INPUT, "analysis": ANALYSIS}, True)
    assert len(analyzed["version"]["analysis"]["knowledge_points"]) == 2
    assert analyzed["points"] == [] and analyzed["version"]["confirmation"] is None
    assert [len(p["result"]["related_recommendations"]) for p in completed["points"]] == [3, 2]
    assert [len(p["result"]["related_platform_recommendations"]["bilibili"]) for p in completed["points"]] == [2, 1]
    assert [len(p["result"]["related_platform_recommendations"]["icourse163"]) for p in completed["points"]] == [1, 1]
    assert all(not p["result"]["related_platform_recommendations"]["xuetangx"] for p in completed["points"])
    (ROOT / "fixture-example-analysis.json").write_text(json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "fixture-example-search.json").write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Self-check passed: 2 knowledge points; all=5, Bilibili=3, MOOC=2, Xuetang=0; no server started.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        print(f"Synthetic Android UI fixture listening only on http://{HOST}:{PORT}", flush=True)
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
