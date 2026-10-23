"""Bounded gap completion. Generated URLs are leads, never source evidence."""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext
from copy import copy, deepcopy
from uuid import uuid4

from .fetcher import FETCH_DEADLINE_AT, platform_for_url
from .models import Candidate, Query, Resource, now
from .ranking import has_type_evidence, has_video_evidence
from .providers import HTTPProvider, QueryBudgetReached, SearchBudgetReached, SearchError
from .queries import PLATFORMS, video_recovery_search_phrases_with_diagnostics
from .technical_prefix import leading_technical_owner
from .url_utils import normalize_url


def fallback_available(service, request) -> bool:
    return bool(service.settings.ai_video_fallback_enabled
                and service.settings.fetch_enabled and service.settings.max_detail_pages > 0
                and service.settings.search_provider != "official_sitemap"
                and request.preferred_platforms
                and (callable(getattr(service.llm, "suggest_video_discovery", None))
                     or callable(getattr(service.llm, "suggest_video_urls", None))))


def visible_point_ids(service, job) -> set[str]:
    """Use the actual result projection, including qualified related references."""
    result = service.results(job["job_id"]) or {}
    resources = service.store.resources(job["job_id"])
    covered = set()
    for group in result.get("groups", []):
        if group.get("scope_mismatch"):
            continue
        technology = (group.get("technology")
                      or job.get("request", {}).get("topic_technologies", {}).get(group.get("text"))
                      or leading_technical_owner(group.get("text", "")))
        rows = [*group.get("items", []), *group.get("partial_items", []),
                *group.get("related_recommendations", [])]
        if group.get("recommendation_policy") != "related-reference-v1":
            rows += group.get("discovery_items", [])
        def usable(row):
            resource = resources.get(row.get("resource", {}).get("resource_id"), row.get("resource", {}))
            reference = row.get("reference") or {}
            if "link_eligible" in reference:
                if job.get("status") in {"queued", "running"} and resource.get("fetch_status") == "not_fetched":
                    return False  # Let the already-budgeted detail attempt inspect this lead.
                # New projections certify a current relevant link, not playback.
                # Rebind its retained evidence; old records keep the strict gate.
                if reference["link_eligible"] is not True or (technology and
                        reference.get("technical_context") not in {"observed", "parent_course"}):
                    return False
                from .related_recommendations import reference_link_eligible
                evidence = service.store.evidence(job["job_id"], resource["resource_id"])
                identifiers = set(reference.get("evidence_ids", []))
                retained = [e for e in evidence if e.get("evidence_id") in identifiers]
                return (bool(identifiers) and identifiers == {e.get("evidence_id") for e in retained}
                    and reference_link_eligible(resource, evidence, retained,
                        target=row.get("resource", {}).get("canonical_url") or row.get("resource", {}).get("url")))
            if (resource.get("fetch_status") not in {"fetched", "success"}
                    or resource.get("requires_payment") is True
                    or resource.get("cache", {}).get("stale")):
                return False
            evidence = service.store.evidence(job["job_id"], resource["resource_id"])
            if not has_video_evidence(resource, evidence):
                return False
            if row.get("reference"):
                # A topical reference with an unknown implementation context
                # must not close a gap for an explicitly selected technology.
                # Page/catalog relevance is still sufficient; this does not
                # require exact teaching or complete coverage of the concept.
                if technology and row["reference"].get("technical_context") not in {"observed", "parent_course"}:
                    return False
                ids = set(row["reference"].get("evidence_ids", []))
                return bool(set(row["reference"].get("basis", [])) & {"page", "catalog"}) and any(
                    e.get("evidence_id") in ids and e.get("kind") in {"page", "catalog"}
                    and not e.get("cache", {}).get("stale") for e in evidence)
            ids = set(row.get("match", {}).get("supporting_evidence_ids", []))
            return any(e.get("evidence_id") in ids and e.get("kind") in {"page", "catalog"} for e in evidence)
        if any(usable(row) for row in rows):
            covered.add(group["knowledge_point_id"])
    return covered


def verified_ai_resource(resource, evidence) -> bool:
    """Old independently discovered resources retain their existing policy."""
    if (not any(row.get("kind") in {"ai_suggestion", "page_link"} for row in evidence)
            or any(row.get("kind") in {"search", "course_library"} for row in evidence)):
        return True
    return (resource.get("fetch_status") in {"fetched", "success"}
            and resource.get("metadata_evidence_level") in {"page", "catalog"}
            and has_type_evidence(resource, evidence))


def reserve_fallback(service, job, state) -> float:
    """Carve capacity out of existing job caps; never enlarge them."""
    if not fallback_available(service, state["request"]) or job.get("ai_video_fallback", {}).get("model_calls"):
        return 0
    missing = len(state["points"]) - len(visible_point_ids(service, job))
    if not missing:
        return 0
    remaining = max(0, service.settings.max_detail_pages - state["reserved"])
    pages = min(3 * missing, max(missing, remaining // 3), remaining)
    state["detail_limit"] = service.settings.max_detail_pages - pages
    if callable(getattr(service.llm, "suggest_video_discovery", None)):
        cap = job["budgets"]["max_search_requests"]
        initial = job.get("platform_search", {}).get("initial_search_requests", len(state["points"]))
        # Three complementary phrases, each with at most one transport retry.
        held = min(6 * missing, max(0, cap - max(initial, job["progress"]["search_requests"])))
        state["search_limit"] = cap - held
    deadline = FETCH_DEADLINE_AT.get()
    seconds = max(0, deadline - asyncio.get_running_loop().time()) if deadline else service.settings.deadline_seconds
    return min(180, seconds / 2) if pages else 0


def _fallback_deadline(service, state):
    deadline = FETCH_DEADLINE_AT.get()
    default = asyncio.get_running_loop().time() + service.settings.deadline_seconds
    return min(deadline or default, state.get("fallback_effective_deadline", deadline or default))


def _grounded_final_reserve(service, job, state):
    from . import grounded_related
    settings = service.settings
    if not (settings.llm_provider == "openai_compatible" and settings.llm_api_key.strip()
            and settings.llm_model.strip() and settings.llm_base_url.strip()):
        return 0
    stats = job.get("grounded_related", {})
    calls = max(0, grounded_related.MAX_MODEL_CALLS - stats.get("judgment_calls", 0) - stats.get("review_calls", 0))
    remaining = _fallback_deadline(service, state) - asyncio.get_running_loop().time()
    return min(calls * grounded_related.CALL_SECONDS, remaining) if calls >= 2 and remaining >= 40 else 0


async def _finish_grounded_recovery(service, job, state, points, query_hints=None):
    """Finish against the current complete own pool, even without new IO capacity."""
    from . import grounded_related
    for _ in range(grounded_related.MAX_BATCHES):
        before = sum(job.get("grounded_related", {}).get(k, 0) for k in ("judgment_calls", "review_calls"))
        await _recover_from_own_metadata(service, job, state, points, query_hints, final=True)
        after = sum(job.get("grounded_related", {}).get(k, 0) for k in ("judgment_calls", "review_calls"))
        if after == before or after > grounded_related.MAX_MODEL_CALLS - 2:
            break


async def run_ai_video_fallback(service, job, state, *, effective_deadline=None):
    from .ai_video_fallback import direct_video_url, video_search_phrase

    if effective_deadline is not None:
        state["fallback_effective_deadline"] = effective_deadline
    request = state["request"]
    if not fallback_available(service, request) or job.get("platform_search", {}).get("followup_pending"):
        return
    if job.get("ai_video_fallback", {}).get("model_calls"):
        return
    # Do not spend a short remaining source window on an early audit.
    # A complete final audit still gets its own reserved stage.
    if _fallback_deadline(service, state) - asyncio.get_running_loop().time() >= 180:
        await _recover_from_own_metadata(service, job, state, state["points"])
    state["grounded_initial_phase_done"] = True
    covered = visible_point_ids(service, job)
    points = [point for point in state["points"] if point["knowledge_point_id"] not in covered]
    if not points:
        return
    diagnostic = job["ai_video_fallback"] = {"status": "checking", "model_calls": 0,
        "requested_point_ids": [point["knowledge_point_id"] for point in points],
        "candidate_count": 0, "covered_points": 0, "remaining_points": len(points)}
    if state["reserved"] >= service.settings.max_detail_pages:
        diagnostic["status"] = "detail_budget_exhausted"
        job["budget_limited"] = True
        await _finish_grounded_recovery(service, job, state, points)
        covered = visible_point_ids(service, job)
        count = sum(point["knowledge_point_id"] in covered for point in points)
        diagnostic.update(covered_points=count, remaining_points=len(points) - count)
        if count == len(points):
            diagnostic["status"] = "completed"
        service._save(job)
        return
    job["phase"] = "fetching"
    diagnostic.update(status="suggesting", model_calls=1)
    service._save(job)
    excluded = list(state["resources"][rid]["canonical_url"] for rid in state["resources"])
    combined = callable(getattr(service.llm, "suggest_video_discovery", None))
    plans = {}
    try:
        async with asyncio.timeout(20):
            if combined:
                audited_discovery = getattr(service.llm, "suggest_video_discovery_with_diagnostics", None)
                if callable(audited_discovery):
                    plans, model_output = await audited_discovery(
                        [point["text"] for point in points], request, excluded_urls=excluded)
                    # The adapter supplies bounded counters/enums, never raw model
                    # text or rejected URLs. Empty output and filtering differ.
                    diagnostic["model_output"] = model_output
                else:
                    plans = await service.llm.suggest_video_discovery(
                        [point["text"] for point in points], request, excluded_urls=excluded)
                if not isinstance(plans, dict):
                    raise ValueError("Invalid discovery plan")
                suggestions = {point["text"]: plans.get(point["text"], {}).get("urls", [])
                               for point in points if isinstance(plans.get(point["text"], {}), dict)}
            else:
                suggestions = await service.llm.suggest_video_urls(
                    [point["text"] for point in points], request, excluded_urls=excluded)
        if not isinstance(suggestions, dict):
            raise ValueError("Invalid URL suggestions")
        service.llm_status = "available"
    except asyncio.CancelledError:
        diagnostic["status"] = "interrupted"
        service._save(job)
        raise
    except Exception as exc:
        service.llm_status = "fault"
        diagnostic.update(status="unavailable", error_type=type(exc).__name__)
        response = getattr(exc, "response", None)
        if response is not None and isinstance(getattr(response, "status_code", None), int):
            diagnostic["http_status"] = response.status_code
        job["upstream_partial"] = True
        service._save(job)
        if not combined:
            return
        suggestions = {}

    urls = {}
    for point in points:
        values = suggestions.get(point["text"], [])
        accepted = []
        for value in values[:3] if isinstance(values, list) else []:
            url = direct_video_url(value, request.preferred_platforms)
            if url and url not in excluded and url not in accepted:
                accepted.append(url)
        urls[point["knowledge_point_id"]] = accepted
    diagnostic.update(status="fetching", candidate_count=sum(map(len, urls.values())))
    # Keep one actual source-page slot per gap even if remembered URLs all fail.
    direct_limit = service.settings.max_detail_pages
    search_remaining = max(0, job["budgets"]["max_search_requests"] - job["progress"]["search_requests"])
    if combined:
        direct_limit -= min(len(points), search_remaining, max(0, direct_limit - state["reserved"]))
    state["detail_limit"] = direct_limit
    service._save(job)
    legacy_seconds = max(0, _fallback_deadline(service, state) - asyncio.get_running_loop().time())
    legacy_deadline = asyncio.get_running_loop().time() + min(15, legacy_seconds / 3)
    state["legacy_recovery_deadline"] = legacy_deadline
    try:
        async def fetch_direct():
            # Reserve each first-choice page before allowing any catalog followup;
            # one point cannot consume the other points' first inspection slots.
            for index in range(3):
                covered = visible_point_ids(service, job)
                scheduled = []
                for point in points:
                    pid = point["knowledge_point_id"]
                    if pid in covered or index >= len(urls[pid]):
                        continue
                    url = urls[pid][index]
                    rid = "res_" + hashlib.sha256(url.encode()).hexdigest()[:24]
                    existing = state["resources"].get(rid)
                    if existing is None and state["reserved"] >= direct_limit:
                        continue
                    stamp = now()
                    service.store.add_evidence(job["job_id"], rid, pid, {
                        "evidence_id": "ev_" + str(uuid4()), "kind": "ai_suggestion",
                        "source": "ai_video_fallback", "knowledge_point_id": pid,
                        "url": url, "observed_at": stamp, "independent_detail_required": True})
                    if existing is None:
                        resource = Resource(resource_id=rid, title="", url=url, canonical_url=url,
                                            platform=platform_for_url(url), discovered_at=stamp).model_dump()
                        state["resources"][rid] = resource
                        state["candidates"][rid] = Candidate(id=rid, title="", url=url, snippet="",
                            query="", source="ai_video_fallback", discovered_at=stamp).model_dump()
                        service.store.save_resource(job["job_id"], resource)
                        job["progress"]["resources_discovered"] = len(state["resources"])
                    if rid not in state["candidate_groups"][pid]:
                        state["candidate_groups"][pid].append(rid)
                    if rid in state["started"]:
                        service._rank(job, point, state["resources"][rid], request)
                        continue
                    key, cached = service._page_cache(state["resources"][rid])
                    # AI-only leads must not be revived from stale source facts.
                    if cached and cached["cache"].get("stale"):
                        cached = None
                    if not cached and state["reserved"] >= direct_limit:
                        continue
                    state["started"].add(rid)
                    if not cached:
                        state["reserved"] += 1
                    scheduled.append((rid, key, cached))
                service._save(job)
                async with asyncio.TaskGroup() as tasks:
                    for rid, key, cached in scheduled:
                        tasks.create_task(service._enrich_one(job, state, rid, key, cached))
        deadline = FETCH_DEADLINE_AT.get()
        remaining = max(0, deadline - asyncio.get_running_loop().time()) if deadline else service.settings.deadline_seconds
        try:
            # Remembered links cannot consume the real-source recovery window.
            async with asyncio.timeout_at(legacy_deadline if combined and search_remaining else _fallback_deadline(service, state)):
                await fetch_direct()
        except TimeoutError:
            diagnostic["direct_fetch_timed_out"] = True
        state["detail_limit"] = service.settings.max_detail_pages
        state["search_limit"] = job["budgets"]["max_search_requests"]
        if combined:
            deadline = FETCH_DEADLINE_AT.get()
            remaining = max(0, deadline - asyncio.get_running_loop().time()) if deadline else service.settings.deadline_seconds
            try:
                async with asyncio.timeout_at(state["legacy_recovery_deadline"]):
                    await _inspect_retained_candidates(service, job, state, points)
            except TimeoutError:
                diagnostic["retained_fetch_timed_out"] = True
            finally:
                state["detail_limit"] = service.settings.max_detail_pages
            # Keep the real-search path reachable even when observed links are
            # slow or all fail. This uses the same global deadline/page caps.
            deadline = FETCH_DEADLINE_AT.get()
            remaining = max(0, deadline - asyncio.get_running_loop().time()) if deadline else service.settings.deadline_seconds
            search_remaining = max(0, job["budgets"]["max_search_requests"] - job["progress"]["search_requests"])
            platforms = [p for p in request.preferred_platforms if p in {"bilibili", "icourse163"}]
            search_available = any(provider is not None and error is None for _, provider, error in
                [service._ai_search_source(Query(knowledge_point_id=points[0]["knowledge_point_id"],
                 query=points[0]["text"], domain_filters=[PLATFORMS[p]])) for p in platforms])
            state["detail_limit"] = service.settings.max_detail_pages - min(
                len(points), search_remaining if search_available else 0,
                max(0, service.settings.max_detail_pages - state["reserved"]))
            try:
                async with asyncio.timeout_at(state["legacy_recovery_deadline"]):
                    await _recover_from_page_links(service, job, state, points)
            except TimeoutError:
                diagnostic["page_link_fetch_timed_out"] = True
            finally:
                state["detail_limit"] = service.settings.max_detail_pages
            query_hints = {}
            for point in points:
                plan = plans.get(point["text"], {})
                raw = plan.get("queries", []) if isinstance(plan, dict) else []
                hints = [phrase for value in (raw[:2] if isinstance(raw, list) else [])
                         if (phrase := video_search_phrase(value))]
                # Original and bilingual core-operation phrases remain usable
                # even when the model is unavailable. None are source evidence.
                phrases, query_diagnostic = video_recovery_search_phrases_with_diagnostics(
                    point["text"], request, hints)
                query_hints[point["knowledge_point_id"]] = phrases
                diagnostic.setdefault("query_planning", []).append({
                    "point_index": len(diagnostic.get("query_planning", [])), **query_diagnostic})
            await _recover_from_search(service, job, state, points, query_hints)
        else:
            await _finish_grounded_recovery(service, job, state, points)
    except asyncio.CancelledError:
        diagnostic["status"] = "interrupted"
        service._save(job)
        raise
    finally:
        covered = visible_point_ids(service, job)
        count = sum(point["knowledge_point_id"] in covered for point in points)
        diagnostic.update(covered_points=count, remaining_points=len(points) - count)
        if diagnostic["status"] != "interrupted":
            diagnostic["status"] = "completed" if count == len(points) else "partial"
        if count != len(points):
            job["upstream_partial"] = True
        service._save(job)


async def _recover_from_own_metadata(service, job, state, points, query_hints=None, *, final=False):
    """Use a small audited semantic budget before spending more source IO.

    This is a mutation-phase operation only. Stored decisions are independently
    rebound by the result projector; neither GET nor cache reads call a model.
    """
    from . import grounded_related
    from .related_recommendations import related_recommendation

    settings, request = service.settings, state["request"]
    if (settings.llm_provider != "openai_compatible" or not settings.llm_api_key.strip()
            or not settings.llm_model.strip() or not settings.llm_base_url.strip()):
        return
    stats = job.setdefault("grounded_related", {"version": grounded_related.VERSION, "batches": 0,
        "judgment_calls": 0, "review_calls": 0, "pairs_attempted": 0, "accepted": 0,
        "attempted": [], "point_attempts": {}, "decisions": {}})
    job["budgets"].update(grounded_related_max_batches=grounded_related.MAX_BATCHES,
        grounded_related_max_model_calls=grounded_related.MAX_MODEL_CALLS,
        grounded_related_max_pairs_per_batch=grounded_related.MAX_PAIRS,
        grounded_related_max_pairs_per_point=grounded_related.MAX_PER_POINT,
        grounded_related_call_timeout_seconds=grounded_related.CALL_SECONDS)
    stats.setdefault("transport_starts", {})
    stats.setdefault("judged", {})
    calls = stats["judgment_calls"] + stats["review_calls"]
    if calls > grounded_related.MAX_MODEL_CALLS - 2:
        return
    covered = visible_point_ids(service, job)
    first_pass = not final
    if first_pass and state.get("grounded_initial_phase_done"):
        return
    revisions = {rid: grounded_related._hash({key: resource.get(key) for key in
        ("fetched_at", "title", "description", "chapters", "field_provenance")})
        for rid, resource in state["resources"].items()}
    initial_sources = state.get("grounded_related_initial_sources", {})
    queues = []
    contexts = {}
    for point in points:
        pid = point["knowledge_point_id"]
        available = grounded_related.MAX_PER_POINT - stats["point_attempts"].get(pid, 0)
        if pid in covered or available <= 0:
            continue
        candidates = []
        for rid, resource in state["resources"].items():
            evidence = service.store.evidence(job["job_id"], rid)
            lexical = related_recommendation(point, resource, evidence, request)
            if (lexical and set(lexical["reference"]["basis"]) & {"page", "catalog"}
                    and lexical["reference"].get("technical_context") in {"observed", "parent_course"}):
                continue
            pair = grounded_related.prepare_pair(point, resource, evidence, request,
                hints=(query_hints or {}).get(pid, ()))
            if (not pair or pair["fingerprint"] in stats["judged"]
                    or stats["transport_starts"].get(pair["fingerprint"], 0) >= 2):
                continue
            own_title = resource.get("title") or ""
            own_description = resource.get("description") or ""
            score = _discovery_priority(service, point, request, own_title, own_description)
            linked = rid in state.get("candidate_groups", {}).get(pid, [])
            candidates.append((linked, score, rid, pair))
            contexts[pair["pair_id"]] = (pid, rid)
        candidates.sort(key=lambda row: (
            stats["transport_starts"].get(row[3]["fingerprint"], 0) == 0,
            _prepared_reference_priority(row[3]), row[0], row[1]), reverse=True)
        queues.append([entry[3] for entry in candidates[:available]])
    pairs = [queue[index] for index in range(1 if first_pass else grounded_related.MAX_PER_POINT) for queue in queues
             if len(queue) > index][:grounded_related.MAX_PAIRS]
    # A long real catalog must not make an otherwise valid whole batch exceed
    # the transport bound. Allocate only pairs that fit the actual JSON schema.
    bounded_pairs = []
    for pair in pairs:
        if grounded_related._safe_payload(grounded_related.batch_payload([*bounded_pairs, pair]), settings):
            bounded_pairs.append(pair)
    pairs = bounded_pairs
    if not pairs:
        return
    deadline = _fallback_deadline(service, state)
    remaining = max(0, deadline - asyncio.get_running_loop().time())
    stage_seconds = grounded_related.CALL_SECONDS * 2
    if remaining < stage_seconds:
        return
    if first_pass:
        state["grounded_related_initial_sources"] = revisions
    if first_pass:
        state["grounded_initial_phase_done"] = True
    stats["batches"] += 1
    stats["pairs_attempted"] += len(pairs)
    def phase(name):
        # This callback is at the actual transport boundary, not allocation.
        stats[name + "_calls"] += 1
        if name == "judgment":
            for pair in pairs:
                fp = pair["fingerprint"]
                stats["attempted"].append(fp)
                stats["transport_starts"][fp] = stats["transport_starts"].get(fp, 0) + 1
        service._save(job)
    def on_call(entry):
        ledger = stats.setdefault("calls", [])
        if len(ledger) < grounded_related.MAX_MODEL_CALLS:
            ledger.append({"call_index": stats["judgment_calls"] + stats["review_calls"], **entry})
        if entry["outcome"] != "ok":
            stats["last_error"] = {"call_index": stats["judgment_calls"] + stats["review_calls"],
                                   "phase": entry["phase"], "outcome": entry["outcome"]}
        service._save(job)
    def on_judged(outcomes):
        for pair in pairs:
            if pair["pair_id"] not in outcomes or pair["fingerprint"] in stats["judged"]:
                continue
            pid, _ = contexts[pair["pair_id"]]
            stats["judged"][pair["fingerprint"]] = outcomes[pair["pair_id"]]
            stats["point_attempts"][pid] = stats["point_attempts"].get(pid, 0) + 1
        service._save(job)
    service._save(job)
    try:
        async with asyncio.timeout(stage_seconds):
            decisions = await grounded_related.judge_batch(settings, pairs,
                client=getattr(service.llm, "client", None),
                timeout_seconds=grounded_related.CALL_SECONDS, phase=phase, on_judged=on_judged, on_call=on_call)
        stats["status"] = "completed" if decisions else "completed_without_acceptance"
        stats.pop("error_type", None)
        for pair_id, decision in decisions.items():
            pid, rid = contexts[pair_id]
            stats["decisions"].setdefault(pid, {})[rid] = decision
            stats["accepted"] += 1
    except asyncio.CancelledError:
        stats["status"] = "interrupted"
        raise
    except Exception as exc:
        stats["status"] = "unavailable"
        stats["error_type"] = type(exc).__name__
    finally:
        service._save(job)


def _prepared_reference_priority(pair):
    """Rank admitted own segments; never turn overlap into a match decision.

    Technology context explains ownership, not the requested operation. Keep
    generic/unknown pairs eligible after more relevant current own observations;
    the existing judgment and independent review still decide all references.
    """
    from .ranking import tokens
    from .related_concepts import reference_concept_hints

    topic = pair["core"]["text"]
    technology = pair["core"].get("technology") or ""
    wanted = tokens(topic) - tokens(technology)
    # Use a coarse tier, not a token-count contest: longer generic course
    # descriptions must not outrank concise API/operation declarations merely
    # by repeating more words from a compound topic. Preserve the old ordering
    # within each tier; unknown synonyms remain eligible in the lower tier.
    return any(wanted & tokens(segment) or reference_concept_hints(topic, segment)
               for source in pair["core"]["sources"] for segment in source["segments"])


def _discovery_priority(service, point, request, title, snippet):
    """Order actual search leads for fetching; this supplies no match evidence."""
    from .ranking import own_resource_snippet
    from .related_concepts import reference_concept_hints, reference_technology_context

    title, snippet = title or "", own_resource_snippet(snippet or "")
    technology = request.topic_technologies.get(point["text"]) or point.get("technology") or ""
    context = not technology or reference_technology_context(technology, title + " " + snippet)
    title_match = service._point_relevance(point, title) + bool(reference_concept_hints(point["text"], title))
    snippet_match = service._point_relevance(point, snippet) + bool(reference_concept_hints(point["text"], snippet))
    return int(context), title_match, snippet_match


async def _inspect_retained_candidates(service, job, state, points):
    """Inspect bounded existing search leads that lexical scheduling omitted.

    A broad tutorial's real catalog may contain the concept despite its title.
    This never retries a stopped search provider or supplies matching evidence.
    """
    from .ai_video_fallback import direct_video_url

    # Keep a fresh source-page slot per gap when another search can still run.
    # A stopped index does not block inspection of its previously returned URLs.
    platforms = [p for p in state["request"].preferred_platforms if p in {"bilibili", "icourse163"}]
    search_remaining = max(0, job["budgets"]["max_search_requests"] - job["progress"]["search_requests"])
    available = any(provider is not None and error is None for _, provider, error in
                    [service._ai_search_source(Query(knowledge_point_id=points[0]["knowledge_point_id"],
                     query=points[0]["text"], domain_filters=[PLATFORMS[p]])) for p in platforms])
    reserve = min(len(points), search_remaining, max(0, service.settings.max_detail_pages - state["reserved"])) if available else 0
    detail_limit = state["detail_limit"] = service.settings.max_detail_pages - reserve
    queues = {}
    for point in points:
        pid = point["knowledge_point_id"]
        candidates = []
        for rid in state["candidate_groups"][pid]:
            resource = state["resources"][rid]
            if rid in state["started"] or not direct_video_url(resource["canonical_url"], state["request"].preferred_platforms):
                continue
            observations = [row for row in service.store.evidence(job["job_id"], rid, pid)
                            if row.get("kind") == "search" and row.get("knowledge_point_id") == pid]
            if not observations:
                continue
            score = max(_discovery_priority(service, point, state["request"], row.get("title"), row.get("snippet"))
                        for row in observations)
            candidates.append((score, rid))
        queues[pid] = [rid for _, rid in sorted(candidates, key=lambda entry: entry[0], reverse=True)[:3]]
    for index in range(3):
        covered = visible_point_ids(service, job)
        scheduled = []
        for point in points:
            pid = point["knowledge_point_id"]
            if pid in covered or index >= len(queues[pid]):
                continue
            rid = queues[pid][index]
            if rid in state["started"]:
                continue
            key, cached = service._page_cache(state["resources"][rid])
            if cached and cached["cache"].get("stale"):
                cached = None
            if not cached and state["reserved"] >= detail_limit:
                continue
            state["started"].add(rid)
            if not cached:
                state["reserved"] += 1
            job["ai_video_fallback"]["retained_pages_inspected"] = job["ai_video_fallback"].get("retained_pages_inspected", 0) + 1
            scheduled.append((rid, key, cached))
        async with asyncio.TaskGroup() as tasks:
            for rid, key, cached in scheduled:
                tasks.create_task(service._enrich_one(job, state, rid, key, cached))


async def _recover_from_page_links(service, job, state, points):
    """Inspect bounded observed links; only each target's own page can match.

    One hop from independently discovered, fresh verified pages. Anchor labels
    prioritize navigation and never become resource titles or match evidence.
    """
    from .ai_video_fallback import direct_video_url
    from .related_concepts import reference_concept_hints, reference_technology_context

    request = state["request"]
    children = state.setdefault("page_link_children", set())
    inspected = state.setdefault("page_links_inspected", {})
    queues = {}
    for point in points:
        pid = point["knowledge_point_id"]
        technology = request.topic_technologies.get(point["text"]) or point.get("technology") or ""
        candidates = {}
        for parent_id in list(state["candidate_groups"][pid]):
            parent = state["resources"][parent_id]
            if (parent_id in children or parent.get("fetch_status") not in {"fetched", "success"}
                    or parent.get("video_evidence_status") != "page_verified" or parent.get("cache", {}).get("stale")):
                continue
            observations = service.store.evidence(job["job_id"], parent_id, pid)
            if not any(row.get("kind") in {"search", "ai_suggestion"}
                       and row.get("knowledge_point_id") == pid for row in observations):
                continue
            parent_urls = {normalize_url(value) for value in (parent.get("canonical_url"), parent.get("resolved_url")) if value}
            for lead in state.get("observed_video_leads", {}).get(parent_id, [])[:24]:
                if not isinstance(lead, dict) or lead.get("source_url") not in parent_urls:
                    continue
                url = direct_video_url(lead.get("url"), request.preferred_platforms)
                title = lead.get("title")
                if not url or not isinstance(title, str) or not title or len(title) > 300:
                    continue
                relevance = service._point_relevance(point, title)
                hints = reference_concept_hints(point["text"], title)
                # Unrelated neighboring videos do not spend scarce detail slots.
                if not (relevance or hints) or (technology and not reference_technology_context(technology, title)):
                    continue
                rid = "res_" + hashlib.sha256(normalize_url(url).encode()).hexdigest()[:24]
                if rid == parent_id or rid in inspected.get(pid, set()):
                    continue
                score = 2 * relevance + len(hints)
                if rid not in candidates or score > candidates[rid][0]:
                    candidates[rid] = (score, rid, url, title, lead["source_url"])
        queues[pid] = sorted(candidates.values(), key=lambda row: -row[0])[:max(0, 3 - len(inspected.get(pid, set())))]
    for index in range(3):
        covered = visible_point_ids(service, job)
        scheduled = []
        for point in points:
            pid = point["knowledge_point_id"]
            if pid in covered or index >= len(queues[pid]):
                continue
            _, rid, url, title, parent_url = queues[pid][index]
            existing = state["resources"].get(rid)
            key, cached = service._page_cache(existing or {"canonical_url": url})
            if cached and cached["cache"].get("stale"):
                cached = None
            if rid not in state["started"] and not cached and state["reserved"] >= state["detail_limit"]:
                continue
            inspected.setdefault(pid, set()).add(rid)
            stamp = now()
            service.store.add_evidence(job["job_id"], rid, pid, {
                "evidence_id": "ev_" + str(uuid4()), "kind": "page_link", "source": "fetched_page_link",
                "knowledge_point_id": pid, "url": url, "source_url": parent_url,
                "observed_title": title, "observed_at": stamp, "independent_detail_required": True})
            if existing is None:
                resource = Resource(resource_id=rid, title="", url=url, canonical_url=url,
                    platform=platform_for_url(url), discovered_at=stamp).model_dump()
                state["resources"][rid] = resource
                state["candidates"][rid] = Candidate(id=rid, title="", url=url, snippet="", query="",
                    source="fetched_page_link", discovered_at=stamp).model_dump()
                service.store.save_resource(job["job_id"], resource)
                job["progress"]["resources_discovered"] = len(state["resources"])
                children.add(rid)
            if rid not in state["candidate_groups"][pid]:
                state["candidate_groups"][pid].append(rid)
            if rid in state["started"]:
                service._rank(job, point, state["resources"][rid], request)
                continue
            # An already discovered but newly inspected target is still a child
            # for this traversal; its own outgoing links cannot expand this run.
            children.add(rid)
            state["started"].add(rid)
            if not cached:
                state["reserved"] += 1
            diagnostic = job["ai_video_fallback"]
            diagnostic["page_links_inspected"] = diagnostic.get("page_links_inspected", 0) + 1
            scheduled.append((rid, key, cached))
        service._save(job)
        async with asyncio.TaskGroup() as tasks:
            for rid, key, cached in scheduled:
                tasks.create_task(service._enrich_one(job, state, rid, key, cached))


async def _recover_from_search(service, job, state, points, query_hints):
    """Find real addresses after model hints fail; all requests stay accounted."""
    request = state["request"]
    platforms = [p for p in request.preferred_platforms if p in {"bilibili", "icourse163"}]
    if not platforms:
        await _finish_grounded_recovery(service, job, state, points, query_hints)
        return
    diagnostic = job["ai_video_fallback"]
    diagnostic["search_requests"] = 0
    pending_fetches = set()
    recovery_deadline = _fallback_deadline(service, state) - _grounded_final_reserve(service, job, state)
    state["recovery_source_deadline"] = recovery_deadline
    try:
        for round_index in range(3):
            covered = visible_point_ids(service, job)
            waiting = [point for point in points if point["knowledge_point_id"] not in covered]
            if not waiting or state["reserved"] >= service.settings.max_detail_pages:
                break
            remaining_rounds = max((len(query_hints[point["knowledge_point_id"]]) - round_index
                                    for point in waiting), default=0)
            if remaining_rounds <= 0:
                break
            remaining = max(0, recovery_deadline - asyncio.get_running_loop().time())
            # A slow original query (including its bounded transport retry) cannot
            # consume every complementary phrase's search and source-page window.
            # This divides the existing deadline; it never extends any job cap.
            round_deadline = asyncio.get_running_loop().time() + remaining / remaining_rounds
            try:
                async with asyncio.timeout_at(round_deadline):
                    await _recover_search_round(service, job, state, waiting, query_hints, round_index, platforms,
                                                round_deadline, pending_fetches)
            except TimeoutError:
                diagnostic["search_round_timeouts"] = diagnostic.get("search_round_timeouts", 0) + 1
                service._save(job)
        # A source fetch belongs to the whole recovery window. Do not cancel
        # it merely because another query phrase is now eligible to run.
        if pending_fetches:
            try:
                async with asyncio.timeout_at(recovery_deadline):
                    await asyncio.gather(*pending_fetches)
            except TimeoutError:
                diagnostic["detail_fetch_timed_out"] = True
        # Cancel/drain outstanding page work BEFORE entering the final audit.
        # A sibling which never returns cannot consume the model's reserve.
        for task in pending_fetches:
            if not task.done():
                task.cancel()
        if pending_fetches:
            await asyncio.gather(*pending_fetches, return_exceptions=True)
        pending_fetches.clear()
        await _finish_grounded_recovery(service, job, state, points, query_hints)
    finally:
        # No network work may outlive the job or explicit user cancellation.
        for task in pending_fetches:
            if not task.done():
                task.cancel()
        if pending_fetches:
            await asyncio.gather(*pending_fetches, return_exceptions=True)


async def _recover_search_round(service, job, state, waiting, query_hints, round_index, platforms, round_deadline, pending_fetches):
    from .ai_video_fallback import direct_video_url

    request = state["request"]
    diagnostic = job["ai_video_fallback"]
    found = {}
    # Finish searches by the midpoint so a stalled sibling cannot prevent the
    # other points' already discovered pages from being fetched this round.
    loop = asyncio.get_running_loop()
    round_remaining = max(0, round_deadline - loop.time())
    search_deadline = loop.time() + min(20, max(0, round_remaining - min(1, round_remaining / 2)))
    async def discover(point):
        pid = point["knowledge_point_id"]
        hints = query_hints[pid]
        if round_index >= len(hints):
            return
        # Prioritize direct videos; both compact model phrases may use the
        # same platform after an overly exact original query returns no match.
        platform = "bilibili" if "bilibili" in platforms else platforms[0]
        domain = PLATFORMS[platform]
        path = "" if platform == "bilibili" else "/course/"
        query = Query(knowledge_point_id=pid, query=f"site:{domain}{path} {hints[round_index]}", domain_filters=[domain])
        try:
            async with asyncio.timeout_at(search_deadline):
                items = await _search_one(service, job, state, query)
        except TimeoutError:
            diagnostic["search_query_timeouts"] = diagnostic.get("search_query_timeouts", 0) + 1
            service._save(job)
            return
        # Every URL below came from an actual source response. The model's
        # phrase is used only for discovery, never as title or relevance.
        # Search summaries can describe neighbouring recommendations rather
        # than this video's own content. A failed leading result must not
        # prevent the next real candidate from being inspected.
        # Inspect the most relevant real titles/catalog snippets before
        # spending the per-query cap on generic intros or installations.
        ordered = sorted(items, key=lambda item: _discovery_priority(
            service, point, request, item.title, item.snippet), reverse=True)
        found[pid] = list(dict.fromkeys(url for item in ordered
            if (url := direct_video_url(item.url, request.preferred_platforms))
            and "res_" + hashlib.sha256(normalize_url(url).encode()).hexdigest()[:24]
                not in state["started"]))[:service.settings.search_results_per_query]
    async with asyncio.TaskGroup() as tasks:
        for point in waiting:
            tasks.create_task(discover(point))
    # Continue through this bounded provider response, stopping each point as
    # soon as its fetched source qualifies. Existing page/time caps and the
    # cross-point round-robin still govern every enrichment; no new search is
    # needed just to inspect the fourth result already returned by a provider.
    for index in range(max((len(rows) for rows in found.values()), default=0)):
        covered = visible_point_ids(service, job)
        scheduled = []
        for point in waiting:
            pid = point["knowledge_point_id"]
            if pid in covered or index >= len(found.get(pid, [])):
                continue
            rid = "res_" + hashlib.sha256(normalize_url(found[pid][index]).encode()).hexdigest()[:24]
            if rid not in state["resources"] or rid in state["started"]:
                continue
            key, cached = service._page_cache(state["resources"][rid])
            if cached and cached["cache"].get("stale"):
                cached = None
            if not cached and state["reserved"] >= service.settings.max_detail_pages:
                job["budget_limited"] = True
                continue
            state["started"].add(rid)
            if not cached:
                state["reserved"] += 1
            scheduled.append((rid, key, cached))
        for rid, key, cached in scheduled:
            pending_fetches.add(asyncio.create_task(service._enrich_one(job, state, rid, key, cached)))
        if pending_fetches:
            done, _ = await asyncio.wait(pending_fetches, timeout=max(0, round_deadline - loop.time()))
            for task in done:
                pending_fetches.remove(task)
                task.result()
        # These leads were observed on newly fetched search results; the
        # pre-search legacy window has already expired. Keep this one hop inside
        # the current source round and before the final audit reserve.
        link_deadline = min(round_deadline,
            state.get("recovery_source_deadline", round_deadline), loop.time() + 20)
        if loop.time() >= link_deadline:
            break
        try:
            async with asyncio.timeout_at(link_deadline):
                await _recover_from_page_links(service, job, state, waiting)
        except TimeoutError:
            diagnostic["page_link_fetch_timed_out"] = True


async def _search_one(service, job, state, query):
    used = 0
    provider_name, provider, error = service._ai_search_source(query)
    attempt = {"knowledge_point_id": query.knowledge_point_id, "query": query.query,
        "domain_filters": query.domain_filters, "provider": provider_name,
        "search_phase": "recovery", "executed_at": now(), "status": "completed",
        "cache_hit": False, "network_attempted": False, "candidate_count": 0}
    async def count_request():
        nonlocal used
        if provider_name in state.get("recovery_stopped_sources", set()):
            raise SearchError("source_stopped", "搜索来源已返回拒绝响应")
        # Recheck the selected provider's stop before each request starts.
        _, current_provider, current_error = service._ai_search_source(query)
        if current_error:
            raise current_error
        if current_provider is None:
            raise SearchError("not_configured", "没有可用的检索来源")
        if job["progress"]["search_requests"] >= job["budgets"]["max_search_requests"]:
            raise SearchBudgetReached()
        if used >= 2:
            raise QueryBudgetReached()
        used += 1
        job["progress"]["search_requests"] += 1
        job["ai_video_fallback"]["search_requests"] += 1
        service._save(job)
    if provider is not None and not isinstance(provider, HTTPProvider):
        provider = copy(provider)
        if hasattr(provider, "request_hook"):
            provider.request_hook = count_request
    scope = provider.query_scope(count_request) if isinstance(provider, HTTPProvider) else nullcontext()
    job["progress"]["queries_planned"] += 1
    items = []
    try:
        with scope:
            try:
                if error:
                    raise error
                if provider is None:
                    raise SearchError("not_configured", "没有可用的检索来源")
                async with state["network_slots"]:
                    if not hasattr(provider, "request_hook"):
                        await count_request()
                    items = await provider.search(query.query, state["request"].language,
                                                  service.settings.search_results_per_query, query.domain_filters)
                items = [row if isinstance(row, Candidate) else Candidate.model_validate(row) for row in items]
                job["progress"]["search_successes"] += 1
            except SearchBudgetReached as exc:
                items = [row if isinstance(row, Candidate) else Candidate.model_validate(row) for row in exc.partial_candidates]
                attempt.update(status="partial", error_code="query_budget_exhausted")
                if items:
                    job["progress"]["search_successes"] += 1
            except SearchError as exc:
                attempt.update(status="failed", error_code=exc.code)
                job["progress"]["search_failures"] += 1
            finally:
                attempt["provider_requests"] = deepcopy(getattr(provider, "last_requests", [])) if used else []
                attempt["network_attempted"] = bool(used)
                if any(isinstance(row.get("http_status"), int) and 400 <= row["http_status"] < 500
                       for row in attempt["provider_requests"]):
                    state.setdefault("recovery_stopped_sources", set()).add(provider_name)
    except asyncio.CancelledError:
        attempt.update(status="cancelled", error_code="task_cancelled")
        raise
    except Exception:
        attempt.update(status="failed", error_code="search_unavailable")
        job["progress"]["search_failures"] += 1
    finally:
        attempt["candidate_count"] = len(items)
        service.store.add_attempt(job["job_id"], attempt)
        job["progress"]["queries_completed"] += 1
        service._save(job)
    service._record_search_candidates(job, state, query, items, {"hit": False, "cached_at": None, "stale": False})
    job["progress"]["candidates_discovered"] += len(items)
    job["progress"]["resources_discovered"] = len(state["resources"])
    service._save(job)
    return items
