"""Opt-in three-point MOOC gap filling; no network without --live.

Two explicit discovery stages share a fresh database and the same provider,
fetcher and renderer objects: Tavily plus existing Bilibili discovery, followed
by Serper MOOC supplementation. A third, zero-search warm test is admitted only
when every fixed point has a verified library course and a recent Tavily clock.
The output must be a new directory outside the repository. No paid plan, source
fallback, prior artifact, manual course URL, or model call is used.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
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
from backend.app.providers import build_provider, SearchBudgetReached
from backend.app.result_stream import job_snapshot, result_events
from backend.app.service import JobService
from scripts.compare_mooc_providers_live import fetch_tavily_usage
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_course_library_live import backup_library, frame_observation, is_library_card, StreamConnection, summarize_stream
from scripts.verify_split_provider_live import make_fetcher, scrub

POINTS = ["pandas 数据分组与聚合", "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
SOURCE_CAPS = {"tavily": 18, "serper": 18, "searxng": 9}
OVERRIDES = dict(
    search_provider="searxng", bilibili_search_provider="searxng", mooc_search_provider="tavily",
    bilibili_search_rounds=3, mooc_search_rounds=6, search_results_per_query=10,
    shared_course_library_enabled=True, mooc_gap_search_enabled=True, mooc_target_courses_per_point=3,
    mooc_refresh_enabled=True, mooc_refresh_interval_seconds=86400,
    tavily_allow_keyless=False, llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False,
    parallel_platform_search=True, max_search_requests=27, max_detail_pages=24,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2,
    fetch_enabled=True, fetch_min_interval_seconds=2, global_concurrency=2,
    deadline_seconds=300, allow_stale_cache=False,
)
SOURCE_FILES = (
    "scripts/verify_mooc_gaps_live.py", "backend/app/config.py", "backend/app/providers.py",
    "backend/app/service.py", "backend/app/platform_search.py", "backend/app/result_stream.py",
    "backend/app/mooc_relevance.py", "backend/app/mooc_queries.py", "backend/app/mooc_refresh.py",
    "backend/app/course_library.py", "backend/app/fetcher.py", "backend/app/extractor.py",
)


def make_plan(live=False, confirm_serper_free_trial=False):
    return {"schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run",
        "knowledge_points": POINTS, "source_request_caps": SOURCE_CAPS,
        "corpus_sha256": hashlib.sha256(json.dumps(POINTS, ensure_ascii=False).encode()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        "overrides": {name: value for name, value in OVERRIDES.items() if "api_key" not in name},
        "renderer": "All configured renderer settings preserved; one renderer/fetcher object across stages.",
        "stages": [{"name": "tavily", "platforms": ["bilibili", "icourse163"], "max_search_requests": 27},
                   {"name": "serper", "platforms": ["icourse163"], "max_search_requests": 18},
                   {"name": "warm", "platforms": ["icourse163"], "target_courses_per_point": 1,
                    "max_actual_search_requests": 0, "admission": "Every point has a qualified library course and a recent Tavily refresh observation."}],
        "serper_free_trial_confirmed": bool(confirm_serper_free_trial), "serper_free_remaining_required": 18,
        "tavily_free_remaining_required": 18, "usage_http_requests": 1,
        "database": "Fresh temporary SQLite shared only by this run; known-secret-screened backup retained outside repository.",
        "source_objects_shared": True, "fallback_enabled": False, "billing_changes": False,
        "cache_seeded": False, "known_urls_seeded": False, "prior_artifacts_read": False,
        "llm_calls": 0, "fetch_retries": 0, "manual_gold_labels": False, "precision": "unknown", "recall": "unknown",
        "stream_transport": "In-process production SSE generator; no claim of browser or HTTP-wire measurement."}


def isolated_settings(configured, database, stage):
    if stage not in {"tavily", "serper", "warm"}:
        raise ValueError("Unknown stage")
    values = dict(OVERRIDES, mooc_search_provider="serper" if stage == "serper" else "tavily",
                  max_search_requests=27 if stage == "tavily" else 18,
                  mooc_target_courses_per_point=1 if stage == "warm" else 3)
    return replace(configured, database_path=str(database), **values).validate()


def sufficient_free_usage(usage):
    def enough(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and 18 <= value <= 1_000_000_000 and math.isfinite(value))
    return bool(usage.get("allowed") and enough(usage.get("plan_remaining")) and usage.get("paygo_usage") == 0
                and (usage.get("key_remaining") == "no_key_limit" or enough(usage.get("key_remaining"))))


class SourceLedger:
    """Combine global/stage caps with production budget hooks before dispatch."""
    def __init__(self):
        self.stage = "tavily"
        self.total = {source: 0 for source in SOURCE_CAPS}
        self.stages = {}
        self.on_change = lambda: None

    def install(self, providers):
        for name, provider in providers.items():
            original_scope = provider.query_scope

            def scoped(request_hook, *, source=name, original=original_scope):
                async def reserve():
                    allowed = self.stage == source or (self.stage == "tavily" and source == "searxng")
                    if not allowed or self.total[source] >= SOURCE_CAPS[source]:
                        raise SearchBudgetReached()
                    if request_hook:
                        await request_hook()
                    self.total[source] += 1
                    stage = self.stages.setdefault(self.stage, {key: 0 for key in SOURCE_CAPS})
                    stage[source] += 1
                    self.on_change()
                return original(reserve)
            provider.query_scope = scoped

    def snapshot(self):
        return {"current_stage": self.stage, "actual_dispatch_reservations": dict(self.total),
                "stage_reservations": {stage: dict(rows) for stage, rows in self.stages.items()}, "caps": SOURCE_CAPS,
                "meaning": "Reserved immediately before provider HTTP dispatch; a transport failure is still an attempted request."}


def library_entries(service):
    return {row["entry_key"] for row in service.store.connection.execute(
        "SELECT entry_key FROM shared_mooc_courses WHERE status='verified' AND expires>?", (time.time(),))}


def point_coverage(service, target=3):
    rows = []
    profile = service._course_library_profile()
    for index, text in enumerate(POINTS):
        point = {"knowledge_point_id": "coverage-" + str(index), "text": text}
        matches = service.course_library.lookup(point, profile, limit=service.settings.shared_course_library_max_candidates)
        rows.append({"text": text, "qualified_count": len(matches), "target": target,
            "remaining": max(0, target - len(matches)),
            "courses": [{"entry_key": row["entry_key"], "url": row["resource"]["url"],
                         "title": row["resource"]["title"]} for row in matches]})
    return rows


def warm_admission(service):
    coverage = point_coverage(service, target=1)
    request = SearchRequest(knowledge_points=POINTS, preferred_platforms=["icourse163"], language="zh")
    profile = {"library": service._course_library_profile(), "search": service._search_identity("tavily")}
    recent = []
    for index, text in enumerate(POINTS):
        key = service.mooc_refresh.topic_key({"knowledge_point_id": "warm-" + str(index), "text": text}, request, profile)
        row = service.store.connection.execute("SELECT last_success FROM mooc_refresh_state WHERE topic_key=?", (key,)).fetchone()
        recent.append(bool(row and 0 <= time.time() - row["last_success"] < service.settings.mooc_refresh_interval_seconds))
    return {"allowed": all(row["qualified_count"] for row in coverage) and all(recent),
            "per_point": [{**row, "recent_tavily_refresh": is_recent} for row, is_recent in zip(coverage, recent)],
            "reason": "ready" if all(row["qualified_count"] for row in coverage) and all(recent)
                      else "qualified_library_course_or_recent_tavily_clock_missing"}


async def run_stage(service, store, output, stage, secrets, ledger, summary_sink):
    output.mkdir(exist_ok=False)
    platforms = ["bilibili", "icourse163"] if stage == "tavily" else ["icourse163"]
    created = service.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=platforms, language="zh"),
                             consumer_key="mooc-gaps-" + stage)
    if created.get("reused"):
        raise ValueError("Each stage requires a distinct job")
    job_id = created["job_id"]
    started = time.monotonic()
    before_entries = library_entries(service)
    before_revision = store.connection.total_changes
    initial = job_snapshot(service, store, job_id)
    rows = []
    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": []}

    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))

    def journal():
        save("job.json", store.get_job(job_id))
        save("search_attempts.json", store.attempts(job_id))
        save("network.json", network)
        save("source-ledger.json", ledger.snapshot())

    ledger.stage = stage
    ledger.on_change = journal
    journal()

    async def before_target():
        network["target_http_requests"] += 1
        journal()

    async def before_dns():
        network["dns_http_requests"] += 1
        journal()

    def response(result, kind):
        parsed = urlsplit(result.url)
        network["responses"].append({"kind": kind, "host": parsed.hostname,
            "url": urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")),
            "http_status": result.status_code, "bytes": len(result.body),
            "sha256": hashlib.sha256(result.body).hexdigest()})
        journal()

    connection = StreamConnection()

    async def observe():
        async for message in result_events(connection, lambda: job_snapshot(service, store, job_id),
                lambda: store.connection.total_changes, initial, initial_revision=before_revision):
            row = frame_observation(message, round((time.monotonic() - started) * 1000))
            if row is not None:
                rows.append(row)
                save("stream-events.json", rows)
                journal()

    token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                 "response": response, "max_retries": 0})
    observer = asyncio.create_task(observe())
    error_type = None
    cancelled = None
    try:
        await service.run(job_id)
        await asyncio.wait_for(observer, timeout=5)
    except asyncio.CancelledError as exc:
        cancelled, error_type = exc, "CancelledError"
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        NETWORK_OBSERVER.reset(token)
        connection.disconnected = True
        if not observer.done():
            observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        ledger.on_change = lambda: None
        journal()
        job, attempts = store.get_job(job_id), store.attempts(job_id)
        resources, results = store.resources(job_id), service.results(job_id) or {}
        evidence = {rid: store.evidence(job_id, rid) for rid in resources}
        for name, value in (("resources", resources), ("evidence", evidence), ("results", results), ("stream-events", rows)):
            save(name + ".json", value)
        source_stats = {}
        for source in SOURCE_CAPS:
            calls = [attempt for attempt in attempts if attempt.get("provider") == source]
            requests = [request for attempt in calls for request in attempt.get("provider_requests", [])]
            credits = [row["api_credits"] for row in requests if isinstance(row.get("api_credits"), (int, float))
                       and not isinstance(row["api_credits"], bool) and 0 <= row["api_credits"] <= 1_000_000_000]
            source_stats[source] = {"http_requests": len(requests), "observed_credits": sum(credits) if credits or not requests else "unknown",
                "requests_with_observed_credits": len(credits), "credits_complete": len(credits) == len(requests),
                "cache_hits": sum(bool(call.get("cache_hit")) for call in calls),
                "skipped_slots": sum(call.get("status") == "skipped" for call in calls)}
        per_point = []
        for group in results.get("groups", []):
            mooc = group.get("discovery_platform_items", {}).get("icourse163", [])
            bili = group.get("discovery_platform_items", {}).get("bilibili", [])
            per_point.append({"text": group.get("text", group.get("knowledge_point", "unknown")),
                "knowledge_point_id": group["knowledge_point_id"], "qualified_mooc_cards": len(mooc),
                "library_cards": sum(is_library_card(item) for item in mooc), "bilibili_cards": len(bili),
                "relevance_status_counts": group.get("mooc_relevance", {}).get("status_counts", {})})
        names = {point["knowledge_point_id"]: point["text"] for point in job["knowledge_points"]}
        for row in per_point:
            row["text"] = names[row["knowledge_point_id"]]
        fresh_entries = library_entries(service)
        summary = {"stage": stage, "job_id": job_id, "job_status": job["status"], "error_type": error_type,
            "job_terminal": job["status"] not in {"queued", "running"} and job.get("phase") != "awaiting_followup",
            "job_reused": bool(created.get("reused")), "elapsed_seconds": round(time.monotonic() - started, 3),
            "sources": source_stats, "search_http_requests": sum(row["http_requests"] for row in source_stats.values()),
            "detail_target_http_requests": network["target_http_requests"], "dns_http_requests": network["dns_http_requests"],
            "new_verified_entries": len(fresh_entries - before_entries), "new_verified_entry_keys": sorted(fresh_entries - before_entries),
            "library_stats": service.course_library.stats(), "library_coverage": point_coverage(service),
            "per_point": per_point, "progress": job["progress"], "gap_search": job.get("gap_search", {}),
            "source_states": service.health()["search_sources"], "stream": summarize_stream(rows),
            "precision": "unknown", "recall": "unknown", "llm_calls": 0}
        summary_sink[stage] = scrub(summary, secrets)
        save("summary.json", summary)
    if cancelled is not None:
        raise cancelled
    return summary_sink[stage]


async def run(output, *, live=False, confirm_serper_free_trial=False, configured=None):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("Output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", make_plan(live, confirm_serper_free_trial))
    summary = {"status": "dry_run", "started_at": now(), "usage_http_requests": 0, "search_http_requests": 0,
        "detail_target_http_requests": 0, "stages": {}, "all_tests_finished": False,
        "all_points_at_target": False, "all_points_have_qualified_course": False,
        "warm_demonstrated": False, "llm_calls": 0, "billing_changes": False, "precision": "unknown", "recall": "unknown"}
    if not live:
        atomic_json(output / "summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)

    def save():
        atomic_json(output / "summary.json", scrub(summary, secrets))

    missing = [name for name, value in (("TAVILY_API_KEY", configured.tavily_api_key), ("SERPER_API_KEY", configured.serper_api_key),
                                       ("SEARXNG_URL", configured.searxng_url)) if not value.strip()]
    if missing or not confirm_serper_free_trial or configured.search_provider_for("bilibili") != "searxng":
        summary.update(status="preflight_blocked", reason="missing_configuration" if missing else
            "serper_free_trial_not_confirmed" if not confirm_serper_free_trial else "bilibili_provider_not_searxng",
            missing_environment_variables=missing)
        save()
        return scrub(summary, secrets)
    usage = await fetch_tavily_usage(configured.tavily_api_key)
    summary.update(usage_http_requests=1, tavily_free_usage=usage)
    if not sufficient_free_usage(usage):
        summary.update(status="preflight_blocked", reason="eighteen_free_tavily_credits_not_verified")
        save()
        return scrub(summary, secrets)
    ledger = SourceLedger()
    with TemporaryDirectory(prefix="knowledge-sprite-mooc-gaps-") as temporary:
        database = Path(temporary) / "library.sqlite3"
        settings = isolated_settings(configured, database, "tavily")
        store = Store(settings.database_path)
        cancelled = None
        service = None
        try:
            fetcher = make_fetcher(settings)
            providers = {name: build_provider(settings, fetcher=fetcher, store=store, provider_name=name) for name in SOURCE_CAPS}
            ledger.install(providers)
            service = JobService(settings, store, fetcher=fetcher, provider_overrides=providers)
            service._providers.update(providers)
            service._provider_errors.update({name: None for name in providers})
            assert service.llm is None and fetcher.config.max_retries == 0
            renderer = getattr(fetcher, "renderer", None)
            summary.update(status="running", renderer_profile=service._renderer_profile())
            save()
            for stage in ("tavily", "serper"):
                service.settings = isolated_settings(configured, database, stage)
                assert service.fetcher is fetcher and getattr(fetcher, "renderer", None) is renderer
                phase = await run_stage(service, store, output / stage, stage, secrets, ledger, summary["stages"])
                save()
                if not phase["job_terminal"]:
                    raise RuntimeError("Stage did not terminate")
            service.settings = isolated_settings(configured, database, "warm")
            admission = warm_admission(service)
            summary["warm_admission"] = admission
            if admission["allowed"]:
                warm = await run_stage(service, store, output / "warm", "warm", secrets, ledger, summary["stages"])
                summary["warm_demonstrated"] = (warm["search_http_requests"] == 0 and warm["job_terminal"]
                    and len(warm["per_point"]) == 3 and all(row["library_cards"] >= 1 and row["qualified_mooc_cards"] >= 1 for row in warm["per_point"])
                    and warm["stream"]["first_library_card_ms"] is not None and warm["stream"]["displayed_mooc_without_outline_count"] == 0)
            else:
                summary["stages"]["warm"] = {"status": "not_demonstrated", "reason": admission["reason"],
                                             "search_http_requests": 0, "detail_target_http_requests": 0}
            summary["all_tests_finished"] = True
        except asyncio.CancelledError as exc:
            cancelled = exc
            summary.update(status="interrupted", error_type="CancelledError")
        except Exception as exc:
            summary.update(status="harness_error", error_type=type(exc).__name__)
        finally:
            summary["source_ledger"] = ledger.snapshot()
            summary["search_http_requests"] = sum(row.get("search_http_requests", 0) for row in summary["stages"].values())
            summary["detail_target_http_requests"] = sum(row.get("detail_target_http_requests", 0) for row in summary["stages"].values())
            if service is not None:
                coverage = point_coverage(service)
                summary.update(library_coverage=coverage, library_stats=service.course_library.stats(),
                    all_points_have_qualified_course=all(row["qualified_count"] >= 1 for row in coverage),
                    all_points_at_target=all(row["qualified_count"] >= 3 for row in coverage))
            summary["database_backup"] = backup_library(store, output / "library.sqlite3", secrets)
            if summary["all_tests_finished"]:
                summary["status"] = "finished_at_target" if summary["all_points_at_target"] else "finished_with_gaps"
            summary["finished_at"] = now()
            save()
            store.close()
        if cancelled is not None:
            raise cancelled
    return scrub(summary, secrets)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-serper-free-trial", action="store_true", help="Confirm at least 18 unused Serper free-trial credits.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(run(args.output, live=args.live, confirm_serper_free_trial=args.confirm_serper_free_trial))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; current-run evidence and database backup were exported when possible.", file=sys.stderr)
        return 130
    except Exception:
        print("Verification could not run; check configuration and choose a new output directory outside the repository. Secrets are not printed.", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["status"] in {"preflight_blocked", "harness_error"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
