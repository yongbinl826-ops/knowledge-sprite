from __future__ import annotations

import asyncio
import hashlib
import re
import time
import math
from collections import deque
from datetime import datetime, timezone
from copy import deepcopy
from contextlib import suppress
from uuid import uuid4
from urllib.parse import urlsplit
from .config import Settings
from .db import Store
from .fetcher import Fetcher, FetcherConfig, FETCH_DEADLINE_AT, PLATFORM_POLICY_REVIEWS, normalize_url, platform_for_url
from .llm import build_llm
from .models import Candidate, Query, Resource, SearchRequest, now
from .providers import SearchError, SearXNGProvider, build_provider
from .queries import generate_queries, fair_queries
from .ranking import has_course_discovery, has_learning_evidence, has_type_evidence, has_video_evidence, rank_resource, type_from_discovered_url
from .resource_identity import derive_course_identity, diversify, summarize_course_identities
from .url_utils import UnsafeURL
from .ranking import candidate_topic_signal, search_course_evidence, summarize_collection_coverage


class BudgetReached(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class AdmissionRejected(Exception):
    def __init__(self, code: str, message: str, retry_after: int = 1, status: int = 429):
        self.code, self.message, self.retry_after, self.status = code, message, retry_after, status


class JobService:
    """A persistent, single-process queue. Jobs are serialized; page requests are bounded."""
    def __init__(self, settings: Settings, store: Store, provider=None, fetcher=None, llm=None):
        self.settings, self.store = settings, store
        self.provider_error = None
        self.fetcher = fetcher or Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
            timeout_seconds=settings.fetch_timeout_seconds, global_concurrency=settings.global_concurrency,
            min_interval_seconds=settings.fetch_min_interval_seconds,
            allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
            bilibili_public_metadata=settings.bilibili_public_metadata,
            dns_resolver=settings.dns_resolver, phased_timeouts=settings.fetch_phased_timeouts,
            body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
            body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
            body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
        if isinstance(self.fetcher, Fetcher):
            from .rendering import RenderConfig, SafeRenderer
            self.fetcher.renderer = SafeRenderer(RenderConfig(**self._renderer_profile()["config"]))
        try:
            self.provider = provider or build_provider(settings, fetcher=self.fetcher, store=store)
        except SearchError as exc:
            self.provider, self.provider_error = None, exc
        self.official_fallback = None
        if settings.official_sitemap_fallback and settings.search_provider != "official_sitemap":
            from .official_sitemap import OfficialSitemapProvider
            self.official_fallback = OfficialSitemapProvider(settings, fetcher=self.fetcher, store=store)
        self.llm = llm or build_llm(settings)
        self.llm_status = "configured" if self.llm else "unconfigured"
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_pending_jobs)
        self.submissions: deque[float] = deque()
        self.admission_rejections = 0
        self.recent_outcomes: deque[dict] = deque(maxlen=50)
        self.accepting = True
        self.worker: asyncio.Task | None = None
        self.active_tasks: dict[str, asyncio.Task] = {}
        self.cancel_requested: set[str] = set()

    def start(self):
        if self.worker and not self.worker.done():
            return
        self.store.recover()
        self.accepting = True
        self.worker = asyncio.create_task(self._worker())

    async def stop(self):
        self.accepting = False
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
            self.worker = None
        self.store.recover()

    def create(self, request: SearchRequest, idempotency_key: str | None = None) -> dict:
        if len(request.knowledge_points) > self.settings.max_knowledge_points:
            raise ValueError("知识点数量超过当前服务预算")
        if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", idempotency_key):
            raise ValueError("幂等键格式无效")
        normalized = request.model_dump()
        for field in ("project_context", "technical_version"):
            normalized[field] = " ".join(normalized[field].split())
        # Preserve meaningful point/platform scheduling order, but ignore repeats.
        normalized["preferred_platforms"] = list(dict.fromkeys(normalized["preferred_platforms"]))
        request_hash = self.store.cache_key("request", normalized)
        if idempotency_key:
            prior = self.store.idempotent_request(idempotency_key)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise IdempotencyConflict()
                existing = self.store.get_job(prior["job_id"])
                return {"job_id": existing["job_id"], "status": existing["status"], "reused": True}
        existing = self.store.active_job_for_request(normalized)
        if existing:
            if idempotency_key:
                self.store.bind_idempotency_key(idempotency_key, request_hash, existing["job_id"])
            return {"job_id": existing["job_id"], "status": existing["status"], "reused": True}
        self._prune_queue()
        if not self.accepting or (self.worker is not None and self.worker.done()):
            self.admission_rejections += 1
            raise AdmissionRejected("worker_unavailable", "任务工作进程不可用，请检查健康状态", status=503)
        current = time.monotonic()
        while self.submissions and current - self.submissions[0] >= 60:
            self.submissions.popleft()
        if self.queue.full():
            self.admission_rejections += 1
            raise AdmissionRejected("queue_full", "等待任务已达上限，请稍后再试", retry_after=5)
        if len(self.submissions) >= self.settings.submission_limit_per_minute:
            self.admission_rejections += 1
            raise AdmissionRejected("submission_rate_limited", "新任务提交过于频繁，请稍后再试",
                                    retry_after=max(1, math.ceil(60 - (current - self.submissions[0]))))
        job_id = str(uuid4())
        stamp = now()
        job = {"job_id": job_id, "status": "queued", "phase": "queued", "created_at": stamp, "updated_at": stamp,
               "request": normalized, "knowledge_points": [{"knowledge_point_id": str(uuid4()), "text": text} for text in request.knowledge_points],
               "progress": {"queries_planned": 0, "queries_completed": 0, "search_requests": 0, "search_successes": 0,
                            "search_failures": 0, "candidates_discovered": 0, "resources_discovered": 0,
                            "details_attempted": 0, "details_completed": 0, "details_cached": 0, "cache_hits": 0,
                            "catalog_pages_attempted": 0, "catalog_pages_completed": 0},
               "budgets": {"max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                           "deadline_seconds": self.settings.deadline_seconds}, "warnings": [], "errors": []}
        self.store.create_job(job, idempotency_key, request_hash)
        self.queue.put_nowait(job_id)
        self.submissions.append(current)
        return {"job_id": job_id, "status": "queued", "reused": False}

    def _prune_queue(self):
        # No await: admission and queue cleanup are atomic on the single event loop.
        drained = []
        while not self.queue.empty():
            drained.append(self.queue.get_nowait())
        retained = drained
        try:
            retained = [job_id for job_id in drained
                        if (job := self.store.get_job(job_id)) and job["status"] == "queued"]
        finally:
            # Restore every entry if a DB read failed; never orphan persisted jobs.
            # Requeue before task_done so queue.join cannot observe a false zero.
            for job_id in retained:
                self.queue.put_nowait(job_id)
            for _ in drained:
                self.queue.task_done()

    def health(self):
        alive = self.worker is not None and not self.worker.done()
        database_ok = True
        try:
            counts = self.store.job_counts()
            waiting = self.store.oldest_queued_at()
        except Exception:
            database_ok, counts, waiting = False, {}, None
        wait = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(waiting)).total_seconds()) if waiting else 0.0
        provider = self.provider
        current = time.monotonic()
        cooldowns = {name: round(until - current, 3) for name, until in getattr(provider, "engine_pauses", {}).items() if until > current}
        return {"status": "ok" if alive and database_ok and self.accepting else "degraded", "mode": "live", "single_worker": True,
                "worker_alive": alive, "database_ok": database_ok, "accepting": self.accepting,
                "queue_depth": counts.get("queued", 0), "queue_capacity": self.settings.max_pending_jobs,
                "oldest_queue_wait_seconds": round(wait, 3), "active_jobs": len(self.active_tasks),
                "job_counts": counts, "admission_rejections": self.admission_rejections,
                "recent_outcomes": list(self.recent_outcomes),
                "source_cooldown_seconds": max(0, round(getattr(provider, "paused_until", 0) - current, 3)),
                "source_access_denied": bool(getattr(provider, "access_denied", False)), "engine_cooldowns": cooldowns}

    async def cancel(self, job_id: str) -> dict | None:
        job = self.store.get_job(job_id)
        if not job:
            return None
        if job["status"] not in {"queued", "running"}:
            return {"job_id": job_id, "status": job["status"], "cancelled": job["status"] == "cancelled"}
        task = self.active_tasks.get(job_id)
        if task and not task.done():
            if job_id not in self.cancel_requested:
                self.cancel_requested.add(job_id)
                task.cancel()
            # A cancelled child must finish its TaskGroup and network cleanup
            # before the endpoint confirms cancellation. Do not cancel the worker.
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            job = self.store.get_job(job_id)
        else:
            job.update(status="cancelled", phase="done")
            self._warn(job, "用户已取消任务；已保存的结果和来源证据仍可查看")
            self._save(job)
            self._prune_queue()
        return {"job_id": job_id, "status": job["status"], "cancelled": job["status"] == "cancelled"}

    def _save(self, job):
        job["updated_at"] = now()
        self.store.save_job(job)

    @staticmethod
    def _warn(job, text):
        if text not in job["warnings"]:
            job["warnings"].append(text)

    async def _worker(self):
        while True:
            job_id = await self.queue.get()
            try:
                # Separate task ownership lets one job be cancelled without
                # cancelling the queue that serves subsequent jobs.
                await asyncio.create_task(self.run(job_id))
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                # Also contain failures before run() reaches its execution guard.
                # Exception text can expose credentials or private endpoints.
                with suppress(Exception):
                    job = self.store.get_job(job_id)
                    if job and job["status"] in {"queued", "running"}:
                        job.update(status="failed", phase="done")
                        job["errors"].append({"code": "internal_error", "message": "任务处理异常，队列继续处理后续任务；已保存的证据仍可查看"})
                        self._save(job)
            finally:
                # Monitoring must not kill the worker after a transient DB error.
                try:
                    with suppress(Exception):
                        job = self.store.get_job(job_id)
                        if job:
                            self.recent_outcomes.append({"status": job["status"], "at": job["updated_at"]})
                finally:
                    self.queue.task_done()

    async def run(self, job_id: str):
        job = self.store.get_job(job_id)
        if not job or job["status"] != "queued":
            return
        waited = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"])).total_seconds())
        job["queue_wait_seconds"] = round(waited, 3)
        if waited >= self.settings.max_queue_wait_seconds:
            job.update(status="interrupted", phase="done")
            job["errors"].append({"code": "queue_wait_expired", "message": "排队等待超过期限，未发起外部请求；可重新提交"})
            self._save(job)
            return
        task = asyncio.current_task()
        self.active_tasks[job_id] = task
        trace_started_at = now()
        trace_before = dict(getattr(self.fetcher, "trace_counts", {}))
        ends_at = asyncio.get_running_loop().time() + self.settings.deadline_seconds
        parent_deadline = FETCH_DEADLINE_AT.get()
        deadline_token = FETCH_DEADLINE_AT.set(min(ends_at, parent_deadline) if parent_deadline is not None else ends_at)
        try:
            await self._run_job(job)
        finally:
            try:
                trace_after = dict(getattr(self.fetcher, "trace_counts", {}))
                delta = {key: value - trace_before.get(key, 0) for key, value in trace_after.items()
                         if value > trace_before.get(key, 0)}
                events = [deepcopy(event) for event in getattr(self.fetcher, "request_trace", [])
                          if event.get("at", "") >= trace_started_at][-512:]
                job["fetch_diagnostics"] = {"available": hasattr(self.fetcher, "request_trace"),
                    "started_at": trace_started_at, "finished_at": now(), "counts_delta": delta,
                    "events": events, "truncated": sum(delta.values()) > len(events),
                    "scope": "target HTML/XML+robots only; DoH HTTP separately traced for official discovery"
                        if self.settings.search_provider == "official_sitemap" or self.official_fallback
                        else "target HTML+robots only; DoH HTTP uncounted"}
                self._save(job)
            finally:
                self.active_tasks.pop(job_id, None)
                self.cancel_requested.discard(job_id)
                FETCH_DEADLINE_AT.reset(deadline_token)

    async def _run_job(self, job):
        job.update(status="running", phase="expanding")
        self._save(job)
        try:
            async with asyncio.timeout_at(FETCH_DEADLINE_AT.get()):
                await self._execute(job)
            progress = job["progress"]
            if progress["search_successes"] == 0 and progress["search_failures"]:
                job["status"] = "failed"
            elif progress["search_failures"] or job.pop("budget_limited", False) or job.pop("upstream_partial", False):
                job["status"] = "partial"
            else:
                job["status"] = "completed"
        except TimeoutError:
            job["status"] = "partial" if job["progress"]["search_successes"] else "failed"
            self._warn(job, "达到任务期限，已保存目前结果；搜索与页面补全范围受限")
            unfinished = job["progress"]["details_attempted"] - job["progress"]["details_completed"]
            if unfinished > 0:
                self._warn(job, f"{unfinished} 个已开始的详情补全未在期限内完成，仍保留搜索发现状态，页面详情尚未核验")
            unfinished_catalog = job["progress"]["catalog_pages_attempted"] - job["progress"]["catalog_pages_completed"]
            if unfinished_catalog > 0:
                self._warn(job, f"{unfinished_catalog} 个已开始的公开目录页面未在期限内完成，目录尚未核验")
        except asyncio.CancelledError:
            user_cancelled = job["job_id"] in self.cancel_requested
            job["status"] = "cancelled" if user_cancelled else "interrupted"
            self._warn(job, "用户已取消任务；已保存的结果和来源证据仍可查看" if user_cancelled else "服务停止，任务被中断；可重新提交")
            job.pop("budget_limited", None)
            job.pop("upstream_partial", None)
            job["phase"] = "done"
            self._save(job)
            raise
        except Exception:
            # External exception messages can contain Authorization or internal service addresses.
            job["status"] = "partial" if job["progress"]["search_successes"] else "failed"
            job["errors"].append({"code": "internal_error", "message": "任务处理异常，已保留可用证据；请检查服务端运行条件"})
        job.pop("budget_limited", None)
        job.pop("upstream_partial", None)
        job["phase"] = "done"
        self._save(job)

    async def _execute(self, job):
        request = SearchRequest.model_validate(job["request"])
        if self.settings.search_provider == "official_sitemap":
            self._warn(job, "本次仅使用 MIT 官方声明的站点地图；URL 路径词仅用于低置信召回，课程与知识点覆盖须由实际页面确认，其他平台不在本次来源范围")
        points = job["knowledge_points"]
        queries = []
        for point in points:
            if self.settings.search_provider == "official_sitemap":
                queries.append([Query(knowledge_point_id=point["knowledge_point_id"], query=point["text"])])
                continue
            expansions = []
            if self.llm:
                try:
                    expansions = await self.llm.expand(point["text"], request.project_context)
                    self.llm_status = "available"
                except Exception:
                    self.llm_status = "fault"
                    self._warn(job, "模型查询扩展失败，已回退到原始知识点和规则模板")
            queries.append(generate_queries(point["knowledge_point_id"], point["text"], request, expansions,
                open_course_domains=self.settings.open_course_domains))
        schedule = fair_queries(queries)
        job["progress"]["queries_planned"] = len(schedule)
        job["phase"] = "searching"
        self._save(job)
        point_map = {p["knowledge_point_id"]: p for p in points}
        resources = {}
        candidates = {}
        candidate_groups = {p["knowledge_point_id"]: [] for p in points}

        state = {"request": request, "points": points, "point_map": point_map, "resources": resources,
                 "candidates": candidates, "candidate_groups": candidate_groups, "ready": False,
                 "search_finished": False, "changed": asyncio.Event(), "started": set(), "reserved": 0,
                 "cursor": 0, "network_slots": asyncio.Semaphore(self.settings.global_concurrency)}
        # Search remains fair and serial. Detail work begins after every point's first
        # query, then progresses concurrently with subsequent search rounds.
        async with asyncio.TaskGroup() as group:
            group.create_task(self._run_details(job, state))
            try:
                await self._search_queries(job, schedule, state)
            finally:
                state["search_finished"] = True
                state["ready"] = True
                state["changed"].set()
                job["phase"] = "fetching"
                self._save(job)
        limited = [r for r in resources.values() if r.get("metadata_evidence_level") == "search"]
        if limited:
            self._warn(job, f"{len(limited)} 个候选仅搜索发现，页面详情未核验；不代表可播放或免费")
        unknown = sum(not has_type_evidence(resource, self.store.evidence(job["job_id"], resource["resource_id"])) for resource in resources.values())
        if unknown:
            self._warn(job, f"{unknown} 个候选缺少课程或视频类型依据，未作为学习资源展示")
        without_video = sum(has_type_evidence(resource, self.store.evidence(job["job_id"], resource["resource_id"]))
            and not has_video_evidence(resource, self.store.evidence(job["job_id"], resource["resource_id"]))
            and not has_course_discovery(resource, self.store.evidence(job["job_id"], resource["resource_id"])) for resource in resources.values())
        if without_video:
            self._warn(job, f"{without_video} 个已识别类型的候选缺少视频证据，未作为视频课程展示；普通课程目录不代表包含视频")
        discovered_courses = sum(has_course_discovery(resource, self.store.evidence(job["job_id"], resource["resource_id"]))
            and not has_video_evidence(resource, self.store.evidence(job["job_id"], resource["resource_id"])) for resource in resources.values())
        if discovered_courses:
            self._warn(job, f"{discovered_courses} 个搜索发现的课程候选尚未确认是否包含视频；课程入口发现不等于视频或可播放性核验")
        job["phase"] = "ranking"
        self._save(job)
        if self.llm:
            await self._rerank(job, resources)

    async def _search_queries(self, job, schedule, state):
        request, points = state["request"], state["points"]
        point_map, resources = state["point_map"], state["resources"]
        candidates, candidate_groups = state["candidates"], state["candidate_groups"]
        async def count_request():
            if job["progress"]["search_requests"] >= self.settings.max_search_requests:
                raise BudgetReached()
            job["progress"]["search_requests"] += 1
            self._save(job)
        async def check_request_budget():
            if job["progress"]["search_requests"] >= self.settings.max_search_requests:
                raise BudgetReached()
        async def count_discovery_dns():
            current = job["progress"].get("discovery_dns_requests", 0)
            if current >= 2 * self.settings.max_search_requests:
                raise BudgetReached()
            job["progress"]["discovery_dns_requests"] = current + 1
            self._save(job)
        if self.provider and hasattr(self.provider, "request_hook"):
            self.provider.request_hook = count_request
        for provider in (self.provider, self.official_fallback):
            if provider and getattr(provider, "name", None) == "official_sitemap":
                provider.dns_request_hook = count_discovery_dns
                provider.budget_check_hook = check_request_budget
                provider.request_hook = count_request

        for query_index, query in enumerate(schedule):
            cache_key = self.store.cache_key("search", {"provider": self.settings.search_provider,
                "provider_version": 12, "engines": getattr(self.settings, "searxng_engines", ()),
                "original_point": point_map[query.knowledge_point_id]["text"],
                "fallback_engines": getattr(self.settings, "searxng_fallback_engines", ()),
                "video_engines": getattr(self.settings, "searxng_video_engines", ()),
                "service_identity": hashlib.sha256(self.settings.searxng_url.encode()).hexdigest() if self.settings.search_provider == "searxng" else self.settings.search_provider,
                "official_sitemap": {"enabled": self.settings.official_sitemap_fallback, "version": 1,
                    "source_identity": "https://ocw.mit.edu/search/|robots-declared-sitemaps-v1",
                    "children": self.settings.official_sitemap_children_per_query,
                    "ttl": self.settings.official_sitemap_cache_ttl, "search_ttl": self.settings.search_cache_ttl,
                    "original_point": point_map[query.knowledge_point_id]["text"] if self.settings.search_provider == "official_sitemap" or self.official_fallback else None,
                    "dns": self.settings.dns_resolver, "fetch": self.settings.fetch_enabled,
                    "denied": self.settings.denied_fetch_hosts, "allowed": self.settings.allowed_restricted_hosts},
                "query": query.query, "language": request.language, "version": request.technical_version,
                "domains": query.domain_filters, "limit": self.settings.search_results_per_query})
            # An outer query cache must not extend the remaining lifetime of an
            # older index snapshot. Official discovery reuses its own source TTLs.
            query_cache_enabled = not (self.settings.search_provider == "official_sitemap" or self.official_fallback)
            cached = self.store.cache_get(cache_key) if query_cache_enabled else None
            network_attempted = False
            cache_info = {"hit": False, "cached_at": None, "stale": False}
            attempt = {"knowledge_point_id": query.knowledge_point_id, "query": query.query, "domain_filters": query.domain_filters,
                       "provider": self.settings.search_provider, "status": "completed", "candidate_count": 0,
                       "cache_hit": False, "cached_at": None, "stale": False, "error_code": None, "executed_at": now()}
            try:
                if cached:
                    cached_candidates = cached["data"].get("candidates", []) if isinstance(cached["data"], dict) else cached["data"]
                    items = [Candidate.model_validate(c) for c in cached_candidates]
                    cache_info = cached["cache"]
                else:
                    if self.provider_error:
                        raise self.provider_error
                    if not hasattr(self.provider, "request_hook"):
                        await count_request()
                    async with state["network_slots"]:
                        network_attempted = True
                        items = await self._discover(query, request, point_map[query.knowledge_point_id]["text"])
                    items = [c if isinstance(c, Candidate) else Candidate.model_validate(c) for c in items]
                    # Preserve upstream failures alongside results in the cache and execution record.
                    if query_cache_enabled:
                        self.store.cache_set(cache_key, "search", {"candidates": [c.model_dump() for c in items],
                            "upstream_warnings": getattr(self.provider, "last_warnings", []),
                            "provider_requests": getattr(self.provider, "last_requests", []),
                            "provider_dns_requests": getattr(self.provider, "last_dns_requests", []),
                            "discovery": getattr(self.provider, "last_discovery", {})}, self.settings.search_cache_ttl)
                job["progress"]["search_successes"] += 1
            except BudgetReached:
                job["budget_limited"] = True
                self._warn(job, "达到搜索请求预算；按知识点轮转执行，剩余查询未执行")
                requests = getattr(self.provider, "last_requests", [])
                if requests:
                    attempt.update(status="budget_exhausted", error_code="budget_exhausted", provider_requests=requests,
                        provider_dns_requests=getattr(self.provider, "last_dns_requests", []),
                        discovery=getattr(self.provider, "last_discovery", {}))
                    self.store.add_attempt(job["job_id"], attempt)
                    job["progress"]["queries_completed"] += 1
                break
            except SearchError as exc:
                attempt.update(status="failed", error_code=exc.code)
                job["progress"]["search_failures"] += 1
                error = {"code": exc.code, "message": exc.message}
                if error not in job["errors"]:
                    job["errors"].append(error)
                cached = self.store.cache_get(cache_key, allow_stale=self.settings.allow_stale_cache) if query_cache_enabled else None
                if cached:
                    cached_candidates = cached["data"].get("candidates", []) if isinstance(cached["data"], dict) else cached["data"]
                    items = [Candidate.model_validate(c) for c in cached_candidates]
                    cache_info = cached["cache"]
                    attempt["status"] = "stale_cache"
                    job["progress"]["search_successes"] += 1
                    self._warn(job, "搜索服务失败，部分结果来自明确标注时间的过期缓存")
                else:
                    items = []
            except asyncio.CancelledError:
                attempt.update(status="cancelled" if job["job_id"] in self.cancel_requested else "interrupted",
                    error_code="task_cancelled" if job["job_id"] in self.cancel_requested else "task_interrupted",
                    network_attempted=network_attempted,
                    provider_requests=getattr(self.provider, "last_requests", []) if network_attempted else [],
                    provider_dns_requests=getattr(self.provider, "last_dns_requests", []) if network_attempted else [],
                    upstream_warnings=getattr(self.provider, "last_warnings", []) if network_attempted else [])
                self.store.add_attempt(job["job_id"], attempt)
                raise
            except Exception:
                attempt.update(status="failed", error_code="search_unavailable")
                job["progress"]["search_failures"] += 1
                error = {"code": "search_unavailable", "message": "搜索来源处理失败；未使用演示结果"}
                if error not in job["errors"]:
                    job["errors"].append(error)
                items = []
            if cache_info["hit"]:
                job["progress"]["cache_hits"] += 1
            attempt["network_attempted"] = network_attempted
            attempt["upstream_warnings"] = getattr(self.provider, "last_warnings", []) if network_attempted else []
            attempt["provider_requests"] = getattr(self.provider, "last_requests", []) if network_attempted else []
            attempt["provider_dns_requests"] = getattr(self.provider, "last_dns_requests", []) if network_attempted else []
            attempt["discovery"] = getattr(self.provider, "last_discovery", {}) if network_attempted else {}
            origin = cached["data"] if cached and isinstance(cached["data"], dict) else {}
            attempt["cache_origin_requests"] = origin.get("provider_requests", [])
            attempt["cache_origin_warnings"] = origin.get("upstream_warnings", [])
            attempt["cache_origin_dns_requests"] = origin.get("provider_dns_requests", [])
            attempt["cache_origin_discovery"] = origin.get("discovery", {})
            if attempt["upstream_warnings"] or attempt["cache_origin_warnings"]:
                job["upstream_partial"] = True
                self._warn(job, "部分搜索或官方发现来源未完成查询；已保留成功来源的结果，搜索范围受限")
            attempt.update(cache_hit=cache_info["hit"], cached_at=cache_info["cached_at"], stale=cache_info["stale"], candidate_count=len(items))
            self.store.add_attempt(job["job_id"], attempt)
            job["progress"]["queries_completed"] += 1
            job["progress"]["candidates_discovered"] += len(items)
            for candidate in items:
                try:
                    canonical = normalize_url(candidate.url)
                except UnsafeURL:
                    self._warn(job, "已过滤不安全或不可用协议的候选链接")
                    continue
                rid = "res_" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
                eid = "ev_" + str(uuid4())
                evidence = {"evidence_id": eid, "candidate_id": candidate.id, "kind": "search", "source": candidate.source,
                            "source_engines": candidate.source_engines, "type_source": candidate.type_source,
                            "resource_type_hint": candidate.resource_type_hint, "knowledge_point_id": query.knowledge_point_id,
                            "query": candidate.query, "url": candidate.url, "title": candidate.title,
                            "snippet": candidate.snippet, "observed_at": candidate.discovered_at, "cache": cache_info}
                if candidate.thumbnail_url and candidate.thumbnail_source:
                    evidence["thumbnail_url"] = candidate.thumbnail_url
                    evidence["thumbnail_source"] = candidate.thumbnail_source
                if candidate.discovery_evidence:
                    evidence["discovery_evidence"] = candidate.discovery_evidence
                    evidence["cache"] = {"hit": bool(candidate.discovery_evidence.get("cache_hit")),
                        "cached_at": candidate.discovery_evidence.get("observed_at") if candidate.discovery_evidence.get("cache_hit") else None, "stale": False}
                self.store.add_evidence(job["job_id"], rid, query.knowledge_point_id, evidence)
                inferred_type = type_from_discovered_url(canonical)
                video_status = "search_discovered" if inferred_type == "video" or (
                    candidate.type_source == "search_template" and candidate.resource_type_hint in {"video", "playlist"}) else "none"
                type_provenance = {"evidence_id": eid, "source": "url_pattern", "url": candidate.url,
                    "note": "公开平台课程或视频入口格式推断；页面详情与可播放性尚未核验"}
                if inferred_type == "unknown" and candidate.type_source == "search_template" and candidate.resource_type_hint in {"video", "course", "playlist"}:
                    inferred_type = candidate.resource_type_hint
                    type_provenance.update(source="search_template", note="搜索来源按媒体模板分类；页面详情与可播放性尚未核验")
                if inferred_type == "unknown" and search_course_evidence(canonical, evidence):
                    inferred_type = "course"
                    type_provenance.update(source="search_title_url", note="搜索标题、摘要及课程入口格式共同支持；仅搜索发现，页面详情未核验")
                video_provenance = {"evidence_id": eid, "source": "url_pattern" if type_from_discovered_url(canonical) == "video" else "search_template",
                    "url": candidate.url, "note": "仅搜索发现视频入口或视频类结果；页面视频内容及可播放性尚未核验"}
                if rid not in resources:
                    provenance = {k: {"evidence_id": eid, "source": "search", "url": candidate.url} for k in ("title", "url", "description")}
                    if candidate.source == "official_sitemap":
                        provenance["title"]["note"] = "仅由实际 sitemap loc 的 URL 路径词推得，非已获取页面标题"
                    if inferred_type != "unknown":
                        provenance["resource_type"] = type_provenance
                    if video_status == "search_discovered":
                        provenance["video_evidence_status"] = video_provenance
                    resources[rid] = Resource(resource_id=rid, title=candidate.title, url=candidate.url,
                        canonical_url=canonical, platform=platform_for_url(canonical), discovered_at=candidate.discovered_at,
                        description=candidate.snippet or None, cache=cache_info, resource_type=inferred_type,
                        video_evidence_status=video_status, field_provenance=provenance).model_dump()
                    candidates[rid] = candidate.model_dump()
                    self.store.save_resource(job["job_id"], resources[rid])
                elif resources[rid]["resource_type"] == "unknown" and inferred_type != "unknown":
                    resources[rid]["resource_type"] = inferred_type
                    resources[rid]["field_provenance"]["resource_type"] = type_provenance
                    self.store.save_resource(job["job_id"], resources[rid])
                if candidate.thumbnail_url and candidate.thumbnail_source and not resources[rid].get("thumbnail_url"):
                    resources[rid]["thumbnail_url"] = candidate.thumbnail_url
                    resources[rid]["field_provenance"]["thumbnail_url"] = {
                        "evidence_id": eid, "source": candidate.thumbnail_source, "url": candidate.url,
                        "observed_at": candidate.discovered_at,
                        "note": "搜索结果提供的缩略图；未另行采集图片或核验播放"}
                if resources[rid]["video_evidence_status"] == "none" and video_status == "search_discovered":
                    resources[rid]["video_evidence_status"] = video_status
                    resources[rid]["field_provenance"]["video_evidence_status"] = video_provenance
                    self.store.save_resource(job["job_id"], resources[rid])
                if rid not in candidate_groups[query.knowledge_point_id]:
                    candidate_groups[query.knowledge_point_id].append(rid)
                resources[rid]["course_identity"] = derive_course_identity(resources[rid], self.store.evidence(job["job_id"], rid))
                self.store.save_resource(job["job_id"], resources[rid])
                # A later query can provide the first type evidence for a shared
                # URL. Refresh every previously discovered knowledge-point link.
                for point in points:
                    if rid in candidate_groups[point["knowledge_point_id"]]:
                        self._rank(job, point, resources[rid], request)
            job["progress"]["resources_discovered"] = len(resources)
            self._save(job)
            if query_index + 1 >= len(points):
                state["ready"] = True
            state["changed"].set()
            if attempt["error_code"] == "configuration_error":
                break
            if attempt["error_code"] == "access_denied":
                self._warn(job, "搜索服务拒绝访问，已停止剩余查询；保留此前结果及明确标注的缓存证据")
                break

    async def _discover(self, query, request, original_point):
        if getattr(self.provider, "name", None) == "official_sitemap":
            return await self.provider.search(original_point, request.language, self.settings.search_results_per_query,
                query.domain_filters, technical_version=request.technical_version)
        self.provider.last_dns_requests, self.provider.last_discovery = [], {}
        options = {"candidate_check": lambda candidate: candidate_topic_signal(candidate, original_point, request)} if isinstance(self.provider, SearXNGProvider) else {}
        items = await self.provider.search(query.query, request.language, self.settings.search_results_per_query, query.domain_filters, **options)
        if not self.official_fallback or any(candidate_topic_signal(candidate, original_point, request) for candidate in items):
            return items
        # Normal empty or irrelevant responses can invoke this opt-in fallback. Domain-scoped
        # MOOC/Bilibili queries stay in that scope; access errors never enter here.
        try:
            extra = await self.official_fallback.search(original_point, request.language,
                self.settings.search_results_per_query, query.domain_filters, technical_version=request.technical_version)
            # Resource dedup happens downstream; retain each source observation.
            return [*items, *extra]
        except SearchError as exc:
            # The primary completed normally with no results. An independent
            # optional source cannot revoke that outcome or stop later primary
            # queries. Its own provider retains its stop state and request trace.
            failure = {"code": "official_source_failed", "source": "official_sitemap",
                "reason_code": exc.code, "error_code": exc.code, "message": exc.message}
            self.official_fallback.last_status = "fault"
            self.provider.last_warnings = [*getattr(self.provider, "last_warnings", []), failure]
            self.official_fallback.last_discovery["failure"] = failure
            return items
        finally:
            self.provider.last_requests = [*getattr(self.provider, "last_requests", []), *self.official_fallback.last_requests]
            self.provider.last_dns_requests = self.official_fallback.last_dns_requests
            self.provider.last_discovery = self.official_fallback.last_discovery

    @staticmethod
    def _sitemap_only(evidence):
        searches = [row for row in evidence if row.get("kind") == "search"]
        return bool(searches) and all(row.get("source") == "official_sitemap" for row in searches)

    @staticmethod
    def _sitemap_page_covers(point, resource, evidence, request):
        from .official_sitemap import covers_original_topic
        if resource.get("fetch_status") not in {"fetched", "success"}:
            return False
        records = {row["evidence_id"]: row for row in evidence if row.get("kind") in {"page", "catalog"}}
        texts = []
        for field in ("title", "description"):
            basis = resource.get("field_provenance", {}).get(field, {})
            record = records.get(basis.get("evidence_id")) if isinstance(basis, dict) else None
            if record and record.get("field") == field:
                texts.append(resource.get(field) or "")
        # Real extractor catalog rows carry their own indexed evidence records.
        for index, chapter in enumerate(resource.get("chapters", [])):
            record = records.get(chapter.get("evidence_id"))
            if record and record.get("field") == f"chapters.{index}":
                texts.append(chapter.get("title") or "")
        return covers_original_topic(point["text"], " ".join(texts), request.technical_version)

    def _renderer_profile(self):
        return {"version": 6, "config": {
            "enabled": self.settings.js_render_enabled,
            "allowed_hosts": self.settings.js_render_allowed_hosts,
            "allowed_entries": self.settings.js_render_allowed_entries,
            "asset_hosts": self.settings.js_render_asset_hosts,
            "timeout_seconds": self.settings.js_render_timeout_seconds,
            "max_resources": self.settings.js_render_max_resources,
            "max_target_requests": self.settings.js_render_max_target_requests,
            "max_doh_requests": self.settings.js_render_max_doh_requests,
            "max_total_bytes": self.settings.js_render_max_total_bytes,
            "max_dom_bytes": self.settings.js_render_max_dom_bytes,
            "settle_ms": self.settings.js_render_settle_ms,
            "max_observed_data_resources": self.settings.js_render_max_observed_data_resources}}

    def _transport_profile(self):
        return {"version": 3, "phased_timeouts": self.settings.fetch_phased_timeouts,
            "bounded_content_encodings": ["identity", "gzip", "deflate"],
            "initial_timeout_seconds": self.settings.fetch_timeout_seconds,
            "body_idle_timeout_seconds": self.settings.fetch_body_idle_timeout_seconds,
            "body_min_bytes_per_second": self.settings.fetch_body_min_bytes_per_second,
            "body_timeout_cap_seconds": self.settings.fetch_body_timeout_cap_seconds}

    def _page_cache(self, resource):
        platform = platform_for_url(resource["canonical_url"])
        # An unclassified entry can redirect to, or follow a catalog page into,
        # any reviewed platform. Its canonical URL alone cannot select the policy.
        policy_review = PLATFORM_POLICY_REVIEWS.get(platform, PLATFORM_POLICY_REVIEWS)
        key = self.store.cache_key("page", {"url": resource["canonical_url"], "extractor_version": 13,
            "payload_version": 2,
            "platform_policy_review": policy_review,
            "enabled": self.settings.fetch_enabled, "allowed_restricted_hosts": self.settings.allowed_restricted_hosts,
            "bilibili_public_metadata": self.settings.bilibili_public_metadata,
            "denied_fetch_hosts": self.settings.denied_fetch_hosts,
            "dns_resolver": self.settings.dns_resolver, "transport": self._transport_profile(),
            "renderer": self._renderer_profile()})
        cached = self.store.cache_get(key, allow_stale=self.settings.allow_stale_cache)
        if cached and cached["cache"]["stale"] and not self._page_cache_complete(cached["data"]):
            # A short-lived failure is not a permanent stale-cache substitute for
            # a fresh attempt after its retry window or budget has recovered.
            cached = None
        return key, cached

    @staticmethod
    def _page_cache_complete(enriched):
        render_status = (enriched.get("render_diagnostics") or {}).get("status") or ""
        if render_status.startswith("render_") and render_status.endswith("_budget"):
            return False
        if not enriched.get("chapters") and render_status in {
            "render_timeout", "render_incomplete", "render_dependency_blocked", "render_failed"
        }:
            # Fetching the entry HTML does not complete an empty dynamic catalog.
            # Keep its page evidence, but permit another attempt after a short TTL.
            return False
        return enriched.get("fetch_status") in {"fetched", "success", "search_only_policy", "site_policy_blocked", "policy_unreviewed"} and enriched.get("catalog_fetch_status") in {None, "fetched", "success"}

    def _page_cache_ttl(self, enriched):
        render_status = (enriched.get("render_diagnostics") or {}).get("status") or ""
        if enriched.get("catalog_fetch_status") in {"budget_limited", "not_attempted"} or (
            render_status.startswith("render_") and render_status.endswith("_budget")
        ):
            return 0
        return self.settings.page_cache_ttl if self._page_cache_complete(enriched) else min(self.settings.page_cache_ttl, 300)

    @staticmethod
    def _page_metadata(enriched):
        """Keep source-page facts separate from query-specific search fallbacks."""
        result = deepcopy(enriched)
        records = [record for record in result.get("evidence", []) if record.get("kind") != "search"]
        record_map = {record.get("evidence_id") or record.get("id"): record for record in records}
        provenance = result.get("field_provenance", {})
        for field, basis in list(provenance.items()):
            if isinstance(basis, dict) and (basis.get("source") == "search" or basis.get("evidence_id") not in record_map):
                provenance.pop(field)
                if field not in {"fetch_status", "metadata_evidence_level"}:
                    result.pop(field, None)
        for field in ("title", "description"):
            basis = provenance.get(field, {})
            record = record_map.get(basis.get("evidence_id"), {}) if isinstance(basis, dict) else {}
            if record.get("kind") not in {"page", "catalog"}:
                result.pop(field, None)
                provenance.pop(field, None)
        for field in ("resource_id", "url", "canonical_url", "discovered_at", "cache"):
            result.pop(field, None)
            provenance.pop(field, None)
        result["evidence"], result["field_provenance"] = records, provenance
        return result

    def _detail_queues(self, job, state):
        queues = {}
        for point in state["points"]:
            entries = []
            for rid in state["candidate_groups"][point["knowledge_point_id"]]:
                if rid in state["started"]:
                    continue
                resource = state["resources"][rid]
                evidence = self.store.evidence(job["job_id"], rid, point["knowledge_point_id"])
                provisional = rank_resource(point, resource, evidence, state["request"], require_type=False)
                if provisional:
                    entries.append((has_learning_evidence(resource, evidence), provisional["ranking_score"], rid))
                elif self._sitemap_only(evidence):
                    # A bounded real <loc> may be fetched to establish type/title;
                    # URL words alone never qualify it for result display.
                    entries.append((False, 1, rid))
            queues[point["knowledge_point_id"]] = [entry[2] for entry in sorted(entries, key=lambda item: (-item[0], -item[1], item[2]))]
        return queues

    async def _run_details(self, job, state):
        """Round-robin, work-conserving scheduling; reserve budgets before dispatch."""
        pending: dict[asyncio.Task, str] = {}
        active_hosts: set[str] = set()
        try:
            while True:
                state["changed"].clear()
                for task in list(pending):
                    if task.done():
                        active_hosts.discard(pending.pop(task))
                        task.result()
                # While searching, leave capacity for the next fair search request.
                slots = self.settings.global_concurrency if state["search_finished"] else max(1, self.settings.global_concurrency - 1)
                queues = self._detail_queues(job, state) if state["ready"] else {}
                while len(pending) < slots and queues:
                    selected = None
                    points = state["points"]
                    for offset in range(len(points)):
                        index = (state["cursor"] + offset) % len(points)
                        for rid in queues[points[index]["knowledge_point_id"]]:
                            resource = state["resources"][rid]
                            host = urlsplit(resource["canonical_url"]).hostname or ""
                            if host in active_hosts:
                                continue
                            key, cached = self._page_cache(resource)
                            if not cached and state["reserved"] >= self.settings.max_detail_pages:
                                continue
                            selected = rid, host, key, cached
                            state["cursor"] = (index + 1) % len(points)
                            break
                        if selected:
                            break
                    if not selected:
                        break
                    rid, host, key, cached = selected
                    state["started"].add(rid)
                    if not cached:
                        state["reserved"] += 1
                    active_hosts.add(host)
                    task = asyncio.create_task(self._enrich_one(job, state, rid, key, cached))
                    pending[task] = host
                    queues = self._detail_queues(job, state)
                if state["search_finished"] and not pending:
                    if any(queues.values()) and state["reserved"] >= self.settings.max_detail_pages:
                        job["budget_limited"] = True
                        self._warn(job, "达到详情页预算；按知识点轮转补全，未确认类型的候选不会作为课程展示")
                    return
                changed = asyncio.create_task(state["changed"].wait())
                try:
                    await asyncio.wait([changed, *pending], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                    with suppress(asyncio.CancelledError):
                        await changed
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _enrich_one(self, job, state, rid, key, cached):
        resource = state["resources"][rid]
        page_cache_info = {"hit": False, "cached_at": None, "stale": False}
        if cached:
            enriched = cached["data"]
            resource["cache"] = page_cache_info = cached["cache"]
            job["progress"]["cache_hits"] += 1
            job["progress"]["details_cached"] += 1
            if page_cache_info["stale"]:
                self._warn(job, "部分页面元信息来自过期缓存，已标注缓存时间，当前页面状态尚未复核")
        else:
            async with state["network_slots"]:
                job["progress"]["details_attempted"] += 1
                self._save(job)
                async def reserve_catalog_page():
                    # This callback does not yield before reservation; all resource
                    # and follow-up pages consume the same per-job detail budget.
                    if state["reserved"] >= self.settings.max_detail_pages:
                        job["budget_limited"] = True
                        self._warn(job, "达到详情页预算，公开目录导航页未继续读取")
                        return False
                    state["reserved"] += 1
                    job["progress"]["catalog_pages_attempted"] += 1
                    self._save(job)
                    return True
                try:
                    if isinstance(self.fetcher, Fetcher):
                        enriched = await self.fetcher.enrich(state["candidates"][rid], catalog_budget_hook=reserve_catalog_page)
                    else:
                        enriched = await self.fetcher.enrich(state["candidates"][rid])
                except Exception:
                    enriched = {"fetch_status": "fetch_error"}
            enriched = self._page_metadata(enriched)
            ttl = self._page_cache_ttl(enriched)
            if ttl > 0:
                self.store.cache_set(key, "page", enriched, ttl)
        if enriched.get("catalog_fetch_status") not in {None, "fetched", "success"}:
            job["upstream_partial"] = True
            self._warn(job, "部分公开目录页未完成补全，已保存主页证据；目录状态与失败原因可在资源详情查看")
        # Read the current resource again: a later search can have supplied a type
        # while its metadata request was in flight. Never replace the saved URL.
        resource = state["resources"][rid]
        if cached:
            resource["cache"] = page_cache_info
        for field, value in enriched.items():
            if field not in {"resource_id", "url", "canonical_url", "evidence", "field_provenance", "discovered_at", "cache"}:
                if value is not None and not (field == "resource_type" and value == "unknown") and not (
                    field == "video_evidence_status" and value == "none" and resource.get(field) == "search_discovered"):
                    resource[field] = value
        new_ids = {}
        for original in enriched.get("evidence", []):
            old_id = original.get("evidence_id") or original.get("id")
            eid = "ev_" + str(uuid4())
            new_ids[old_id] = eid
            evidence = dict(original, evidence_id=eid, observed_at=original.get("observed_at", enriched.get("fetched_at")), cache=page_cache_info)
            self.store.add_evidence(job["job_id"], rid, None, evidence)
        for field, provenance in enriched.get("field_provenance", {}).items():
            if isinstance(provenance, dict):
                provenance = dict(provenance)
                if provenance.get("evidence_id") in new_ids:
                    provenance["evidence_id"] = new_ids[provenance["evidence_id"]]
                resource["field_provenance"][field] = provenance
        resource["chapters"] = [dict(chapter, evidence_id=new_ids.get(chapter.get("evidence_id"), chapter.get("evidence_id")))
                                if isinstance(chapter, dict) else chapter for chapter in resource.get("chapters", [])]
        resource = Resource.model_validate(resource).model_dump()
        resource["course_identity"] = derive_course_identity(resource, self.store.evidence(job["job_id"], rid))
        state["resources"][rid] = resource
        self.store.save_resource(job["job_id"], resource)
        for point in state["points"]:
            if rid in state["candidate_groups"][point["knowledge_point_id"]]:
                self._rank(job, point, resource, state["request"])
        if not cached:
            job["progress"]["details_completed"] += 1
            job["progress"]["catalog_pages_completed"] += enriched.get("catalog_pages_completed", 0)
        self._save(job)

    def _rank(self, job, point, resource, request):
        evidence = self.store.evidence(job["job_id"], resource["resource_id"], point["knowledge_point_id"])
        if self._sitemap_only(evidence):
            if not self._sitemap_page_covers(point, resource, evidence, request):
                self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])
                return
        # Sitemap URL words remain low-confidence recall even when another search
        # independently found the same URL; they never supplement teaching coverage.
        evidence = [row for row in evidence if not (row.get("kind") == "search" and row.get("source") == "official_sitemap")]
        match = rank_resource(point, resource, evidence, request,
            eligibility_evidence=self.store.evidence(job["job_id"], resource["resource_id"]))
        if match:
            self.store.save_match(job["job_id"], match)
        else:
            self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])

    async def _rerank(self, job, resources):
        matches = self.store.matches(job["job_id"])
        for point in job["knowledge_points"]:
            group = sorted((m for m in matches if m["knowledge_point_id"] == point["knowledge_point_id"]
                            and m.get("topic_evidence_status", "supported") == "supported"), key=lambda m: -m["ranking_score"])[:15]
            if not group:
                continue
            candidates = []
            for match in group:
                resource = resources[match["resource_id"]]
                searches = [entry for entry in self.store.evidence(job["job_id"], match["resource_id"], point["knowledge_point_id"])
                            if entry.get("kind") == "search" and entry.get("source") != "official_sitemap"]
                text_fields = {}
                for field, search_field in (("title", "title"), ("description", "snippet")):
                    basis = resource.get("field_provenance", {}).get(field, {})
                    if isinstance(basis, dict) and basis.get("source") == "search":
                        text_fields[field] = "\n".join(dict.fromkeys(entry[search_field] for entry in searches
                            if isinstance(entry.get(search_field), str)))[:1000]
                    else:
                        text_fields[field] = (resource.get(field) or "")[:1000]
                candidates.append({"candidate_id": match["resource_id"], **text_fields,
                    "evidence_ids": match["matched_evidence_ids"], "rule_score": match["ranking_score"]})
            try:
                rankings = await self.llm.rerank(point["text"], candidates)
                self.llm_status = "available"
                positions = {row["candidate_id"]: row["rank"] for row in rankings}
                # IDs/evidence are validated inside provider. A small bounded bonus preserves rule filtering.
                for match in group:
                    if match["resource_id"] in positions:
                        match["ranking_score"] = round(min(100, match["ranking_score"] + 2 / positions[match["resource_id"]]), 2)
                        self.store.save_match(job["job_id"], match)
            except Exception:
                self.llm_status = "fault"
                self._warn(job, "模型重排失败或输出未通过校验，保留规则排序结果")

    def results(self, job_id: str) -> dict | None:
        job = self.store.get_job(job_id)
        if not job:
            return None
        resources, matches = self.store.resources(job_id), self.store.matches(job_id)
        all_evidence = {rid: self.store.evidence(job_id, rid) for rid in resources}
        for rid, resource in resources.items():
            # Derive old persisted rows at read time without rewriting raw evidence.
            resource["course_identity"] = derive_course_identity(resource, all_evidence[rid])
        groups = []
        request = SearchRequest.model_validate(job["request"])
        for point in job["knowledge_points"]:
            # Re-evaluate stored candidates, including those previously rejected
            # as incomplete compounds. Reading never changes source evidence or DB.
            # A resource discovered for another point does not enter this pool.
            previous_ids = {m["resource_id"] for m in matches if m["knowledge_point_id"] == point["knowledge_point_id"]}
            assessed = []
            for rid, resource in resources.items():
                observed = self.store.evidence(job_id, rid, point["knowledge_point_id"])
                linked = any(row.get("kind") == "search" and row.get("knowledge_point_id") in {None, point["knowledge_point_id"]} for row in observed)
                if not linked and rid not in previous_ids:
                    continue
                if self._sitemap_only(observed) and not self._sitemap_page_covers(point, resource, observed, request):
                    continue
                observed = [row for row in observed if not (row.get("kind") == "search" and row.get("source") == "official_sitemap")]
                match = rank_resource(point, resource, observed, request, eligibility_evidence=all_evidence[rid])
                if match:
                    assessed.append(match)
            assessed.sort(key=lambda m: (-m["ranking_score"], m["resource_id"]))
            def render(matches):
                return diversify([{"resource": resources[m["resource_id"]], "match": m,
                    "evidence": all_evidence[m["resource_id"]]} for m in matches], self.settings.max_results_per_point)
            # Filter before truncating so a platform's best course remains reachable
            # even when it ranks below the all-platform display limit.
            sections = {status: [match for match in assessed if match["topic_evidence_status"] == status]
                        for status in ("supported", "partial", "needs_review")}
            platforms = sorted({resources[m["resource_id"]]["platform"] for m in assessed})
            def platform_section(rows):
                return {platform: render([match for match in rows if resources[match["resource_id"]]["platform"] == platform])
                        for platform in platforms if any(resources[match["resource_id"]]["platform"] == platform for match in rows)}
            items, partial_items, review_items = [render(sections[status]) for status in sections]
            platform_items, partial_platform_items, review_platform_items = [platform_section(sections[status]) for status in sections]
            groups.append(dict(point, total_matches=len(sections["supported"]), total_partial_matches=len(sections["partial"]),
                total_review_matches=len(sections["needs_review"]), section_limit=self.settings.max_results_per_point,
                items=items, platform_items=platform_items, partial_items=partial_items, partial_platform_items=partial_platform_items,
                review_items=review_items, review_platform_items=review_platform_items,
                collection_coverage=summarize_collection_coverage(point["text"], [*items, *partial_items]),
                platform_collection_coverage={platform: summarize_collection_coverage(point["text"], [*platform_items.get(platform, []),
                    *partial_platform_items.get(platform, [])]) for platform in platforms}))
        displayed = [item["resource"] for group in groups for item in [*group["items"],
            *group["partial_items"], *group["review_items"],
            *(item for key in ("platform_items", "partial_platform_items", "review_platform_items") for items in group[key].values() for item in items)]]
        return {"job_id": job_id, "status": job["status"], "groups": groups, "warnings": job["warnings"],
                "search_attempts": self.store.attempts(job_id), "identity_summary": summarize_course_identities(displayed)}

    def capabilities(self):
        config = {"searxng": bool(self.settings.searxng_url), "tavily": bool(self.settings.tavily_api_key),
            "official_sitemap": self.settings.fetch_enabled}
        providers = [{"name": name, "status": "configured" if configured else "unconfigured",
                      "message": "已配置，需实际查询确认可用性" if configured else "尚未配置"} for name, configured in config.items()]
        selected = next((p.copy() for p in providers if p["name"] == self.settings.search_provider), {"status": "unconfigured", "message": "不支持的搜索 Provider"})
        if config.get(self.settings.search_provider) and self.provider:
            selected["status"] = getattr(self.provider, "last_status", "configured")
            selected["message"] = {"configured": "已配置，尚未验证真实搜索", "available": "最近一次搜索请求成功", "fault": "最近搜索请求故障，请查看任务错误"}[selected["status"]]
            for p in providers:
                if p["name"] == self.settings.search_provider:
                    p.update(selected)
        if self.settings.search_provider == "official_sitemap":
            selected["message"] += "；仅 MIT 官方站点地图，其他平台不在此模式的发现范围"
        selected.update(selected_provider=self.settings.search_provider, providers=providers)
        platforms = []
        for key, name in (("bilibili", "B站"), ("icourse163", "中国大学 MOOC"), ("xuetangx", "学堂在线"), ("other", "其他公开网站")):
            policy = PLATFORM_POLICY_REVIEWS.get(key, {})
            status = policy.get("status", "per_site_check_required")
            metadata = "public_metadata_when_allowed"
            if status in {"explicit_permission_required", "explicit_scraping_prohibition"}:
                metadata = "site_policy_blocked"
            elif status == "public_course_metadata_only":
                metadata = "public_course_metadata_only"
            elif status == "unreviewed_permission_scope":
                metadata = "policy_unreviewed"
                domain = {"icourse163": "icourse163.org", "xuetangx": "xuetangx.com"}[key]
                if any(host == domain or host.endswith("." + domain) for host in self.settings.allowed_restricted_hosts):
                    metadata = "public_metadata_with_explicit_scope"
            if not self.settings.fetch_enabled:
                metadata = "disabled"
            elif key == "bilibili" and self.settings.bilibili_public_metadata:
                metadata = "public_video_metadata_only"
                policy = dict(policy, basis="本地自用模式已开启：读取匿名公开视频HTML中的元信息和分P目录，不因许可状态预先停止；实际登录、验证码、访问拒绝和robots规则仍独立检查。平台条款记录保留作来源说明。")
            platforms.append({"id": key, "name": name, "discovery": "out_of_scope" if self.settings.search_provider == "official_sitemap" and key != "other" else "search", "metadata": metadata,
                "playback": "unknown", "policy_status": status, "source_url": policy.get("source_url"),
                "reviewed_at": policy.get("reviewed_at"), "policy_basis": policy.get("basis"),
                "policy_section": policy.get("section"), "terms_date": policy.get("terms_date"),
                "effective_at": policy.get("effective_at"), "review_method": policy.get("review_method")})
        return {"mode": "live", "search": selected,
                "llm": {"status": self.llm_status, "message": {"configured": "模型已配置，尚未实际验证", "available": "最近一次模型调用及结构化校验成功", "fault": "最近模型调用或结构化校验失败，已使用规则回退", "unconfigured": "模型未启用或配置不完整，使用规则查询与排序"}[self.llm_status]},
                "fetch": {"status": "available" if self.settings.fetch_enabled else "disabled", "message": "公开元信息；独立站点策略与 robots 检查，受限时仅保留搜索证据", "browser_fallback": False,
                    "stopped_hosts": list(self.settings.denied_fetch_hosts), "transport": self._transport_profile()},
                "js_render": {**self._renderer_profile()["config"],
                    "status": "disabled" if not self.settings.js_render_enabled or not self.settings.fetch_enabled else
                        "configured" if isinstance(self.fetcher, Fetcher) and self.settings.js_render_allowed_hosts else "unconfigured",
                    "profile_version": self._renderer_profile()["version"],
                    "mode": "anonymous_offline_manifest_fulfill",
                    "message": "仅显式允许来源；资源经安全采集后离线执行，配置不证明真实动态字段已取得",
                    "policy_and_robots_required": True, "online_browser_fallback": False,
                    "process_network_egress": "unknown", "playback_verified": False},
                "official_discovery": {"selected": self.settings.search_provider == "official_sitemap",
                    "fallback_enabled": self.settings.official_sitemap_fallback,
                    "scope": "MIT official robots-declared sitemap links; page evidence required",
                    "children_per_query": self.settings.official_sitemap_children_per_query,
                    "cache_ttl_seconds": self.settings.official_sitemap_cache_ttl,
                    "dns_counter_scope": "discovery_dns_requests counts official discovery DoH HTTP only"},
                "platforms": platforms,
                "limits": {"max_knowledge_points": self.settings.max_knowledge_points, "max_results_per_point": self.settings.max_results_per_point,
                    "max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                    "global_concurrency": self.settings.global_concurrency, "per_host_concurrency": 1},
                "deployment": {"local_only": True, "authentication": False}}
