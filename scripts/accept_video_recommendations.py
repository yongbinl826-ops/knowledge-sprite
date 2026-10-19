"""Bounded live acceptance across four project types; no mock fallback.

Run from the checkout with its Python environment. --env-file may reference an
existing, authorized local configuration; values and service endpoints are never
written to the report. The report is evidence of discovery, not video playback.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    {"id": "python-game", "point": "Pygame 事件处理与碰撞检测", "student": "已学 Python 循环和函数，第一次制作键盘控制的躲避小游戏"},
    {"id": "data-dashboard", "point": "pandas 分组聚合与图表绘制", "student": "会 Python，需按产品汇总 CSV 销售数据并展示图表"},
    {"id": "web-app", "point": "JavaScript 表单校验与 fetch API 请求", "student": "了解 HTML/CSS，首次制作提交数据的网站"},
    {"id": "hardware", "point": "Arduino 模拟传感器读取与串口输出", "student": "首次接触 Arduino，制作读取光敏电阻的实验"},
]

PRODUCT_CASES = [
    {"id": "python-game", "point": "pygame 键盘控制角色左右移动", "student": "会 Python 循环函数，按真实小游戏分析单元学习用方向键连续控制角色移动"},
    {"id": "data-aggregation", "point": "pandas 分组聚合", "student": "会 Python，用 groupby 汇总销售数据；业务字段由学生在项目中练习迁移"},
    {"id": "data-plotting", "point": "matplotlib 绘图与图像保存", "student": "明确采用 pandas 加 Matplotlib 的技术方案变体，用独立绘图单元展示统计结果并保存图像"},
    {"id": "web-app", "point": "JavaScript 表单校验与 fetch API 请求", "student": "会 HTML/CSS，学习表单检查和提交网络请求"},
    {"id": "hardware", "point": "Arduino 模拟传感器读取与串口输出", "student": "首次接触 Arduino，读取低压模拟传感器并观察串口数值"},
]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def safe_link(value):
    from backend.app.url_utils import UnsafeURL, normalize_url
    try:
        canonical = normalize_url(value)
        parts = urlsplit(canonical)
        return not parts.username and not parts.password
    except (UnsafeURL, TypeError, ValueError):
        return False


def public_item(item):
    resource, match = item["resource"], item["match"]
    fields = ("resource_id", "title", "url", "platform", "resource_type", "fetch_status", "metadata_evidence_level",
              "requires_login", "requires_payment", "requires_enrollment", "access_notice", "video_evidence_status", "chapters")
    observed = [{key: entry.get(key) for key in ("evidence_id", "kind", "source", "url", "title", "snippet", "field", "text")
                 if entry.get(key) is not None} for entry in item.get("evidence", [])]
    return {"resource": {key: resource.get(key) for key in fields if resource.get(key) is not None}, "match": match,
            "evidence": observed}


def replay(args):
    """Rescore retained real observations without disguising replay as live I/O."""
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.service import JobService
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource, summarize_collection_coverage
    source = Path(args.replay_from).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit("Output exists; preserve earlier evidence")
    original = json.loads(source.read_text(encoding="utf-8"))
    store = Store(str(source.with_suffix(".sqlite3")))
    try:
        service = JobService(Settings(), store)
        results = service.results(original["job_id"])
        cases = original["cases"]
        product_reassessment = args.suite == "product" and original.get("suite") != "product"
        if product_reassessment:
            # Reassess only each project's previously observed source pool. Do
            # not create a job, add evidence, or claim these units were searched.
            job, resources = store.get_job(original["job_id"]), store.resources(original["job_id"])
            request = SearchRequest.model_validate(job["request"])
            source_ids = {case["id"]: point for case, point in zip(original["cases"], job["knowledge_points"])}
            source_for = {"python-game": "python-game", "data-aggregation": "data-dashboard", "data-plotting": "data-dashboard",
                          "web-app": "web-app", "hardware": "hardware"}
            groups = []
            for case in PRODUCT_CASES:
                previous = source_ids[source_for[case["id"]]]
                target = dict(previous, text=case["point"])
                assessed = []
                for rid, resource in resources.items():
                    evidence = store.evidence(job["job_id"], rid, previous["knowledge_point_id"])
                    if not any(e.get("kind") == "search" and e.get("knowledge_point_id") == previous["knowledge_point_id"] for e in evidence):
                        continue
                    match = rank_resource(target, resource, evidence, request)
                    if match:
                        assessed.append({"resource": resource, "match": match, "evidence": store.evidence(job["job_id"], rid)})
                assessed.sort(key=lambda item: -item["match"]["ranking_score"])
                sections = {key: [item for item in assessed if item["match"]["topic_evidence_status"] == status][:5]
                            for key, status in (("items", "supported"), ("partial_items", "partial"), ("review_items", "needs_review"))}
                groups.append({"text": case["point"], **sections,
                               "source_pool_point": previous["text"],
                               "collection_coverage": summarize_collection_coverage(case["point"], sections["items"] + sections["partial_items"])})
            results, cases = {"groups": groups}, PRODUCT_CASES
        report = {"mode": "saved-live-evidence-product-unit-reassessment" if product_reassessment else "saved-live-evidence-replay",
                  "suite": "product" if product_reassessment else original.get("suite", "stress"),
                  "observed_at": stamp(), "source_report": str(source.relative_to(ROOT)),
                  "source_report_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "new_network_requests": 0,
                  "ranking_source_sha256": hashlib.sha256((ROOT / "backend/app/ranking.py").read_bytes()).hexdigest(),
                  "playback_verified": False, "groups": []}
        for case, group in zip(cases, results["groups"]):
            report["groups"].append({"case_id": case["id"], "point": group["text"],
                                     **({"source_pool_point": group["source_pool_point"]} if product_reassessment else {}),
                                     **{key: [public_item(item) for item in group[key]] for key in ("items", "partial_items", "review_items")},
                                     "collection_coverage": group["collection_coverage"]})
        report["all_requested_units_have_recommendations"] = all(group["items"] or group["partial_items"] for group in report["groups"])
        report["all_unit_parts_evidenced"] = all(group["items"] or group["collection_coverage"]["status"] == "all_subtopics_supported"
                                               for group in report["groups"])
        report["verdict"] = "not-production-accepted" if not (report["all_requested_units_have_recommendations"] and report["all_unit_parts_evidenced"]) else "manual-relevance-review-required"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), "mode": report["mode"], "verdict": report["verdict"],
                          "counts": [{"case": group["case_id"], "supported": len(group["items"]), "partial": len(group["partial_items"])}
                                     for group in report["groups"]]}, ensure_ascii=True))
        return 0
    finally:
        store.close()


async def run(args):
    print("Preparing bounded live video acceptance (credentials and endpoints redacted).", flush=True)
    from dotenv import load_dotenv
    if args.env_file:
        if not Path(args.env_file).is_file():
            raise SystemExit("Authorized env file not found")
        load_dotenv(args.env_file, override=False)
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.models import SearchRequest
    from backend.app.service import JobService

    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit("Output exists; preserve the earlier run with a new --output")
    output.parent.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    if args.default_resource_budgets:
        defaults = Settings()
        settings = replace(settings, max_search_requests=defaults.max_search_requests, max_detail_pages=defaults.max_detail_pages)
    settings = replace(settings, database_path=str(output.with_suffix(".sqlite3")))
    cases = PRODUCT_CASES if args.suite == "product" else CASES
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            raise SystemExit("Selected case is not in this suite")
    report = {"started_at": stamp(), "mode": "live-real-provider", "playback_verified": False, "suite": args.suite,
              "suite_basis": {"stress": "Original compound units retained unchanged; these include a shared-library stress case.",
                              "product": "Pygame unit copied from actual learning_units_live.json; aggregation abstracted from its real sales group units; Matplotlib is an explicitly chosen alternative plotting unit, not the Streamlit default in that analysis. Development acceptance, not blind holdout."}[args.suite],
              "cases": cases, "boundaries": ["No playback requirement; platform login, payment or regional restrictions are access notices, not invalid links.",
              "Discovery evidence does not certify full teaching quality or unseen chapters.", "One new bounded job; no baseline test totals reused."],
              "configuration": {"search_provider": settings.search_provider, "llm_configured": bool(settings.llm_api_key),
                                "max_search_requests": settings.max_search_requests, "max_detail_pages": settings.max_detail_pages,
                                "budget_profile": "application-default" if args.default_resource_budgets else "existing-config",
                                "deadline_seconds": settings.deadline_seconds},
              "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in sorted((ROOT / "backend/app").rglob("*.py"))}, "blockers": []}

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    print(f"Configuration loaded; starting one {len(cases)}-unit {args.suite} live job.", flush=True)
    store = Store(settings.database_path)
    svc = JobService(settings, store)
    request = SearchRequest(knowledge_points=[case["point"] for case in cases], student_level="beginner", language="zh",
                            project_context="四种学生项目验收：" + "；".join(case["student"] for case in cases))
    report["request"] = request.model_dump()
    started = time.monotonic()
    try:
        created = svc.create(request)
        report["job_id"] = created["job_id"]
        save()
        await svc.run(created["job_id"])
        job = store.get_job(created["job_id"])
        results = svc.results(created["job_id"])
        report.update(status=job["status"], elapsed_seconds=round(time.monotonic() - started, 3), progress=job["progress"],
                      warnings=job["warnings"], errors=job["errors"], groups=[])
        for case, group in zip(cases, results["groups"]):
            sections = {key: [public_item(item) for item in group[key]] for key in ("items", "partial_items", "review_items")}
            all_items = [item for key in sections for item in sections[key]]
            chapter_evidence = all(any(e["evidence_id"] == chapter.get("evidence_id") and e["kind"] == "catalog"
                                       for e in item["evidence"]) for item in all_items
                                   for chapter in item["resource"].get("chapters", []) if isinstance(chapter, dict))
            report["groups"].append({"case_id": case["id"], "point": group["text"], **sections,
                                     "collection_coverage": group["collection_coverage"],
                                     "checks": {"has_supported_or_partial": bool(sections["items"] or sections["partial_items"]),
                                                "public_source_links": all(safe_link(item["resource"].get("url")) for item in all_items),
                                                "chapter_evidence_bound": chapter_evidence,
                                                "reasons_and_evidence_present": all(bool(item["match"].get("recommendation_reason")) and
                                                    bool(item["match"].get("supporting_evidence_ids")) for item in all_items)}})
        report["search_attempts"] = [{key: entry.get(key) for key in ("query", "provider", "status", "candidate_count", "cache_hit", "error_code", "executed_at")}
                                     for entry in results["search_attempts"]]
        report["checks"] = {"real_http_search_attempted": job["progress"]["search_requests"] > 0,
                            "all_requested_units_have_recommendations": all(group["checks"]["has_supported_or_partial"] for group in report["groups"]),
                            "all_unit_parts_evidenced": all(group["items"] or group["collection_coverage"]["status"] == "all_subtopics_supported"
                                                            for group in report["groups"]),
                            "all_visible_links_safe": all(group["checks"]["public_source_links"] for group in report["groups"]),
                            "chapters_observed": all(group["checks"]["chapter_evidence_bound"] for group in report["groups"])}
        if not report["checks"]["all_requested_units_have_recommendations"]:
            report["blockers"].append("At least one unit has no evidenced recommendation within the actual configured search/detail budget.")
        if not report["checks"]["all_unit_parts_evidenced"]:
            report["blockers"].append("At least one requested skill component remains unknown; partial evidence is not complete unit coverage.")
        report["verdict"] = "passed-discovery-gates-manual-relevance-review-required" if all(report["checks"].values()) else "not-production-accepted"
    except Exception as exc:
        report.update(verdict="not-production-accepted", error_type=type(exc).__name__)
        report["blockers"].append("Live acceptance failed; no response, credential, or internal endpoint was recorded.")
    finally:
        report["finished_at"] = stamp()
        save()
        store.close()
    print(json.dumps({"output": str(output), "verdict": report["verdict"], "progress": report.get("progress"),
                      "counts": [{"case": group["case_id"], "supported": len(group["items"]), "partial": len(group["partial_items"]),
                                  "review": len(group["review_items"])} for group in report.get("groups", [])]}, ensure_ascii=True), flush=True)
    return 0 if report["verdict"].startswith("passed-") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Existing authorized local dotenv; never copied to output")
    parser.add_argument("--replay-from", help="Rescore a saved acceptance JSON and its sibling SQLite; no network")
    parser.add_argument("--suite", choices=("stress", "product"), default="stress", help="Keep original compound stress cases or test five appropriately separated product learning units")
    parser.add_argument("--case", choices=("python-game", "data-dashboard", "data-aggregation", "data-plotting", "web-app", "hardware"), help="Run only this existing live case; does not change the original learning unit")
    parser.add_argument("--default-resource-budgets", action="store_true", help="Use the application's default 30-search/40-detail budgets, keeping existing endpoint/policy/timeout configuration")
    parser.add_argument("--output", required=True, help="New report under evidence/")
    args = parser.parse_args()
    raise SystemExit(replay(args) if args.replay_from else asyncio.run(run(args)))
