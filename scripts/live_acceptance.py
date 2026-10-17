"""Real API acceptance, never mocks or substitutes a provider. Preserves failures.

uv run --frozen python scripts/live_acceptance.py --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TERMINAL = {"completed", "partial", "failed", "interrupted"}
POINTS = ["Python 列表与字典", "HTML 表单校验", "SQL 多表连接", "地图投影与坐标系"]


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(args):
    output = Path(args.output)
    if output.exists():
        raise SystemExit("Output already exists; use a new --output path to preserve prior evidence.")
    report = {"started_at": now(), "timezone": "Asia/Shanghai", "mode": "live", "base_url": args.base_url,
              "acceptance": "真实联网验收未完成", "jobs": [], "blockers": [],
              "boundaries": ["搜索证据不证明学生可以观看", "页面提取成功不证明免费或完整覆盖", "仅统计本次预算内观测，非成功率估计"]}
    report["source_hashes"] = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                               for folder in [ROOT / "backend/app", ROOT / "frontend/src"] for path in sorted(folder.rglob("*"))
                               if path.is_file() and path.suffix in {".py", ".tsx", ".ts", ".css"}}
    save(output, report)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=15, trust_env=False) as client:
        try:
            response = await client.get("/api/capabilities")
            response.raise_for_status()
            report["capabilities_before"] = response.json()
            for points in [POINTS, [args.novel_point]]:
                payload = {"knowledge_points": points, "language": "zh", "student_level": "beginner",
                           "preferred_platforms": ["bilibili", "icourse163", "xuetangx"]}
                response = await client.post("/api/search-jobs", json=payload)
                response.raise_for_status()
                job_id = response.json()["job_id"]
                entry = {"job_id": job_id, "request": payload, "submitted_at": now(), "snapshots": []}
                report["jobs"].append(entry)
                save(output, report)
                started = asyncio.get_running_loop().time()
                while True:
                    state_response = await client.get(f"/api/search-jobs/{job_id}")
                    state_response.raise_for_status()
                    state = state_response.json()
                    snapshot = {"observed_at": now(), "status": state["status"], "phase": state.get("phase"), "progress": state.get("progress")}
                    if not entry["snapshots"] or snapshot["progress"] != entry["snapshots"][-1]["progress"] or snapshot["status"] != entry["snapshots"][-1]["status"]:
                        entry["snapshots"].append(snapshot)
                        save(output, report)
                        print(f"{job_id[:8]} {snapshot['status']} {snapshot['phase']}: {snapshot['progress']}", flush=True)
                    if state["status"] in TERMINAL:
                        break
                    if asyncio.get_running_loop().time() - started > args.max_wait:
                        raise TimeoutError("Acceptance polling deadline exceeded; server task may still be running")
                    await asyncio.sleep(2)
                entry["final_job"] = state
                results_response = await client.get(f"/api/search-jobs/{job_id}/results")
                results_response.raise_for_status()
                entry["results"] = results_response.json()
                save(output, report)
                if state["status"] == "failed" and any(e.get("code") == "configuration_error" for e in state.get("errors", [])):
                    report["blockers"].append("搜索服务未配置；停止后续真实搜索，未使用替代数据")
                    break
            report["capabilities_after"] = (await client.get("/api/capabilities")).json()
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError) as exc:
            # Do not store raw service bodies, exception strings or headers (may contain secrets).
            report["blockers"].append({"code": type(exc).__name__, "message": "本地 API 访问或验收等待失败；检查运行条件"})
        resources = {item["resource"]["resource_id"]: item["resource"] for entry in report["jobs"]
                     for group in entry.get("results", {}).get("groups", []) for item in group["items"]}
        report["displayed_unique_resources"] = len(resources)
        report["displayed_platform_distribution"] = dict(Counter(r["platform"] for r in resources.values()))
        report["displayed_fetch_status_distribution"] = dict(Counter(r["fetch_status"] for r in resources.values()))
        report["checks"] = {
            "real_search_returned_links": bool(resources),
            "bilibili_discovered": any(r["platform"] == "bilibili" for r in resources.values()),
            "icourse163_discovered": any(r["platform"] == "icourse163" for r in resources.values()),
            "novel_point_returned_links": any(g["items"] for entry in report["jobs"] if args.novel_point in entry["request"]["knowledge_points"] for g in entry.get("results", {}).get("groups", [])),
            "page_enrichment_in_results": any(r["fetch_status"] in {"success", "fetched"} for r in resources.values()),
        }
        report["actual_search_http_requests"] = sum(entry.get("final_job", {}).get("progress", {}).get("search_requests", 0) for entry in report["jobs"])
        report["search_cache_hits"] = sum(1 for entry in report["jobs"] for attempt in entry.get("results", {}).get("search_attempts", []) if attempt.get("cache_hit"))
    # Independent real public-page path. This is not inserted into search results.
    try:
        from backend.app.fetcher import FetcherConfig, Fetcher
        from backend.app.extractor import MetadataExtractor
        from backend.app.config import Settings
        settings = Settings.from_env()
        config_values = {"timeout_seconds": settings.fetch_timeout_seconds}
        if hasattr(settings, "dns_resolver"):
            config_values["dns_resolver"] = settings.dns_resolver
        fetcher = Fetcher(FetcherConfig(**config_values))
        response = await fetcher.fetch(args.page_url)
        if response.status_code == 200 and "html" in response.headers.get("content-type", "").lower():
            page = MetadataExtractor().extract(response.body.decode("utf-8", errors="replace"), response.url, now())
        else:
            page = {"fetch_status": "http_error_or_unsupported_content", "http_status": response.status_code}
        report["independent_page_probe"] = {"input_url": args.page_url, "source": "explicit acceptance reference URL; not a search result", "result": page}
        report["checks"]["independent_page_extraction"] = page.get("fetch_status") in {"success", "fetched"}
    except Exception as exc:
        report["independent_page_probe"] = {"status": "failed", "error_type": type(exc).__name__}
        report["checks"]["independent_page_extraction"] = False
    if all(report["checks"][key] for key in ["real_search_returned_links", "bilibili_discovered", "icourse163_discovered", "novel_point_returned_links", "independent_page_extraction"]):
        report["acceptance"] = "本次限定输入与预算内的真实链路验收已完成；见各任务的部分失败与限制"
    else:
        report["blockers"].extend(f"未完成验收项：{key}" for key, value in report["checks"].items() if not value and key != "page_enrichment_in_results")
    report["finished_at"] = now()
    save(output, report)
    print(json.dumps({"report": str(output), "acceptance": report["acceptance"], "checks": report["checks"]}, ensure_ascii=False), flush=True)
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=f"reports/live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    parser.add_argument("--max-wait", type=int, default=650)
    parser.add_argument("--novel-point", default="CSS Grid 隐式网格与自动放置")
    parser.add_argument("--page-url", default="https://docs.python.org/3/tutorial/datastructures.html")
    sys.exit(asyncio.run(main(parser.parse_args())))
