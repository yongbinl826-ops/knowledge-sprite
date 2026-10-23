"""Opt-in cold/warm shared-course-library check using production job/SSE code.

Default is a network-free plan. --live uses a new isolated database, one fixed
knowledge point and at most three MOOC plus two Bilibili searches per phase.
The warm phase runs only after the cold job is terminal and has added a usable
course. No previous database, known course URL, fixture or live artifact is read.
Choose a NEW output directory outside this repository. Billing is never changed.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.result_stream import job_snapshot, result_events
from backend.app.service import JobService
from scripts.compare_mooc_providers_live import fetch_tavily_usage
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_split_provider_live import make_fetcher, scrub

POINTS = ["pandas 数据分组与聚合"]
PLATFORMS = ["bilibili", "icourse163"]
OVERRIDES = dict(
    # Fixed-budget platform comparison, intentionally excludes unrestricted web.
    open_web_search_enabled=False,
    search_provider="searxng", bilibili_search_provider="searxng", mooc_search_provider="tavily",
    bilibili_search_rounds=2, mooc_search_rounds=3, search_results_per_query=10,
    shared_course_library_enabled=True, mooc_gap_search_enabled=True, mooc_refresh_enabled=False, mooc_target_courses_per_point=1,
    tavily_allow_keyless=False, llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False, js_render_enabled=False,
    parallel_platform_search=True, max_search_requests=5, max_detail_pages=8,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2,
    fetch_enabled=True, fetch_min_interval_seconds=2, global_concurrency=2,
    deadline_seconds=180, allow_stale_cache=False,
)
SOURCE_FILES = (
    "scripts/verify_course_library_live.py", "backend/app/config.py", "backend/app/providers.py",
    "backend/app/service.py", "backend/app/platform_search.py", "backend/app/result_stream.py",
    "backend/app/mooc_relevance.py", "backend/app/course_library.py", "backend/app/discovery_display.py",
    "backend/app/fetcher.py", "backend/app/extractor.py", "backend/app/db.py",
)


def make_plan(live=False):
    return {"schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run",
        "knowledge_points": POINTS, "platforms": PLATFORMS,
        "corpus_sha256": hashlib.sha256(json.dumps(POINTS, ensure_ascii=False).encode()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        "overrides": {key: value for key, value in OVERRIDES.items() if "api_key" not in key},
        "max_search_http_requests_per_phase": 5, "max_mooc_http_requests_both_phases": 6,
        "tavily_free_remaining_required_by_preflight": 8, "usage_http_requests": 1,
        "max_detail_pages_per_phase": 8, "phase_order": ["cold", "warm"],
        "warm_admission": "Cold job terminal and a newly observed course passes a fresh library lookup for the fixed point.",
        "transport": "Production result_stream.result_events SSE generator consumed in process; not a browser or HTTP-wire measurement.",
        "database": "Fresh temporary database, same database across distinct terminal jobs; sanitized-for-known-secrets SQLite backup retained.",
        "cache_seeded": False, "known_urls_seeded": False, "prior_artifacts_read": False,
        "source_fallback": False, "billing_changes": False, "llm_calls": 0, "fetch_retries": 0,
        "manual_gold_labels": False, "precision": "unknown", "recall": "unknown"}


def isolated_settings(configured, database):
    return replace(configured, database_path=str(database), **OVERRIDES).validate()


class StreamConnection:
    """Read-only local observer; it never owns or submits the worker job."""
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


def is_library_card(item):
    # Discovery cards intentionally expose only a small resource projection;
    # the source-bound library receipt is carried in discovery_evidence.
    return any(row.get("kind") == "course_library" and row.get("source") == "shared_course_library"
               for row in item.get("discovery_evidence", []))


def frame_observation(message, elapsed_ms):
    event = "message"
    data = []
    for line in message.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
    if not data:
        return None
    payload = json.loads("\n".join(data))
    platform_ids = {platform: set() for platform in PLATFORMS}
    library_ids, invalid_mooc = set(), set()
    for group in payload.get("groups", []):
        for platform, items in group.get("discovery_platform_items", {}).items():
            if platform not in platform_ids:
                continue
            for item in items:
                resource = item.get("resource", {})
                rid = resource.get("resource_id")
                if rid:
                    platform_ids[platform].add(rid)
                if platform == "icourse163":
                    assessment = item.get("mooc_relevance") or {}
                    if not assessment.get("display_eligible") or assessment.get("status") != "outline_supported":
                        invalid_mooc.add(rid)
                    if is_library_card(item):
                        library_ids.add(rid)
    return {"event": event, "elapsed_ms": elapsed_ms, "received_at": now(),
        "payload_sha256": hashlib.sha256("\n".join(data).encode()).hexdigest(),
        "job_status": (payload.get("job") or {}).get("status", "unknown"),
        "pipeline": payload.get("pipeline", {}),
        "displayed_counts": {platform: len(ids) for platform, ids in platform_ids.items()},
        "displayed_resource_ids": {platform: sorted(ids) for platform, ids in platform_ids.items()},
        "library_card_ids": sorted(library_ids), "invalid_mooc_card_ids": sorted(invalid_mooc)}


def summarize_stream(rows):
    snapshots = [row for row in rows if row["event"] == "snapshot"]
    library = [row for row in snapshots if row["library_card_ids"]]
    ongoing_library = [row for row in library if not row["pipeline"].get("terminal")]
    displaying = [row for row in snapshots if any(row["displayed_counts"].values())]
    return {"snapshot_count": len(snapshots), "complete_received": any(row["event"] == "complete" for row in rows),
        "first_display_ms": displaying[0]["elapsed_ms"] if displaying else None,
        "first_library_card_ms": library[0]["elapsed_ms"] if library else None,
        "first_nonterminal_library_card_ms": ongoing_library[0]["elapsed_ms"] if ongoing_library else None,
        "library_card_observed_before_completion": bool(ongoing_library),
        "displayed_mooc_without_outline_count": sum(len(row["invalid_mooc_card_ids"]) for row in rows),
        "transport": "in-process production SSE generator"}


async def run_phase(service, store, output, phase, secrets):
    output.mkdir(exist_ok=False)

    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))

    created = service.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=PLATFORMS, language="zh"),
                             consumer_key="course-library-live-" + phase)
    if created.get("reused"):
        raise ValueError("Cold/warm verification requires different jobs, not active-job reuse")
    job_id = created["job_id"]
    before_revision = store.connection.total_changes
    initial = job_snapshot(service, store, job_id)
    started = time.monotonic()
    rows = []
    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": []}

    async def before_target():
        network["target_http_requests"] += 1

    async def before_dns():
        network["dns_http_requests"] += 1

    def response(result, kind):
        parsed = urlsplit(result.url)
        network["responses"].append({"kind": kind, "host": parsed.hostname,
            "url": urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")),
            "http_status": result.status_code, "bytes": len(result.body),
            "sha256": hashlib.sha256(result.body).hexdigest()})

    connection = StreamConnection()

    async def observe():
        async for message in result_events(connection, lambda: job_snapshot(service, store, job_id),
                lambda: store.connection.total_changes, initial, initial_revision=before_revision):
            row = frame_observation(message, round((time.monotonic() - started) * 1000))
            if row is not None:
                rows.append(row)
                save("stream-events.json", rows)

    token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                 "response": response, "max_retries": 0})
    observer = asyncio.create_task(observe())
    error_type = None
    try:
        await service.run(job_id)
        await asyncio.wait_for(observer, timeout=5)
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        NETWORK_OBSERVER.reset(token)
        connection.disconnected = True
        if not observer.done():
            observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
    job, attempts = store.get_job(job_id), store.attempts(job_id)
    resources, results = store.resources(job_id), service.results(job_id) or {}
    evidence = {rid: store.evidence(job_id, rid) for rid in resources}
    for name, value in (("job", job), ("search_attempts", attempts), ("resources", resources),
                        ("evidence", evidence), ("results", results), ("network", network), ("stream-events", rows)):
        save(name + ".json", value)
    platforms = {}
    for platform in PLATFORMS:
        calls = [attempt for attempt in attempts if attempt.get("platform") == platform]
        requests = [request for attempt in calls for request in attempt.get("provider_requests", [])]
        items = [item for group in results.get("groups", [])
                 for item in group.get("discovery_platform_items", {}).get(platform, [])]
        platforms[platform] = {
            "search_http_requests": len(requests), "search_attempts": len(calls),
            "search_slots_skipped": sum(attempt.get("status") == "skipped" for attempt in calls),
            "search_cache_hits": sum(bool(attempt.get("cache_hit")) for attempt in calls),
            "displayed_unique_courses": len({item["resource"]["resource_id"] for item in items}),
            "outline_supported_cards": sum((item.get("mooc_relevance") or {}).get("status") == "outline_supported" for item in items),
            "library_cards": sum(is_library_card(item) for item in items),
        }
    summary = {"phase": phase, "job_id": job_id, "status": "harness_error" if error_type else job["status"],
        "error_type": error_type, "job_terminal": job["status"] not in {"queued", "running"} and job.get("phase") != "awaiting_followup",
        "job_reused": bool(created.get("reused")), "elapsed_seconds": round(time.monotonic() - started, 3),
        "search_http_requests": sum(row["search_http_requests"] for row in platforms.values()),
        "detail_target_http_requests": network["target_http_requests"], "dns_http_requests": network["dns_http_requests"],
        "platforms": platforms, "progress": job["progress"], "gap_search": job.get("gap_search", {}),
        "shared_course_library": job.get("shared_course_library", {}), "library_stats": service.course_library.stats(),
        "source_states": service.health()["search_sources"], "stream": summarize_stream(rows),
        "precision": "unknown", "recall": "unknown", "llm_calls": 0}
    save("summary.json", summary)
    return scrub(summary, secrets)


def backup_library(store, target, secrets):
    """Never retain a database containing a known credential echoed by a source."""
    for sql in store.connection.iterdump():
        if any(secret and secret in sql for secret in secrets):
            return {"status": "omitted_sensitive_content", "reason": "known_credential_in_source_content"}
    with sqlite3.connect(target) as destination:
        store.connection.backup(destination)
    return {"status": "saved", "filename": target.name,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def summarize_reuse(cold, warm):
    if warm.get("status") == "not_demonstrated":
        return {"status": "not_demonstrated", "reason": warm["reason"], "mooc_http_requests_saved": "unknown"}
    before, after = cold["platforms"]["icourse163"], warm["platforms"]["icourse163"]
    demonstrated = (warm["job_id"] != cold["job_id"] and cold["job_terminal"] and warm["job_terminal"]
        and not warm["job_reused"] and after["search_http_requests"] == 0 and after["search_slots_skipped"] == 3
        and after["library_cards"] >= 1 and after["outline_supported_cards"] >= 1
        and warm["stream"]["first_library_card_ms"] is not None
        and warm["stream"]["displayed_mooc_without_outline_count"] == 0)
    return {"status": "demonstrated" if demonstrated else "not_demonstrated",
        "mooc_http_requests_saved": before["search_http_requests"] - after["search_http_requests"] if demonstrated else "unknown",
        "warm_mooc_slots_avoided": after["search_slots_skipped"],
        "warm_bilibili_cards": warm["platforms"]["bilibili"]["displayed_unique_courses"],
        "cold_bilibili_cards": cold["platforms"]["bilibili"]["displayed_unique_courses"],
        "bilibili_card_count_retained": warm["platforms"]["bilibili"]["displayed_unique_courses"] >= cold["platforms"]["bilibili"]["displayed_unique_courses"],
        "interpretation": "Saved HTTP count compares these two observed jobs only; no production traffic or cost extrapolation."}


async def run(output, *, live=False, configured=None):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("Live verification output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", make_plan(live))
    summary = {"status": "dry_run", "started_at": now(), "search_http_requests": 0,
        "usage_http_requests": 0, "detail_target_http_requests": 0, "llm_calls": 0, "billing_changes": False,
        "precision": "unknown", "recall": "unknown", "phases": {}, "reuse": {"status": "not_demonstrated"}}
    if not live:
        atomic_json(output / "summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)

    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))

    missing = [name for name, value in (("TAVILY_API_KEY", configured.tavily_api_key),
                                       ("SEARXNG_URL", configured.searxng_url)) if not value.strip()]
    if missing or configured.search_provider_for("bilibili") != "searxng":
        summary.update(status="preflight_blocked", reason="missing_configuration" if missing else "bilibili_provider_not_searxng",
                       missing_environment_variables=missing)
        save("summary.json", summary)
        return scrub(summary, secrets)
    usage = await fetch_tavily_usage(configured.tavily_api_key)
    summary.update(usage_http_requests=1, tavily_free_usage=usage)
    if not usage["allowed"]:
        summary.update(status="preflight_blocked", reason="tavily_free_allowance_not_verified")
        save("summary.json", summary)
        return scrub(summary, secrets)
    with TemporaryDirectory(prefix="knowledge-sprite-library-live-") as temporary:
        settings = isolated_settings(configured, Path(temporary) / "library.sqlite3")
        store = Store(settings.database_path)
        try:
            service = JobService(settings, store, fetcher=make_fetcher(settings))
            assert service.llm is None and service.fetcher.config.max_retries == 0
            cold = await run_phase(service, store, output / "cold", "cold", secrets)
            summary["phases"]["cold"] = cold
            cold_job = store.get_job(cold["job_id"])
            eligible = service.course_library.lookup(cold_job["knowledge_points"][0], service._course_library_profile(), limit=1)
            if cold["job_terminal"] and eligible and cold["progress"].get("library_courses_saved", 0):
                warm = await run_phase(service, store, output / "warm", "warm", secrets)
            else:
                warm = {"status": "not_demonstrated", "search_http_requests": 0, "detail_target_http_requests": 0,
                    "reason": "cold_job_not_terminal" if not cold["job_terminal"] else "cold_has_no_usable_library_course"}
            summary["phases"]["warm"] = warm
            summary["reuse"] = summarize_reuse(cold, warm)
            summary["database_backup"] = backup_library(store, output / "library.sqlite3", secrets)
            summary.update(search_http_requests=sum(row["search_http_requests"] for row in summary["phases"].values()),
                detail_target_http_requests=sum(row["detail_target_http_requests"] for row in summary["phases"].values()),
                status="completed" if summary["reuse"]["status"] == "demonstrated" else "not_demonstrated", finished_at=now())
            save("summary.json", summary)
        finally:
            store.close()
    return scrub(summary, secrets)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(run(args.output, live=args.live))
    except KeyboardInterrupt:
        print("Interrupted; inspect available evidence in the output directory.", file=sys.stderr)
        return 130
    except Exception:
        print("Verification could not run; use valid configuration and a new output directory outside the repository. Secrets are not printed.", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["status"] == "preflight_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
