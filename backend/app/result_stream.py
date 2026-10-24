"""Read-only result snapshots and SSE; reconnecting never submits source work."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter


ACTIVE = {"queued", "running"}
LIMITED = {"rate_limited", "quota_exhausted", "captcha", "access_denied"}


def pipeline(groups, jobs, *, terminal, status=None):
    progress = Counter()
    search_budget = 0
    limited = False
    for job in jobs:
        progress.update({key: value for key, value in (job.get("progress") or {}).items()
                         if isinstance(value, int) and not isinstance(value, bool)})
        search_budget += (job.get("budgets") or {}).get("max_search_requests", 0)
        limited |= any(error.get("code") in LIMITED for error in (job.get("errors") or []))
    cards = set()
    assessments = Counter()
    for group in groups:
        rows = group.get("discovery_items", []) if group.get("discovery_only") else group.get("items", [])
        if group.get("recommendation_policy") == "related-reference-v1":
            # Recommendation counts include qualified related references;
            # teaching-support counts and their source claims remain separate.
            rows = [*group.get("items", []), *group.get("partial_items", []),
                    *group.get("related_recommendations", [])]
        for row in rows:
            resource = row.get("resource", {})
            key = resource.get("canonical_url") or resource.get("resource_id")
            if key:
                cards.add(key)
        assessments.update(group.get("mooc_relevance", {}).get("status_counts", {}))
    stage = ("complete" if terminal else "analyzing" if status == "analyzing" else
             "searching" if any(job.get("phase") in {"expanding", "searching", "awaiting_followup"} for job in jobs)
             else "checking" if any(job.get("status") == "running" for job in jobs) else "queued")
    return {"stage": stage, "terminal": terminal,
            "search_requests": progress["search_requests"], "search_budget": search_budget,
            "candidates": progress["resources_discovered"],
            "checking": 0 if terminal else max(0, progress["details_attempted"] - progress["details_completed"]),
            "checked": progress["details_completed"], "displayed": len(cards),
            "filtered": sum(assessments[key] for key in ("rejected", "outline_no_match", "outline_partial")),
            "unknown": sum(assessments[key] for key in ("outline_unavailable", "search_candidate")),
            "source_limited": limited,
            "counts_scope": "candidates per job; displayed unique URLs; filtered and unknown MOOC point-course pairs"}


def attempts_limited(attempts):
    # A per-query budget can wrap the original provider error. Preserve the
    # source limit recorded on its HTTP trace in both job and project views.
    return any(attempt.get("error_code") in LIMITED or
        (attempt.get("error") or {}).get("code") in LIMITED or
        any(trace.get("error_code") in LIMITED for trace in attempt.get("provider_requests", []))
        for attempt in attempts)


def job_snapshot(service, store, job_id):
    result = service.results(job_id)
    job = store.get_job(job_id)
    if result is None or job is None:
        return None
    terminal = job["status"] not in ACTIVE and job.get("phase") != "awaiting_followup"
    summary = pipeline(result.get("groups", []), [job], terminal=terminal)
    summary["source_limited"] |= attempts_limited(result.get("search_attempts", []))
    return {**result, "job": job, "pipeline": summary}


def project_snapshot(projects, store, project_id, version=None):
    result = projects.results(project_id, version)
    data = result.get("version") or {}
    if data.get("fast_video_search"):
        fast = data["fast_video_search"]
        progress = fast.get("progress", {})
        recommendations = fast.get("recommendations", {})
        cards = {row["resource"].get("canonical_url") or row["resource"].get("url")
                 for rows in recommendations.values() for row in rows}
        terminal = data.get("status") not in {"analyzing", "running"}
        catalog_status = (fast.get("catalog_enrichment") or {}).get("status")
        return {**result, "pipeline": {
            "stage": "complete" if terminal else "searching", "terminal": terminal,
            "catalog_pending": catalog_status == "running", "catalog_status": catalog_status,
            "search_requests": progress.get("search_requests", 0),
            "search_budget": (data.get("budgets") or {}).get("reserved_search_requests", 0),
            "candidates": progress.get("candidates", 0), "checking": 0, "checked": 0,
            "displayed": len(cards - {None, ""}), "covered_points": sum(bool(rows) for rows in recommendations.values()),
            "total_points": len(recommendations), "model_calls": progress.get("model_calls", 0),
            "filtered": 0, "unknown": 0, "source_limited": False,
            "elapsed_seconds": fast.get("elapsed_seconds", 0),
            "counts_scope": "unique recommended courses; title/snippet relevance with optional observed chapters; no playback verification"}}
    job_ids = list(dict.fromkeys(batch["job_id"] for batch in data.get("batches", []) if batch.get("job_id")))
    jobs = [job for job_id in job_ids if (job := store.get_job(job_id))]
    active = data.get("status") in {"analyzing", "running"} or any(job["status"] in ACTIVE for job in jobs)
    groups = [point["result"] for point in result.get("points", []) if point.get("result")]
    summary = pipeline(groups, jobs, terminal=not active, status=data.get("status"))
    summary["source_limited"] |= any(attempts_limited(store.attempts(job_id)) for job_id in job_ids)
    if not jobs:
        summary["search_budget"] = (data.get("budgets") or {}).get("reserved_search_requests", 0)
    return {**result, "pipeline": summary}


def event(name, value):
    content = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(content.encode()).hexdigest()[:20]
    return f"id: {digest}\nevent: {name}\ndata: {content}\n\n"


async def result_events(request, read_snapshot, revision, initial, *, initial_revision=None, interval=.35, heartbeat=15):
    """Coalesce DB changes, emit only changed snapshots, and release on disconnect.

    The SQLite change counter avoids rebuilding all course assessments when the
    source is idle. A fresh initial snapshot makes Last-Event-ID replay unnecessary.
    No worker, source query or per-client queue is created by a subscription.
    """
    snapshot = initial
    # Endpoints capture this synchronously with the initial projection. Capturing
    # here would miss a final write between route return and generator startup.
    # Other callers that omit it receive one unconditional refresh after initial.
    seen_revision = initial_revision
    previous = None
    last_sent = time.monotonic()
    while not await request.is_disconnected():
        if snapshot is not None:
            message = event("snapshot", snapshot)
            if message != previous:
                yield message
                previous = message
                last_sent = time.monotonic()
            if snapshot["pipeline"]["terminal"] and not snapshot["pipeline"].get("catalog_pending"):
                yield event("complete", snapshot)
                return
            snapshot = None
        await asyncio.sleep(interval)
        if await request.is_disconnected():
            return
        if revision() != seen_revision:
            snapshot = read_snapshot()
            seen_revision = revision()
            if snapshot is None:
                yield event("error", {"message": "任务已不可用，请刷新列表。"})
                return
        elif time.monotonic() - last_sent >= heartbeat:
            yield ": keep-alive\n\n"
            last_sent = time.monotonic()
