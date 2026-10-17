from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from uuid import uuid4
from urllib.parse import urlsplit
from .config import Settings
from .db import Store
from .fetcher import Fetcher, FetcherConfig, PLATFORM_POLICY_REVIEWS, normalize_url, platform_for_url
from .llm import build_llm
from .models import Candidate, Resource, SearchRequest, now
from .providers import SearchError, build_provider
from .queries import generate_queries, fair_queries
from .ranking import has_course_discovery, has_learning_evidence, has_type_evidence, has_video_evidence, rank_resource, type_from_discovered_url
from .url_utils import UnsafeURL


class BudgetReached(Exception):
    pass


class JobService:
    """A persistent, single-process queue. Jobs are serialized; page requests are bounded."""
    def __init__(self, settings: Settings, store: Store, provider=None, fetcher=None, llm=None):
        self.settings, self.store = settings, store
        self.provider_error = None
        try:
            self.provider = provider or build_provider(settings)
        except SearchError as exc:
            self.provider, self.provider_error = None, exc
        self.fetcher = fetcher or Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
            timeout_seconds=settings.fetch_timeout_seconds, global_concurrency=settings.global_concurrency,
            allowed_restricted_hosts=settings.allowed_restricted_hosts, dns_resolver=settings.dns_resolver))
        self.llm = llm or build_llm(settings)
        self.llm_status = "configured" if self.llm else "unconfigured"
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def start(self):
        self.store.recover()
        self.worker = asyncio.create_task(self._worker())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        self.store.recover()

    def create(self, request: SearchRequest) -> dict:
        if len(request.knowledge_points) > self.settings.max_knowledge_points:
            raise ValueError("知识点数量超过当前服务预算")
        job_id = str(uuid4())
        stamp = now()
        job = {"job_id": job_id, "status": "queued", "phase": "queued", "created_at": stamp, "updated_at": stamp,
               "request": request.model_dump(), "knowledge_points": [{"knowledge_point_id": str(uuid4()), "text": text} for text in request.knowledge_points],
               "progress": {"queries_planned": 0, "queries_completed": 0, "search_requests": 0, "search_successes": 0,
                            "search_failures": 0, "candidates_discovered": 0, "resources_discovered": 0,
                            "details_attempted": 0, "details_completed": 0, "details_cached": 0, "cache_hits": 0,
                            "catalog_pages_attempted": 0, "catalog_pages_completed": 0},
               "budgets": {"max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                           "deadline_seconds": self.settings.deadline_seconds}, "warnings": [], "errors": []}
        self.store.save_job(job)
        for point in job["knowledge_points"]:
            self.store.add_point(job_id, point)
        self.queue.put_nowait(job_id)
        return {"job_id": job_id, "status": "queued"}

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
                await self.run(job_id)
            finally:
                self.queue.task_done()

    async def run(self, job_id: str):
        job = self.store.get_job(job_id)
        if not job:
            return
        job.update(status="running", phase="expanding")
        self._save(job)
        try:
            async with asyncio.timeout(self.settings.deadline_seconds):
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
            job["status"] = "interrupted"
            self._warn(job, "服务停止，任务被中断；可重新提交")
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
        points = job["knowledge_points"]
        queries = []
        for point in points:
            expansions = []
            if self.llm:
                try:
                    expansions = await self.llm.expand(point["text"], request.project_context)
                    self.llm_status = "available"
                except Exception:
                    self.llm_status = "fault"
                    self._warn(job, "模型查询扩展失败，已回退到原始知识点和规则模板")
            queries.append(generate_queries(point["knowledge_point_id"], point["text"], request, expansions))
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
        if self.provider and hasattr(self.provider, "request_hook"):
            self.provider.request_hook = count_request

        for query_index, query in enumerate(schedule):
            cache_key = self.store.cache_key("search", {"provider": self.settings.search_provider,
                "provider_version": 4, "engines": getattr(self.settings, "searxng_engines", ()),
                "fallback_engines": getattr(self.settings, "searxng_fallback_engines", ()),
                "video_engines": getattr(self.settings, "searxng_video_engines", ()),
                "service_identity": hashlib.sha256(self.settings.searxng_url.encode()).hexdigest() if self.settings.search_provider == "searxng" else "tavily",
                "query": query.query, "language": request.language, "version": request.technical_version,
                "domains": query.domain_filters, "limit": self.settings.search_results_per_query})
            cached = self.store.cache_get(cache_key)
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
                    network_attempted = True
                    async with state["network_slots"]:
                        items = await self.provider.search(query.query, request.language, self.settings.search_results_per_query, query.domain_filters)
                    items = [c if isinstance(c, Candidate) else Candidate.model_validate(c) for c in items]
                    # Preserve upstream failures alongside results in the cache and execution record.
                    self.store.cache_set(cache_key, "search", {"candidates": [c.model_dump() for c in items],
                        "upstream_warnings": getattr(self.provider, "last_warnings", []),
                        "provider_requests": getattr(self.provider, "last_requests", [])}, self.settings.search_cache_ttl)
                job["progress"]["search_successes"] += 1
            except BudgetReached:
                job["budget_limited"] = True
                self._warn(job, "达到搜索请求预算；按知识点轮转执行，剩余查询未执行")
                requests = getattr(self.provider, "last_requests", [])
                if requests:
                    attempt.update(status="budget_exhausted", error_code="budget_exhausted", provider_requests=requests)
                    self.store.add_attempt(job["job_id"], attempt)
                    job["progress"]["queries_completed"] += 1
                break
            except SearchError as exc:
                attempt.update(status="failed", error_code=exc.code)
                job["progress"]["search_failures"] += 1
                error = {"code": exc.code, "message": exc.message}
                if error not in job["errors"]:
                    job["errors"].append(error)
                cached = self.store.cache_get(cache_key, allow_stale=self.settings.allow_stale_cache)
                if cached:
                    cached_candidates = cached["data"].get("candidates", []) if isinstance(cached["data"], dict) else cached["data"]
                    items = [Candidate.model_validate(c) for c in cached_candidates]
                    cache_info = cached["cache"]
                    attempt["status"] = "stale_cache"
                    job["progress"]["search_successes"] += 1
                    self._warn(job, "搜索服务失败，部分结果来自明确标注时间的过期缓存")
                else:
                    items = []
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
            origin = cached["data"] if cached and isinstance(cached["data"], dict) else {}
            attempt["cache_origin_requests"] = origin.get("provider_requests", [])
            attempt["cache_origin_warnings"] = origin.get("upstream_warnings", [])
            if attempt["upstream_warnings"] or attempt["cache_origin_warnings"]:
                job["upstream_partial"] = True
                self._warn(job, "SearXNG 部分上游引擎未完成查询；已保留成功来源的结果，搜索范围受限")
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
                self.store.add_evidence(job["job_id"], rid, query.knowledge_point_id, evidence)
                inferred_type = type_from_discovered_url(canonical)
                video_status = "search_discovered" if inferred_type == "video" or (
                    candidate.type_source == "search_template" and candidate.resource_type_hint in {"video", "playlist"}) else "none"
                type_provenance = {"evidence_id": eid, "source": "url_pattern", "url": candidate.url,
                    "note": "公开平台课程或视频入口格式推断；页面详情与可播放性尚未核验"}
                if inferred_type == "unknown" and candidate.type_source == "search_template" and candidate.resource_type_hint in {"video", "course", "playlist"}:
                    inferred_type = candidate.resource_type_hint
                    type_provenance.update(source="search_template", note="搜索来源按媒体模板分类；页面详情与可播放性尚未核验")
                video_provenance = {"evidence_id": eid, "source": "url_pattern" if type_from_discovered_url(canonical) == "video" else "search_template",
                    "url": candidate.url, "note": "仅搜索发现视频入口或视频类结果；页面视频内容及可播放性尚未核验"}
                if rid not in resources:
                    provenance = {k: {"evidence_id": eid, "source": "search", "url": candidate.url} for k in ("title", "url", "description")}
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
                if resources[rid]["video_evidence_status"] == "none" and video_status == "search_discovered":
                    resources[rid]["video_evidence_status"] = video_status
                    resources[rid]["field_provenance"]["video_evidence_status"] = video_provenance
                    self.store.save_resource(job["job_id"], resources[rid])
                if rid not in candidate_groups[query.knowledge_point_id]:
                    candidate_groups[query.knowledge_point_id].append(rid)
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

    def _page_cache(self, resource):
        key = self.store.cache_key("page", {"url": resource["canonical_url"], "extractor_version": 5,
            "enabled": self.settings.fetch_enabled, "allowed_restricted_hosts": self.settings.allowed_restricted_hosts,
            "dns_resolver": self.settings.dns_resolver})
        return key, self.store.cache_get(key, allow_stale=self.settings.allow_stale_cache)

    def _detail_queues(self, job, state):
        queues = {}
        for point in state["points"]:
            entries = []
            for rid in state["candidate_groups"][point["knowledge_point_id"]]:
                if rid in state["started"]:
                    continue
                resource = state["resources"][rid]
                evidence = self.store.evidence(job["job_id"], rid)
                provisional = rank_resource(point, resource, evidence, state["request"], require_type=False)
                if provisional:
                    entries.append((has_learning_evidence(resource, evidence), provisional["ranking_score"], rid))
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
            ttl = self.settings.page_cache_ttl if enriched.get("fetch_status") in {"fetched", "success", "search_only_policy", "site_policy_blocked", "policy_unreviewed"} else min(self.settings.page_cache_ttl, 300)
            self.store.cache_set(key, "page", enriched, ttl)
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
        evidence = self.store.evidence(job["job_id"], resource["resource_id"])
        match = rank_resource(point, resource, evidence, request)
        if match:
            self.store.save_match(job["job_id"], match)
        else:
            self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])

    async def _rerank(self, job, resources):
        matches = self.store.matches(job["job_id"])
        for point in job["knowledge_points"]:
            group = sorted((m for m in matches if m["knowledge_point_id"] == point["knowledge_point_id"]), key=lambda m: -m["ranking_score"])[:15]
            if not group:
                continue
            candidates = [{"candidate_id": m["resource_id"], "title": resources[m["resource_id"]]["title"],
                           "description": (resources[m["resource_id"]].get("description") or "")[:1000],
                           "evidence_ids": m["matched_evidence_ids"], "rule_score": m["ranking_score"]} for m in group]
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
        groups = []
        for point in job["knowledge_points"]:
            group = sorted((m for m in matches if m["knowledge_point_id"] == point["knowledge_point_id"]
                and has_learning_evidence(resources[m["resource_id"]], self.store.evidence(job_id, m["resource_id"]))), key=lambda m: (-m["ranking_score"], m["resource_id"]))
            def render(matches):
                return [{"resource": resources[m["resource_id"]], "match": m,
                    "evidence": self.store.evidence(job_id, m["resource_id"])} for m in matches[:self.settings.max_results_per_point]]
            # Filter before truncating so a platform's best course remains reachable
            # even when it ranks below the all-platform display limit.
            platforms = sorted({resources[m["resource_id"]]["platform"] for m in group})
            platform_items = {platform: render([m for m in group if resources[m["resource_id"]]["platform"] == platform])
                              for platform in platforms}
            groups.append(dict(point, total_matches=len(group), items=render(group), platform_items=platform_items))
        return {"job_id": job_id, "status": job["status"], "groups": groups, "warnings": job["warnings"], "search_attempts": self.store.attempts(job_id)}

    def capabilities(self):
        config = {"searxng": bool(self.settings.searxng_url), "tavily": bool(self.settings.tavily_api_key)}
        providers = [{"name": name, "status": "configured" if configured else "unconfigured",
                      "message": "已配置，需实际查询确认可用性" if configured else "尚未配置"} for name, configured in config.items()]
        selected = next((p.copy() for p in providers if p["name"] == self.settings.search_provider), {"status": "unconfigured", "message": "不支持的搜索 Provider"})
        if config.get(self.settings.search_provider) and self.provider:
            selected["status"] = getattr(self.provider, "last_status", "configured")
            selected["message"] = {"configured": "已配置，尚未验证真实搜索", "available": "最近一次搜索请求成功", "fault": "最近搜索请求故障，请查看任务错误"}[selected["status"]]
            for p in providers:
                if p["name"] == self.settings.search_provider:
                    p.update(selected)
        selected.update(selected_provider=self.settings.search_provider, providers=providers)
        platforms = []
        for key, name in (("bilibili", "B站"), ("icourse163", "中国大学 MOOC"), ("xuetangx", "学堂在线"), ("other", "其他公开网站")):
            policy = PLATFORM_POLICY_REVIEWS.get(key, {})
            status = policy.get("status", "per_site_check_required")
            metadata = "public_metadata_when_allowed"
            if status in {"explicit_permission_required", "explicit_scraping_prohibition"}:
                metadata = "site_policy_blocked"
            elif status == "unreviewed_permission_scope":
                metadata = "policy_unreviewed"
                domain = {"icourse163": "icourse163.org", "xuetangx": "xuetangx.com"}[key]
                if any(host == domain or host.endswith("." + domain) for host in self.settings.allowed_restricted_hosts):
                    metadata = "public_metadata_with_explicit_scope"
            if not self.settings.fetch_enabled:
                metadata = "disabled"
            platforms.append({"id": key, "name": name, "discovery": "search", "metadata": metadata,
                "playback": "unknown", "policy_status": status, "source_url": policy.get("source_url"),
                "reviewed_at": policy.get("reviewed_at")})
        return {"mode": "live", "search": selected,
                "llm": {"status": self.llm_status, "message": {"configured": "模型已配置，尚未实际验证", "available": "最近一次模型调用及结构化校验成功", "fault": "最近模型调用或结构化校验失败，已使用规则回退", "unconfigured": "模型未启用或配置不完整，使用规则查询与排序"}[self.llm_status]},
                "fetch": {"status": "available" if self.settings.fetch_enabled else "disabled", "message": "公开元信息；独立站点策略与 robots 检查，受限时仅保留搜索证据", "browser_fallback": False},
                "platforms": platforms,
                "limits": {"max_knowledge_points": self.settings.max_knowledge_points, "max_results_per_point": self.settings.max_results_per_point,
                    "max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                    "global_concurrency": self.settings.global_concurrency, "per_host_concurrency": 1},
                "deployment": {"local_only": True, "authentication": False}}
