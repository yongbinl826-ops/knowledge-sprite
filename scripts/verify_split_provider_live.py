"""Opt-in, isolated integration check of the real split-provider JobService.

python scripts/verify_split_provider_live.py --live --output reports/runtime/split-provider-NEW
Omit --live for a network-free plan. Existing output directories are refused.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.service import JobService
from scripts.test_tavily_mooc_recall import atomic_json, now

POINTS = ["Python 列表与字典", "pandas 数据分组与聚合"]
PLATFORMS = ["bilibili", "icourse163"]
OVERRIDES = dict(search_provider="searxng", bilibili_search_provider="searxng", mooc_search_provider="tavily",
    tavily_allow_keyless=True, tavily_api_key="", llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False, js_render_enabled=False,
    parallel_platform_search=True, max_search_requests=8, max_detail_pages=6,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2, deadline_seconds=180,
    allow_stale_cache=False)


def scrub(value, secrets=()):
    if isinstance(value, dict):
        return {key: scrub(item, secrets) for key, item in value.items()
                if str(key).lower() not in {"headers", "authorization", "cookie", "set-cookie", "api_key"}}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[credential redacted]")
        value = re.sub(r"\bBearer\s+\S+|\btvly-[A-Za-z0-9_-]+", "[credential redacted]", value, flags=re.I)
        return re.sub(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;&]+", "[credential redacted]", value, flags=re.I)
    return value


def make_fetcher(settings):
    return Fetcher(FetcherConfig(enabled=settings.fetch_enabled, max_retries=0,
        timeout_seconds=settings.fetch_timeout_seconds, global_concurrency=settings.global_concurrency,
        min_interval_seconds=settings.fetch_min_interval_seconds,
        allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
        bilibili_public_metadata=settings.bilibili_public_metadata, dns_resolver=settings.dns_resolver,
        phased_timeouts=settings.fetch_phased_timeouts, body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
        body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
        body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))


def platform_summary(platform, attempts, resources, evidence, results):
    rows = [resource for resource in resources.values() if resource.get("platform") == platform]
    calls = [attempt for attempt in attempts if attempt.get("platform") == platform]
    displayed = {item["resource"]["resource_id"] for group in results.get("groups", [])
                 for item in group.get("discovery_platform_items", {}).get(platform, [])}
    return {"provider": "searxng" if platform == "bilibili" else "tavily", "discovery_count": len(displayed),
        "stored_resource_count": len(rows), "returned_candidates_across_queries": sum(row.get("candidate_count", 0) for row in calls),
        "search_http_requests": sum(len(row.get("provider_requests", [])) for row in calls),
        "search_attempt_statuses": dict(Counter(row.get("status", "unknown") for row in calls)),
        "detail_statuses": dict(Counter(row.get("fetch_status", "unknown") for row in rows)),
        "fetched_detail_count": sum(row.get("fetch_status") == "fetched" for row in rows),
        "courses_with_chapters": sum(bool(row.get("chapters")) for row in rows),
        "chapter_count": sum(len(row.get("chapters", [])) for row in rows),
        "evidence_count": sum(len(evidence.get(row["resource_id"], [])) for row in rows)}


async def run(output: Path, *, live=False, configured=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = {"created_at": now(), "mode": "live" if live else "dry_run", "knowledge_points": POINTS,
        "platforms": PLATFORMS, "overrides": {key: value for key, value in OVERRIDES.items() if "api_key" not in key},
        "account_credentials_sent": False, "fetch_retries": 0, "database": "fresh temporary SQLite; exported then removed",
        "cache_seeded": False, "known_urls_seeded": False, "provider_injection": False,
        "interpretation": "Real discovery and fetched evidence only; no claim of teaching suitability, playback or production reliability."}
    atomic_json(output / "plan.json", plan)
    summary = {"started_at": now(), "status": "planned", "llm_calls": 0, "playback": "unknown",
               "teaching_suitability": "unknown", "production_reliability": "unknown"}
    if not live:
        summary.update(status="dry_run", search_http_requests=0, detail_target_http_requests=0)
        atomic_json(output / "summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.llm_api_key) if value)
    if not configured.searxng_url:
        summary.update(status="preflight_blocked", reason="SEARXNG_URL_not_configured")
        atomic_json(output / "summary.json", summary)
        return summary
    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": []}
    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))
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
            "http_status": result.status_code, "bytes": len(result.body), "sha256": hashlib.sha256(result.body).hexdigest()})
        save("network.json", network)
    with TemporaryDirectory(prefix="knowledge-sprite-split-") as temporary:
        settings = replace(configured, database_path=str(Path(temporary) / "live.sqlite3"), **OVERRIDES).validate()
        store = Store(settings.database_path)
        service = JobService(settings, store, fetcher=make_fetcher(settings))
        assert service.llm is None and service.fetcher.config.max_retries == 0
        job_id = service.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=PLATFORMS, language="zh"))["job_id"]
        summary.update(status="running", job_id=job_id)
        save("summary.json", summary)
        save("job.json", store.get_job(job_id))
        token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                      "response": response, "max_retries": 0})
        try:
            await service.run(job_id)
        finally:
            NETWORK_OBSERVER.reset(token)
            try:
                job, attempts, results, resources = store.get_job(job_id), store.attempts(job_id), service.results(job_id), store.resources(job_id)
                evidence = {rid: store.evidence(job_id, rid) for rid in resources}
                for name, value in (("job", job), ("search_attempts", attempts), ("results", results),
                                    ("resources", resources), ("evidence", evidence), ("network", network)):
                    save(name + ".json", value)
                summary.update(status=job["status"], finished_at=now(), job_progress=job["progress"],
                    search_http_requests=sum(len(row.get("provider_requests", [])) for row in attempts),
                    detail_target_http_requests=network["target_http_requests"], dns_http_requests=network["dns_http_requests"],
                    platforms={platform: platform_summary(platform, attempts, resources, evidence, results or {}) for platform in PLATFORMS},
                    source_states=service.health()["search_sources"], fetch_status_counts=dict(Counter(row["http_status"] for row in network["responses"])))
                save("summary.json", summary)
            finally:
                store.close()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
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
