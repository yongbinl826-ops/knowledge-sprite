"""Bounded, isolated Tavily/Serper MOOC comparison; dry-run unless --live.

Before a real comparison configure both keys and verify at least eight unused
Serper free-trial credits, then pass --confirm-serper-free-trial. Tavily's free
plan and remaining allowance are checked through its read-only usage endpoint.
Output must be a NEW directory outside the repository. No paid plan is enabled.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.mooc_relevance import _public_course
from backend.app.service import JobService
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_mooc_relevance_live import assess_candidates
from scripts.verify_split_provider_live import make_fetcher, scrub

POINTS = ["Python 列表与字典", "pandas 数据分组与聚合", "SQL 多表连接与分组查询", "HTML 表单与网页结构"]
PROVIDERS = ("tavily", "serper")
REQUEST_CAP = 8
OVERRIDES = dict(
    # Fixed-budget platform comparison, intentionally excludes unrestricted web.
    open_web_search_enabled=False,
    tavily_allow_keyless=False, llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    shared_course_library_enabled=False, mooc_gap_search_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False, js_render_enabled=False,
    parallel_platform_search=True, bilibili_search_rounds=2, mooc_search_rounds=2,
    max_search_requests=REQUEST_CAP, search_results_per_query=10, max_detail_pages=12,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2,
    fetch_enabled=True, fetch_min_interval_seconds=2, global_concurrency=2,
    deadline_seconds=250, allow_stale_cache=False,
)
SOURCE_FILES = (
    "scripts/compare_mooc_providers_live.py", "backend/app/config.py", "backend/app/providers.py",
    "backend/app/service.py", "backend/app/platform_search.py", "backend/app/mooc_relevance.py",
    "backend/app/fetcher.py", "backend/app/extractor.py", "backend/app/db.py",
)


def make_plan(live=False, confirm_serper_free_trial=False):
    return {"schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run",
        "providers": list(PROVIDERS), "knowledge_points": POINTS, "platforms": ["icourse163"],
        "corpus_sha256": hashlib.sha256(json.dumps(POINTS, ensure_ascii=False).encode()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        "overrides": {key: value for key, value in OVERRIDES.items() if "api_key" not in key},
        "max_search_http_requests_per_provider": REQUEST_CAP, "usage_http_requests": 1,
        "serper_free_trial_confirmed": bool(confirm_serper_free_trial),
        "serper_free_trial_minimum_remaining_required": REQUEST_CAP,
        "billing_changes": False, "llm_calls": 0, "fetch_retries": 0,
        "database": "separate fresh temporary SQLite per provider; metadata exported, database removed",
        "fetcher": "one shared instance; host restrictions, Retry-After, robots rules and pacing survive provider changes",
        "course_page_cache_shared": False,
        "cache_seeded": False, "known_urls_seeded": False, "shared_library_enabled": False,
        "gap_search_enabled": False, "provider_fallback": False,
        "query_comparison": "Same fixed points, literal site-scoped queries, two rounds, ten results and detail/time budgets.",
        "provider_order": list(PROVIDERS), "randomized_order": False,
        "manual_gold_labels": False, "precision": "unknown", "recall": "unknown",
        "interpretation": "Observed course discovery and source-bound outline coverage only; no estimate of precision, recall, playback or teaching quality."}


def isolated_settings(configured, database, provider):
    if provider not in PROVIDERS:
        raise ValueError("Unknown comparison provider")
    return replace(configured, database_path=str(database), search_provider=provider,
        bilibili_search_provider="", mooc_search_provider=provider, **OVERRIDES).validate()


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 1_000_000_000 and math.isfinite(value))


def assess_free_usage(body):
    """Fail closed; expose no response prose, user details, keys or arbitrary plan names."""
    account = body.get("account") if isinstance(body, dict) else None
    key = body.get("key") if isinstance(body, dict) else None
    if not isinstance(account, dict) or not isinstance(key, dict):
        return {"allowed": False, "reason": "usage_schema_unknown"}
    plan = account.get("current_plan")
    free = isinstance(plan, str) and plan.strip().casefold() in {"researcher", "free"}
    result = {"allowed": False, "current_plan": plan.strip().casefold() if free else "not_verified_free"}
    for name in ("plan_usage", "plan_limit", "paygo_usage", "paygo_limit"):
        result[name] = account[name] if _number(account.get(name)) else "unknown"
    if account.get("paygo_limit", "missing") is None:
        result["paygo_limit"] = None
    for name in ("usage", "limit"):
        result["key_" + name] = key[name] if _number(key.get(name)) else "unknown"
    if key.get("limit", "missing") is None:
        result["key_limit"] = None
    if all(_number(result[name]) for name in ("plan_limit", "plan_usage")):
        result["plan_remaining"] = max(0, result["plan_limit"] - result["plan_usage"])
    else:
        result["plan_remaining"] = "unknown"
    if result["key_limit"] is None:
        result["key_remaining"] = "no_key_limit"
    elif all(_number(result[name]) for name in ("key_limit", "key_usage")):
        result["key_remaining"] = max(0, result["key_limit"] - result["key_usage"])
    else:
        result["key_remaining"] = "unknown"
    enough_account = _number(result["plan_remaining"]) and result["plan_remaining"] >= REQUEST_CAP
    enough_key = result["key_remaining"] == "no_key_limit" or (
        _number(result["key_remaining"]) and result["key_remaining"] >= REQUEST_CAP)
    # A null paygo limit is not evidence that pay-as-you-go is enabled. This
    # run is bounded to eight basic searches and must fit inside the observed
    # free allowance. Existing positive paygo usage still fails closed. The
    # usage response is a point-in-time snapshot, not an account-wide lock.
    no_paygo_usage = result["paygo_usage"] == 0
    result["allowed"] = free and enough_account and enough_key and no_paygo_usage
    result["reason"] = "free_allowance_verified" if result["allowed"] else "free_allowance_not_verified"
    return result


async def fetch_tavily_usage(key):
    """One read-only request with a bounded body and no retries or redirects."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", "https://api.tavily.com/usage",
                    headers={"Authorization": "Bearer " + key, "Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    return {"allowed": False, "reason": "usage_http_error", "http_status": response.status_code}
                if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    return {"allowed": False, "reason": "usage_encoding_invalid"}
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > 65536:
                        return {"allowed": False, "reason": "usage_body_too_large"}
                    body.extend(chunk)
                return {**assess_free_usage(json.loads(body)), "http_status": 200}
    except (httpx.HTTPError, ValueError, TypeError):
        return {"allowed": False, "reason": "usage_request_failed"}


def fetch_controls(fetcher):
    """Non-secret audit snapshot; no provider change may reset these controls."""
    current = time.monotonic()
    return {"captured_at": now(),
        "blocked_hosts": [{key: row[key] for key in ("host", "status", "source", "observed_at") if key in row}
                          for row in getattr(fetcher, "_blocked_hosts", {}).values()],
        "paused_hosts": [{"host": host, "remaining_seconds": round(until - current, 3)}
                         for host, until in getattr(fetcher, "_paused_until", {}).items() if until > current]}


async def run_provider(output, configured, provider, secrets, *, fetcher=None):
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": [], "events": []}

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
            "http_status": result.status_code, "bytes": len(result.body),
            "sha256": hashlib.sha256(result.body).hexdigest()})
        save("network.json", network)

    def target_trace(event):
        network["events"].append(event)
        network["host_controls"] = fetch_controls(fetcher)
        save("network.json", network)

    with TemporaryDirectory(prefix="knowledge-sprite-mooc-compare-") as temporary:
        settings = isolated_settings(configured, Path(temporary) / "comparison.sqlite3", provider)
        store = Store(settings.database_path)
        try:
            fetcher = fetcher if fetcher is not None else make_fetcher(settings)
            service = JobService(settings, store, fetcher=fetcher)
            assert service.llm is None and service.fetcher.config.max_retries == 0
            assert not settings.shared_course_library_enabled and not settings.mooc_gap_search_enabled
            original_save = service._save
            def save_progress(job):
                original_save(job)
                save("job.json", job)
                save("search_attempts.json", store.attempts(job["job_id"]))
            service._save = save_progress
            job_id = service.create(SearchRequest(knowledge_points=POINTS,
                preferred_platforms=["icourse163"], language="zh"))["job_id"]
            save("job.json", store.get_job(job_id))
            save("summary.json", {"provider": provider, "job_id": job_id, "status": "running"})
            network["host_controls"] = fetch_controls(fetcher)
            save("network.json", network)
            token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                         "response": response, "target_trace": target_trace, "max_retries": 0})
            failure, cancelled = None, False
            try:
                await service.run(job_id)
            except asyncio.CancelledError:
                # Export retained attempts/evidence before TemporaryDirectory
                # cleanup; never spend another request after cancellation.
                cancelled = True
            except Exception as exc:
                # Never serialize arbitrary exception bodies from an external
                # source; export what was observed and classify the failure.
                failure = type(exc).__name__
            finally:
                NETWORK_OBSERVER.reset(token)
            network["host_controls"] = fetch_controls(fetcher)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            resources, results = store.resources(job_id), service.results(job_id) or {}
            evidence = {rid: store.evidence(job_id, rid) for rid in resources}
            quality = assess_candidates(job, resources, evidence, results)
            for name, value in (("job", job), ("search_attempts", attempts), ("resources", resources),
                                ("evidence", evidence), ("results", results), ("network", network), ("quality", quality)):
                save(name + ".json", value)
            requests = [request for attempt in attempts for request in attempt.get("provider_requests", [])]
            credited = [request["api_credits"] for request in requests if _number(request.get("api_credits"))]
            mooc_urls = {row.get("canonical_url") or row["url"] for row in resources.values()
                         if row.get("platform") == "icourse163"}
            outline_urls = {candidate["url"] for point in quality["per_point"] for candidate in point["candidates"]
                            if candidate["assessment"]["status"] == "outline_supported"}
            summary = {"provider": provider, "job_id": job_id,
                "status": "cancelled" if cancelled else "harness_error" if failure else job["status"],
                "cancelled": cancelled,
                "error_type": failure, "elapsed_seconds": round(time.monotonic() - started, 3),
                "search_http_requests": len(requests), "search_http_budget": REQUEST_CAP,
                "search_http_budget_exceeded": len(requests) > REQUEST_CAP,
                "search_http_status_counts": dict(Counter(str(row.get("http_status", "unknown")) for row in requests)),
                "raw_candidates_across_queries": sum(row.get("raw_candidate_count", 0) for row in requests),
                "independent_mooc_urls": len(mooc_urls), "native_course_urls": sum(bool(_public_course(url)) for url in mooc_urls),
                "outline_supported_unique_courses": len(outline_urls),
                "outline_supported_point_course_pairs": quality["status_counts"].get("outline_supported", 0),
                "actually_displayed_point_course_pairs": quality["actually_displayed_count"],
                "observed_api_credits": sum(credited) if credited or not requests else "unknown",
                "requests_with_observed_credits": len(credited), "credits_complete": len(credited) == len(requests),
                "detail_target_http_requests": network["target_http_requests"], "dns_http_requests": network["dns_http_requests"],
                "per_point": [{key: point[key] for key in ("text", "own_point_candidate_count", "actually_displayed_count", "status_counts")}
                              for point in quality["per_point"]],
                "source_states": service.health()["search_sources"],
                "fetch_host_controls": fetch_controls(fetcher),
                "precision": "unknown", "recall": "unknown", "manual_gold_labels": False, "llm_calls": 0}
            save("summary.json", summary)
            if cancelled:
                raise asyncio.CancelledError
            return summary
        finally:
            store.close()


async def run(output, *, live=False, confirm_serper_free_trial=False, configured=None):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("Comparison output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", make_plan(live, confirm_serper_free_trial))
    summary = {"started_at": now(), "status": "dry_run", "search_http_requests": 0,
        "usage_http_requests": 0, "detail_target_http_requests": 0, "llm_calls": 0,
        "billing_changes": False, "precision": "unknown", "recall": "unknown", "providers": {}}
    if not live:
        atomic_json(output / "summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    missing = [name for name, value in (("TAVILY_API_KEY", configured.tavily_api_key),
                                       ("SERPER_API_KEY", configured.serper_api_key)) if not value.strip()]
    if missing or not confirm_serper_free_trial:
        summary.update(status="preflight_blocked", missing_environment_variables=missing,
            reason="missing_api_keys" if missing else "serper_free_trial_not_confirmed")
        atomic_json(output / "summary.json", summary)
        return summary
    secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)
    usage = await fetch_tavily_usage(configured.tavily_api_key)
    summary.update(usage_http_requests=1, tavily_free_usage=usage)
    if not usage["allowed"]:
        summary.update(status="preflight_blocked", reason="tavily_free_allowance_not_verified")
        atomic_json(output / "summary.json", scrub(summary, secrets))
        return summary
    # Search/metadata caches stay in separate fresh Stores. Host access controls
    # and robots pacing belong to the target website, not a search provider.
    shared_fetcher = make_fetcher(isolated_settings(configured, ":memory:", PROVIDERS[0]))
    for provider in PROVIDERS:
        try:
            summary["providers"][provider] = await run_provider(
                output / provider, configured, provider, secrets, fetcher=shared_fetcher)
        except asyncio.CancelledError:
            retained = output / provider / "summary.json"
            if retained.is_file():
                summary["providers"][provider] = json.loads(retained.read_text(encoding="utf-8"))
            summary.update(status="cancelled", finished_at=now())
            raise
        finally:
            summary["search_http_requests"] = sum(row.get("search_http_requests", 0) for row in summary["providers"].values())
            summary["detail_target_http_requests"] = sum(row.get("detail_target_http_requests", 0) for row in summary["providers"].values())
            if summary["status"] != "cancelled":
                summary["status"] = "running"
            atomic_json(output / "summary.json", scrub(summary, secrets))
    summary.update(status="completed" if all(row["status"] == "completed" for row in summary["providers"].values()) else "partial",
                   finished_at=now())
    atomic_json(output / "summary.json", scrub(summary, secrets))
    return scrub(summary, secrets)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-serper-free-trial", action="store_true",
                        help="Confirm the configured Serper key has at least 8 unused free-trial credits; no purchased credits.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(run(args.output, live=args.live, confirm_serper_free_trial=args.confirm_serper_free_trial))
    except KeyboardInterrupt:
        print("Interrupted; inspect the output directory for available evidence.", file=sys.stderr)
        return 130
    except Exception:
        print("Comparison could not run; check configuration and use a new output directory outside the repository. Secrets are not printed.", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["status"] == "preflight_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
