"""Opt-in, isolated MOOC relevance check using real split-provider JobService.

python scripts/verify_mooc_relevance_live.py --live --output reports/runtime/mooc-relevance-NEW
Omit --live for a network-free plan. Existing output directories are refused.
The same observed candidates are compared before/after filtering; no second search,
manual gold set, precision/recall claim, paid credentials, or LLM calls are used.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.ranking import has_type_evidence
from backend.app.service import JobService
from backend.app.url_utils import UnsafeURL, normalize_url
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_split_provider_live import make_fetcher, platform_summary, scrub

POINTS = ["Python 列表与字典", "pandas 数据分组与聚合", "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
PLATFORMS = ["bilibili", "icourse163"]
OVERRIDES = dict(
    # Fixed-budget platform comparison, intentionally excludes unrestricted web.
    open_web_search_enabled=False,
    shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False,
    search_provider="searxng", bilibili_search_provider="searxng", mooc_search_provider="tavily",
    tavily_allow_keyless=True, tavily_api_key="", llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False, js_render_enabled=False,
    parallel_platform_search=True, max_search_requests=16, max_detail_pages=12,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2,
    fetch_enabled=True, fetch_min_interval_seconds=2, deadline_seconds=250, allow_stale_cache=False,
)
SOURCE_FILES = (
    "scripts/verify_mooc_relevance_live.py", "scripts/verify_split_provider_live.py",
    "backend/app/mooc_relevance.py", "backend/app/service.py", "backend/app/platform_search.py",
    "backend/app/config.py", "backend/app/providers.py", "backend/app/discovery_display.py",
    "backend/app/ranking.py", "backend/app/extractor.py", "backend/app/fetcher.py",
)


def make_plan(live: bool) -> dict:
    """Persist the fixed corpus, budgets, and code snapshot before runtime loading."""
    return {
        "schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run",
        "knowledge_points": POINTS, "platforms": PLATFORMS,
        "corpus_sha256": hashlib.sha256(json.dumps(POINTS, ensure_ascii=False).encode()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          if (ROOT / name).is_file() else None for name in SOURCE_FILES},
        "overrides": {key: value for key, value in OVERRIDES.items() if "api_key" not in key},
        "account_credentials_sent": False, "llm_calls": 0, "fetch_retries": 0,
        "database": "fresh temporary SQLite; exported then removed",
        "cache_seeded": False, "known_urls_seeded": False, "provider_injection": False,
        "comparison": "Type-only eligibility and new relevance filtering on the same observed candidates; no replay requests.",
        "manual_gold_labels": False, "precision": "unknown", "recall": "unknown",
        "interpretation": "Observed syllabus headings support named topic coverage only; teaching quality, playback, and production reliability remain unknown.",
    }


def isolated_settings(configured: Settings, database: Path) -> Settings:
    """Preserve configured transport/site rules while removing account credentials."""
    return replace(configured, database_path=str(database), **OVERRIDES).validate()


def own_searches(point: dict, resource: dict, evidence: list[dict]) -> list[dict]:
    """Require the candidate's own URL and exact knowledge-point evidence binding."""
    try:
        target = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
    except (UnsafeURL, TypeError, ValueError):
        return []
    rows = []
    for row in evidence:
        if (row.get("kind") != "search" or row.get("knowledge_point_id") != point["knowledge_point_id"]
                or not row.get("evidence_id") or not row.get("title")):
            continue
        try:
            if normalize_url(row.get("url", "")) == target:
                rows.append(row)
        except (UnsafeURL, TypeError, ValueError):
            continue
    return rows


def type_only_eligible(point: dict, resource: dict, evidence: list[dict]) -> bool:
    """Frozen pre-filter card gate, independent of the new relevance assessment."""
    return (resource.get("fetch_status") != "not_found" and has_type_evidence(resource, evidence)
            and bool(own_searches(point, resource, evidence)))


def assess_candidates(job: dict, resources: dict, evidence: dict, results: dict) -> dict:
    # Lazy import keeps a dry run independent of the live assessment/runtime.
    from backend.app.mooc_relevance import assess_mooc_relevance

    groups = {row["knowledge_point_id"]: row for row in results.get("groups", [])}
    per_point = []
    all_rows = []
    for point in job["knowledge_points"]:
        point_id = point["knowledge_point_id"]
        group = groups.get(point_id, {})
        displayed = {row["resource"]["resource_id"] for row in
                     group.get("discovery_platform_items", {}).get("icourse163", [])}
        bilibili = {row["resource"]["resource_id"] for row in
                    group.get("discovery_platform_items", {}).get("bilibili", [])}
        rows = []
        for resource_id, resource in resources.items():
            observed = evidence.get(resource_id, [])
            if resource.get("platform") != "icourse163" or not own_searches(point, resource, observed):
                continue
            scoped = [row for row in observed if row.get("knowledge_point_id") in {None, point_id}]
            assessment = assess_mooc_relevance(point, resource, scoped)
            original = type_only_eligible(point, resource, observed)
            rows.append({
                "resource_id": resource_id, "title": resource.get("title"), "url": resource.get("url"),
                "fetch_status": resource.get("fetch_status"), "chapter_count": len(resource.get("chapters", [])),
                "type_only_eligible": original,
                "filtered_eligible": original and assessment["display_eligible"],
                "actually_displayed": resource_id in displayed,
                "assessment": assessment,
            })
        original_ids = {row["resource_id"] for row in rows if row["type_only_eligible"]}
        eligible_ids = {row["resource_id"] for row in rows if row["filtered_eligible"]}
        per_point.append({
            "knowledge_point_id": point_id, "text": point["text"], "own_point_candidate_count": len(rows),
            "original_type_only_discovery_count": len(original_ids), "filtered_discovery_count": len(eligible_ids),
            "original_resource_ids": sorted(original_ids), "filtered_resource_ids": sorted(eligible_ids),
            "removed_resource_ids": sorted(original_ids - eligible_ids),
            "actually_displayed_count": len(displayed), "actually_displayed_resource_ids": sorted(displayed),
            "displayed_without_eligible_assessment": sorted(displayed - eligible_ids),
            "bilibili_discovery_count": len(bilibili), "bilibili_resource_ids": sorted(bilibili),
            "status_counts": dict(Counter(row["assessment"]["status"] for row in rows)),
            "displayed_evidence": [{"resource_id": row["resource_id"], "title": row["title"], "url": row["url"],
                "status": row["assessment"]["status"], "matched_chapters": row["assessment"].get("matched_chapters", []),
                "subtopics": row["assessment"].get("subtopics", []),
                "evidence_ids": row["assessment"].get("evidence_ids", [])} for row in rows if row["actually_displayed"]],
            "candidates": rows,
        })
        all_rows.extend(rows)
    return {
        "comparison": "Same live observations, with no extra search requests or manual gold labels.",
        "count_unit": "knowledge-point/resource pairs; a course found for two points is counted twice",
        "precision": "unknown", "recall": "unknown", "manual_gold_labels": False,
        "per_point": per_point,
        "status_counts": dict(Counter(row["assessment"]["status"] for row in all_rows)),
        "original_type_only_discovery_count": sum(row["original_type_only_discovery_count"] for row in per_point),
        "filtered_discovery_count": sum(row["filtered_discovery_count"] for row in per_point),
        "actually_displayed_count": sum(row["actually_displayed_count"] for row in per_point),
        "displayed_without_eligible_assessment_count": sum(len(row["displayed_without_eligible_assessment"]) for row in per_point),
    }


async def run(output: Path, *, live: bool = False, configured: Settings | None = None) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", make_plan(live))
    summary = {"started_at": now(), "status": "planned", "llm_calls": 0,
        "account_credentials_sent": False, "playback": "unknown", "teaching_suitability": "unknown",
        "production_reliability": "unknown", "precision": "unknown", "recall": "unknown"}
    if not live:
        summary.update(status="dry_run", search_http_requests=0, detail_target_http_requests=0)
        atomic_json(output / "summary.json", summary)
        return summary

    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.llm_api_key) if value)

    def save(name: str, value):
        atomic_json(output / name, scrub(value, secrets))

    if not configured.searxng_url:
        summary.update(status="preflight_blocked", reason="SEARXNG_URL_not_configured")
        save("summary.json", summary)
        return summary
    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": []}

    async def before_target():
        network["target_http_requests"] += 1
        save("network.json", network)

    async def before_dns():
        network["dns_http_requests"] += 1
        save("network.json", network)

    def response(result, kind):
        parsed = urlsplit(result.url)
        network["responses"].append({"kind": kind, "host": parsed.hostname,
            "url": urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")),
            "http_status": result.status_code, "bytes": len(result.body),
            "sha256": hashlib.sha256(result.body).hexdigest()})
        save("network.json", network)

    with TemporaryDirectory(prefix="knowledge-sprite-mooc-quality-") as temporary:
        settings = isolated_settings(configured, Path(temporary) / "live.sqlite3")
        store = Store(settings.database_path)
        try:
            service = JobService(settings, store, fetcher=make_fetcher(settings))
            assert service.llm is None and service.fetcher.config.max_retries == 0
            assert not settings.tavily_api_key and not settings.llm_api_key
            job_id = service.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=PLATFORMS,
                                                 language="zh"))["job_id"]
            summary.update(status="running", job_id=job_id)
            save("summary.json", summary)
            save("job.json", store.get_job(job_id))
            token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                          "response": response, "max_retries": 0})
            try:
                await service.run(job_id)
            finally:
                NETWORK_OBSERVER.reset(token)
                job, attempts = store.get_job(job_id), store.attempts(job_id)
                resources, results = store.resources(job_id), service.results(job_id) or {}
                evidence = {rid: store.evidence(job_id, rid) for rid in resources}
                for name, value in (("job", job), ("search_attempts", attempts), ("results", results),
                                    ("resources", resources), ("evidence", evidence), ("network", network)):
                    save(name + ".json", value)
                quality = assess_candidates(job, resources, evidence, results)
                save("quality.json", quality)
                summary.update(status=job["status"], finished_at=now(), job_progress=job["progress"],
                    search_http_requests=sum(len(row.get("provider_requests", [])) for row in attempts),
                    detail_target_http_requests=network["target_http_requests"], dns_http_requests=network["dns_http_requests"],
                    platforms={platform: platform_summary(platform, attempts, resources, evidence, results)
                               for platform in PLATFORMS},
                    source_states=service.health()["search_sources"],
                    fetch_status_counts=dict(Counter(row["http_status"] for row in network["responses"])),
                    relevance={key: value for key, value in quality.items() if key != "per_point"},
                    per_point=[{key: row[key] for key in ("text", "own_point_candidate_count",
                        "original_type_only_discovery_count", "filtered_discovery_count", "actually_displayed_count",
                        "bilibili_discovery_count", "status_counts")} for row in quality["per_point"]])
                save("summary.json", summary)
        finally:
            store.close()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Perform one bounded free/keyless live job.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(run(args.output, live=args.live))
    except (FileExistsError, ValueError):
        print("Existing output directory or invalid configuration; configuration values are not printed.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; available job evidence has been exported.", file=sys.stderr)
        return 130
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] not in {"preflight_blocked", "failed", "interrupted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
