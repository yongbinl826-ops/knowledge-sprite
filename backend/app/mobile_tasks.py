"""Capability-bound, absolute-lifetime personal processing on one RAM queue."""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict, deque
from contextlib import suppress
import hashlib
import hmac
import ipaddress
import json
import math
import re
import sqlite3
import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import Store
from .models import SearchRequest, now
from .project_models import AnalysisDocument, ProjectInput, ReviewedTopicTechnologies
from .professional_concepts import reviewed_technologies
from .project_service import ProjectError
from .service import AdmissionRejected, JobService
from .mobile_public import COUNTERS, DailyBudgetFull, iso


class MobileError(Exception):
    def __init__(self, code="not_found", status=404, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after
        self.message = "任务不存在或已失效" if status == 404 else {
            409: "任务标识已用于不同操作，请新建任务。", 422: "操作内容无效，请检查后重试。",
            429: "暂时达到处理或每日预算上限，请稍后再试。", 503: "服务暂时无法接收新任务。"}.get(status, "任务暂时无法处理。")


class MobileTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["analysis", "search", "direct_search"]
    input: ProjectInput | None = None
    analysis: AnalysisDocument | None = None
    request: SearchRequest | None = None
    acknowledged_skipped_prerequisites: list[str] = Field(default_factory=list, max_length=24)
    reviewed_topic_technologies: ReviewedTopicTechnologies | None = None

    @model_validator(mode="after")
    def exact_kind_fields(self):
        if self.kind != "search" and self.reviewed_topic_technologies is not None:
            raise ValueError("Reviewed context is only valid for reviewed project search")
        if self.kind == "analysis" and (self.input is None or self.analysis is not None or self.request is not None or self.acknowledged_skipped_prerequisites):
            raise ValueError("Analysis requires only input")
        if self.kind == "search" and (self.input is None or self.analysis is None or self.request is not None):
            raise ValueError("Search requires input and reviewed analysis")
        if self.kind == "search" and self.reviewed_topic_technologies is not None:
            reviewed_technologies(self.reviewed_topic_technologies, self.analysis.model_dump()["knowledge_points"])
        if self.kind == "direct_search" and (self.request is None or self.input is not None or self.analysis is not None or self.acknowledged_skipped_prerequisites):
            raise ValueError("Direct search requires only request")
        return self


def task_id(value):
    try:
        parsed = UUID(value)
        if parsed.version == 4 and str(parsed) == value:
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    raise MobileError()


def capability(headers):
    values = headers.getlist("authorization")
    if len(values) != 1 or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", values[0]):
        raise MobileError()
    raw = values[0][7:]
    decoded = base64.urlsafe_b64decode(raw + "=")
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != raw:
        raise MobileError()
    return hashlib.sha256(decoded).digest()


class MobileRAMStore(Store):
    def __init__(self):
        super().__init__(":memory:")
        self.connection.execute("PRAGMA secure_delete=ON")
        self.connection.execute("PRAGMA temp_store=MEMORY")

    def active_job_for_request(self, _request):
        # A later device task must never extend an earlier personal job's TTL.
        return None


class MobileJobService(JobService):
    async def _worker(self):
        # Same single serialized queue. Do not retain the last complete job in
        # an idle worker frame after its RAM rows have expired.
        while True:
            job_id = await self.queue.get()
            job = None
            try:
                await asyncio.create_task(self.run(job_id))
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                with suppress(Exception):
                    job = self.store.get_job(job_id)
                    if job and job["status"] in {"queued", "running"}:
                        job.update(status="failed", phase="done")
                        job["errors"].append({"code": "internal_error", "message": "任务处理失败，请手动重试。"})
                        self._save(job)
            finally:
                with suppress(Exception):
                    job = self.store.get_job(job_id)
                    if job:
                        self.recent_outcomes.append({"status": job["status"], "at": job["updated_at"]})
                job = None
                self.queue.task_done()


class MobileTasks:
    def __init__(self, settings, store, jobs, projects, public, *, clock=None, monotonic=None):
        self.settings, self.store, self.jobs, self.projects, self.public = settings, store, jobs, projects, public
        # The shared queue reads public extractor facts on each new task. No
        # task capability, private project or prior match is given to the library.
        self.jobs.public_library = public
        self.clock, self.monotonic = clock or time.time, monotonic or time.monotonic
        self.records, self.tombstones, self.ip_buckets = {}, set(), OrderedDict()
        self.observation_memo = OrderedDict()
        self.public_observation_error = False
        self.lock = asyncio.Lock()
        self.cleaner = None

    def start(self):
        self.cleaner = asyncio.create_task(self._clean_loop())

    async def _clean_loop(self):
        while True:
            await asyncio.sleep(self.settings.mobile_cleanup_interval_seconds)
            await self.cleanup_once(observe=True)

    def healthy(self):
        return bool(self.cleaner and not self.cleaner.done() and self.public.healthy())

    def rate(self, peer, *, new=False):
        try:
            key = str(ipaddress.ip_address(peer))
        except (ValueError, TypeError):
            key = "unknown-peer"
        current = self.monotonic()
        self._prune_ips(current)
        if key not in self.ip_buckets:
            if len(self.ip_buckets) >= self.settings.mobile_max_ip_buckets:
                raise MobileError("peer_rate_capacity", 429, 60)
            self.ip_buckets[key] = {"all": deque(), "new": deque()}
        bucket = self.ip_buckets[key]
        for name, limit in (("all", self.settings.mobile_per_ip_requests_per_minute),
                            ("new", self.settings.mobile_per_ip_tasks_per_minute)):
            if name == "new" and not new:
                continue
            if len(bucket[name]) >= limit:
                raise MobileError("peer_rate_limited", 429, max(1, math.ceil(60 - current + bucket[name][0])))
        bucket["all"].append(current)
        if new:
            bucket["new"].append(current)

    def _prune_ips(self, current):
        for key, bucket in list(self.ip_buckets.items()):
            for values in bucket.values():
                while values and current - values[0] >= 60:
                    values.popleft()
            if not any(bucket.values()):
                self.ip_buckets.pop(key, None)

    def _auth(self, identifier, digest):
        record = self.records.get(identifier)
        if not record or not hmac.compare_digest(record["cap_digest"], digest):
            raise MobileError()
        return record

    def _status(self, record):
        if record.get("cancelled"):
            return "cancelled"
        if record.get("error"):
            return "failed"
        if record.get("project_id"):
            version = self.projects.db.version(record["project_id"], 1)
            raw = (version or {}).get("status", "failed")
        else:
            raw = (self.store.get_job(record.get("job_id")) or {}).get("status", "failed")
        if raw in {"analyzed", "completed", "no_results"}:
            return "completed"
        if raw == "partial":
            return "partial"
        if raw == "cancelled":
            return "cancelled"
        if raw in {"analyzing", "running"}:
            return "running"
        if raw in {"queued", "confirmed"}:
            return "queued"
        return "failed"

    def _view(self, record):
        result, error = None, record.get("error")
        if record.get("project_id"):
            if record["kind"] == "analysis":
                result = self.projects.view(record["project_id"], 1)
            else:
                result = self.projects.results(record["project_id"], 1)
            raw_error = (result.get("version") or {}).get("error")
            if raw_error:
                error = {"code": raw_error.get("code", "task_failed"), "message": "任务处理失败，请保留本机内容后手动重试。"}
        elif record.get("job_id"):
            result = self.jobs.results(record["job_id"])
        return {"task_id": record["task_id"], "kind": record["kind"], "expires_at": iso(record["expires_at"]),
                "status": self._status(record), "error": error, "result": result}

    def _job_ids(self, record):
        if record.get("project_id"):
            row = self.projects.db.version(record["project_id"], 1) or {}
            return {b["job_id"] for b in row.get("batches", []) if b.get("job_id")}
        return {record["job_id"]} if record.get("job_id") else set()

    def _costs(self, payload, selected=None):
        costs = dict.fromkeys(COUNTERS, 0)
        costs["tasks"] = 1
        if payload.kind == "analysis":
            costs.update(analysis_calls=2, model_calls=2)
            return costs
        if payload.kind == "direct_search":
            from .platform_search import platform_budget
            request = payload.request
            plan = platform_budget(self.settings, len(request.knowledge_points), request.preferred_platforms)
            costs["search_requests"] = plan["max_search_requests"] if plan else self.settings.max_search_requests
            costs["detail_pages"] = self.settings.max_detail_pages
            n = len(request.knowledge_points)
            # Even a partially populated skill map with no platform lanes can
            # expand the other points, then rerank every point. Reserve the
            # whole worst case, never infer actual spend from this amount.
            costs["model_calls"] = (2 * n + self.settings.teaching_match_max_calls_per_job + 1 if request.learning_skills else 2 * n)
            fallback_batches = 1
            fallback_platforms = request.preferred_platforms
        else:
            budget = self.projects._budget(selected, payload.input.preferred_platforms)
            costs["search_requests"] = budget["reserved_search_requests"]
            costs["detail_pages"] = budget["reserved_detail_pages"]
            costs["model_calls"] = 2 * len(selected)
            fallback_batches = budget["batch_count"]
            fallback_platforms = payload.input.preferred_platforms
        if (self.settings.ai_video_fallback_enabled and self.settings.fetch_enabled
                and self.settings.search_provider != "official_sitemap" and fallback_platforms):
            costs["model_calls"] += fallback_batches
        # 4 page hops * (1 page + up to 4 robot hops) * 2 attempts.
        # Renderer is disabled in mobile mode. This is reservation, not spend.
        costs["detail_http"] = costs["detail_pages"] * 40
        return costs

    async def create(self, identifier, digest, payload, peer):
        await self.cleanup_once()
        fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).digest()
        async with self.lock:
            if identifier in self.records:
                record = self._auth(identifier, digest)
                if not hmac.compare_digest(record["payload_digest"], fingerprint):
                    raise MobileError("task_conflict", 409)
                return self._view(record)
            if identifier in self.tombstones:
                raise MobileError()
            if not self.healthy():
                raise MobileError("mobile_not_ready", 503)
            self.rate(peer, new=True)
            if len(self.records) >= self.settings.mobile_max_tasks:
                raise MobileError("task_capacity", 429, self.settings.mobile_cleanup_interval_seconds)
            if len(self.tombstones) >= self.settings.mobile_max_tombstones:
                raise MobileError("task_id_capacity", 429, 60)
            if sum(self._status(r) in {"queued", "running"} for r in self.records.values()) >= self.settings.mobile_max_active_tasks:
                raise MobileError("active_task_capacity", 429, 5)
            pending, limit = ((self.projects.analysis_tasks, self.settings.max_pending_analyses)
                if payload.kind == "analysis" else (self.projects.tasks, self.settings.max_pending_project_searches))
            if payload.kind != "direct_search" and sum(not t.done() for t in pending.values()) >= limit:
                raise MobileError("task_queue_full", 429, 5)
            project_id = None
            selected = None
            try:
                if payload.kind == "search":
                    project = self.projects.create(payload.input)
                    project_id = project["project_id"]
                    data = self.projects._new_version(project, payload.input.model_dump(), status="analyzed",
                        analysis=payload.analysis.model_dump(), origin="student_edit")
                    data.update(model=None, prompt_version=None)
                    self.projects.db.save(project_id, data, new=True)
                    confirmed = self.projects.confirm(project_id, 1, payload.acknowledged_skipped_prerequisites,
                        reviewed_topic_technologies=payload.reviewed_topic_technologies)
                    by_id = {p["id"]: p for p in payload.analysis.model_dump()["knowledge_points"]}
                    selected = [by_id[k] for k in confirmed["version"]["confirmation"]["selected_ids"]]
                costs = self._costs(payload, selected)
                self.public.reserve(costs)
            except DailyBudgetFull:
                if project_id:
                    self._delete_project(project_id)
                raise MobileError("daily_budget_exhausted", 429, 3600) from None
            except sqlite3.Error:
                if project_id:
                    self._delete_project(project_id)
                raise MobileError("mobile_not_ready", 503) from None
            except (ProjectError, ValueError):
                if project_id:
                    self._delete_project(project_id)
                raise MobileError("invalid_request", 422) from None
            current = self.clock()
            record = {"task_id": identifier, "kind": payload.kind, "cap_digest": digest, "payload_digest": fingerprint,
                      "expires_at": current + self.settings.mobile_task_ttl_seconds,
                      "deadline": self.monotonic() + self.settings.mobile_task_ttl_seconds,
                      "project_id": project_id, "job_id": None}
            self.records[identifier] = record
            try:
                if payload.kind == "analysis":
                    record["project_id"] = self.projects.create(payload.input)["project_id"]
                    self.projects.analyze(record["project_id"], 0)
                elif payload.kind == "search":
                    self.projects.search(project_id, 1)
                else:
                    created = self.jobs.create(payload.request, idempotency_key="mobile:" + identifier,
                                               consumer_key="mobile:" + identifier)
                    record["job_id"] = created["job_id"]
            except (ProjectError, AdmissionRejected, ValueError):
                # Reservation is deliberately not returned; a failed start must
                # also stay idempotent under uncertain network delivery.
                record["error"] = {"code": "task_start_failed", "message": "任务暂时无法启动，请稍后手动创建新任务。"}
            return self._view(record)

    async def get(self, identifier, digest):
        await self.cleanup_once()
        async with self.lock:
            return self._view(self._auth(identifier, digest))

    async def cancel(self, identifier, digest):
        await self.cleanup_once()
        async with self.lock:
            record = self._auth(identifier, digest)
            if self._status(record) in {"queued", "running"}:
                await self._cancel(record)
                record["cancelled"] = True
            return self._view(record)

    async def _cancel(self, record):
        pid = record.get("project_id")
        if pid:
            for mapping in (self.projects.analysis_tasks, self.projects.tasks):
                pending = mapping.get((pid, 1))
                if pending and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                mapping.pop((pid, 1), None)
            for jid in self._job_ids(record):
                await self.jobs.cancel(jid)
            data = self.projects.db.version(pid, 1)
            if data and data["status"] in {"analyzing", "confirmed", "running"}:
                data.update(status="cancelled", cancel_requested=True)
                self.projects.db.save(pid, data)
        elif record.get("job_id"):
            await self.jobs.cancel(record["job_id"])

    def _delete_project(self, pid):
        conn = self.store.connection
        for table in ("project_point_job_mappings", "project_prerequisites", "project_functions",
                      "project_knowledge_points", "project_batches", "project_versions"):
            conn.execute(f"DELETE FROM {table} WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.commit()

    def _erase(self, record):
        job_ids = self._job_ids(record)
        if record.get("project_id"):
            self._delete_project(record["project_id"])
        conn = self.store.connection
        for jid in job_ids:
            for table in ("matches", "evidence", "search_attempts", "resources", "knowledge_points", "job_consumers", "idempotency_keys"):
                conn.execute(f"DELETE FROM {table} WHERE job_id=?", (jid,))
            conn.execute("DELETE FROM jobs WHERE id=?", (jid,))
            self.jobs.cancel_requested.discard(jid)
        conn.execute("DELETE FROM cache")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mooc_refresh_state'").fetchone():
            # A refresh topic digest is derived from a private request. Expiry
            # may conservatively clear these leases; daily reservations remain
            # solely in the separate persistent public/aggregate database.
            conn.execute("DELETE FROM mooc_refresh_state")
        conn.commit()
        self.jobs._prune_queue()
        if hasattr(self.jobs, "_read_rank_cache"):
            del self.jobs._read_rank_cache
        for provider in self.jobs._providers.values():
            for field in ("last_requests", "last_warnings"):
                if hasattr(provider, field):
                    setattr(provider, field, [])
        if hasattr(self.jobs.fetcher, "request_trace"):
            self.jobs.fetcher.request_trace.clear()
        for key in list(self.observation_memo):
            if key[0] == record["task_id"]:
                self.observation_memo.pop(key)

    def _observe(self):
        for record in self.records.values():
            for jid in self._job_ids(record):
                for rid, resource in self.store.resources(jid).items():
                    evidence = self.store.evidence(jid, rid)
                    key = (record["task_id"], jid, rid)
                    fingerprint = hashlib.sha256(json.dumps([resource, evidence], sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode()).digest()
                    if self.observation_memo.get(key) == fingerprint:
                        self.observation_memo.move_to_end(key)
                        continue
                    self.public.observe(resource, evidence)
                    self.observation_memo[key] = fingerprint
                    self.observation_memo.move_to_end(key)
                    while len(self.observation_memo) > 4096:
                        self.observation_memo.popitem(last=False)

    async def cleanup_once(self, *, force=False, observe=False):
        async with self.lock:
            for identifier, record in list(self.records.items()):
                if force or self.clock() >= record["expires_at"] or self.monotonic() >= record["deadline"]:
                    await self._cancel(record)
                    self._erase(record)
                    self.records.pop(identifier)
                    self.tombstones.add(identifier)
            if not force and observe:
                try:
                    self._observe()
                    self.public.prune()
                    self.public_observation_error = False
                except (sqlite3.Error, ValueError, TypeError):
                    # Public observation is optional; private TTL cleanup must
                    # continue even if persistence is temporarily unavailable.
                    self.public_observation_error = True
            self._prune_ips(self.monotonic())

    async def stop(self):
        if self.cleaner:
            self.cleaner.cancel()
            await asyncio.gather(self.cleaner, return_exceptions=True)
            self.cleaner = None
        await self.cleanup_once(force=True)
        self.records.clear()
        self.tombstones.clear()
        self.ip_buckets.clear()
        self.observation_memo.clear()
