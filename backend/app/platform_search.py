"""Bounded, incremental platform discovery with fair supplementary rounds."""
from __future__ import annotations

import asyncio
import re
from contextlib import nullcontext
from copy import copy, deepcopy

from .models import Candidate, Query, now
from .providers import HTTPProvider, QueryBudgetReached, SearchBudgetReached, SearchError, SearXNGProvider
from .queries import PLATFORMS, gap_query_candidates, generate_queries
from .mooc_queries import mooc_query_label, mooc_query_site
from .ranking import candidate_topic_signal


def platform_budget(settings, count, platforms):
    selected = list(dict.fromkeys(platforms))
    if not settings.parallel_platform_search or not selected or settings.search_provider == "official_sitemap":
        return None
    initial = count * len(selected)
    rounds = {platform: {"bilibili": settings.bilibili_search_rounds,
                        "icourse163": settings.mooc_search_rounds}.get(platform, 2)
              for platform in selected}
    total = count * sum(rounds.values())
    if total > settings.max_search_requests:
        raise ValueError(f"本批需要 {total} 次搜索预算（首轮 {initial} 次及补搜 {total - initial} 次），当前上限为 {settings.max_search_requests} 次")
    return {"policy": "platform-rounds-v1" if all(value == 2 for value in rounds.values()) else "platform-rounds-v2",
            "platforms": selected, "platform_rounds": rounds,
            "initial_search_requests": initial, "followup_search_requests": total - initial,
            "max_search_requests": total,
            "platform_request_limits": {platform: rounds[platform] * count for platform in selected}}


def _supplementary_labels(point, platform, request):
    """Recall smaller explicit targets; never change the independent match target."""
    text = point["text"]
    parts = list(request.learning_targets.get(text, [])) or list(request.learning_skills.get(text, []))
    if not parts:
        # A whole name remains the first two queries. Later rounds may find a
        # broad course through one explicit component, with its owner retained.
        body = re.sub(r"^\s*[A-Za-z][A-Za-z0-9_+#.]*\s+", "", text)
        parts = re.split(r"[与和、]|\s+and\s+", body, flags=re.I)
        if len(parts) < 2:
            parts = []
    scoped_request = request.model_copy(update={"preferred_platforms": [platform]})
    labels = []
    for part in parts[:4]:
        queries = gap_query_candidates(point["knowledge_point_id"], text, scoped_request, [part])
        query = next((query for query in queries if query.domain_filters == [PLATFORMS[platform]]), None)
        if query:
            label = re.sub(r"\s*(?:视频教程|video tutorial)$", "", query.query.split(" ", 1)[-1], flags=re.I)
            if label and label.casefold() not in {row.casefold() for row in labels}:
                labels.append(label)
    return labels


def platform_query(point, platform, request, *, followup=False, round_index=None):
    index = int(followup) if round_index is None else round_index
    maximum = 10 if platform == "icourse163" else 6
    if not 0 <= index < maximum:
        raise ValueError(f"Platform search round must be between 0 and {maximum - 1}")
    if platform == "icourse163":
        label, suffix = mooc_query_label(point, request, index)
        return Query(knowledge_point_id=point["knowledge_point_id"],
                     query=f"site:{mooc_query_site(index)} {label} {suffix}".strip(), domain_filters=["icourse163.org"])
    followup = index > 0
    domain = PLATFORMS[platform]
    path = "/video" if platform == "bilibili" else "/course" if platform == "icourse163" else ""
    label = point["text"]
    if followup:
        alternatives = generate_queries(point["knowledge_point_id"], point["text"], request)
        selected = next((query for query in alternatives if query.domain_filters == [domain]), None)
        if selected:
            label = re.sub(r"\s*(?:视频教程|video tutorial|课程 教学|course lesson)$", "", selected.query.split(" ", 1)[-1], flags=re.I)
    suffix = ("video tutorial" if request.language == "en" else "视频教程") if platform == "bilibili" else (
        "course lessons" if request.language == "en" else "课程 教学")
    if followup:
        suffix = ("video tutorial examples" if request.language == "en" else "视频教程 示例") if platform == "bilibili" else (
            "course syllabus" if request.language == "en" else "课程 大纲")
    if index >= 2:
        labels = _supplementary_labels(point, platform, request)
        label = labels[(index - 2) % len(labels)] if labels and index < 5 else point["text"]
        if platform == "bilibili":
            suffixes = ("教学 实战", "教程 讲解", "实例 操作", "课程 完整") if request.language != "en" else (
                "practical tutorial", "lesson walkthrough", "worked examples", "complete course")
        else:
            suffixes = ("课程 章节", "课程 内容", "课程 知识点", "课程 学习目标") if request.language != "en" else (
                "course chapters", "course content", "course topics", "course learning objectives")
        suffix = suffixes[index - 2]
    version = f" {request.technical_version}" if request.technical_version and not followup else ""
    return Query(knowledge_point_id=point["knowledge_point_id"],
                 query=f"site:{domain}{path} {label}{version} {suffix}", domain_filters=[domain])


async def search_platform_rounds(service, job, state):
    plan = job["platform_search"]
    request = state["request"]
    points = state["points"]
    progress = job["progress"]
    progress.setdefault("platform_search_requests", {platform: 0 for platform in plan["platforms"]})
    progress.setdefault("initial_platform_pairs_completed", 0)
    progress.setdefault("followup_platform_pairs_completed", 0)
    gap_enabled = (getattr(service.settings, "mooc_gap_search_enabled", False)
                   and not service.settings.teaching_match_enabled
                   and "icourse163" in plan["platforms"])
    if gap_enabled:
        progress.setdefault("queries_skipped", 0)
        progress.setdefault("gap_queries_skipped", 0)
        gap = job.setdefault("gap_search", {})
        gap.update(enabled=True, policy="verified-outline-gap-v1",
                   target_courses_per_point=service.settings.mooc_target_courses_per_point)
        gap.setdefault("points", {})

    def gap_point(point):
        """Coverage is recomputed against this point, never inferred from hits."""
        accepted = service._mooc_coverage_count(job, point, state)
        target = service.settings.mooc_target_courses_per_point
        row = job["gap_search"]["points"].setdefault(point["knowledge_point_id"], {})
        row.update(accepted_count=accepted, target=target, remaining=max(0, target - accepted))
        row.setdefault("queries_skipped", 0)
        if accepted >= target:
            row["stopped_reason"] = "coverage_target_met"
        return row

    def skip_covered(point, query, phase, round_index, row):
        # A skipped slot completes the bounded plan, but is neither a provider
        # success nor an actual search request/credit. Keep a separate counter
        # and an explicit attempt so streamed progress remains auditable.
        attempt = {"knowledge_point_id": point["knowledge_point_id"], "platform": "icourse163",
            "query": query.query, "domain_filters": query.domain_filters,
            "provider": service.settings.search_provider_for("icourse163"),
            "search_phase": phase, "search_round": round_index + 1,
            "status": "skipped", "error_code": None, "skip_reason": "coverage_target_met",
            "executed_at": now(), "priority_request_limit": 1, "candidate_count": 0,
            "network_attempted": False, "provider_requests": [], "upstream_warnings": [],
            "cache_origin_warnings": [], "cache_hit": False, "cached_at": None, "stale": False}
        service.store.add_attempt(job["job_id"], attempt)
        progress["queries_completed"] += 1
        progress["queries_skipped"] += 1
        progress["gap_queries_skipped"] += 1
        progress[f"{phase}_platform_pairs_completed"] += 1
        row["queries_skipped"] += 1
        service._save(job)
        state["changed"].set()
        return attempt

    async def execute(point, platform, query, phase, round_index, *, refreshing=False):
        used = 0
        async def count_request():
            nonlocal used
            if progress["search_requests"] >= job["budgets"]["max_search_requests"]:
                raise SearchBudgetReached()
            if used >= 1 or progress["platform_search_requests"][platform] >= plan["platform_request_limits"][platform]:
                raise QueryBudgetReached()
            # No await between checking and reserving; platform lanes share one
            # application event loop and cannot overspend this reservation.
            used += 1
            progress["search_requests"] += 1
            progress["platform_search_requests"][platform] += 1
            service._save(job)

        provider_name, provider, provider_error = service._search_source(query)
        if provider is not None and not isinstance(provider, HTTPProvider):
            # Injected/offline providers get isolated trace attributes; their
            # shared transport/call collectors remain shared by a shallow copy.
            provider = copy(provider)
            provider.last_requests, provider.last_warnings = [], []
            if hasattr(provider, "request_hook"):
                provider.request_hook = count_request
        scope = provider.query_scope(count_request) if isinstance(provider, HTTPProvider) else nullcontext(provider)
        cache_key = service.store.cache_key("search", {"policy": plan["policy"],
            **service._search_identity(provider_name),
            "original_point": point["text"], "query": query.query, "domains": query.domain_filters,
            "language": request.language, "limit": service.settings.search_results_per_query})
        cached = None if refreshing else service.store.cache_get(cache_key)
        if (cached is None and not refreshing and platform == "icourse163"
                and provider_name in {"tavily", "serper"}):
            # The provider observation is unchanged when the exact query,
            # point, language, domain and limit still match an earlier plan.
            # Read its original expiry; do not relabel or renew it as a search.
            legacy_key = service.store.cache_key("search", {"policy": plan["policy"],
                **service._search_identity(provider_name), "mooc_query_policy": "course-discovery-phrases-v1",
                "original_point": point["text"], "query": query.query, "domains": query.domain_filters,
                "language": request.language, "limit": service.settings.search_results_per_query})
            cached = service.store.cache_get(legacy_key)
        cache_info = {"hit": False, "cached_at": None, "stale": False}
        attempt = {"knowledge_point_id": point["knowledge_point_id"], "platform": platform,
            "query": query.query, "domain_filters": query.domain_filters,
            "provider": provider_name, "search_phase": phase, "search_round": round_index + 1,
            "status": "completed", "error_code": None, "executed_at": now(),
            **({"refresh_probe": True} if refreshing else {}),
            "priority_request_limit": 1, "candidate_count": 0, "network_attempted": False}
        items, requests, warnings = [], [], []
        cancelled = False
        with scope:
            try:
                if cached:
                    items = [Candidate.model_validate(row) for row in cached["data"]["candidates"]]
                    cache_info = cached["cache"]
                    if cached["data"].get("partial_primary") is True:
                        attempt.update(status="partial", error_code="query_budget_exhausted")
                        if phase == "followup":
                            job["budget_limited"] = True
                else:
                    if provider_error:
                        raise provider_error
                    async with state["network_slots"]:
                        if not hasattr(provider, "request_hook"):
                            await count_request()
                        attempt["network_attempted"] = True
                        options = {"candidate_check": lambda candidate: candidate_topic_signal(candidate, point["text"], request)} if isinstance(provider, SearXNGProvider) else {}
                        items = await provider.search(query.query, request.language,
                            service.settings.search_results_per_query, query.domain_filters, **options)
                    items = [row if isinstance(row, Candidate) else Candidate.model_validate(row) for row in items]
                    service.store.cache_set(cache_key, "search", {"candidates": [row.model_dump() for row in items],
                        "upstream_warnings": deepcopy(getattr(provider, "last_warnings", []))}, service.settings.search_cache_ttl)
                progress["search_successes"] += 1
            except SearchBudgetReached as exc:
                items = [row if isinstance(row, Candidate) else Candidate.model_validate(row) for row in exc.partial_candidates]
                observed = getattr(provider, "last_requests", [])
                # HTTP 200 confirms the gateway response, not the upstream
                # engine. A blocked optional fallback must not conceal an
                # explicitly failed primary with no retained candidates.
                engine_failed = any(row.get("code") == "upstream_engine_failed"
                                    for row in getattr(provider, "last_warnings", []))
                succeeded = items or (not engine_failed and any(
                    row.get("status") == "completed" and row.get("http_status") == 200 for row in observed))
                source_error = next((row.get("error_code") for row in reversed(observed) if row.get("error_code")), None)
                attempt.update(status="partial" if succeeded else "failed",
                               error_code="query_budget_exhausted" if succeeded else (
                                   "upstream_engine_failed" if engine_failed else source_error or "query_budget_exhausted"))
                progress["search_successes" if succeeded else "search_failures"] += 1
                # A broad MOOC query can return useful course observations but
                # miss the finer original topic, prompting an optional fallback
                # beyond this slot's one-request allowance. Reuse the completed
                # primary observation without pretending the fallback ran. Do
                # not cache source faults or a stop before the primary finished.
                source_warnings = getattr(provider, "last_warnings", [])
                clean_primary = (platform == "icourse163" and isinstance(provider, SearXNGProvider)
                    and used == 1 and succeeded and observed
                    and all(row.get("status") == "completed" and row.get("http_status") == 200
                            and not row.get("error_code") for row in observed)
                    and all(row.get("code") == "no_topic_signal" for row in source_warnings))
                if clean_primary:
                    service.store.cache_set(cache_key, "search", {
                        "candidates": [row.model_dump() for row in items],
                        "upstream_warnings": deepcopy(source_warnings), "partial_primary": True,
                    }, service.settings.search_cache_ttl)
                if phase == "followup":
                    job["budget_limited"] = True
            except SearchError as exc:
                attempt.update(status="failed", error_code=exc.code)
                progress["search_failures"] += 1
                error = {"code": exc.code, "message": exc.message}
                if error not in job["errors"]:
                    job["errors"].append(error)
            except asyncio.CancelledError:
                attempt.update(status="cancelled", error_code="task_cancelled")
                cancelled = True
            except Exception:
                attempt.update(status="failed", error_code="search_unavailable")
                progress["search_failures"] += 1
                error = {"code": "search_unavailable", "message": "搜索来源处理失败，已保留其他来源结果"}
                if error not in job["errors"]:
                    job["errors"].append(error)
            finally:
                requests = deepcopy(getattr(provider, "last_requests", [])) if not cached else []
                warnings = deepcopy(getattr(provider, "last_warnings", [])) if not cached else []
        if isinstance(provider, HTTPProvider):
            attempt["network_attempted"] = bool(requests)
        origin_warnings = cached["data"].get("upstream_warnings", []) if cached else []
        if warnings or origin_warnings:
            job["upstream_partial"] = True
            service._warn(job, "部分平台搜索未完成，已保留其他平台返回的课程与视频")
        attempt.update(provider_requests=requests, upstream_warnings=warnings,
            cache_origin_warnings=origin_warnings, cache_hit=cache_info["hit"],
            cached_at=cache_info["cached_at"], stale=cache_info["stale"], candidate_count=len(items))
        service.store.add_attempt(job["job_id"], attempt)
        if cancelled:
            raise asyncio.CancelledError
        progress["queries_completed"] += 1
        progress["cache_hits"] += int(cache_info["hit"])
        progress["candidates_discovered"] += len(items)
        progress[f"{phase}_platform_pairs_completed"] += 1
        service._record_search_candidates(job, state, query, items, cache_info)
        progress["resources_discovered"] = len(state["resources"])
        # Start page/outline verification as soon as the first search result is
        # stored. The fair search barrier only orders searches, never details.
        if items:
            state["ready"] = True
        service._save(job)
        state["changed"].set()
        return attempt

    async def round_for_platform(platform, phase, round_index):
        for point in points:
            pid = point["knowledge_point_id"]
            if phase == "initial":
                query = platform_query(point, platform, request)
            elif round_index == 1:
                query = Query.model_validate(plan["followups"][platform][pid])
            else:
                query = platform_query(point, platform, request, round_index=round_index)
            coverage = gap_point(point) if gap_enabled and platform == "icourse163" else None
            refresh = getattr(service, "mooc_refresh", None) if service.settings.mooc_refresh_enabled else None
            refresh_key, refresh_claim = None, None
            if coverage is not None and refresh is not None:
                refresh_key = refresh.topic_key(point, request, {"library": service._course_library_profile(),
                    "search": service._search_identity(service.settings.search_provider_for("icourse163"))})
                if phase == "initial" and not coverage["remaining"]:
                    refresh_claim = refresh.claim(refresh_key)
                    if refresh_claim is not None:
                        query = platform_query(point, platform, request, round_index=refresh_claim["query_index"])
            if coverage is not None and coverage["remaining"] and round_index > 0:
                # Only supplementary searches wait. Every point/platform still
                # gets its fair first-pass decision before any second query.
                # The service wait is bounded, cancellable and holds no network
                # slot; completed outline checks can satisfy the target first.
                await service._wait_mooc_checks(job, point, state)
                coverage = gap_point(point)
            if coverage is not None and not coverage["remaining"] and refresh_claim is None:
                attempt = skip_covered(point, query, phase, round_index, coverage)
            else:
                attempt = await execute(point, platform, query, phase, round_index, refreshing=refresh_claim is not None)
                if refresh_key is not None:
                    refresh.observed(refresh_key, attempt)
                if refresh_claim is not None:
                    progress["mooc_refresh_probes"] = progress.get("mooc_refresh_probes", 0) + 1
                if coverage is not None:
                    coverage = gap_point(point)
                    if coverage["remaining"]:
                        coverage["stopped_reason"] = attempt.get("error_code") or None
                    service._save(job)
            if phase == "initial":
                retry = attempt["status"] == "failed"
                # Failed initial queries get one retry only after the barrier;
                # successful queries use a supplementary phrase in that slot.
                plan["followups"][platform][pid] = (query if retry else platform_query(
                    point, platform, request, followup=True)).model_dump()
                service._save(job)

    # Old persisted v1 plans intentionally retain two rounds even if current
    # environment configuration has since been expanded.
    rounds = plan.get("platform_rounds") or {platform: 2 for platform in plan["platforms"]}

    async def run_round(phase, round_index):
        async with asyncio.TaskGroup() as tasks:
            for platform in plan["platforms"]:
                if round_index < rounds[platform]:
                    tasks.create_task(round_for_platform(platform, phase, round_index))

    if not plan.get("initial_done"):
        plan["followups"] = {platform: {} for platform in plan["platforms"]}
        await run_round("initial", 0)
        plan.update(initial_done=True, followup_pending=max(rounds.values()) > 1, completed_rounds=1)
        state["ready"] = True
        state["changed"].set()
        service._save(job)
        if plan.get("defer_followups") and plan["followup_pending"]:
            return
    for round_index in range(max(1, plan.get("completed_rounds", 1)), max(rounds.values())):
        await run_round("followup", round_index)
        plan["completed_rounds"] = round_index + 1
        service._save(job)
    plan.update(followup_pending=False, finished=True)
    if gap_enabled:
        for point in points:
            coverage = gap_point(point)
            if coverage["remaining"] and not coverage.get("stopped_reason"):
                coverage["stopped_reason"] = "max_rounds_reached"
    service._save(job)
