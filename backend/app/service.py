from __future__ import annotations

from .technical_prefix import leading_technical_owner

import asyncio
import hashlib
import re
import time
import math
import json
from collections import Counter, deque
from datetime import datetime, timezone
from copy import deepcopy
from contextlib import suppress
from uuid import uuid4
from urllib.parse import parse_qsl, urlsplit
from .config import Settings
from .db import Store
from .fetcher import Fetcher, FetcherConfig, FETCH_DEADLINE_AT, PLATFORM_POLICY_REVIEWS, normalize_url, platform_for_url
from .llm import build_llm
from .models import Candidate, Query, Resource, SearchRequest, now
from .read_rank_cache import ReadRankCache
from .read_related_cache import ReadRelatedCache
from .providers import HTTPProvider, QueryBudgetReached, SearchBudgetReached, SearchError, SearXNGProvider, build_provider
from .queries import PLATFORMS, generate_queries, fair_queries, prioritize_video_entry_query, gap_query_candidates, public_catalog_query
from .probe_priority import probe_api_priority
from .ranking import has_course_discovery, has_learning_evidence, has_type_evidence, has_video_evidence, rank_resource, type_from_discovered_url
from .resource_identity import derive_course_identity, diversify, summarize_course_identities
from .source_adapters.bilibili import unavailable_video_projection
from .video_availability import has_known_media_fault, project_unconfirmed_video_shell, project_unconfirmed_fetched_media
from .url_utils import UnsafeURL
from .ranking import candidate_topic_signal, decompose_topic, relevance, search_course_evidence, summarize_collection_coverage, coverage_targets, tokens
from . import teaching_match
from . import teaching_review
from .learning_support import summarize_learning_support
from .discovery_display import discovered_video, display_discovered_videos
from .related_recommendations import POLICY_VERSION as RECOMMENDATION_POLICY
from .mooc_relevance import assess_mooc_relevance, is_mooc_resource, teaching_probe_eligible
from .platform_search import platform_budget, search_platform_rounds
from .course_library import CourseLibrary, course_family_key
from .mooc_queries import MOOC_QUERY_POLICY
from .mooc_refresh import MoocRefresh
from .ai_video_service import reserve_fallback, run_ai_video_fallback, verified_ai_resource


def _topic_pointer_reservoir(point: dict) -> dict:
    """At most four candidates for each of the six original declared skills."""
    skills = point.get("learning_skills")
    if not isinstance(skills, list):
        return {}
    return {f"skill_{index+1}": {"skill": skill, "items": []}
            for index, skill in enumerate(skills[:6]) if isinstance(skill, str) and skill.strip()}


def _reserve_topic_pointer(pools: dict, point: dict, resource: dict, evidence: list, pointer: dict) -> None:
    """Bounded read-only allocation; producer remains responsible for proof."""
    if not isinstance(pointer, dict):
        return
    pool = pools.get(pointer.get("skill_id"))
    missing = pointer.get("missing_components")
    if (pool is None or pointer.get("skill") != pool["skill"]
            or pointer.get("knowledge_point_id") != point.get("knowledge_point_id")
            or pointer.get("resource_id") != resource.get("resource_id")
            or pointer.get("scope") != "topic_declared" or pointer.get("basis") != "catalog"
            or not isinstance(missing, list) or any(not isinstance(value, str) for value in missing)):
        return
    try:
        target = normalize_url(pointer.get("target_url"))
    except (UnsafeURL, ValueError, TypeError):
        return
    entry = {"resource": resource, "evidence": evidence, "pointer": pointer}
    order = (len(missing), target, str(resource.get("resource_id", "")),
             str(pointer.get("evidence_id", "")), str(pointer.get("quote", "")))
    # Replace a duplicate URL only with a more specific/stably ordered record.
    previous = next((item for item in pool["items"] if item[0][1] == target), None)
    if previous is not None:
        if previous[0] <= order:
            return
        pool["items"].remove(previous)
    pool["items"].append((order, entry))
    pool["items"].sort(key=lambda item: item[0])
    del pool["items"][4:]


def _display_topic_pointers(pools: dict) -> list[dict]:
    """Original-skill round robin, four slots, stable URL deduplication."""
    result, used, positions = [], set(), {key: 0 for key in pools}
    while len(result) < 4:
        progressed = False
        for key, pool in pools.items():
            rows = pool["items"]
            index = positions[key]
            while index < len(rows) and rows[index][0][1] in used:
                index += 1
            positions[key] = index
            if index == len(rows):
                continue
            order, entry = rows[index]
            result.append(entry)
            used.add(order[1])
            positions[key] += 1
            progressed = True
            if len(result) == 4:
                break
        if not progressed:
            break
    return result


def _learning_literal_hits(pair: dict) -> list[set[str]]:
    """Own-observation allocation hints, never teaching claims or aliases."""
    from .ranking import _confirmed_target_non_teaching
    ignored = {"the", "and", "or", "with", "for", "from", "into", "using", "use", "of", "in", "to", "as", "via", "by", "an", "on", "is", "a"}
    observations = [o for o in pair.get("observations", [])
                    if isinstance(o, dict) and o.get("basis") in {"title", "description", "catalog", "lesson_notes"}]
    own = "\n".join(s for o in observations for s in o.get("segments", []) if isinstance(s, str))
    scope = {"title": "\n".join(s for o in observations if o["basis"] == "title" for s in o.get("segments", []) if isinstance(s, str)),
             "body": "\n".join(s for o in observations if o["basis"] != "title" for s in o.get("segments", []) if isinstance(s, str))}
    result = []
    for row in pair.get("skills", []):
        skill = row.get("text", "")
        owner = leading_technical_owner(skill) or pair.get("technology") or ""
        declared = pair.get("technology") or ""
        if "." in str(owner) and owner != declared:
            owner = declared if declared and str(owner).casefold().startswith(str(declared).casefold()+".") else str(owner).split(".", 1)[0]
        names = []
        for match in re.finditer(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_]*(?:[.-][A-Za-z_][A-Za-z0-9_]*)*)(\s*\()?", skill):
            name, call = match.groups()
            if len(name) < 3 or name.casefold() in ignored or name.casefold() == str(owner).casefold():
                continue
            shaped = bool(call or re.search(r"[a-z][A-Z]|[_.-]", name))
            # Uppercase acronyms describe families (PWM/CSV/DOM); keep their
            # existing lexical marginal relevance, without API priority.
            if not shaped and name.isupper():
                continue
            names.append((name, 2 if shaped else 1))
        hits = set()
        owner_present = bool(owner and re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(str(owner)) + r"(?![A-Za-z0-9_.-])", own, re.I))
        for name, weight in names:
            qualified_owner = bool(owner and name.casefold().startswith(str(owner).casefold()+"."))
            if not owner_present and not qualified_owner:
                continue
            if re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])", own, re.I):
                if not _confirmed_target_non_teaching(name, str(owner), [scope]):
                    hits.add(str(weight)+":"+name.casefold())
        # Explicit own prerequisite/future/non-teaching declarations may not
        # receive a positive inspection priority merely from their API tokens.
        if hits and _confirmed_target_non_teaching(skill, str(owner), [scope]):
            hits.clear()
        result.append(hits)
    return result


def _learning_bound_notes_hint(pair: dict) -> bool:
    """Prefer inspectable own teaching notes over broad metadata-only entries.

    prepare_pair already requires the notes' exact own-video/provenance binding.
    This hint is only allocation quality, never a teaching or stage-fit answer.
    """
    from .ranking import _confirmed_target_non_teaching
    owner = pair.get("technology") or ""
    if not owner or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+#.-]*", owner):
        return False
    notes = "\n".join(segment for row in pair.get("observations", [])
                      if row.get("basis") == "lesson_notes" for segment in row.get("segments", []))
    if not re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(owner) + r"(?![A-Za-z0-9_-])", notes, re.I):
        return False
    scope = {"title": "", "body": notes}
    return any(not _confirmed_target_non_teaching(skill["text"], owner, [scope])
               for skill in pair.get("skills", []))


def _learning_concept_inspection_hints(pair: dict, targets: list[str]) -> set[str]:
    """Confirmed concept identifiers allocate inspections, never support claims.

    These are exact student-confirmed concept strings, not inferred API aliases.
    Qualified identifiers also expose their literal final component for recall;
    the source still needs its own declared technology and teaching scope.
    """
    from .ranking import _confirmed_target_non_teaching
    owner = pair.get("technology") or ""
    observations = pair.get("observations", [])
    own = "\n".join(segment for row in observations for segment in row.get("segments", []))
    if not owner or not re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(owner) + r"(?![A-Za-z0-9_-])", own, re.I):
        return set()
    scope = {"title": "\n".join(s for o in observations if o.get("basis") == "title" for s in o.get("segments", [])),
             "body": "\n".join(s for o in observations if o.get("basis") != "title" for s in o.get("segments", []))}
    ignored = {owner.casefold(), "the", "and", "or", "with", "from", "using", "into", "for"}
    hits = set()
    for target in targets[:16]:
        if not isinstance(target, str) or len(target) > 500:
            continue
        for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", target):
            token = match.group().split(".")[-1]
            if len(token) < 3 or token.casefold() in ignored:
                continue
            if (re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", own)
                    and not _confirmed_target_non_teaching(token, owner, [scope])):
                hits.add(token)
                if len(hits) == 16:
                    return hits
    return hits


def _select_learning_candidates(candidates: list[tuple], skills: list[str], inspection_targets: list[str] | None = None) -> list[tuple]:
    """Preserve four slots and marginal fairness; prefer uncovered literal APIs.

    Inputs already passed prepare_pair media/provenance/scope checks. The same
    job's own observations alone allocate slots; every chosen pair still needs
    judgment/review. No URL, source identity, project-demo or API vocabulary is
    used as a positive answer.
    """
    remaining = list(candidates)
    selected, covered = [], [0.0] * len(skills)
    literal_covered = [set() for _ in skills]
    hints = {row[1]: _learning_literal_hits(row[2]) for row in remaining}
    notes = {row[1]: _learning_bound_notes_hint(row[2]) for row in remaining}
    concepts = {row[1]: _learning_concept_inspection_hints(row[2], inspection_targets or []) for row in remaining}
    inspected_concepts = set()
    while remaining and len(selected) < 4:
        def priority(row):
            gains = [max(0.0, value - covered[index]) for index, value in enumerate(row[4])]
            literal = [hints[row[1]][i] - literal_covered[i] for i in range(len(skills))]
            literal_gain = sum(max((int(name.split(":", 1)[0]) for name in group), default=0)  / (1 + len(literal_covered[i])) for i, group in enumerate(literal))
            return (-literal_gain, -sum(bool(group) for group in literal), -len(concepts[row[1]] - inspected_concepts), -int(notes[row[1]]),
                    -sum(gains), -sum(value > 0 for value in gains), -row[0], row[1])
        chosen = min(remaining, key=priority)
        remaining.remove(chosen)
        selected.append(chosen)
        covered = [max(value, chosen[4][index]) for index, value in enumerate(covered)]
        literal_covered = [prior | hints[chosen[1]][i] for i, prior in enumerate(literal_covered)]
        inspected_concepts.update(concepts[chosen[1]])
    return selected


class BudgetReached(SearchBudgetReached):
    pass


class IdempotencyConflict(Exception):
    pass


class AdmissionRejected(Exception):
    def __init__(self, code: str, message: str, retry_after: int = 1, status: int = 429):
        self.code, self.message, self.retry_after, self.status = code, message, retry_after, status


class JobService:
    """A persistent, single-process queue. Jobs are serialized; page requests are bounded."""
    def __init__(self, settings: Settings, store: Store, provider=None, fetcher=None, llm=None, *, provider_overrides=None):
        self.settings, self.store = settings, store
        self.course_library = (CourseLibrary(store, ttl_seconds=settings.shared_course_library_ttl_seconds,
            max_candidates=settings.shared_course_library_max_candidates)
            if settings.shared_course_library_enabled else None)
        self.mooc_refresh = (MoocRefresh(store, settings.mooc_refresh_interval_seconds)
            if settings.mooc_refresh_enabled else None)
        self.provider_error = None
        self.fetcher = fetcher or Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
            timeout_seconds=settings.fetch_timeout_seconds, global_concurrency=settings.global_concurrency,
            min_interval_seconds=settings.fetch_min_interval_seconds,
            allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
            bilibili_public_metadata=settings.bilibili_public_metadata,
            bilibili_public_metadata_max_bytes=settings.bilibili_public_metadata_max_bytes,
            dns_resolver=settings.dns_resolver, phased_timeouts=settings.fetch_phased_timeouts,
            body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
            body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
            body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
        if isinstance(self.fetcher, Fetcher):
            from .rendering import RenderConfig, SafeRenderer
            self.fetcher.renderer = SafeRenderer(RenderConfig(**self._renderer_profile()["config"]))
        try:
            self.provider = provider or (provider_overrides or {}).get(settings.search_provider) or build_provider(settings, fetcher=self.fetcher, store=store)
        except SearchError as exc:
            self.provider, self.provider_error = None, exc
        # One object per source preserves that source's access stops, cooldowns
        # and spacing. Optional platform routing never resets another source.
        self._providers = {settings.search_provider: self.provider}
        self._provider_errors = {settings.search_provider: self.provider_error}
        self._searxng_failover_health = {}
        names = [settings.search_provider_for(platform) for platform in PLATFORMS]
        if settings.ai_video_fallback_enabled:
            names += [name for name, key in (("serper", settings.serper_api_key), ("tavily", settings.tavily_api_key or settings.tavily_backup_api_key)) if key]
        if settings.searxng_failover_provider == "tavily" and (settings.tavily_api_key or settings.tavily_backup_api_key):
            names.append("tavily")
        for name in dict.fromkeys(names):
            if name in self._providers:
                continue
            try:
                self._providers[name] = (provider_overrides or {}).get(name) or build_provider(
                    settings, fetcher=self.fetcher, store=store, provider_name=name)
                self._provider_errors[name] = None
            except SearchError as exc:
                self._providers[name], self._provider_errors[name] = None, exc
        self.official_fallback = None
        if settings.official_sitemap_fallback and settings.search_provider != "official_sitemap":
            from .official_sitemap import OfficialSitemapProvider
            self.official_fallback = OfficialSitemapProvider(settings, fetcher=self.fetcher, store=store)
        self.public_catalog = None
        self.twt_catalog = None
        if settings.public_catalog_fallback and settings.search_provider != "official_sitemap":
            from .public_catalog import PublicCatalogProvider
            self.public_catalog = PublicCatalogProvider(settings, fetcher=self.fetcher, store=store)
            from .techwithtim_catalog import TechWithTimCatalogProvider
            self.twt_catalog = TechWithTimCatalogProvider(settings, fetcher=self.fetcher, store=store)
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

    @staticmethod
    def _query_platform(query):
        # Do not infer a platform from query text or a mixed-domain search.
        return next((platform for platform, domain in PLATFORMS.items()
                     if query.domain_filters == [domain]), None)

    def _search_source(self, query, *, job=None):
        name = self.settings.search_provider_for(self._query_platform(query))
        if job is not None and name == "searxng" and self._failover_enabled():
            platform = self._query_platform(query)
            reason = self._searxng_failover_reason(query)
            if platform and reason:
                route = {"from": "searxng", "to": "tavily", "reason": reason,
                         "source_identity": self._searxng_failover_identity()}
                job["platform_search"].setdefault("source_failovers", {})[platform] = route
                return "tavily", self._providers.get("tavily"), self._provider_errors.get("tavily")
        if name == self.settings.search_provider:
            # The legacy injectable slot remains authoritative, including
            # callers that replace it before starting the worker.
            return name, self.provider, getattr(self, "provider_error", None)
        return name, self._providers.get(name), self._provider_errors.get(name)

    def _failover_enabled(self):
        # An already-configured key is necessary; never opt into keyless access.
        return (getattr(self.settings, "searxng_failover_provider", "") == "tavily"
                and bool(self.settings.tavily_api_key or self.settings.tavily_backup_api_key) and self._providers.get("tavily") is not None
                and self._provider_errors.get("tavily") is None)

    def _ai_search_source(self, query):
        """Gap-only routing; never changes the ordinary platform provider."""
        configured = self.settings.search_provider_for(self._query_platform(query))
        selected = self.settings.ai_video_search_provider
        if selected == "auto":
            selected = ("serper" if self.settings.serper_api_key else
                        "tavily" if self.settings.tavily_api_key or self.settings.tavily_backup_api_key else configured)
        if selected == "default":
            selected = configured
        if selected == configured:
            if configured == "searxng" and self._searxng_failover_stop(query):
                return configured, None, SearchError("source_stopped", "搜索来源暂时受限")
            return self._search_source(query)
        # This is the preselected independent index, not another endpoint for
        # the stopped ordinary provider. Keep both provider objects and their
        # access state intact; never fall through to another index on a stop.
        provider, error = self._providers.get(selected), self._provider_errors.get(selected)
        if provider is not None:
            if getattr(provider, "quota_exhausted", False):
                return selected, None, SearchError("quota_exhausted", "搜索来源额度已用尽")
            if getattr(provider, "access_denied", False):
                return selected, None, SearchError("access_denied", "搜索来源此前拒绝访问")
            if getattr(provider, "paused_until", 0) > time.monotonic():
                return selected, None, SearchError("rate_limited", "搜索来源仍在暂停期内")
        return selected, provider, error

    def _searxng_failover_identity(self):
        return self.store.cache_key("searxng-failover-source", self._search_identity("searxng"))

    def _searxng_query_engines(self, query):
        course = query.domain_filters == ["icourse163.org"]
        video = bool(re.search(r"视频|\bvideo\b", query.query, re.I))
        primary = (self.settings.searxng_video_engines if not course and video
                   and self.settings.searxng_video_engines else self.settings.searxng_engines)
        if not primary:
            return ()  # Unknown default groups are not an attributable engine scope.
        return tuple(dict.fromkeys((*primary, *self.settings.searxng_fallback_engines)))

    def _searxng_failover_stop(self, query):
        """Recheck at election and at the actual fallback request hook."""
        provider = self._source_objects().get("searxng")
        if provider is None:
            return None
        current = time.monotonic()
        if getattr(provider, "access_denied", False):
            return "access_denied"
        if getattr(provider, "paused_until", 0) > current:
            return "rate_limited"
        if getattr(provider, "default_group_pause_until", 0) > current:
            return "default_group_access_pause"
        engines = self._searxng_query_engines(query)
        pauses = getattr(provider, "engine_pauses", {})
        timeouts = getattr(provider, "engine_timeout_cooldowns", {})
        if any(pauses.get(engine, 0) > current and (timeouts.get(engine, 0) <= current
               or pauses[engine] > timeouts[engine]) for engine in engines):
            return "engine_access_pause"
        return None

    def _searxng_failover_reason(self, query):
        platform = self._query_platform(query)
        if not platform or self._searxng_failover_stop(query):
            return None
        provider = self._source_objects().get("searxng")
        if provider is None:
            return None
        current = time.monotonic()
        engines = self._searxng_query_engines(query)
        pauses = getattr(provider, "engine_pauses", {})
        timeouts = getattr(provider, "engine_timeout_cooldowns", {})
        record = self._searxng_failover_health.get((platform, self._searxng_failover_identity()))
        if record and record["until"] > current:
            return record["reason"]
        # Explicit engine health, not last_status or an unrelated platform's
        # fault. An available configured fallback engine may still be used.
        if engines and all(timeouts.get(engine, 0) > current and pauses.get(engine, 0) > current
                           for engine in engines):
            return "engine_timeout_cooldown"
        return None

    def _observe_searxng_attempt(self, job, attempt):
        """Elect only from an actual failed observation, preserving its clock."""
        if not self._failover_enabled() or attempt.get("provider") != "searxng":
            return False
        try:
            query = Query(knowledge_point_id=attempt["knowledge_point_id"], query=attempt["query"],
                          domain_filters=attempt["domain_filters"])
        except (ValueError, TypeError, KeyError):
            return False
        platform = self._query_platform(query)
        if not platform or self.settings.search_provider_for(platform) != "searxng":
            return False
        if not any(point["knowledge_point_id"] == query.knowledge_point_id for point in job["knowledge_points"]):
            return False
        requests = attempt.get("provider_requests", [])
        if (not isinstance(requests, list) or not requests
                or any(not isinstance(row, dict) or row.get("provider") != "searxng" for row in requests)):
            return False
        warnings = [*attempt.get("upstream_warnings", []),
                    *(warning for row in requests for warning in row.get("upstream_warnings", []))]
        if (attempt.get("candidate_count") or attempt.get("status") != "failed"
                or attempt.get("error_code") not in {"search_timeout", "search_unavailable", "upstream_engine_failed"}
                or any(row.get("reason_code") in {"captcha", "access_denied", "rate_limited", "suspended"}
                       or row.get("code") == "no_topic_signal" for row in warnings)):
            return False
        try:
            stamp = datetime.fromisoformat(attempt["executed_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return False
            remaining = 300 - (datetime.now(timezone.utc) - stamp).total_seconds()
            if not 0 < remaining <= 300:
                return False
        except (ValueError, TypeError, KeyError):
            return False
        self._searxng_failover_health[(platform, self._searxng_failover_identity())] = {
            "until": time.monotonic() + remaining, "reason": attempt["error_code"]}
        return True

    def restore_searxng_failover_health(self, job_id, *, source_identity):
        """Replay only this Store's real attempts from an explicitly bound runtime.

        No requests or DB writes; old timestamps cannot renew the 300s window.
        The caller must supply the original runtime's nonsecret source identity.
        """
        if source_identity != self._search_identity("searxng"):
            return 0
        job = self.store.get_job(job_id)
        return sum(self._observe_searxng_attempt(job, attempt) for attempt in self.store.attempts(job_id))

    def _source_objects(self):
        return {**self._providers, self.settings.search_provider: self.provider}

    @staticmethod
    def _discovery_trace(provider):
        discovery = getattr(provider, "last_discovery", {})
        name = getattr(provider, "name", None)
        return {name: discovery} if name in {"public_catalog", "techwithtim_catalog"} else discovery

    def _search_identity(self, name):
        identity = {"provider": name, "provider_version": 13}
        if name == "searxng":
            identity.update(endpoint=hashlib.sha256(self.settings.searxng_url.encode()).hexdigest(),
                engines=self.settings.searxng_engines, video_engines=self.settings.searxng_video_engines,
                fallback_engines=self.settings.searxng_fallback_engines)
        elif name == "tavily":
            identity.update(endpoint="https://api.tavily.com/search", search_depth="basic", mooc_query_policy=MOOC_QUERY_POLICY)
        elif name == "serper":
            identity.update(endpoint="https://google.serper.dev/search", mooc_query_policy=MOOC_QUERY_POLICY)
        return identity

    def _course_library_profile(self):
        from .mooc_relevance import MATCH_RULES_VERSION
        return self.store.cache_key("course-library-profile", {"version": 2, "extractor_version": 15,
            "matching_rules": MATCH_RULES_VERSION, "course_identity": "public-course-id-and-term-v2",
            "outline_policy": "mooc-outline-v1", "platform_policy": PLATFORM_POLICY_REVIEWS.get("icourse163"),
            "fetch_enabled": self.settings.fetch_enabled, "allowed_hosts": self.settings.allowed_restricted_hosts,
            "denied_hosts": self.settings.denied_fetch_hosts, "transport": self._transport_profile(),
            "renderer": self._renderer_profile()})

    def _mooc_discovery_policy(self, request):
        if "icourse163" not in request.preferred_platforms:
            return None
        if not (self.settings.shared_course_library_enabled or self.settings.mooc_gap_search_enabled):
            return None
        return {"version": 2, "course_count_policy": "distinct-course-id-v1",
            "shared_library": self.settings.shared_course_library_enabled,
            "gap_search": self.settings.mooc_gap_search_enabled,
            "target_courses_per_point": self.settings.mooc_target_courses_per_point,
            "library_ttl_seconds": self.settings.shared_course_library_ttl_seconds,
            "library_max_candidates": self.settings.shared_course_library_max_candidates,
            "gap_check_wait_seconds": self.settings.mooc_gap_check_wait_seconds,
            **({"refresh_enabled": True, "refresh_interval_seconds": self.settings.mooc_refresh_interval_seconds}
               if self.settings.mooc_refresh_enabled else {}),
            "profile": self._course_library_profile()}

    def _seed_course_library(self, job, state):
        if (not self.settings.shared_course_library_enabled or self.course_library is None
                or "icourse163" not in state["request"].preferred_platforms
                or job.get("shared_course_library", {}).get("loaded")):
            return
        profile = self._course_library_profile()
        pairs, imported = 0, set()
        for point in state["points"]:
            families = set()
            # Look past matching semesters of the same course, while retaining
            # the library's configured bound and each entry's own evidence.
            for hit in self.course_library.lookup(point, profile,
                    limit=self.settings.shared_course_library_max_candidates,
                    request=state["request"], allow_related=True):
                family = course_family_key(hit["resource"]["canonical_url"])
                if not family or family in families:
                    continue
                if len(families) >= self.settings.mooc_target_courses_per_point:
                    break
                families.add(family)
                resource, observations = deepcopy(hit["resource"]), deepcopy(hit["evidence"])
                rid = "res_" + hashlib.sha256(resource["canonical_url"].encode()).hexdigest()[:24]
                if rid not in state["resources"]:
                    ids = {row["evidence_id"]: "ev_" + str(uuid4()) for row in observations}
                    for row in observations:
                        row["evidence_id"] = ids[row["evidence_id"]]
                    for provenance in resource.get("field_provenance", {}).values():
                        if isinstance(provenance, dict) and provenance.get("evidence_id") in ids:
                            provenance["evidence_id"] = ids[provenance["evidence_id"]]
                    for chapter in resource.get("chapters", []):
                        if isinstance(chapter, dict) and chapter.get("evidence_id") in ids:
                            chapter["evidence_id"] = ids[chapter["evidence_id"]]
                    resource["resource_id"] = rid
                    resource["cache"] = {"hit": True, "stale": False, "cached_at": hit.get("observed_at")}
                    state["resources"][rid] = resource
                    state["started"].add(rid)
                    self.store.save_resource(job["job_id"], resource)
                    imported.add(rid)
                else:
                    observations = [row for row in observations if row.get("kind") == "course_library"]
                    for row in observations:
                        row["evidence_id"] = "ev_" + str(uuid4())
                for row in observations:
                    pid = point["knowledge_point_id"] if row.get("kind") == "course_library" else None
                    if pid:
                        row["knowledge_point_id"] = pid
                    self.store.add_evidence(job["job_id"], rid, pid, row)
                if rid not in state["candidate_groups"][point["knowledge_point_id"]]:
                    state["candidate_groups"][point["knowledge_point_id"]].append(rid)
                    pairs += 1
        job["shared_course_library"] = {"loaded": True, "matched_pairs": pairs,
            "reused_courses": len(imported), "profile": profile}
        job["progress"]["library_hit_pairs"] = pairs
        job["progress"]["library_courses_reused"] = len(imported)
        job["progress"]["resources_discovered"] = len(state["resources"])
        if imported:
            state["ready"] = True
            state["changed"].set()
        self._save(job)

    def _mooc_coverage_count(self, job, point, state):
        urls = set()
        for rid in state["candidate_groups"].get(point["knowledge_point_id"], []):
            resource = state["resources"].get(rid, {})
            if not is_mooc_resource(resource):
                continue
            if resource.get("course_library") and not self._library_resource_current(resource):
                continue
            evidence = self.store.evidence(job["job_id"], rid)
            if (assess_mooc_relevance(self._mooc_assessment_point(point), resource, evidence)["display_eligible"]
                    and discovered_video(point, resource, evidence)):
                key = course_family_key(resource["canonical_url"])
                if key:
                    urls.add(key)
        return len(urls)

    @staticmethod
    def _mooc_assessment_point(point):
        if not point.get("technology"):
            return point
        from .professional_concepts import contextual_concept_name
        return {**point, "text": contextual_concept_name(point["text"], point["technology"])}

    def _seed_public_library(self, job, state):
        """Mobile persistent library supplies public facts, never user matches."""
        public = getattr(self, "public_library", None)
        if public is None or job.get("public_library_reuse", {}).get("loaded"):
            return
        imported, pairs = set(), 0
        for point in state["points"]:
            for hit in public.lookup(point, state["request"], limit=12):
                resource, observations = deepcopy(hit["resource"]), deepcopy(hit["evidence"])
                if resource.get("platform") == "icourse163" and self.course_library is not None:
                    # Reuse the existing outline receipt validator. A related
                    # public card alone is never a full-outline assessment.
                    profile = self._course_library_profile()
                    self.course_library.observe(resource, observations, profile)
                    current = next((row for row in self.course_library.lookup(point, profile,
                        limit=self.settings.shared_course_library_max_candidates,
                        request=state["request"], allow_related=True)
                        if row["resource"]["canonical_url"] == resource["canonical_url"]), None)
                    if current:
                        resource, observations = deepcopy(current["resource"]), deepcopy(current["evidence"])
                rid = "res_" + hashlib.sha256(resource["canonical_url"].encode()).hexdigest()[:24]
                if rid not in state["resources"]:
                    digest = hit["content_sha256"]
                    ids = {row["evidence_id"]: "ev_" + str(uuid4()) for row in observations}
                    for row in observations:
                        row["evidence_id"] = ids[row["evidence_id"]]
                    for proof in resource.get("field_provenance", {}).values():
                        if isinstance(proof, dict) and proof.get("evidence_id") in ids:
                            proof["evidence_id"] = ids[proof["evidence_id"]]
                    for chapter in resource.get("chapters", []):
                        if isinstance(chapter, dict) and chapter.get("evidence_id") in ids:
                            chapter["evidence_id"] = ids[chapter["evidence_id"]]
                    resource.update(resource_id=rid, public_library={"course_id": hit["course_id"],
                        "observed_at": hit["observed_at"], "expires_at": hit["expires_at"], "content_sha256": digest},
                        cache={"hit": True, "stale": False, "cached_at": hit["observed_at"]})
                    state["resources"][rid] = resource
                    state["started"].add(rid)
                    self.store.save_resource(job["job_id"], resource)
                    for row in observations:
                        pid = point["knowledge_point_id"] if row.get("kind") == "course_library" else None
                        self.store.add_evidence(job["job_id"], rid, pid, row)
                    imported.add(rid)
                else:
                    for row in observations:
                        if row.get("kind") == "course_library":
                            row["evidence_id"] = "ev_" + str(uuid4())
                            self.store.add_evidence(job["job_id"], rid, point["knowledge_point_id"], row)
                if rid not in state["candidate_groups"][point["knowledge_point_id"]]:
                    state["candidate_groups"][point["knowledge_point_id"]].append(rid)
                    pairs += 1
        job["public_library_reuse"] = {"loaded": True, "resources": len(imported), "point_pairs": pairs,
            "scope": "public source facts; current-point relevance reassessed; no teaching claims copied"}
        job["progress"]["public_library_hit_pairs"] = pairs
        job["progress"]["library_hit_pairs"] = job["progress"].get("library_hit_pairs", 0) + pairs
        if imported:
            state["ready"] = True
            state["changed"].set()
        self._save(job)

    def _public_library_current(self, resource, evidence):
        public = getattr(self, "public_library", None)
        return public is not None and public.is_current(resource, evidence)

    def _library_resource_current(self, resource):
        return bool(self.settings.shared_course_library_enabled and self.course_library is not None
                    and self.course_library.is_current(resource, self._course_library_profile()))

    async def _wait_mooc_checks(self, job, point, state):
        """Let existing own-course probes settle before spending another query."""
        if not self.settings.fetch_enabled:
            return
        until = time.monotonic() + self.settings.mooc_gap_check_wait_seconds
        started = time.monotonic()
        while time.monotonic() < until:
            if self._mooc_coverage_count(job, point, state) >= self.settings.mooc_target_courses_per_point:
                break
            pending = False
            for rid in state["candidate_groups"].get(point["knowledge_point_id"], []):
                resource = state["resources"].get(rid, {})
                if not is_mooc_resource(resource) or resource.get("fetch_status") != "not_fetched":
                    continue
                if rid not in state["started"] and state["reserved"] >= self.settings.max_detail_pages:
                    continue
                evidence = self.store.evidence(job["job_id"], rid)
                if assess_mooc_relevance(point, resource, evidence)["probe_eligible"]:
                    pending = True
                    break
            if not pending:
                break
            # Do not clear the shared event or reserve a network slot: the
            # detail worker must keep making progress and cancellation must win.
            await asyncio.sleep(.1)
        waited = round((time.monotonic() - started) * 1000)
        job["progress"]["gap_check_wait_ms"] = job["progress"].get("gap_check_wait_ms", 0) + waited

    def _refresh_gap_coverage(self, job, state):
        if not job.get("gap_search", {}).get("enabled"):
            return
        for point in state["points"]:
            row = job["gap_search"]["points"].setdefault(point["knowledge_point_id"], {})
            count = self._mooc_coverage_count(job, point, state)
            target = self.settings.mooc_target_courses_per_point
            row.update(accepted_count=count, target=target, remaining=max(0, target-count))
            if count >= target:
                row["stopped_reason"] = "coverage_target_met"

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

    def create(self, request: SearchRequest, idempotency_key: str | None = None, *, consumer_key: str | None = None,
               defer_platform_followups: bool = False) -> dict:
        consumer_key = consumer_key or "manual"
        if len(request.knowledge_points) > self.settings.max_knowledge_points:
            raise ValueError("知识点数量超过当前服务预算")
        if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", idempotency_key):
            raise ValueError("幂等键格式无效")
        normalized = request.model_dump()
        for optional_target in ("learning_targets", "learning_skills", "topic_technologies"):
            if not normalized.get(optional_target):
                normalized.pop(optional_target, None)
        for field in ("project_context", "technical_version"):
            normalized[field] = " ".join(normalized[field].split())
        # Preserve meaningful point/platform scheduling order, but ignore repeats.
        normalized["preferred_platforms"] = list(dict.fromkeys(normalized["preferred_platforms"]))
        try:
            search_plan = platform_budget(self.settings, len(request.knowledge_points), request.preferred_platforms)
        except ValueError as exc:
            raise AdmissionRejected("search_budget_insufficient", str(exc), status=422) from None
        discovery_policy = self._mooc_discovery_policy(request)
        identity = {"request": normalized,
            "policy": search_plan["policy"], "defer_followups": defer_platform_followups,
            **({"platform_rounds": search_plan["platform_rounds"]}
               if search_plan["policy"] != "platform-rounds-v1" else {})} if search_plan else normalized
        if discovery_policy:
            identity = {**identity, "discovery_policy": discovery_policy}
        if search_plan and search_plan.get("followup_point_indexes") is not None:
            identity = {**identity, "followup_point_indexes": search_plan["followup_point_indexes"]}
        failover_policy = ({"provider": self.settings.searxng_failover_provider, "version": 1,
                            "cooldown_seconds": 300, "scope": "parallel-platform-slots"}
                           if search_plan and self.settings.searxng_failover_provider else None)
        if failover_policy:
            identity = {**identity, "source_failover_policy": failover_policy}
        request_hash = self.store.cache_key("request", identity)
        if idempotency_key:
            prior = self.store.idempotent_request(idempotency_key)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise IdempotencyConflict()
                existing = self.store.get_job(prior["job_id"])
                self.store.add_job_consumer(existing["job_id"], consumer_key)
                return {"job_id": existing["job_id"], "status": existing["status"], "reused": True}
        existing = self.store.active_job_for_request(normalized)
        if existing:
            prior_plan = existing.get("platform_search")
            prior_rounds = (prior_plan.get("platform_rounds") or
                           {platform: 2 for platform in prior_plan["platforms"]}) if prior_plan else None
            requested_rounds = search_plan["platform_rounds"] if search_plan else None
            # Equal request text is not an equal search plan after an operator
            # changes per-source limits. Old persisted v1 plans mean two rounds.
            if (prior_rounds != requested_rounds or existing.get("discovery_policy") != discovery_policy
                    or (prior_plan or {}).get("followup_point_indexes") != (search_plan or {}).get("followup_point_indexes")
                    or existing.get("source_failover_policy") != failover_policy):
                existing = None
        # Project initial passes must reach their own cross-batch barrier.
        # Idempotency still reuses this exact batch; unrelated consumers cannot
        # start its followups before that project's remaining initial passes.
        if search_plan and (defer_platform_followups or (existing or {}).get("platform_search", {}).get("defer_followups")):
            existing = None
        if existing and existing["job_id"] in self.cancel_requested:
            existing = None
        if existing:
            if idempotency_key:
                self.store.bind_idempotency_key(idempotency_key, request_hash, existing["job_id"])
            self.store.add_job_consumer(existing["job_id"], consumer_key)
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
               "request": normalized, "knowledge_points": [{"knowledge_point_id": str(uuid4()), "text": text,
                   **({"learning_targets": list(request.learning_targets[text])} if request.learning_targets.get(text) else {}),
                   **({"learning_skills": list(request.learning_skills[text])} if request.learning_skills.get(text) else {}),
                   **({"technology": request.topic_technologies[text]} if request.topic_technologies.get(text) else {})}
                   for text in request.knowledge_points],
               "progress": {"queries_planned": 0, "queries_completed": 0, "search_requests": 0, "search_successes": 0,
                            "search_failures": 0, "candidates_discovered": 0, "resources_discovered": 0,
                            "details_attempted": 0, "details_completed": 0, "details_cached": 0, "cache_hits": 0,
                            "catalog_pages_attempted": 0, "catalog_pages_completed": 0},
               "budgets": {"max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                           "deadline_seconds": self.settings.deadline_seconds}, "warnings": [], "errors": []}
        if search_plan:
            job["platform_search"] = {**search_plan, "defer_followups": defer_platform_followups}
            if search_plan.get("budget_limited"):
                job["budget_limited"] = True
                job["warnings"].append("已预留所有知识点和来源的首轮；后续补搜按现有总预算公平轮转，未增加请求额度。")
            job["budgets"].update({key: value for key, value in search_plan.items() if key != "policy"})
        if discovery_policy:
            job["discovery_policy"] = discovery_policy
        if failover_policy:
            job["source_failover_policy"] = failover_policy
        if request.learning_skills and self.settings.teaching_match_enabled:
            job["progress"].update(teaching_match_calls=0, teaching_pairs_evaluated=0, teaching_cache_hits=0,
                teaching_review_calls=0, teaching_claims_reviewed=0, teaching_claims_accepted=0,
                teaching_pair_validation_failures=0)
            job["budgets"].update(teaching_match_max_calls=self.settings.teaching_match_max_calls_per_job,
                teaching_match_max_pairs=20, teaching_match_max_pairs_per_point=4,
                teaching_match_call_timeout_seconds=teaching_match.DEADLINE_SECONDS,
                teaching_match_reserved_seconds=min(self.settings.teaching_match_max_calls_per_job * teaching_match.DEADLINE_SECONDS
                                                    + (teaching_review.DEADLINE_SECONDS if self.settings.teaching_match_max_calls_per_job else 0),
                                                    self.settings.deadline_seconds / 4) if self.llm else 0,
                teaching_match_output_token_limit=min(self.settings.llm_max_output_tokens, 3000))
            job["budgets"].update(teaching_review_max_calls=1 if self.settings.teaching_match_max_calls_per_job else 0,
                teaching_review_timeout_seconds=teaching_review.DEADLINE_SECONDS,
                teaching_review_output_token_limit=min(self.settings.llm_max_output_tokens, 1500),
                teaching_total_model_max_calls=self.settings.teaching_match_max_calls_per_job + (1 if self.settings.teaching_match_max_calls_per_job else 0))
        self.store.create_job(job, idempotency_key, request_hash, consumer_key=consumer_key)
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
        sources = {name: {"source_cooldown_seconds": max(0, round(getattr(source, "paused_until", 0) - current, 3)),
            "source_access_denied": bool(getattr(source, "access_denied", False)),
            "engine_cooldowns": {engine: round(until - current, 3)
                for engine, until in getattr(source, "engine_pauses", {}).items() if until > current}}
            for name, source in self._source_objects().items()}
        return {"status": "ok" if alive and database_ok and self.accepting else "degraded", "mode": "live", "single_worker": True,
                "worker_alive": alive, "database_ok": database_ok, "accepting": self.accepting,
                "queue_depth": counts.get("queued", 0), "queue_capacity": self.settings.max_pending_jobs,
                "oldest_queue_wait_seconds": round(wait, 3), "active_jobs": len(self.active_tasks),
                "job_counts": counts, "admission_rejections": self.admission_rejections,
                "recent_outcomes": list(self.recent_outcomes),
                "source_cooldown_seconds": max(0, round(getattr(provider, "paused_until", 0) - current, 3)),
                "source_access_denied": bool(getattr(provider, "access_denied", False)), "engine_cooldowns": cooldowns,
                "search_sources": sources}

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
        waited = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(job.get("queue_enqueued_at", job["created_at"]))).total_seconds())
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
        active_started = time.monotonic()
        spent = job.get("platform_search_active_seconds", 0) if job.get("platform_search") else 0
        ends_at = asyncio.get_running_loop().time() + max(0, job["budgets"]["deadline_seconds"] - spent)
        parent_deadline = FETCH_DEADLINE_AT.get()
        deadline_token = FETCH_DEADLINE_AT.set(min(ends_at, parent_deadline) if parent_deadline is not None else ends_at)
        try:
            await self._run_job(job)
        finally:
            if job.get("platform_search"):
                job["platform_search_active_seconds"] = spent + time.monotonic() - active_started
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
        if job.get("platform_search", {}).get("budget_limited"):
            job["budget_limited"] = True
        job.update(status="running", phase="expanding")
        self._save(job)
        try:
            async with asyncio.timeout_at(FETCH_DEADLINE_AT.get()):
                await self._execute(job)
            progress = job["progress"]
            if (progress["search_successes"] == 0 and progress["search_failures"] and not progress.get("library_hit_pairs")
                    and not job.get("ai_video_fallback", {}).get("covered_points")
                    and not job.get("grounded_related", {}).get("accepted")):
                job["status"] = "failed"
            elif progress["search_failures"] or job.pop("budget_limited", False) or job.pop("upstream_partial", False):
                job["status"] = "partial"
            else:
                job["status"] = "completed"
        except TimeoutError:
            if job.get("platform_search"):
                job["platform_search"].update(followup_pending=False, finished=True, stopped_reason="job_deadline")
            job["status"] = "partial" if (job["progress"]["search_successes"] or job["progress"].get("library_hit_pairs")
                or job.get("ai_video_fallback", {}).get("covered_points")
                or job.get("grounded_related", {}).get("accepted")) else "failed"
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
            if job.get("platform_search"):
                job["platform_search"].update(followup_pending=False, finished=True, stopped_reason="processing_error")
            job["status"] = "partial" if (job["progress"]["search_successes"] or job["progress"].get("library_hit_pairs")
                or job.get("ai_video_fallback", {}).get("covered_points")
                or job.get("grounded_related", {}).get("accepted")) else "failed"
            job["errors"].append({"code": "internal_error", "message": "任务处理异常，已保留可用证据；请检查服务端运行条件"})
        job.pop("budget_limited", None)
        job.pop("upstream_partial", None)
        job["phase"] = "awaiting_followup" if (job.get("platform_search", {}).get("followup_pending")
            and job["status"] not in {"cancelled", "interrupted"}) else "done"
        self._save(job)

    def resume_platform_search(self, job_id: str, *, consumer_key: str):
        job = self.store.get_job(job_id)
        plan = (job or {}).get("platform_search", {})
        if not (job and plan.get("initial_done") and plan.get("followup_pending")):
            return False
        if job["status"] in {"queued", "running", "cancelled", "interrupted"}:
            return False
        owner = self.store.connection.execute("SELECT 1 FROM job_consumers WHERE job_id=? AND consumer_key=?",
                                              (job_id, consumer_key)).fetchone()
        if not owner:
            raise ValueError("该项目未持有此检索任务")
        if job.get("platform_search_active_seconds", 0) >= job["budgets"]["deadline_seconds"]:
            plan.update(followup_pending=False, finished=True, stopped_reason="job_deadline")
            job.update(phase="done", status="partial")
            self._save(job)
            return False
        if not self.accepting or (self.worker is not None and self.worker.done()):
            raise AdmissionRejected("worker_unavailable", "补充检索工作进程不可用，首轮结果已保留", status=503)
        if self.queue.full():
            raise AdmissionRejected("queue_full", "补充检索队列暂不可用，首轮结果已保留", retry_after=5)
        job.update(status="queued", phase="queued", queue_enqueued_at=now())
        plan["defer_followups"] = False
        self._save(job)
        self.queue.put_nowait(job_id)
        return True

    async def _execute(self, job):
        request = SearchRequest.model_validate(job["request"])
        if self.settings.search_provider == "official_sitemap":
            self._warn(job, "本次仅使用 MIT 官方声明的站点地图；URL 路径词仅用于低置信召回，课程与知识点覆盖须由实际页面确认，其他平台不在本次来源范围")
        points = job["knowledge_points"]
        queries = []
        for point in ([] if job.get("platform_search") else points):
            if self.settings.search_provider == "official_sitemap":
                queries.append([Query(knowledge_point_id=point["knowledge_point_id"], query=point["text"])])
                continue
            expansions = []
            if self.llm and not point.get("learning_skills"):
                try:
                    expansions = await self.llm.expand(point["text"], request.project_context)
                    self.llm_status = "available"
                except Exception:
                    self.llm_status = "fault"
                    self._warn(job, "模型查询扩展失败，已回退到原始知识点和规则模板")
            queries.append(prioritize_video_entry_query(generate_queries(point["knowledge_point_id"], point["text"], request, expansions,
                open_course_domains=self.settings.open_course_domains)))
        schedule = fair_queries(queries)
        job["progress"]["queries_planned"] = job["platform_search"]["max_search_requests"] if job.get("platform_search") else len(schedule)
        job["phase"] = "searching"
        self._save(job)
        point_map = {p["knowledge_point_id"]: p for p in points}
        resources = self.store.resources(job["job_id"]) if job.get("platform_search", {}).get("initial_done") else {}
        candidates = {}
        candidate_groups = {p["knowledge_point_id"]: [] for p in points}
        if resources:
            for rid in resources:
                for evidence in self.store.evidence(job["job_id"], rid):
                    pid = evidence.get("knowledge_point_id")
                    if evidence.get("kind") in {"search", "course_library"} and pid in candidate_groups and rid not in candidate_groups[pid]:
                        candidate_groups[pid].append(rid)
                    if evidence.get("kind") == "search" and rid not in candidates:
                        # Resume with the original retained search observation;
                        # a deferred detail fetch must not lose its source input.
                        candidates[rid] = Candidate(id=evidence.get("candidate_id") or rid,
                            title=evidence.get("title") or resources[rid]["title"],
                            url=evidence["url"], snippet=evidence.get("snippet") or "",
                            source=evidence.get("source") or "unknown", query=evidence.get("query") or "",
                            discovered_at=evidence.get("observed_at") or resources[rid]["discovered_at"],
                            resource_type_hint=evidence.get("resource_type_hint", "unknown"),
                            source_engines=evidence.get("source_engines", []), type_source=evidence.get("type_source"),
                            discovery_evidence=evidence.get("discovery_evidence"), thumbnail_url=evidence.get("thumbnail_url"),
                            thumbnail_source=evidence.get("thumbnail_source")).model_dump()

        state = {"request": request, "points": points, "point_map": point_map, "resources": resources,
                 "candidates": candidates, "candidate_groups": candidate_groups, "ready": False,
                 "search_finished": False, "changed": asyncio.Event(),
                 "started": {rid for rid, resource in resources.items() if resource.get("fetch_status") != "not_fetched"},
                 "reserved": job["progress"]["details_attempted"] + job["progress"].get("catalog_pages_attempted", 0),
                 "cursor": 0, "network_slots": asyncio.Semaphore(self.settings.global_concurrency)}
        self._seed_course_library(job, state)
        self._seed_public_library(job, state)
        fallback_reserve = reserve_fallback(self, job, state)
        # Platform search signals readiness as soon as candidates are persisted;
        # details can verify and publish courses while the first round continues.
        reserve = (min(self.settings.teaching_match_max_calls_per_job * teaching_match.DEADLINE_SECONDS
                       + (teaching_review.DEADLINE_SECONDS if self.settings.teaching_match_max_calls_per_job else 0),
                       self.settings.deadline_seconds / 4) if request.learning_skills and self.llm and self.settings.teaching_match_enabled else 0)
        source_deadline = FETCH_DEADLINE_AT.get()
        try:
            async with asyncio.timeout_at(source_deadline - reserve - fallback_reserve if source_deadline is not None else None):
                async with asyncio.TaskGroup() as group:
                    group.create_task(self._run_details(job, state))
                    try:
                        if job.get("platform_search"):
                            await search_platform_rounds(self, job, state)
                        else:
                            await self._search_queries(job, schedule, state)
                    finally:
                        state["search_finished"] = True
                        state["ready"] = True
                        state["changed"].set()
                        job["phase"] = "fetching"
                        self._save(job)
        except TimeoutError:
            if not (reserve or fallback_reserve):
                raise
            job["budget_limited"] = True
            self._warn(job, "来源检索已到达预留时限，已保留当前资料并继续核对视频；可调整目标后重试。")
            plan = job.get("platform_search")
            if plan and not (plan.get("defer_followups") and plan.get("initial_done") and plan.get("followup_pending")):
                # A timed-out active round is not the project's intentional
                # first-pass barrier. Spend the reserve on remaining gaps now.
                plan.update(followup_pending=False, finished=True, stopped_reason="source_deadline")
        if not job.get("platform_search", {}).get("followup_pending"):
            try:
                async with asyncio.timeout_at(source_deadline - reserve if source_deadline is not None else None):
                    await run_ai_video_fallback(self, job, state, effective_deadline=source_deadline - reserve if source_deadline is not None else None)
            except TimeoutError:
                job["budget_limited"] = True
            finally:
                state["detail_limit"] = self.settings.max_detail_pages
        self._refresh_gap_coverage(job, state)
        limited = [r for r in resources.values() if r.get("metadata_evidence_level") == "search"
                   and any(row.get("kind") == "search" for row in self.store.evidence(job["job_id"], r["resource_id"]))]
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
        if job.get("platform_search", {}).get("followup_pending"):
            return
        if request.learning_skills and self.settings.teaching_match_enabled:
            await self._match_learning_skills(job, resources)
        if self.llm and self.settings.teaching_match_enabled:
            await self._rerank(job, resources)

    async def _match_learning_skills(self, job, resources):
        """Bounded mutation phase. Reading results never makes model calls.

        Search text only schedules source inspections. Every accepted decision
        is rebound to this job's own current page, media and exact skill list.
        """
        request = SearchRequest.model_validate(job["request"])
        points = [point for point in job["knowledge_points"] if point.get("learning_skills")]
        if not points:
            return
        for counter in ("teaching_match_calls", "teaching_pairs_evaluated", "teaching_cache_hits",
                        "teaching_review_calls", "teaching_claims_reviewed", "teaching_claims_accepted",
                        "teaching_pair_validation_failures"):
            job["progress"].setdefault(counter, 0)
        cap = self.settings.teaching_match_max_calls_per_job
        configured = (self.settings.llm_provider == "openai_compatible" and self.settings.llm_api_key.strip()
                      and self.settings.llm_model.strip() and self.settings.llm_base_url.strip())
        if not cap or not configured:
            self._warn(job, "技能语义匹配未启用；仅保留当前来源可逐字核对的技能主题，空结果可调整技能或到平台检索。")
            return
        queues = []
        pair_context = {}
        for point in points:
            candidates = []
            for rid, resource in resources.items():
                observed = self._teaching_evidence(self.store.evidence(job["job_id"], rid, point["knowledge_point_id"]))
                pair = teaching_match.prepare_pair(point, resource, observed, request.student_level)
                if pair is None:
                    continue
                # Own metadata can be reused across units in this job. A search
                # title from another point is never part of the judgment.
                body = " ".join(segment for row in pair["observations"] for segment in row["segments"])
                scores = [relevance(skill, body) for skill in point["learning_skills"]]
                candidates.append((max(scores, default=0), rid, pair, observed, scores))
            # Own literal APIs allocate inspection slots before broad lexical
            # families, without changing any judgment/claim or call budget.
            selected = _select_learning_candidates(candidates, point["learning_skills"], point.get("learning_targets", []))
            queue = []
            for _, rid, pair, observed, _ in selected:
                queue.append(pair)
                pair_context[pair["pair_id"]] = (point, resources[rid], observed)
            queues.append(queue)
        ordered = [queue[index] for index in range(4) for queue in queues if len(queue) > index][:20]
        pending = []
        def apply(pair, decision):
            point, resource, observed = pair_context[pair["pair_id"]]
            verified = teaching_review.validate_reviewed(point, resource, observed, decision, request.student_level)
            if verified is None:
                return False
            job.setdefault("teaching_decisions", {}).setdefault(point["knowledge_point_id"], {})[resource["resource_id"]] = decision
            match = rank_resource({**point, "_teaching_decision": decision}, resource, observed, request,
                eligibility_evidence=self.store.evidence(job["job_id"], resource["resource_id"]))
            if match:
                self.store.save_match(job["job_id"], {**match, "_teaching_decision": decision})
            else:
                self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])
            return True
        for pair in ordered:
            key = self.store.cache_key("teaching_decision-v2-reviewed", {"fingerprint": pair["fingerprint"]})
            cached = self.store.cache_get(key, allow_stale=False)
            if cached and apply(pair, cached["data"]):
                job["progress"]["teaching_cache_hits"] += 1
            else:
                pending.append(pair)
        calls = 0
        fresh_pairs, fresh_decisions = [], {}
        remaining_calls = max(0, cap - job["progress"]["teaching_match_calls"])
        while pending and calls < remaining_calls:
            batch, size = [], 0
            while pending and len(batch) < teaching_match.MAX_PAIRS:
                cost = len(json.dumps(pending[0]["payload"], ensure_ascii=False, separators=(",", ":")))
                if batch and size + cost > 30_000:
                    break
                pair = pending.pop(0)
                if cost > 30_000:
                    continue
                batch.append(pair)
                size += cost
            if not batch:
                break
            calls += 1
            job["progress"]["teaching_match_calls"] += 1
            job["progress"]["teaching_pairs_evaluated"] += len(batch)
            # An attempted model pair must stay unknown on failure/cancellation.
            # Persist a non-cacheable sentinel before awaiting upstream; GET
            # must not mistake its missing decision for a literal fallback.
            for pair in batch:
                point, resource, _ = pair_context[pair["pair_id"]]
                job.setdefault("teaching_decisions", {}).setdefault(point["knowledge_point_id"], {})[resource["resource_id"]] = {}
            self._save(job)
            try:
                decisions = await teaching_match.judge_batch(self.settings, batch)
            except Exception:
                # A plugin/test transport failure cannot discard completed
                # search work or disclose its raw error. Cancellation propagates.
                decisions = {}
            if not decisions:
                self.llm_status = "fault"
                job["upstream_partial"] = True
                self._warn(job, "部分技能匹配未返回可核对结论，已保留原始来源；可到平台核对或稍后重试。")
                continue
            self.llm_status = "available"
            invalid_pairs = 0
            for pair in batch:
                decision = decisions.get(pair["pair_id"])
                point, resource, observed = pair_context[pair["pair_id"]]
                verified = teaching_match.validate_decision(point, resource, observed, decision, request.student_level) if decision is not None else None
                if verified is not None:
                    fresh_pairs.append(pair)
                    fresh_decisions[pair["pair_id"]] = verified
                else:
                    invalid_pairs += 1
            if invalid_pairs:
                job["progress"]["teaching_pair_validation_failures"] += invalid_pairs
                job["upstream_partial"] = True
                self._warn(job, "部分候选的技能声明未通过来源绑定校验，保持未知；其他有效声明继续独立复核。")
            self._save(job)
        claims, mapping = teaching_review.prepare_claims(fresh_pairs, fresh_decisions)
        if len(claims) < sum(len(decision["supports"]) for decision in fresh_decisions.values()):
            job["budget_limited"] = True
            self._warn(job, "内容复核达到载荷上限，未核对的声明保持未知；可缩小单元后重试。")
        report, review_failed = {}, False
        if claims:
            if job["progress"]["teaching_review_calls"] >= 1:
                review_failed = True
            else:
                job["progress"]["teaching_review_calls"] += 1
                job["progress"]["teaching_claims_reviewed"] += len(claims)
                self._save(job)
                try:
                    report = await teaching_review.review_batch(self.settings, claims)
                except Exception:
                    report = None
                review_failed = report is None
                self.llm_status = "fault" if review_failed else "available"
            if review_failed:
                report = {}
                job["upstream_partial"] = True
                self._warn(job, "技能内容复核未完成，未确认的模型声明保持未知；来源已保留，可稍后重试。")
        reviewed = teaching_review.reviewed_decisions(fresh_pairs, fresh_decisions, mapping, report)
        for pair in fresh_pairs:
            decision = reviewed.get(pair["pair_id"])
            if decision is not None and apply(pair, decision):
                job["progress"]["teaching_claims_accepted"] += len(decision["supports"])
                # A failed audit never becomes a cached successful negative.
                if not review_failed:
                    key = self.store.cache_key("teaching_decision-v2-reviewed", {"fingerprint": pair["fingerprint"]})
                    self.store.cache_set(key, "teaching_decision", decision, 3600)
        if pending:
            job["budget_limited"] = True
            self._warn(job, "本次技能匹配已到达预算，仅核对优先候选；未核对的来源不计作已证实技能。")
        self._save(job)

    async def _search_queries(self, job, schedule, state):
        request, points = state["request"], state["points"]
        point_map, resources = state["point_map"], state["resources"]
        candidates, candidate_groups = state["candidates"], state["candidate_groups"]
        # Reserve complete fair rounds; a fractional optional round must not
        # weaken the guarantee that each point gets its first primary request.
        # A requested direct-video source needs room for an independent allowed
        # fallback when its primary engine times out. Two one-request rounds can
        # otherwise spend the entire budget on empty primary observations. Keep
        # all points' first slices reserved; do not raise the global budget.
        targeted_video_first = bool(schedule and schedule[0].domain_filters == ["bilibili.com"])
        tight_public_budget = bool(self.public_catalog and self.settings.max_search_requests < 4 * len(points))
        public_round = 1 if tight_public_budget else 2
        public_reserve = 0
        learning_public_round = bool(self.public_catalog and any(point.get("learning_skills") for point in points))
        if tight_public_budget or learning_public_round:
            sources = {"twt" if self.twt_catalog and re.match(r"^pygame\s", point["text"], re.I)
                       and self.twt_catalog.supports(point["text"]) else "fcc" for point in points}
            # One robots plus the declared directory cap per distinct source.
            # Keep every unit's first primary request, within the same budget.
            public_reserve = min(sum(4 if source == "twt" else 3 for source in sources),
                                 max(0, self.settings.max_search_requests - len(points)))
        requests_per_round = 2 if targeted_video_first else 1
        priority_rounds = 2 if self.settings.max_search_requests >= 2 * requests_per_round * len(points) else 1
        priority_query_count = min(len(schedule), priority_rounds * len(points))
        learning_round_sizes = {}
        if learning_public_round:
            # Retain each original primary skill query. Insert a complete public
            # frame, with actual frame boundaries even for mixed/unequal lists.
            per_point = {point["knowledge_point_id"]: [query for query in schedule
                         if query.knowledge_point_id == point["knowledge_point_id"]] for point in points}
            frames = [[per_point[point["knowledge_point_id"]][index] for point in points
                       if index < len(per_point[point["knowledge_point_id"]])]
                      for index in range(max(map(len, per_point.values()), default=0))]
            if self.settings.max_search_requests - public_reserve < sum(map(len, frames[:priority_rounds])):
                priority_rounds = 1
            priority_query_count = sum(map(len, frames[:priority_rounds]))
            insert_at = min(max(public_round, priority_rounds), len(frames))
            public_frame = []
            for point in points:
                skills = point.get("learning_skills") or []
                source_target = skills[min(insert_at, len(skills) - 1)] if skills else point["text"]
                use_twt = bool(self.twt_catalog and re.match(r"^pygame\s", point["text"], re.I)
                               and self.twt_catalog.supports(point["text"]))
                public_frame.append(Query(knowledge_point_id=point["knowledge_point_id"],
                    query=public_catalog_query(source_target),
                    domain_filters=["www.techwithtim.net" if use_twt else "www.freecodecamp.org"]))
            # Inspect one declared source family before repeating that family.
            # This protects the distinct cold-source reserve; it does not add
            # requests or promise every different tag fits the global budget.
            source_frames = {}
            for query in public_frame:
                source_frames.setdefault(tuple(query.domain_filters), []).append(query)
            public_frame = [frame[index] for index in range(max(map(len, source_frames.values()), default=0))
                            for frame in source_frames.values() if index < len(frame)]
            frames.insert(insert_at, public_frame)
            schedule[:] = []
            for frame in frames:
                learning_round_sizes[len(schedule)] = len(frame)
                schedule.extend(frame)
            state.setdefault("public_catalog_scheduled", set()).update(point["knowledge_point_id"] for point in points)
            job["progress"]["queries_planned"] = len(schedule)
            self._save(job)
        query_request_limit = None
        query_request_start = 0
        async def check_request_budget():
            # The global limit always wins. A priority-query slice only defers
            # optional backup/retry/discovery work to protect other points.
            if job["progress"]["search_requests"] >= state.get("search_limit", self.settings.max_search_requests):
                raise BudgetReached()
            if (query_request_limit is not None
                    and job["progress"]["search_requests"] - query_request_start >= query_request_limit):
                raise QueryBudgetReached()
        async def count_request():
            await check_request_budget()
            job["progress"]["search_requests"] += 1
            self._save(job)
        async def count_discovery_dns():
            current = job["progress"].get("discovery_dns_requests", 0)
            if current >= 2 * self.settings.max_search_requests:
                raise BudgetReached()
            job["progress"]["discovery_dns_requests"] = current + 1
            self._save(job)
        for provider in self._source_objects().values():
            if provider and hasattr(provider, "request_hook"):
                provider.request_hook = count_request
        for provider in (*self._source_objects().values(), self.official_fallback, self.public_catalog, self.twt_catalog):
            if provider and getattr(provider, "name", None) in {"official_sitemap", "public_catalog", "techwithtim_catalog"}:
                provider.dns_request_hook = count_discovery_dns
                provider.budget_check_hook = check_request_budget
                provider.request_hook = count_request

        for query_index, query in enumerate(schedule):
            if query_index > 0 and (query_index in learning_round_sizes if learning_public_round else query_index % len(points) == 0):
                # At each complete fair-round boundary, spend the next round
                # on observed coverage gaps before repeating a fully
                # supported unit. The original full point remains the matching
                # target. Narrow query text cannot upgrade its missing skills.
                round_size = learning_round_sizes.get(query_index, len(points))
                next_round = schedule[query_index:query_index + round_size]
                prioritized = []
                for next_query in next_round:
                    point = point_map[next_query.knowledge_point_id]
                    # Reviewed transferable skills already have their own fair
                    # query schedule. Exact project checks must not replace it.
                    dedicated_public = learning_public_round and self._public_provider(next_query) is not None
                    plan = ({"subtopics": []} if point.get("learning_skills") or dedicated_public else
                            coverage_targets(point["text"], point["learning_targets"])
                            if point.get("learning_targets") else decompose_topic(point["text"]))
                    covered, complete = set(), False
                    for rid, resource in resources.items():
                        observed = self.store.evidence(job["job_id"], rid, point["knowledge_point_id"])
                        if not any(row.get("kind") == "search" and row.get("knowledge_point_id") == point["knowledge_point_id"] for row in observed):
                            continue
                        match = rank_resource(point, resource, self._teaching_evidence(observed), request)
                        if not match:
                            continue
                        complete = complete or match.get("topic_evidence_status") == "supported"
                        covered.update(row["id"] for row in match.get("subtopic_coverage", []) if row["status"] == "supported")
                    gap_selection = None
                    missing = sorted((part for part in plan["subtopics"] if part["id"] not in covered),
                        key=lambda part: not part["id"].startswith("learning_target_"))
                    if plan["subtopics"] and not missing:
                        complete = True
                    if missing:
                        # A wholly uncovered unit needs discovery just as much as
                        # a partial one. Search each missing skill separately;
                        # do not require an initial hit before permitting a
                        # bounded catalog probe. Query words remain recall only.
                        pid = point["knowledge_point_id"]
                        seen = state.setdefault("gap_query_keys", {}).setdefault(pid, set())
                        for gap_query in gap_query_candidates(pid, point["text"], request,
                                [part["text"] for part in missing], open_course_domains=self.settings.open_course_domains):
                            key = (gap_query.query, tuple(gap_query.domain_filters))
                            if key not in seen:
                                next_query = gap_query
                                gap_selection = (key, gap_query)
                                break
                    # A public directory gets its own fair query slice, instead
                    # of an unreachable extra request after every search-engine
                    # backup has consumed the budget. It never runs after a
                    # primary access-denied stop, and never changes the target.
                    if (not learning_public_round and self.public_catalog and not complete and query_index >= public_round * len(points)
                            and point["knowledge_point_id"] not in state.setdefault("public_catalog_scheduled", set())):
                        use_twt = bool(self.twt_catalog and re.match(r"^pygame\s", point["text"], re.I)
                                       and self.twt_catalog.supports(point["text"]))
                        next_query = Query(knowledge_point_id=point["knowledge_point_id"], query=public_catalog_query(point["text"]),
                                           domain_filters=["www.techwithtim.net" if use_twt else "www.freecodecamp.org"])
                        state["public_catalog_scheduled"].add(point["knowledge_point_id"])
                        gap_selection = None
                    if gap_selection is not None:
                        key, chosen_gap = gap_selection
                        state.setdefault("planned_gap_queries", set()).add((pid, chosen_gap.query, tuple(chosen_gap.domain_filters)))
                    prioritized.append((complete, next_query))
                schedule[query_index:query_index + round_size] = [entry[1] for entry in sorted(prioritized, key=lambda entry: entry[0])]
                query = schedule[query_index]
            budget_stopped = False
            query_request_start = job["progress"]["search_requests"]
            query_request_limit = (max(1, (self.settings.max_search_requests - public_reserve - query_request_start)
                // (priority_query_count - query_index)) if query_index < priority_query_count else None)
            provider_name, provider, provider_error = self._search_source(query)
            cache_key = self.store.cache_key("search", {**self._search_identity(provider_name),
                "original_point": point_map[query.knowledge_point_id]["text"],
                "official_sitemap": {"enabled": self.settings.official_sitemap_fallback, "version": 1,
                    "source_identity": "https://ocw.mit.edu/search/|robots-declared-sitemaps-v1",
                    "children": self.settings.official_sitemap_children_per_query,
                    "ttl": self.settings.official_sitemap_cache_ttl, "search_ttl": self.settings.search_cache_ttl,
                    "original_point": point_map[query.knowledge_point_id]["text"] if provider_name == "official_sitemap" or self.official_fallback else None,
                    "dns": self.settings.dns_resolver, "fetch": self.settings.fetch_enabled,
                    "denied": self.settings.denied_fetch_hosts, "allowed": self.settings.allowed_restricted_hosts},
                "query": query.query, "language": request.language, "version": request.technical_version,
                "domains": query.domain_filters, "limit": self.settings.search_results_per_query})
            # An outer query cache must not extend the remaining lifetime of an
            # older index snapshot. Official discovery reuses its own source TTLs.
            public_provider = self._public_provider(query)
            public_query = public_provider is not None
            if public_query:
                provider_name, provider, provider_error = public_provider.name, public_provider, None
            query_cache_enabled = not (provider_name == "official_sitemap" or self.official_fallback or public_query)
            cached = self.store.cache_get(cache_key) if query_cache_enabled else None
            network_attempted = False
            cache_info = {"hit": False, "cached_at": None, "stale": False}
            attempt = {"knowledge_point_id": query.knowledge_point_id, "query": query.query, "domain_filters": query.domain_filters,
                       "provider": provider_name, "status": "completed", "candidate_count": 0,
                       "cache_hit": False, "cached_at": None, "stale": False, "error_code": None, "executed_at": now(),
                       "priority_request_limit": query_request_limit,
                       "priority_query_count": priority_query_count}
            try:
                if cached:
                    cached_candidates = cached["data"].get("candidates", []) if isinstance(cached["data"], dict) else cached["data"]
                    items = [Candidate.model_validate(c) for c in cached_candidates]
                    cache_info = cached["cache"]
                else:
                    if provider_error:
                        raise provider_error
                    if not hasattr(provider, "request_hook"):
                        await count_request()
                    async with state["network_slots"]:
                        network_attempted = True
                        items = await self._discover(query, request, point_map[query.knowledge_point_id]["text"])
                    items = [c if isinstance(c, Candidate) else Candidate.model_validate(c) for c in items]
                    # Preserve upstream failures alongside results in the cache and execution record.
                    if query_cache_enabled:
                        self.store.cache_set(cache_key, "search", {"candidates": [c.model_dump() for c in items],
                            "upstream_warnings": getattr(provider, "last_warnings", []),
                            "provider_requests": getattr(provider, "last_requests", []),
                            "provider_dns_requests": getattr(provider, "last_dns_requests", []),
                            "discovery": self._discovery_trace(provider)}, self.settings.search_cache_ttl)
                job["progress"]["search_successes"] += 1
            except QueryBudgetReached as exc:
                # Keep completed observations, but continue the fair schedule.
                # This is deliberately distinct from exhausting the job limit.
                job["budget_limited"] = True
                self._warn(job, "按剩余请求额度为各知识点的优先轮次预留机会；部分备用搜索或官方补充未执行，已保留返回候选并继续其他知识点")
                items = list(exc.partial_candidates)
                attempt.update(status="partial" if items else "query_budget_exhausted", error_code="query_budget_exhausted")
                requests = getattr(provider, "last_requests", [])
                engine_failed = any(row.get("code") == "upstream_engine_failed"
                                    for row in getattr(provider, "last_warnings", []))
                if not items and requests and engine_failed:
                    attempt.update(status="failed", error_code="upstream_engine_failed")
                    job["progress"]["search_failures"] += 1
                elif items or any(record.get("status") == "completed" and record.get("http_status") == 200 for record in requests):
                    job["progress"]["search_successes"] += 1
                elif requests:
                    job["progress"]["search_failures"] += 1
            except SearchBudgetReached as exc:
                job["budget_limited"] = True
                self._warn(job, "达到搜索请求预算；按知识点轮转执行，剩余查询未执行")
                requests = getattr(provider, "last_requests", [])
                items = list(exc.partial_candidates)
                if items:
                    # Persist completed observations before honoring the stop.
                    # Partial queries never enter the successful-query cache.
                    budget_stopped = True
                    attempt.update(status="partial", error_code="budget_exhausted")
                    job["progress"]["search_successes"] += 1
                elif requests:
                    engine_failed = any(row.get("code") == "upstream_engine_failed"
                                        for row in getattr(provider, "last_warnings", []))
                    attempt.update(status="failed" if engine_failed else "budget_exhausted",
                        error_code="upstream_engine_failed" if engine_failed else "budget_exhausted", provider_requests=requests,
                        upstream_warnings=getattr(provider, "last_warnings", []),
                        provider_dns_requests=getattr(provider, "last_dns_requests", []),
                        discovery=self._discovery_trace(provider))
                    if engine_failed:
                        job["progress"]["search_failures"] += 1
                    self.store.add_attempt(job["job_id"], attempt)
                    job["progress"]["queries_completed"] += 1
                if not items:
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
                    network_attempted=bool(provider.last_requests) if isinstance(provider, HTTPProvider) and network_attempted else network_attempted,
                    provider_requests=getattr(provider, "last_requests", []) if network_attempted else [],
                    provider_dns_requests=getattr(provider, "last_dns_requests", []) if network_attempted else [],
                    upstream_warnings=getattr(provider, "last_warnings", []) if network_attempted else [])
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
            attempt["network_attempted"] = bool(provider.last_requests) if isinstance(provider, HTTPProvider) and network_attempted else network_attempted
            attempt["upstream_warnings"] = getattr(provider, "last_warnings", []) if network_attempted else []
            attempt["provider_requests"] = getattr(provider, "last_requests", []) if network_attempted else []
            attempt["provider_dns_requests"] = getattr(provider, "last_dns_requests", []) if network_attempted else []
            attempt["discovery"] = self._discovery_trace(provider) if network_attempted else {}
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
            gap_key = (query.knowledge_point_id, query.query, tuple(query.domain_filters))
            if (gap_key in state.get("planned_gap_queries", set())
                    and attempt["status"] != "query_budget_exhausted"):
                state["planned_gap_queries"].discard(gap_key)
                state.setdefault("gap_query_keys", {}).setdefault(query.knowledge_point_id, set()).add((query.query, tuple(query.domain_filters)))
                state.setdefault("gap_queries", {})[query.knowledge_point_id] = query.query
                state.setdefault("gap_query_history", {}).setdefault(query.knowledge_point_id, set()).add(query.query)
            job["progress"]["queries_completed"] += 1
            job["progress"]["candidates_discovered"] += len(items)
            self._record_search_candidates(job, state, query, items, cache_info, public_query)
            job["progress"]["resources_discovered"] = len(resources)
            self._save(job)
            if query_index + 1 >= len(points):
                state["ready"] = True
            state["changed"].set()
            if budget_stopped:
                break
            if attempt["error_code"] == "configuration_error" and len(self._providers) == 1:
                break
            if attempt["error_code"] == "access_denied" and not public_query:
                if len(self._providers) == 1:
                    self._warn(job, "搜索服务拒绝访问，已停止剩余查询；保留此前结果及明确标注的缓存证据")
                    break
                self._warn(job, "搜索来源拒绝访问，已停止该来源的后续网络请求；保留其他来源及已有结果")
            if attempt["error_code"] == "quota_exhausted" and len(self._providers) == 1:
                break

    def _record_search_candidates(self, job, state, query, items, cache_info, public_query=False):
        request, points = state["request"], state["points"]
        resources, candidates = state["resources"], state["candidates"]
        candidate_groups = state["candidate_groups"]
        for candidate_index, candidate in enumerate(items):
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
                evidence["discovery_evidence"] = dict(candidate.discovery_evidence)
                if public_query and candidate.source in {"public_catalog", "techwithtim_catalog"} and candidate_index < 6:
                    # Queue order only. This rank is assigned by ingestion,
                    # scoped to this point's actual provider response.
                    evidence["discovery_evidence"]["admission_result_index"] = candidate_index
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
            # A library receipt binds public page facts. Search observations
            # remain separate and cannot mutate that verified snapshot.
            if (not resources[rid].get("course_library") and candidate.thumbnail_url
                    and candidate.thumbnail_source and not resources[rid].get("thumbnail_url")):
                resources[rid]["thumbnail_url"] = candidate.thumbnail_url
                resources[rid]["field_provenance"]["thumbnail_url"] = {
                    "evidence_id": eid, "source": candidate.thumbnail_source, "url": candidate.url,
                    "observed_at": candidate.discovered_at,
                    "note": "搜索结果提供的缩略图；未另行采集图片或核验播放"}
            if resources[rid].get("video_evidence_status", "none") == "none" and video_status == "search_discovered":
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

    def _public_provider(self, query):
        if query.domain_filters == ["www.freecodecamp.org"]:
            return self.public_catalog
        if query.domain_filters == ["www.techwithtim.net"]:
            return self.twt_catalog
        return None

    async def _discover(self, query, request, original_point):
        provider_name, provider, provider_error = self._search_source(query)
        public_provider = self._public_provider(query)
        if public_provider:
            try:
                recall_options = ({"learning_targets": request.learning_skills.get(original_point)
                                   or request.learning_targets.get(original_point, [])}
                                  if public_provider.name == "techwithtim_catalog" else {})
                return await public_provider.search(query.query, request.language, self.settings.search_results_per_query,
                    query.domain_filters, original_point=original_point, technical_version=request.technical_version, **recall_options)
            finally:
                # Preserve the existing attempt serializer while identifying the
                # independent provider explicitly in its request/source records.
                if self.provider:
                    self.provider.last_requests = public_provider.last_requests
                    self.provider.last_dns_requests = public_provider.last_dns_requests
                    self.provider.last_warnings = public_provider.last_warnings
                    self.provider.last_discovery = {public_provider.name: public_provider.last_discovery}
        if provider_error:
            raise provider_error
        if getattr(provider, "name", None) == "official_sitemap":
            return await provider.search(original_point, request.language, self.settings.search_results_per_query,
                query.domain_filters, technical_version=request.technical_version)
        provider.last_dns_requests, provider.last_discovery = [], {}
        options = {"candidate_check": lambda candidate: candidate_topic_signal(candidate, original_point, request)} if isinstance(provider, SearXNGProvider) else {}
        items = await provider.search(query.query, request.language, self.settings.search_results_per_query, query.domain_filters, **options)
        if not self.official_fallback or any(candidate_topic_signal(candidate, original_point, request) for candidate in items):
            return items
        # Normal empty or irrelevant responses can invoke this opt-in fallback. Domain-scoped
        # MOOC/Bilibili queries stay in that scope; access errors never enter here.
        try:
            extra = await self.official_fallback.search(original_point, request.language,
                self.settings.search_results_per_query, query.domain_filters, technical_version=request.technical_version)
            # Resource dedup happens downstream; retain each source observation.
            return [*items, *extra]
        except SearchBudgetReached as exc:
            # The primary response has already completed. Keep it even if the
            # opt-in official source has no remaining request/DNS allowance.
            exc.partial_candidates = [*items, *exc.partial_candidates]
            raise
        except SearchError as exc:
            # The primary completed normally with no results. An independent
            # optional source cannot revoke that outcome or stop later primary
            # queries. Its own provider retains its stop state and request trace.
            failure = {"code": "official_source_failed", "source": "official_sitemap",
                "reason_code": exc.code, "error_code": exc.code, "message": exc.message}
            self.official_fallback.last_status = "fault"
            provider.last_warnings = [*getattr(provider, "last_warnings", []), failure]
            self.official_fallback.last_discovery["failure"] = failure
            return items
        finally:
            provider.last_requests = [*getattr(provider, "last_requests", []), *self.official_fallback.last_requests]
            provider.last_dns_requests = self.official_fallback.last_dns_requests
            provider.last_discovery = self.official_fallback.last_discovery

    @staticmethod
    def _teaching_evidence(evidence):
        return [row for row in evidence if not (row.get("kind") == "search"
            and row.get("source") in {"official_sitemap", "public_catalog", "techwithtim_catalog"})]

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
        page_host = urlsplit(resource["canonical_url"]).hostname
        extractor_version = (15 if page_host == "www.freecodecamp.org" else
                             18 if page_host in {"www.techwithtim.net", "techwithtim.net"} else
                             15 if page_host in {"www.icourse163.org", "icourse163.org"} else
                             18 if page_host in {"www.bilibili.com", "bilibili.com"} else 13)
        key = self.store.cache_key("page", {"url": resource["canonical_url"], "extractor_version": extractor_version,
            **({"mooc_public_route_version": 2} if page_host in {"www.icourse163.org", "icourse163.org"} else {}),
            **({"bilibili_metadata_size_policy": {"version": 1,
                "max_bytes": self.settings.bilibili_public_metadata_max_bytes,
                "max_state_chars": 4_000_000}} if page_host in {"www.bilibili.com", "bilibili.com"} else {}),
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
            if point.get("technology"):
                from .professional_concepts import contextual_concept_name
                try:
                    point = {**point, "text": contextual_concept_name(point["text"], point["technology"])}
                except ValueError:
                    queues[point["knowledge_point_id"]] = []
                    continue
            entries = []
            mooc_entries = []
            public_priorities = {}
            probe_priorities = {}
            for rid in state["candidate_groups"][point["knowledge_point_id"]]:
                if rid in state["started"]:
                    continue
                resource = state["resources"][rid]
                evidence = self.store.evidence(job["job_id"], rid, point["knowledge_point_id"])
                provisional = None
                if is_mooc_resource(resource):
                    assessment = assess_mooc_relevance(point, resource, evidence)
                    if assessment["probe_eligible"] and (not self.settings.teaching_match_enabled
                            or teaching_probe_eligible(point, resource, evidence)):
                        mooc_entries.append((assessment["probe_priority"], rid))
                        continue
                    if (not self.settings.teaching_match_enabled or any(code in assessment["reason_codes"] for code in (
                            "unsupported_public_course_route", "missing_same_point_search_observation"))):
                        continue
                    # Keep existing genuinely supported atomic terms (including
                    # Chinese-only names). A new broad-course probe is additive;
                    # it is not a mandatory owner parser for old positive ranks.
                    provisional = rank_resource(point, resource, self._teaching_evidence(evidence), state["request"])
                    if not provisional:
                        continue
                else:
                    provisional = rank_resource(point, resource, self._teaching_evidence(evidence), state["request"], require_type=False)
                if provisional:
                    # Spend scarce metadata requests on already evidenced topic
                    # support before higher lexical-only discovery scores. This
                    # changes queue order, never admission or display standards.
                    available_ids = {entry["evidence_id"] for entry in evidence
                        if entry.get("evidence_id") and entry.get("kind") in {"search", "page", "catalog"}
                        and (entry.get("kind") != "search" or entry.get("knowledge_point_id") in {None, point["knowledge_point_id"]})}
                    supporting_ids = set(provisional.get("supporting_evidence_ids", []))
                    evidenced_topic = (provisional.get("topic_evidence_status") in {"supported", "partial"}
                        and bool(supporting_ids) and supporting_ids.issubset(available_ids))
                    entries.append((False, evidenced_topic, has_learning_evidence(resource, evidence), provisional["ranking_score"], rid))
                elif self._gap_catalog_probe(point, resource, evidence, state):
                    # An exact gap query may return a real video course whose
                    # broad search title cannot prove its individual lessons.
                    # Allow two catalog probes per point, ahead of repetitive
                    # known-subtopic enrichment. Query text itself never enters
                    # ranking evidence, and display still requires page facts.
                    state.setdefault("gap_probe_candidates", set()).add((point["knowledge_point_id"], rid))
                    probe_priorities[rid] = probe_api_priority(point, evidence,
                        owner=leading_technical_owner(point["text"]), owner_gate_passed=True)
                    entries.append((True, False, True, JobService._point_relevance(point, resource.get("title") or ""), rid))
                elif self._targeted_catalog_probe(point, resource, evidence, state):
                    # A long project-specific title may have no parseable
                    # conjunction. Probe at most two observed videos with the
                    # exact tool; only their own page facts can earn a match.
                    state.setdefault("gap_probe_candidates", set()).add((point["knowledge_point_id"], rid))
                    probe_priorities[rid] = probe_api_priority(point, evidence,
                        owner=leading_technical_owner(point["text"]), owner_gate_passed=True)
                    entries.append((True, False, True, JobService._point_relevance(point, resource.get("title") or ""), rid))
                elif self._public_catalog_probe(point, resource, evidence, state):
                    state.setdefault("public_probe_candidates", set()).add((point["knowledge_point_id"], rid))
                    public_priorities[rid] = self._public_catalog_probe_priority(point, resource, evidence)
                    entries.append((True, False, False, 1, rid))
                elif self._sitemap_only(evidence):
                    # A bounded real <loc> may be fetched to establish type/title;
                    # URL words alone never qualify it for result display.
                    entries.append((False, False, False, 1, rid))
            queues[point["knowledge_point_id"]] = [entry[4] for entry in sorted(entries, key=lambda item: (
                -item[0], -item[1], -item[2],
                -probe_priorities.get(item[4], (0, 0))[0], -probe_priorities.get(item[4], (0, 0))[1],
                -public_priorities.get(item[4], 0), -item[3], item[4]))]
            if mooc_entries:
                # Retain other platforms' relative order and total page budget.
                # Alternate with MOOC using actual starts, so rebuilding this
                # queue cannot repeatedly reset the preference to the first lane.
                existing = queues[point["knowledge_point_id"]]
                mooc = [rid for _, rid in sorted(mooc_entries, key=lambda item: (-item[0], item[1]))]
                starts = [state["resources"][rid] for rid in state["candidate_groups"][point["knowledge_point_id"]]
                          if rid in state["started"]]
                mooc_first = sum(is_mooc_resource(row) for row in starts) < sum(not is_mooc_resource(row) for row in starts)
                first, second = (mooc, existing) if mooc_first else (existing, mooc)
                queues[point["knowledge_point_id"]] = [rid for index in range(max(len(first), len(second)))
                    for lane in (first, second) if index < len(lane) for rid in [lane[index]]]
        return queues

    @staticmethod
    def _point_relevance(point, text):
        return max(relevance(skill, text) for skill in point.get("learning_skills") or [point["text"]])

    @staticmethod
    def _public_catalog_probe_priority(point, resource, evidence):
        """Preserve provider discovery order inside its existing two-probe tier.

        No identity/teaching/availability or admission decision is added here.
        Other points, URLs, non-public engines and malformed indices cannot
        donate priority. Old retained observations may use their bounded actual
        heading match counts, never a query string or URL word.
        """
        values = [1]
        canonical = resource.get("canonical_url") or resource.get("url") or ""
        for row in evidence:
            if (row.get("kind") != "search" or row.get("source") not in {"public_catalog", "techwithtim_catalog"}
                    or row.get("knowledge_point_id") != point["knowledge_point_id"]):
                continue
            try:
                if normalize_url(row.get("url", "")) != normalize_url(canonical):
                    continue
            except (UnsafeURL, TypeError, ValueError):
                continue
            facts = row.get("discovery_evidence")
            if not isinstance(facts, dict) or facts.get("kind") != "public_catalog_link" or facts.get("independent_detail_required") is not True:
                continue
            position = facts.get("admission_result_index")
            if type(position) is int and 0 <= position < 6:
                values.append(100 - position)
                continue
            # Legacy discovery metadata can still prefer an actually matched
            # heading. Never infer a match from its query or source address.
            counts = []
            for key in ("literal_heading_matches", "heading_hint_matches"):
                items = facts.get(key)
                counts.append(len({item for item in items[:24] if isinstance(item, str) and 0 < len(item) <= 100})
                              if isinstance(items, list) else 0)
            values.append(1 + counts[0] + counts[1] / 100)
        return max(values)

    @staticmethod
    def _public_catalog_probe(point, resource, evidence, state):
        from .public_catalog import article_url
        from .techwithtim_catalog import lesson_url
        pid = point["knowledge_point_id"]
        if len(state.get("public_probes_started", {}).get(pid, set())) >= 2:
            return False
        canonical = resource.get("canonical_url", "")
        source = ("public_catalog" if article_url(canonical, "https://www.freecodecamp.org") else
                  "techwithtim_catalog" if lesson_url(canonical) else None)
        if source is None:
            return False
        return any(row.get("kind") == "search" and row.get("source") == source
                   and row.get("knowledge_point_id") == pid for row in evidence)

    @staticmethod
    def _probe_owner_in_title(owner, title):
        """Probe admission only; an exact namespace supplies no skill proof."""
        return (tokens(owner) <= tokens(title)
                or bool(re.search(r"(?<![A-Za-z0-9_.+#-])" + re.escape(owner)
                                  + r"\.[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_])", title, re.I)))

    @staticmethod
    def _targeted_catalog_probe(point, resource, evidence, state):
        pid = point["knowledge_point_id"]
        limit = 4 if point.get("learning_skills") else 2
        if len(state.get("gap_probes_started", {}).get(pid, set())) >= limit:
            return False
        if not has_type_evidence(resource, evidence) or not has_video_evidence(resource, evidence):
            return False
        if point.get("learning_skills") and JobService._declared_api_probe(point, resource, evidence):
            return True
        owners = [leading_technical_owner(text) for text in point.get("learning_skills") or [point["text"]]]
        owners = [owner for owner in owners if owner]
        if not owners:
            return False
        return any(row.get("kind") == "search" and row.get("source") not in {"public_catalog", "techwithtim_catalog", "official_sitemap"}
                   and row.get("knowledge_point_id") == pid and row.get("query")
                   and any(JobService._probe_owner_in_title(owner, row.get("title") or "") for owner in owners)
                   for row in evidence)

    @staticmethod
    def _declared_api_probe(point, resource, evidence):
        """Inspect native entries with literal APIs already declared here.

        Exact identifier spelling is recall only. No skill, alias or teaching
        claim is inferred, and wrong-point/foreign-qualified names cannot lend
        their provenance. The caller retains its existing four-probe cap.
        """
        try:
            canonical = normalize_url(resource.get("canonical_url") or resource.get("url") or "")
        except (UnsafeURL, ValueError, TypeError):
            return False
        if type_from_discovered_url(canonical) != "video":
            return False
        def same_resource(row):
            try:
                return normalize_url(row.get("url", "")) == canonical
            except (UnsafeURL, ValueError, TypeError):
                return False
        identifiers = set()
        pattern = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)(\s*\()?")
        for label in [*(point.get("learning_skills") or []), *(point.get("learning_targets") or [])][:14]:
            if not isinstance(label, str):
                continue
            for match in pattern.finditer(label[:120]):
                name, call = match.groups()
                if len(name) >= 4 and ("." in name or "_" in name or call or re.search(r"[a-z][A-Z]", name)):
                    identifiers.add(name)
        return any(row.get("kind") == "search" and row.get("knowledge_point_id") == point["knowledge_point_id"] and same_resource(row)
            and row.get("source") not in {"public_catalog", "techwithtim_catalog", "official_sitemap"} and row.get("query")
            and isinstance(row.get("title"), str)
            and any(re.search(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"(?![A-Za-z0-9_.])", row["title"]) for name in identifiers)
            for row in evidence)

    @staticmethod
    def _gap_catalog_probe(point, resource, evidence, state):
        pid = point["knowledge_point_id"]
        gap_queries = set(state.get("gap_query_history", {}).get(pid, set()))
        if current := state.get("gap_queries", {}).get(pid):
            gap_queries.add(current)
        probe_limit = 4 if point.get("learning_targets") else 2
        if not gap_queries or len(state.get("gap_probes_started", {}).get(pid, set())) >= probe_limit:
            return False
        if not has_type_evidence(resource, evidence) or not has_video_evidence(resource, evidence):
            return False
        searches = [row for row in evidence if row.get("kind") == "search" and row.get("query") in gap_queries
                    and row.get("knowledge_point_id") == pid]
        context = decompose_topic(point["text"])["shared_context"]
        if not context and point.get("learning_targets"):
            owner = leading_technical_owner(point["text"])
            context = [owner] if owner else []
        if not searches or not context:
            return False
        # Course chapter names commonly join modules with underscores, e.g.
        # Pandas_Matplotlib. Use the same complete technical tokens as ranking;
        # PandasWrapper remains a different identifier. This only permits a
        # bounded metadata probe and supplies no instructional equivalence.
        return any(JobService._probe_owner_in_title(context[0], row.get("title") or "") for row in searches)

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
                            if not cached and state["reserved"] >= state.get("detail_limit", self.settings.max_detail_pages):
                                continue
                            selected = rid, host, key, cached, points[index]["knowledge_point_id"]
                            state["cursor"] = (index + 1) % len(points)
                            break
                        if selected:
                            break
                    if not selected:
                        break
                    rid, host, key, cached, selected_point = selected
                    state["started"].add(rid)
                    if (selected_point, rid) in state.get("gap_probe_candidates", set()):
                        state.setdefault("gap_probes_started", {}).setdefault(selected_point, set()).add(rid)
                    if (selected_point, rid) in state.get("public_probe_candidates", set()):
                        state.setdefault("public_probes_started", {}).setdefault(selected_point, set()).add(rid)
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
                    if state["reserved"] >= state.get("detail_limit", self.settings.max_detail_pages):
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
        enriched = unavailable_video_projection(enriched, self.store.evidence(job["job_id"], rid))
        # Navigation leads stay private to this run/cache, outside Resource and
        # all public recommendation facts. The target always needs its own fetch.
        state.setdefault("observed_video_leads", {})[rid] = (
            enriched.get("_video_leads", []) if not page_cache_info.get("stale") else [])
        if enriched.get("catalog_fetch_status") not in {None, "fetched", "success"}:
            job["upstream_partial"] = True
            self._warn(job, "部分公开目录页未完成补全，已保存主页证据；目录状态与失败原因可在资源详情查看")
        # Read the current resource again: a later search can have supplied a type
        # while its metadata request was in flight. Never replace the saved URL.
        resource = state["resources"][rid]
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
        if self.course_library is not None and is_mooc_resource(resource):
            current_page_cache = False
            if cached and page_cache_info.get("hit") is True and page_cache_info.get("stale") is False:
                # Matching rules are absent from the page-cache scope. Recheck
                # its actual current key and payload before allowing the same
                # source observation to be validated under a new library rule.
                selected_key, selected_cache = self._page_cache(resource)
                current_page_cache = bool(selected_key == key and selected_cache
                    and selected_cache["cache"].get("hit") is True
                    and selected_cache["cache"].get("stale") is False
                    and selected_cache["data"] == cached["data"])
            saved = self.course_library.observe(resource, self.store.evidence(job["job_id"], rid),
                self._course_library_profile(), current_page_cache=current_page_cache)
            if saved:
                job["progress"]["library_courses_saved"] = job["progress"].get("library_courses_saved", 0) + 1
        for point in state["points"]:
            if rid in state["candidate_groups"][point["knowledge_point_id"]]:
                self._rank(job, point, resource, state["request"])
        if not cached:
            job["progress"]["details_completed"] += 1
            job["progress"]["catalog_pages_completed"] += enriched.get("catalog_pages_completed", 0)
        self._refresh_gap_coverage(job, state)
        self._save(job)

    def _rank(self, job, point, resource, request):
        evidence = self.store.evidence(job["job_id"], resource["resource_id"], point["knowledge_point_id"])
        if not verified_ai_resource(resource, self.store.evidence(job["job_id"], resource["resource_id"])):
            self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])
            return
        if self._sitemap_only(evidence):
            if not self._sitemap_page_covers(point, resource, evidence, request):
                self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])
                return
        # Sitemap URL words remain low-confidence recall even when another search
        # independently found the same URL; they never supplement teaching coverage.
        evidence = self._teaching_evidence(evidence)
        match = rank_resource(point, resource, evidence, request,
            eligibility_evidence=self.store.evidence(job["job_id"], resource["resource_id"]))
        if match:
            self.store.save_match(job["job_id"], match)
        else:
            self.store.delete_match(job["job_id"], point["knowledge_point_id"], resource["resource_id"])

    @staticmethod
    def _evidence_sort_key(match, resource, evidence):
        """Prefer actual supporting own body/catalog, without creating support.

        Called only after the original rank/identity gates. A page title, an
        arbitrary catalog, and a foreign/stale/unbound record earn no priority.
        Original scores and evidence/coverage remain unchanged.
        """
        supporting = set(match.get("supporting_evidence_ids") or [])
        fallback = (0, -match["ranking_score"], match["resource_id"])
        cache = resource.get("cache")
        if cache is not None and (not isinstance(cache, dict) or cache.get("stale")):
            return fallback
        provenance = resource.get("field_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        try:
            own_urls = {normalize_url(resource[k]) for k in ("url", "canonical_url", "resolved_url") if resource.get(k)}
        except (UnsafeURL, TypeError, ValueError):
            own_urls = set()
        own_support = False
        for row in evidence:
            cache = row.get("cache")
            if (row.get("evidence_id") not in supporting or not row.get("source")
                    or row.get("source") == "search"
                    or (cache is not None and (not isinstance(cache, dict) or cache.get("stale")))):
                continue
            try:
                if normalize_url(row.get("url")) not in own_urls:
                    continue
            except (UnsafeURL, TypeError, ValueError):
                continue
            field = row.get("field")
            if row.get("kind") == "page" and field in {"description", "video_topic_summary"}:
                proof = provenance.get(field)
                if not isinstance(proof, dict):
                    continue
                try:
                    bound = (proof.get("evidence_id") == row["evidence_id"]
                             and proof.get("source") == row["source"]
                             and normalize_url(proof.get("url")) in own_urls
                             and resource.get(field) == row.get("text"))
                except (UnsafeURL, TypeError, ValueError):
                    bound = False
                own_support = own_support or bound
            elif row.get("kind") == "catalog":
                try:
                    raw = json.loads(row.get("text") or "")
                except (TypeError, ValueError):
                    continue
                if not isinstance(raw, dict) or not raw.get("title"):
                    continue
                for chapter in resource.get("chapters") or []:
                    if (not isinstance(chapter, dict) or chapter.get("evidence_id") != row["evidence_id"]
                            or chapter.get("source") != row["source"]):
                        continue
                    # All source fields must agree, not merely a title keyword.
                    if all(chapter.get(key) == value for key, value in raw.items()):
                        own_support = True
        return (-int(own_support), -match["ranking_score"], match["resource_id"])

    async def _rerank(self, job, resources):
        matches = self.store.matches(job["job_id"])
        for point in job["knowledge_points"]:
            group = sorted((m for m in matches if m["knowledge_point_id"] == point["knowledge_point_id"]
                            and m.get("topic_evidence_status", "supported") == "supported"),
                           key=lambda m: self._evidence_sort_key(m, resources[m["resource_id"]],
                               self.store.evidence(job["job_id"], m["resource_id"], point["knowledge_point_id"])))[:15]
            if not group:
                continue
            candidates = []
            for match in group:
                resource = resources[match["resource_id"]]
                searches = [entry for entry in self.store.evidence(job["job_id"], match["resource_id"], point["knowledge_point_id"])
                            if entry.get("kind") == "search" and entry.get("source") not in {"official_sitemap", "public_catalog", "techwithtim_catalog"}]
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
        if not self.settings.teaching_match_enabled:
            return self._discovery_results(job)
        read_cache = getattr(self, "_read_rank_cache", None)
        if read_cache is None:
            self._read_rank_cache = read_cache = ReadRankCache(ranker=rank_resource)
        resources, matches = self.store.resources(job_id), self.store.matches(job_id)
        stored_matches = {(m["knowledge_point_id"], m["resource_id"]): m for m in matches}
        all_evidence = {rid: self.store.evidence(job_id, rid) for rid in resources}
        resources = {rid: resource for rid, resource in resources.items()
                     if (not resource.get("public_library") or self._public_library_current(resource, all_evidence[rid]))
                     and (not resource.get("course_library") or self._library_resource_current(resource))
                     and resource.get("requires_payment") is not True
                     and not has_known_media_fault(resource, all_evidence[rid])
                     and verified_ai_resource(resource, all_evidence[rid])}
        for rid, resource in resources.items():
            resource = resources[rid] = unavailable_video_projection(resource, all_evidence[rid])
            resource = resources[rid] = project_unconfirmed_video_shell(resource, all_evidence[rid])
            resource = resources[rid] = project_unconfirmed_fetched_media(resource, all_evidence[rid])
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
            pointer_pools = _topic_pointer_reservoir(point)
            for rid, resource in resources.items():
                observed = self.store.evidence(job_id, rid, point["knowledge_point_id"])
                linked = any((row.get("kind") in {"search", "ai_suggestion"}
                              and row.get("knowledge_point_id") in {None, point["knowledge_point_id"]})
                             or (row.get("kind") == "page_link"
                                 and row.get("knowledge_point_id") == point["knowledge_point_id"]) for row in observed)
                decision = job.get("teaching_decisions", {}).get(point["knowledge_point_id"], {}).get(rid)
                if decision is None:
                    decision = stored_matches.get((point["knowledge_point_id"], rid), {}).get("_teaching_decision")
                pointer_only = False
                if not linked and rid not in previous_ids:
                    # A source actually inspected for this skill may have been
                    # discovered for another point in the same job. Only a
                    # current, fully rebound sealed decision can link it here,
                    # including a genuine reviewed empty. This grants catalog
                    # pointers only, never primary ranking or teaching support.
                    if (not pointer_pools or not isinstance(decision, dict)
                            or teaching_review.validate_reviewed(point, resource, observed, decision,
                                                                 request.student_level) is None):
                        continue
                    pointer_only = True
                if self._sitemap_only(observed) and not self._sitemap_page_covers(point, resource, observed, request):
                    continue
                observed = self._teaching_evidence(observed)
                ranked_point = {**point, "_teaching_decision": decision} if decision is not None else point
                match = (None if pointer_only else read_cache.rank(ranked_point, resource, observed, request,
                                                                  eligibility_evidence=all_evidence[rid]))
                if match:
                    assessed.append(match)
                elif pointer_pools:
                    # Own, actually observed chapter headings may remain useful
                    # discovery pointers even when complete skill teaching is
                    # unknown. They never become matches or coverage claims.
                    pair = teaching_match.prepare_pair(point, resource, observed, request.student_level)
                    if pair:
                        for pointer in teaching_match.topic_pointers(pair)[:6]:
                            _reserve_topic_pointer(pointer_pools, point, resource, all_evidence[rid], pointer)
            related_topic_pointers = _display_topic_pointers(pointer_pools)
            assessed.sort(key=lambda m: self._evidence_sort_key(m, resources[m["resource_id"]], all_evidence[m["resource_id"]]))
            # One visible course entry per identified same-platform family
            # when no offering is known. Status outranks evidence for choosing
            # that representative; existing order wins within the same status.
            # Review/related observations are never removed by this projection.
            course_keys, representatives = {}, {}
            status_priority = {"supported": 0, "partial": 1}
            for match in assessed:
                status = match["topic_evidence_status"]
                if status not in status_priority:
                    continue
                resource = resources[match["resource_id"]]
                identity = resource.get("course_identity") or {}
                family = identity.get("family_id")
                if (identity.get("status") != "identified" or not family
                        or identity.get("role") != "course"
                        or identity.get("offering_id") is not None):
                    continue
                key = (resource["platform"], family)
                course_keys[match["resource_id"]] = key
                previous = representatives.get(key)
                if (previous is None or status_priority[status]
                        < status_priority[previous["topic_evidence_status"]]):
                    representatives[key] = match
            assessed = [match for match in assessed
                        if match["resource_id"] not in course_keys
                        or representatives[course_keys[match["resource_id"]]] is match]
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
            groups.append(dict(point, **({"learning_coverage": summarize_learning_support(point, [*items, *partial_items])} if point.get("learning_skills") else {}),
                **({"related_topic_pointers": related_topic_pointers} if point.get("learning_skills") else {}),
                total_matches=len(sections["supported"]), total_partial_matches=len(sections["partial"]),
                total_review_matches=len(sections["needs_review"]), section_limit=self.settings.max_results_per_point,
                items=items, platform_items=platform_items, partial_items=partial_items, partial_platform_items=partial_platform_items,
                review_items=review_items, review_platform_items=review_platform_items,
                collection_coverage=summarize_collection_coverage(point["text"], [*items, *partial_items], point.get("learning_targets", [])),
                platform_collection_coverage={platform: summarize_collection_coverage(point["text"], [*platform_items.get(platform, []),
                    *partial_platform_items.get(platform, [])], point.get("learning_targets", [])) for platform in platforms}))
        displayed = [item["resource"] for group in groups for item in [*group["items"],
            *group["partial_items"], *group["review_items"],
            *(item for key in ("platform_items", "partial_platform_items", "review_platform_items") for items in group[key].values() for item in items)]]
        self._add_related_recommendations(groups, resources, all_evidence, request, job=job)
        return {"job_id": job_id, "status": job["status"], "groups": groups, "warnings": job["warnings"],
                "recommendation_policy": RECOMMENDATION_POLICY,
                "search_attempts": self.store.attempts(job_id), "identity_summary": summarize_course_identities(displayed)}

    def _add_related_recommendations(self, groups, resources, evidence, request, *, job=None):
        read_cache = getattr(self, "_read_related_cache", None)
        if read_cache is None:
            self._read_related_cache = read_cache = ReadRelatedCache()
        for group in groups:
            # This projector reads only these point inputs. Display sections
            # change as unrelated candidates arrive and must not invalidate
            # unchanged point/resource pairs. MOOC assessment retains its full
            # group below; its complete assessment is separately sealed.
            related_point = {key: group.get(key) for key in ("knowledge_point_id", "text", "technology")}
            qualified = {row["resource"]["resource_id"]: row["mooc_relevance"]
                         for row in group.get("discovery_items", []) if row.get("mooc_relevance", {}).get("display_eligible")}
            for rid, resource in resources.items():
                if is_mooc_resource(resource):
                    assessment = assess_mooc_relevance(self._mooc_assessment_point(group), resource, evidence.get(rid, []))
                    if assessment.get("status") == "outline_supported" and assessment.get("display_eligible"):
                        qualified[rid] = assessment
            rows, platforms = read_cache.recommendations(related_point, resources, evidence, request,
                self.settings.max_results_per_point, qualified_outlines=qualified,
                grounded_decisions=(job or {}).get("grounded_related", {}).get("decisions", {}).get(group["knowledge_point_id"], {}))
            group.update(related_recommendations=rows, related_platform_recommendations=platforms,
                         recommendation_policy=RECOMMENDATION_POLICY,
                         total_related_recommendations=len(rows),
                         outline_evidence_summary={"qualified_course_count": len(qualified),
                            "resource_ids": sorted(qualified), "related_reference_count": len(rows),
                            "counts_are_independent": True})

    def _discovery_results(self, job):
        """Keep video discovery; require own-course outline support for MOOC."""
        resources = self.store.resources(job["job_id"])
        evidence = {rid: self.store.evidence(job["job_id"], rid) for rid in resources}
        resources = {rid: resource for rid, resource in resources.items()
                     if resource.get("requires_payment") is not True
                     and not has_known_media_fault(resource, evidence[rid])
                     and verified_ai_resource(resource, evidence[rid])}
        for rid, resource in resources.items():
            resources[rid] = unavailable_video_projection(resource, evidence[rid])
        groups = []
        for point in job["knowledge_points"]:
            candidates, mooc_diagnostics = [], []
            for rid, resource in resources.items():
                candidate = discovered_video(point, resource, evidence[rid])
                if is_mooc_resource(resource):
                    if not any(row.get("kind") in {"search", "course_library"} and row.get("knowledge_point_id") == point["knowledge_point_id"]
                               for row in evidence[rid]):
                        continue
                    assessment = assess_mooc_relevance(point, resource, evidence[rid])
                    if resource.get("course_library") and not self._library_resource_current(resource):
                        assessment = {**assessment, "status": "outline_unavailable", "display_eligible": False,
                            "probe_eligible": False, "reason": "shared_library_observation_no_longer_current"}
                    mooc_diagnostics.append({"resource_id": rid, "title": resource.get("title"),
                        "url": resource.get("canonical_url") or resource.get("url"), "assessment": assessment})
                    if not assessment["display_eligible"]:
                        continue
                    if candidate:
                        candidate["mooc_relevance"] = assessment
                if candidate:
                    candidates.append(candidate)
            rows, platforms = display_discovered_videos(candidates)
            # Count a course once after each semester independently qualifies.
            # Every retained card keeps its own evidence; no URL is synthesized
            # and no outline is transferred to a different entry or semester.
            seen_mooc, unique_rows = set(), []
            for row in rows:
                if row.get("mooc_relevance"):
                    key = course_family_key(row["resource"]["canonical_url"])
                    if key in seen_mooc:
                        continue
                    seen_mooc.add(key)
                unique_rows.append(row)
            rows = unique_rows
            platforms = {platform: [row for row in rows if row["resource"]["platform"] == platform]
                         for platform in platforms}
            groups.append({**point, "discovery_only": True, "discovery_items": rows,
                "discovery_platform_items": platforms, "total_matches": 0, "total_partial_matches": 0,
                "total_review_matches": 0, "items": [], "partial_items": [], "review_items": [],
                "platform_items": {}, "partial_platform_items": {}, "review_platform_items": {},
                "mooc_relevance": {"schema_version": "mooc-outline-v1", "policy": "outline_required",
                    "candidate_count": len(mooc_diagnostics),
                    "recommended_count": sum(bool(row.get("mooc_relevance")) for row in rows),
                    "status_counts": dict(Counter(row["assessment"]["status"] for row in mooc_diagnostics)),
                    "candidates": mooc_diagnostics}})
        # Historical cancelled jobs can have no request or groups. Reading a
        # terminal empty snapshot must not invent a request or fail the stream.
        if groups:
            self._add_related_recommendations(groups, resources, evidence, SearchRequest.model_validate(job["request"]), job=job)
        return {"job_id": job["job_id"], "status": job["status"], "groups": groups,
                "discovery_only": True, "warnings": job["warnings"],
                "recommendation_policy": RECOMMENDATION_POLICY,
                "search_attempts": self.store.attempts(job["job_id"])}

    def capabilities(self):
        from . import grounded_related
        config = {"searxng": bool(self.settings.searxng_url),
            "tavily": bool(self.settings.tavily_api_key or self.settings.tavily_backup_api_key or self.settings.tavily_allow_keyless),
            "serper": bool(self.settings.serper_api_key),
            "official_sitemap": self.settings.fetch_enabled}
        def provider_status(name):
            configured = config.get(name, False)
            provider = self._source_objects().get(name)
            status = getattr(provider, "last_status", "configured") if configured else "unconfigured"
            if self._provider_errors.get(name):
                status = "unconfigured"
            message = {"configured": "已配置，尚未验证真实搜索", "available": "最近一次搜索请求成功",
                "fault": "最近搜索请求故障，请查看任务错误", "unconfigured": "尚未配置"}.get(status, "搜索状态未知")
            result = {"name": name, "status": status, "message": message, "configured": configured}
            if name == "tavily":
                mode = "api_key" if self.settings.tavily_api_key or self.settings.tavily_backup_api_key else "keyless" if self.settings.tavily_allow_keyless else "unconfigured"
                result["auth_mode"] = mode
                result["backup_configured"] = bool(self.settings.tavily_backup_api_key and self.settings.tavily_backup_api_key != self.settings.tavily_api_key)
                if mode == "keyless":
                    result["message"] += "；免密模式仅供有限试用，不代表生产可用性"
            if name == "official_sitemap":
                result["message"] += "；仅 MIT 官方站点地图，其他平台不在此模式的发现范围"
            return result
        providers = [provider_status(name) for name in config]
        selected = provider_status(self.settings.search_provider)
        platform_providers = {platform: provider_status(self.settings.search_provider_for(platform))
                              for platform in ("bilibili", "icourse163")}
        selected.update(selected_provider=self.settings.search_provider, providers=providers,
                        platform_providers=platform_providers)
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
            platforms.append({"id": key, "name": name, "discovery": "out_of_scope" if self.settings.search_provider_for(key) == "official_sitemap" and key != "other" else "search", "metadata": metadata,
                "search_provider": self.settings.search_provider_for(key),
                **({"metadata_max_bytes": self.settings.bilibili_public_metadata_max_bytes,
                    "metadata_max_state_chars": 4_000_000} if key == "bilibili" else {}),
                "search_status": provider_status(self.settings.search_provider_for(key))["status"],
                "playback": "unknown", "policy_status": status, "source_url": policy.get("source_url"),
                "reviewed_at": policy.get("reviewed_at"), "policy_basis": policy.get("basis"),
                "policy_section": policy.get("section"), "terms_date": policy.get("terms_date"),
                "effective_at": policy.get("effective_at"), "review_method": policy.get("review_method")})
        return {"mode": "live", "search": selected, "teaching_match_enabled": self.settings.teaching_match_enabled,
                "ai_video_fallback": {"enabled": self.settings.ai_video_fallback_enabled,
                    "policy_version": "grounded-video-v2", "search_provider": self.settings.ai_video_search_provider,
                    "retained_candidate_probes_per_point": 3,
                    "max_recovery_attempts_per_query": 2,
                    "max_recovery_queries_per_point": 3,
                    "max_page_link_hops": 1, "max_page_link_probes_per_point": 3,
                    "exclude_known_paid_videos": True,
                    "model_configured": callable(getattr(self.llm, "suggest_video_urls", None)),
                    "max_calls_per_job": 1, "max_urls_per_point": 3,
                    "requires_verified_page": True, "read_time_model_calls": 0},
                "related_reference_verification": {"policy_version": grounded_related.VERSION,
                    "max_batches_per_job": grounded_related.MAX_BATCHES,
                    "max_model_calls_per_job": grounded_related.MAX_MODEL_CALLS,
                    "max_pairs_per_batch": grounded_related.MAX_PAIRS,
                    "max_pairs_per_point": grounded_related.MAX_PER_POINT,
                    "call_timeout_seconds": grounded_related.CALL_SECONDS,
                    "independent_positive_review": True, "read_time_model_calls": 0,
                    "total_deadline_extended": False},
                "shared_course_library": {"enabled": self.course_library is not None,
                    "persistent_public_reuse_enabled": getattr(self, "public_library", None) is not None,
                    "ttl_seconds": self.settings.shared_course_library_ttl_seconds,
                    "scope": "public MOOC own-page and outline evidence only; rematched for each knowledge point",
                    "stats": self.course_library.stats() if self.course_library is not None else {}},
            "mooc_gap_search": {"enabled": self.settings.mooc_gap_search_enabled,
                    "query_refresh_enabled": self.mooc_refresh is not None,
                    "query_refresh_interval_seconds": self.settings.mooc_refresh_interval_seconds,
                    "target_courses_per_point": self.settings.mooc_target_courses_per_point,
                    "check_wait_seconds": self.settings.mooc_gap_check_wait_seconds},
                "mooc_relevance": {"schema_version": "mooc-outline-v1",
                    "enabled": True, "policy": "outline_required",
                    "scope": "icourse163 public course outline; every selected subtopic must have bound catalog evidence",
                    "model_calls": 0, "playback_verified": False},
                "platform_search": {"parallel": self.settings.parallel_platform_search,
                    "open_web_enabled": self.settings.open_web_search_enabled,
                    "open_web_scope": "one unrestricted initial query per point within the same hard request budget",
                    "searxng_failover": {"provider": self.settings.searxng_failover_provider or None,
                        "configured": self._failover_enabled(), "cooldown_seconds": 300,
                        "extra_requests_per_slot": 0},
                    "providers": platform_providers,
                    "initial_requests_per_point_per_platform": 1,
                    "followup_requests_per_point_per_platform": max(self.settings.bilibili_search_rounds, self.settings.mooc_search_rounds) - 1,
                    "rounds_per_point": {"bilibili": self.settings.bilibili_search_rounds,
                        "icourse163": self.settings.mooc_search_rounds},
                    "initial_pass_before_followups": True},
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
                "public_catalog_discovery": {"enabled": self.settings.public_catalog_fallback,
                    "scope": "freeCodeCamp public tag cards and Tech With Tim category/series lesson links; independent video and topic page evidence required",
                    "max_indexes_per_query": 3, "max_indexes_by_source": {"freecodecamp": 2, "techwithtim": 3},
                    "max_series_per_query": 2, "max_detail_probes_per_point": 2,
                    "cache_ttl_seconds": self.settings.search_cache_ttl,
                    "status": getattr(self.public_catalog, "last_status", "disabled")},
                "learning_skill_matching": {"judge_max_calls_per_job": self.settings.teaching_match_max_calls_per_job,
                    "positive_claim_review_max_calls_per_job": 1 if self.settings.teaching_match_max_calls_per_job else 0,
                    "max_pairs_per_job": 20, "max_candidates_per_point": 4, "read_time_model_calls": 0,
                    "judge_timeout_seconds": teaching_match.DEADLINE_SECONDS,
                    "review_timeout_seconds": teaching_review.DEADLINE_SECONDS,
                    "judge_max_output_tokens": min(self.settings.llm_max_output_tokens, 3000),
                    "review_max_output_tokens": min(self.settings.llm_max_output_tokens, 1500),
                    "total_deadline_extended": False, "decision_cache_ttl_seconds": 3600},
                "platforms": platforms,
                "limits": {"max_knowledge_points": self.settings.max_knowledge_points, "max_results_per_point": self.settings.max_results_per_point,
                    "max_search_requests": self.settings.max_search_requests, "max_detail_pages": self.settings.max_detail_pages,
                    "global_concurrency": self.settings.global_concurrency, "per_host_concurrency": 1},
                "deployment": {"local_only": True, "authentication": False}}
