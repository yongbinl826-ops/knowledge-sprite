"""Bounded real-network regression suite. No retries of failed cases or fixture results.

Each invocation creates a new report; source hashes and every case are retained.
The intentionally unavailable endpoint check is isolated from production SQLite.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import sys
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.ranking import type_from_discovered_url
from backend.app.service import JobService
from backend.app.url_utils import normalize_url, UnsafeURL

TERMINAL = {"completed", "partial", "failed", "interrupted"}
CASES = [
    {"name": "required_chinese", "request": {"knowledge_points": ["Python 列表与字典", "HTML 表单校验", "SQL 多表连接", "地图投影与坐标系"], "language": "zh"}},
    {"name": "previously_failed_d3", "request": {"knowledge_points": ["D3.js 数据连接 enter update exit"], "language": "zh"}},
    {"name": "english_and_duplicate_input", "request": {"knowledge_points": ["Scheme higher-order procedures", "Eigenvalues and eigenvectors", "Scheme higher-order procedures"], "language": "en", "preferred_platforms": []}},
    {"name": "nonsense_no_result", "request": {"knowledge_points": ["qzxvkb7391unfindablecourse"], "language": "en", "preferred_platforms": []}},
    # Regression input actually submitted in the browser; no URL or candidate is seeded.
    {"name": "browser_discovered_course", "request": {"knowledge_points": ["D3.js enter update exit", "Structure and Interpretation of Computer Programs"], "language": "en", "preferred_platforms": []}},
    {"name": "platform_route_regression", "request": {"knowledge_points": ["Python", "linear algebra"], "language": "any", "preferred_platforms": ["icourse163", "xuetangx"]}},
]


def now():
    return datetime.now(timezone.utc).isoformat()


def hashes():
    output = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in [ROOT / "backend/app", ROOT / "frontend/src"] for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".css"}}
    output[str(Path(__file__).relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return output


def public_link(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def same_resource_url(first, second):
    try:
        return normalize_url(first) == normalize_url(second)
    except (UnsafeURL, TypeError, ValueError):
        return False


def catalog_link(value):
    if not public_link(value) or not value or len(value) > 8192 or value.strip() != value:
        return False
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        urlsplit(value).port  # Reject malformed ports, as the browser URL parser does.
    except ValueError:
        return False
    return True


def valid_chapter_times(chapter):
    for key in ("start_seconds", "end_seconds", "duration_seconds"):
        value = chapter.get(key)
        if value is None:
            continue
        # bool subclasses int in Python, but is never a recorded number of seconds.
        if type(value) not in (int, float):
            return False
        try:
            if not math.isfinite(value):
                return False
        except OverflowError:
            return False
        if value < 0 or (key == "duration_seconds" and value == 0):
            return False
    start, end = chapter.get("start_seconds"), chapter.get("end_seconds")
    return start is None or end is None or end >= start


def audit_resource_evidence(item):
    """Validate separate evidence layers without trusting a type label or page flag alone."""
    resource = item["resource"]
    records = {record.get("evidence_id"): record for record in item.get("evidence", [])}
    provenance = resource.get("field_provenance", {})
    video_provenance = provenance.get("video_evidence_status", {})
    video_record = records.get(video_provenance.get("evidence_id"), {}) if isinstance(video_provenance, dict) else {}
    declared = resource.get("video_evidence_status", "none")
    search_basis = ((video_provenance.get("source") == "url_pattern" and type_from_discovered_url(resource.get("url", "")) == "video")
        or (video_provenance.get("source") == "search_template" and video_record.get("type_source") == "search_template"
            and video_record.get("resource_type_hint") == "video")) if isinstance(video_provenance, dict) else False
    search_discovered = (declared == "search_discovered" and video_record.get("kind") == "search" and search_basis
        and video_record.get("url") == resource.get("url")
        and public_link(video_record.get("url")))
    page_verified = (declared == "page_verified" and video_record.get("kind") in {"page", "catalog"}
        and video_record.get("field") == "video_evidence_status" and public_link(video_record.get("url"))
        and video_provenance.get("source") == video_record.get("source")
        and video_provenance.get("url") == video_record.get("url")
        and resource.get("metadata_evidence_level") in {"page", "catalog"}
        and resource.get("fetch_status") in {"fetched", "success"})
    chapters = resource.get("chapters", [])
    verified_chapters = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("title"), str) or not chapter["title"].strip():
            continue
        evidence_id = chapter.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            continue
        record = records.get(evidence_id, {})
        if record.get("kind") != "catalog" or record.get("field") != f"chapters.{index}" or not catalog_link(record.get("url")):
            continue
        try:
            fields = json.loads(record.get("text", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(fields, dict) or any(fields.get(key) != chapter.get(key) for key in ("title", "url", "start_seconds", "end_seconds", "duration_seconds")):
            continue
        if not valid_chapter_times(chapter) or not valid_chapter_times(fields):
            continue
        if chapter.get("url") is not None and not catalog_link(chapter["url"]):
            continue
        verified_chapters.append(chapter)
    video_catalog = (page_verified and resource.get("catalog_kind") in {"video_playlist", "video_chapters"}
        and bool(chapters) and len(verified_chapters) == len(chapters))
    playback_provenance = provenance.get("playback_verified", {})
    playback_record = records.get(playback_provenance.get("evidence_id"), {}) if isinstance(playback_provenance, dict) else {}
    playback_verified = (resource.get("playback_verified") is True and playback_record.get("kind") == "playback"
        and playback_record.get("field") == "playback_verified" and public_link(playback_record.get("url")))
    type_provenance = provenance.get("resource_type", {})
    type_record = records.get(type_provenance.get("evidence_id"), {}) if isinstance(type_provenance, dict) else {}
    course_search_candidate = (declared == "none" and resource.get("resource_type") == "course"
        and any(record.get("kind") == "search" and same_resource_url(record.get("url"), resource.get("url")) for record in records.values())
        and type_from_discovered_url(resource.get("url", "")) == "course")
    return {"declared_video_evidence_status": declared, "search_discovered": search_discovered,
            "page_verified": page_verified, "video_catalog": video_catalog, "verified_chapter_count": len(verified_chapters),
            "course_search_candidate": course_search_candidate,
            "playback_verified": playback_verified, "playback_claimed": resource.get("playback_verified") is True,
            "has_type_provenance": resource.get("resource_type") in {"video", "course", "playlist"}
                and type_record.get("kind") in {"search", "page", "catalog"}}


async def run_case(client, entry, save):
    response = await client.post("/api/search-jobs", json=entry["request"])
    response.raise_for_status()
    entry.update(job_id=response.json()["job_id"], submitted_at=now(), snapshots=[])
    save()
    async with asyncio.timeout(650):
        while True:
            response = await client.get(f"/api/search-jobs/{entry['job_id']}")
            response.raise_for_status()
            state = response.json()
            snapshot = {"status": state["status"], "phase": state["phase"], "progress": state["progress"]}
            if not entry["snapshots"] or snapshot != entry["snapshots"][-1]["state"]:
                entry["snapshots"].append({"observed_at": now(), "state": snapshot})
                save()
                print(f"{entry['name']} {state['status']} {state['phase']} {state['progress']}", flush=True)
            if state["status"] in TERMINAL:
                break
            await asyncio.sleep(2)
    response = await client.get(f"/api/search-jobs/{entry['job_id']}/results")
    response.raise_for_status()
    entry.update(final_job=state, results=response.json(), finished_at=now())
    save()


async def unavailable_source_check():
    # A bound socket that is never listen()ed on gives an actual refused connection.
    # No mock transport, no production config/database mutation, no external traffic.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        settings = replace(Settings(), database_path=":memory:",
            searxng_url=f"http://127.0.0.1:{reserved.getsockname()[1]}", search_max_retries=0,
            search_min_interval_seconds=0, search_timeout_seconds=1, fetch_enabled=False)
        store = Store(":memory:")
        try:
            service = JobService(settings, store)
            created = service.create(SearchRequest(knowledge_points=["network failure validation"], preferred_platforms=[]))
            await service.run(created["job_id"])
            state = store.get_job(created["job_id"])
            results = service.results(created["job_id"])
            return {"scope": "real refused TCP connection to isolated local endpoint; NOT an external outage test",
                    "state": state, "results": results,
                    "passed": state["status"] == "failed" and not any(g["items"] for g in results["groups"])}
        finally:
            store.close()


async def main(args):
    path = Path(args.output)
    if path.exists():
        raise SystemExit("Refusing to overwrite existing evidence report")
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"started_at": now(), "mode": "live", "base_url": args.base_url,
              "source_hashes_start": hashes(), "acceptance": "真实联网验收未完成", "cases": [],
              "boundaries": ["无自动重跑失败用例", "搜索/页面/目录/观看为独立证据层级", "失败及未知不会用替代课程填充"]}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=20, trust_env=False) as client:
        report["capabilities_before"] = (await client.get("/api/capabilities")).json()
        for case in CASES:
            entry = {"name": case["name"], "request": case["request"].copy()}
            report["cases"].append(entry)
            try:
                await run_case(client, entry, save)
            except (httpx.HTTPError, TimeoutError, KeyError, ValueError) as exc:
                entry["blocked"] = {"error_type": type(exc).__name__, "message": "本地接口或等待失败，未伪造终态"}
                save()
                break
        report["capabilities_after"] = (await client.get("/api/capabilities")).json()
    report["isolated_network_failure"] = await unavailable_source_check()
    default_items = [item for entry in report["cases"] for group in entry.get("results", {}).get("groups", []) for item in group["items"]]
    # Both the default view and each platform filter are reachable in the UI.
    all_items = [item for entry in report["cases"] for group in entry.get("results", {}).get("groups", [])
                 for item in [*group["items"], *(item for items in group.get("platform_items", {}).values() for item in items)]]
    audits = [(item, audit_resource_evidence(item)) for item in all_items]
    representatives = {}
    for item, audit in audits:
        rid = item["resource"]["resource_id"]
        old = representatives.get(rid)
        strength = (audit["video_catalog"], audit["page_verified"], audit["search_discovered"])
        if old is None or strength > (old[1]["video_catalog"], old[1]["page_verified"], old[1]["search_discovered"]):
            representatives[rid] = (item, audit)
    resources = {rid: item["resource"] for rid, (item, _) in representatives.items()}
    report["summary"] = {
        "displayed_unique_resources": len(resources),
        "display_scope": "default top results plus platform-filter top results; deduplicated by resource identity",
        "default_view_unique_resources": len({item["resource"]["resource_id"] for item in default_items}),
        "platforms": dict(Counter(r["platform"] for r in resources.values())),
        "types": dict(Counter(r["resource_type"] for r in resources.values())),
        "fetch_statuses": dict(Counter(r["fetch_status"] for r in resources.values())),
        "actual_search_http_requests": sum(e.get("final_job", {}).get("progress", {}).get("search_requests", 0) for e in report["cases"]),
        "search_cache_hits": sum(bool(a.get("cache_hit")) for e in report["cases"] for a in e.get("results", {}).get("search_attempts", [])),
        "video_evidence_counts": {
            "search_discovered": sum(a["search_discovered"] for _, a in representatives.values()),
            "page_verified": sum(a["page_verified"] for _, a in representatives.values()),
            "none_or_unsupported": sum(not (a["search_discovered"] or a["page_verified"]) for _, a in representatives.values()),
            "course_search_candidates": sum(a["course_search_candidate"] for _, a in representatives.values()),
            "video_catalog": sum(a["video_catalog"] for _, a in representatives.values()),
            "playback_verified": sum(a["playback_verified"] for _, a in representatives.values()),
            "playback_claimed_without_evidence": sum(a["playback_claimed"] and not a["playback_verified"] for _, a in representatives.values()),
        },
        "video_evidence_audit": [{"resource_id": item["resource"]["resource_id"], "url": item["resource"]["url"], **audit} for item, audit in representatives.values()],
        "catalogs": [{"url": r["url"], "chapters": r["chapters"], "provenance": r["field_provenance"].get("chapters")} for r in resources.values() if r["chapters"]],
        "page_examples": [{"url": r["url"], "fetched_at": r["fetched_at"], "type": r["resource_type"], "provenance": r["field_provenance"]} for r in resources.values() if r["metadata_evidence_level"] in {"page", "catalog"}],
        "video_page_examples": [{"url": item["resource"]["url"], "provenance": item["resource"]["field_provenance"].get("video_evidence_status")} for item, audit in representatives.values() if audit["page_verified"]],
        "video_catalog_examples": [{"url": item["resource"]["url"], "catalog_kind": item["resource"].get("catalog_kind"), "chapters": item["resource"]["chapters"]} for item, audit in representatives.values() if audit["video_catalog"]],
    }
    by_name = {e["name"]: e for e in report["cases"]}
    def groups(name):
        return by_name.get(name, {}).get("results", {}).get("groups", [])
    negative = by_name.get("nonsense_no_result", {})
    checks = {
        "all_cases_terminal": len(report["cases"]) == len(CASES) and all(e.get("final_job", {}).get("status") in TERMINAL for e in report["cases"]),
        "four_chinese_points_each_return_courses": len(groups("required_chinese")) == 4 and all(g["items"] for g in groups("required_chinese")),
        "d3_returned_courses": any(g["items"] for g in groups("previously_failed_d3")),
        "english_points_each_return_courses": len(groups("english_and_duplicate_input")) == 2 and all(g["items"] for g in groups("english_and_duplicate_input")),
        "duplicate_input_deduplicated": len(groups("english_and_duplicate_input")) == 2,
        "only_evidenced_course_video_types": bool(audits) and all(a["has_type_provenance"] for _, a in audits),
        "all_displayed_have_supported_discovery_evidence": bool(audits) and all(a["search_discovered"] or a["page_verified"] or a["course_search_candidate"] for _, a in audits),
        "no_invented_resource_urls": bool(all_items) and all(any(e.get("kind") == "search" and e.get("url") == item["resource"]["url"] for e in item["evidence"]) for item in all_items),
        "bilibili_discovered": any(r["platform"] == "bilibili" for r in resources.values()),
        "icourse163_discovered": any(r["platform"] == "icourse163" for r in resources.values()),
        "xuetangx_discovered": any(r["platform"] == "xuetangx" for r in resources.values()),
        "page_verified_video_on_search_result": bool(report["summary"]["video_page_examples"]),
        "video_catalog_on_search_result": bool(report["summary"]["video_catalog_examples"]),
        "no_unsupported_playback_claims": all(not a["playback_claimed"] or a["playback_verified"] for _, a in audits),
        "normal_no_result": negative.get("final_job", {}).get("status") == "completed" and not any(g["items"] for g in groups("nonsense_no_result")),
        "isolated_actual_network_failure": report["isolated_network_failure"]["passed"],
    }
    report["source_hashes_finish"] = hashes()
    checks["sources_unchanged_during_run"] = report["source_hashes_start"] == report["source_hashes_finish"]
    report["checks"] = checks
    report["playback_validation"] = {"performed_by_this_suite": False, "status": "unknown",
        "note": "本脚本验证搜索、视频结构和视频目录证据；未实际播放视频，不把页面结构当作可播放性验收"}
    report["unmet_checks"] = [name for name, value in checks.items() if not value]
    required = [name for name in checks if name != "xuetangx_discovered"]
    if all(checks[name] for name in required):
        report["acceptance"] = "本轮限定用例的搜索、视频结构和视频目录链路验收通过；观看未实测，来源失败与限制见原始记录"
    report["finished_at"] = now()
    save()
    print(json.dumps({"report": str(path), "acceptance": report["acceptance"], "checks": checks}, ensure_ascii=False), flush=True)
    return 0 if all(checks[name] for name in required) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=f"reports/live-revision-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    sys.exit(asyncio.run(main(parser.parse_args())))
