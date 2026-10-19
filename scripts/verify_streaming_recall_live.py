"""Opt-in expanded recall and real HTTP/SSE check, isolated from user data.

Run without --live for a network-free plan. With --live, this starts a temporary
loopback API and consumes its SSE response as bytes arrive; ASGITransport is not
used because it buffers streaming responses. Only free/keyless sources are used.
Existing output directories are refused. Choose an artifact directory outside
the checkout, e.g. a new directory under the operating system temporary folder.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.fetcher import NETWORK_OBSERVER
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_mooc_relevance_live import assess_candidates
from scripts.verify_split_provider_live import make_fetcher, platform_summary, scrub

POINTS = ["pandas 数据分组与聚合", "Python 列表与字典"]
PLATFORMS = ["bilibili", "icourse163"]
OVERRIDES = dict(
    search_provider="searxng", bilibili_search_provider="searxng", mooc_search_provider="tavily",
    bilibili_search_rounds=3, mooc_search_rounds=5, search_results_per_query=12,
    tavily_allow_keyless=True, tavily_api_key="", llm_provider="none", llm_api_key="",
    teaching_match_enabled=False, teaching_match_max_calls_per_job=0, project_semantic_review_enabled=False,
    official_sitemap_fallback=False, public_catalog_fallback=False, js_render_enabled=False,
    parallel_platform_search=True, max_search_requests=80, max_detail_pages=60,
    search_max_retries=0, search_timeout_seconds=20, search_min_interval_seconds=2,
    fetch_enabled=True, fetch_min_interval_seconds=2, deadline_seconds=360,
    allow_stale_cache=False, local_only=True,
)
SOURCE_FILES = (
    "scripts/verify_streaming_recall_live.py", "scripts/verify_mooc_relevance_live.py",
    "scripts/verify_split_provider_live.py", "backend/app/main.py", "backend/app/result_stream.py",
    "backend/app/mooc_relevance.py", "backend/app/service.py", "backend/app/platform_search.py",
    "backend/app/config.py", "backend/app/providers.py", "backend/app/discovery_display.py",
)
MAX_SSE_FRAME_BYTES = 8 * 1024 * 1024


def make_plan(live: bool) -> dict:
    return {
        "schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run",
        "knowledge_points": POINTS, "platforms": PLATFORMS,
        "corpus_sha256": hashlib.sha256(json.dumps(POINTS, ensure_ascii=False).encode()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          if (ROOT / name).is_file() else None for name in SOURCE_FILES},
        "overrides": {key: value for key, value in OVERRIDES.items() if "api_key" not in key},
        "planned_search_requests": len(POINTS) * (OVERRIDES["bilibili_search_rounds"] + OVERRIDES["mooc_search_rounds"]),
        "account_credentials_sent": False, "llm_calls": 0, "fetch_retries": 0,
        "database": "fresh temporary SQLite; exported then removed",
        "cache_seeded": False, "known_urls_seeded": False, "provider_injection": False,
        "transport": "real loopback HTTP; SSE frames recorded on receipt before job completion",
        "source_limits": "Provider cooldowns/denials stop further requests; no source switching or retry override.",
        "manual_gold_labels": False, "precision": "unknown", "recall": "unknown",
        "interpretation": "Observe candidate growth, verified card arrival, and source limits; no claim of teaching quality, playback, or production reliability.",
    }


def isolated_settings(configured: Settings, database: Path) -> Settings:
    return replace(configured, database_path=str(database), **OVERRIDES).validate()


async def sse_frames(lines):
    """Decode actual SSE boundaries; comments and incomplete EOF frames do not emit."""
    event, event_id, data, size = "message", None, [], 0
    async for line in lines:
        if line == "":
            if data:
                yield {"event": event, "id": event_id, "data": "\n".join(data)}
            event, event_id, data, size = "message", None, [], 0
            continue
        if line.startswith(":"):
            continue
        size += len(line.encode("utf-8"))
        if size > MAX_SSE_FRAME_BYTES:
            raise ValueError("SSE frame exceeds bounded observation limit")
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "id" and "\x00" not in value:
            event_id = value
        elif field == "data":
            data.append(value)


def timeline_row(frame: dict, elapsed_ms: int) -> dict:
    payload = json.loads(frame["data"])
    if not isinstance(payload, dict):
        raise ValueError("SSE data must be an object")
    platform_ids = {platform: set() for platform in PLATFORMS}
    unsupported = []
    for group in payload.get("groups", []):
        for platform, items in group.get("discovery_platform_items", {}).items():
            if platform not in platform_ids:
                continue
            for item in items:
                resource = item.get("resource", {})
                resource_id = resource.get("resource_id")
                if resource_id:
                    platform_ids[platform].add(resource_id)
                if platform == "icourse163":
                    assessment = item.get("mooc_relevance", {})
                    if not assessment.get("display_eligible") or assessment.get("status") != "outline_supported":
                        unsupported.append(resource_id)
    job = payload.get("job") or {}
    pipeline = payload.get("pipeline") or {}
    return {
        "received_at": now(), "elapsed_ms": elapsed_ms, "event": frame["event"], "event_id": frame["id"],
        "payload_sha256": hashlib.sha256(frame["data"].encode()).hexdigest(),
        "job_status": job.get("status", payload.get("status", "unknown")),
        "pipeline": pipeline,
        "displayed_unique_counts": {platform: len(ids) for platform, ids in platform_ids.items()},
        "displayed_resource_ids": {platform: sorted(ids) for platform, ids in platform_ids.items()},
        "displayed_mooc_without_verified_outline": unsupported,
    }


def stream_summary(rows: list[dict]) -> dict:
    snapshots = [row for row in rows if row["event"] == "snapshot"]
    ongoing = [row for row in snapshots if not row["pipeline"].get("terminal", False)]
    displaying = [row for row in ongoing if sum(row["displayed_unique_counts"].values())]
    candidates = [row for row in snapshots if row["pipeline"].get("candidates", 0)]
    completions = [row for row in rows if row["event"] == "complete"]
    mooc = [row for row in ongoing if row["displayed_unique_counts"]["icourse163"]]
    return {
        "snapshot_count": len(snapshots), "nonterminal_snapshot_count": len(ongoing),
        "nonterminal_display_snapshot_count": len(displaying), "nonterminal_mooc_display_snapshot_count": len(mooc),
        "first_candidates_ms": candidates[0]["elapsed_ms"] if candidates else None,
        "first_display_ms": displaying[0]["elapsed_ms"] if displaying else None,
        "first_verified_mooc_ms": mooc[0]["elapsed_ms"] if mooc else None,
        "complete_received": bool(completions),
        "complete_terminal": bool(completions and completions[-1]["pipeline"].get("terminal")),
        "cards_observed_before_completion": bool(displaying and completions),
        "mooc_observed_before_completion": bool(mooc and completions),
        "displayed_mooc_without_verified_outline_count": sum(len(row["displayed_mooc_without_verified_outline"]) for row in rows),
        "interpretation": "Only cards seen in a nonterminal SSE frame count as observed incremental display; an empty run cannot establish card streaming.",
    }


@asynccontextmanager
async def loopback_server(app):
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error",
                                          access_log=False, timeout_graceful_shutdown=5))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async def started():
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Temporary API exited before startup")
                await asyncio.sleep(0.01)
        await asyncio.wait_for(started(), timeout=10)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=15)
        finally:
            sock.close()


async def run(output: Path, *, live: bool = False, configured: Settings | None = None) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", make_plan(live))
    summary = {"started_at": now(), "status": "planned", "llm_calls": 0,
               "account_credentials_sent": False, "playback": "unknown", "precision": "unknown",
               "recall": "unknown", "teaching_suitability": "unknown", "production_reliability": "unknown"}
    if not live:
        summary.update(status="dry_run", search_http_requests=0, detail_target_http_requests=0, stream_events=0)
        atomic_json(output / "summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.llm_api_key) if value)

    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))

    if not configured.searxng_url:
        summary.update(status="preflight_blocked", reason="SEARXNG_URL_not_configured")
        save("summary.json", summary)
        return summary
    from backend.app.main import create_app

    network = {"target_http_requests": 0, "dns_http_requests": 0, "responses": []}
    rows = []

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

    with TemporaryDirectory(prefix="knowledge-sprite-streaming-") as temporary:
        settings = isolated_settings(configured, Path(temporary) / "live.sqlite3")
        app = create_app(settings, fetcher=make_fetcher(settings))
        token = NETWORK_OBSERVER.set({"before_target_http": before_target, "before_dns_http": before_dns,
                                      "response": response, "max_retries": 0})
        try:
            async with loopback_server(app) as base_url:
                service, store = app.state.service, app.state.store
                assert service.llm is None and service.fetcher.config.max_retries == 0
                started = time.monotonic()
                job_id = None
                try:
                    async with httpx.AsyncClient(base_url=base_url, trust_env=False,
                                                timeout=settings.deadline_seconds + 30) as client:
                        created = await client.post("/api/search-jobs", json={
                            "knowledge_points": POINTS, "preferred_platforms": PLATFORMS, "language": "zh"})
                        created.raise_for_status()
                        job_id = created.json()["job_id"]
                        summary.update(status="running", job_id=job_id)
                        save("summary.json", summary)
                        async with client.stream("GET", f"/api/search-jobs/{job_id}/events") as stream:
                            stream.raise_for_status()
                            if "text/event-stream" not in stream.headers.get("content-type", ""):
                                raise ValueError("Expected real SSE content type")
                            async for frame in sse_frames(stream.aiter_lines()):
                                if frame["event"] not in {"snapshot", "complete"}:
                                    continue
                                row = timeline_row(frame, round((time.monotonic() - started) * 1000))
                                rows.append(row)
                                save("stream-timeline.json", rows)
                                if frame["event"] == "complete":
                                    break
                finally:
                    if job_id:
                        job = store.get_job(job_id)
                        if job["status"] in {"queued", "running"}:
                            await service.cancel(job_id)
                            job = store.get_job(job_id)
                        attempts, resources = store.attempts(job_id), store.resources(job_id)
                        evidence = {rid: store.evidence(job_id, rid) for rid in resources}
                        results = service.results(job_id) or {}
                        quality = assess_candidates(job, resources, evidence, results)
                        for name, value in (("job", job), ("search_attempts", attempts), ("results", results),
                                            ("resources", resources), ("evidence", evidence), ("quality", quality),
                                            ("network", network), ("stream-timeline", rows)):
                            save(name + ".json", value)
                        summary.update(status=job["status"], finished_at=now(), job_progress=job["progress"],
                            search_http_requests=sum(len(row.get("provider_requests", [])) for row in attempts),
                            detail_target_http_requests=network["target_http_requests"], dns_http_requests=network["dns_http_requests"],
                            platforms={platform: platform_summary(platform, attempts, resources, evidence, results)
                                       for platform in PLATFORMS}, source_states=service.health()["search_sources"],
                            fetch_status_counts=dict(Counter(row["http_status"] for row in network["responses"])),
                            stream_events=len(rows), streaming=stream_summary(rows),
                            relevance={key: value for key, value in quality.items() if key != "per_point"},
                            per_point=[{key: row[key] for key in ("text", "own_point_candidate_count",
                                "original_type_only_discovery_count", "filtered_discovery_count", "actually_displayed_count",
                                "bilibili_discovery_count", "status_counts")} for row in quality["per_point"]])
                        save("summary.json", summary)
        finally:
            NETWORK_OBSERVER.reset(token)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run one bounded job using only free/keyless sources.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(run(args.output, live=args.live))
    except (FileExistsError, ValueError):
        print("Output already exists or configuration/stream is invalid; configuration values are not printed.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; available job and stream evidence has been exported.", file=sys.stderr)
        return 130
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] not in {"preflight_blocked", "failed", "interrupted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
