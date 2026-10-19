"""Search discovery only. Provider endpoint configuration is trusted server input."""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit
import httpx
from .models import Candidate
from .config import Settings
from .url_utils import UnsafeURL, normalize_url, safe_thumbnail_url


class SearchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class SearchBudgetReached(Exception):
    """Budget stop carrying only candidates already returned by real sources."""
    def __init__(self):
        super().__init__()
        self.partial_candidates: list[Candidate] = []


class QueryBudgetReached(SearchBudgetReached):
    """This query's fair share ended; other points may still use job budget."""


class SearchProvider(Protocol):
    name: str
    async def search(self, query: str, language: str, limit: int, domain_filters: list[str]) -> list[Candidate]: ...


def retry_after_seconds(value: str | None) -> float:
    try:
        if value is None:
            return 60.0
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else 60.0
    except (ValueError, TypeError, OverflowError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0.0, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60.0


def parse_candidates(items: list, provider: str, query: str, limit: int, domains: list[str], *, audit: dict | None = None) -> list[Candidate]:
    results = []
    if audit is not None:
        audit.update(filter_counts={}, candidate_trace=[], candidate_trace_omitted=0)
    def record(index: int, reason: str, url=None):
        if audit is None:
            return
        counts = audit["filter_counts"]
        counts[reason] = counts.get(reason, 0) + 1
        if len(audit["candidate_trace"]) >= 20:
            audit["candidate_trace_omitted"] += 1
            return
        trace = {"index": index, "reason": reason}
        # A search engine may return arbitrary data. Never reflect credentials,
        # local URLs, query values or fragments into request diagnostic traces.
        try:
            safe = urlsplit(normalize_url(url))
            public_url = urlunsplit((safe.scheme, safe.netloc, safe.path, "", ""))
            trace.update(url=public_url[:500], url_truncated=len(public_url) > 500,
                         query_redacted=bool(safe.query or safe.fragment),
                         url_sha256=hashlib.sha256(url.encode()).hexdigest())
        except (UnsafeURL, TypeError, ValueError):
            pass
        # Keep bounded source text so rejection diagnostics can be reviewed.
        # Redact URLs (including embedded credentials/query values) and controls.
        if isinstance(item, dict):
            for field, value, cap in (("title", item.get("title"), 600),
                    ("snippet", item.get("content") or item.get("snippet"), 1200)):
                if isinstance(value, str):
                    clean = re.sub(r"https?://\S+", "[url redacted]", value, flags=re.I)
                    clean = re.sub(r"\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*", "[credentials redacted]", clean, flags=re.I)
                    clean = re.sub(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", "[credential redacted]", clean, flags=re.I)
                    clean = re.sub(r"[\x00-\x1f\x7f]", " ", clean)
                    trace[field] = clean[:cap]
                    trace[field + "_truncated"] = len(clean) > cap
        audit["candidate_trace"].append(trace)
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            record(index, "invalid_item")
            continue
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not url:
            record(index, "missing_url")
            continue
        if not isinstance(title, str) or not title.strip():
            record(index, "invalid_title", url)
            continue
        if len(url) > 4096:
            record(index, "url_too_long", url)
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                record(index, "invalid_url", url)
                continue
            if domains and not any(parsed.hostname == d or parsed.hostname.endswith("." + d) for d in domains):
                record(index, "domain_mismatch", url)
                continue
        except ValueError:
            record(index, "invalid_url", url)
            continue
        if len(results) >= limit:
            record(index, "limit_reached", url)
            continue
        snippet = item.get("content") or item.get("snippet") or ""
        if not isinstance(snippet, str):
            snippet = ""
        engines = item.get("engines") or [item.get("engine")]
        engines = [e for e in engines if isinstance(e, str) and re.fullmatch(r"[a-zA-Z0-9 ._-]{1,60}", e)] if isinstance(engines, list) else []
        video_result = provider == "searxng" and item.get("template") == "videos.html"
        thumbnail = safe_thumbnail_url(item.get("thumbnail")) if provider == "searxng" else None
        results.append(Candidate(id=hashlib.sha256(f"{provider}\0{query}\0{url}".encode()).hexdigest()[:24],
                                 title=title[:600], url=url[:4096], snippet=snippet[:4000], source=provider, query=query,
                                 source_engines=engines, resource_type_hint="video" if video_result else "unknown",
                                 type_source="search_template" if video_result else None,
                                 thumbnail_url=thumbnail, thumbnail_source="search.thumbnail" if thumbnail else None))
        record(index, "accepted", url)
    return results


class HTTPProvider:
    name = "unknown"
    read_error_statuses: frozenset[int] = frozenset()
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        from contextvars import ContextVar
        self._query_observations = ContextVar(f"provider-query-{id(self)}", default=None)
        self._request_start_lock = asyncio.Lock()
        self.settings, self.client = settings, client
        self.paused_until = 0.0
        self.access_denied = False
        self.last_request_started = 0.0
        self.last_status = "configured"
        self.last_warnings: list[dict] = []
        self.last_requests: list[dict] = []
        self.request_hook: Callable[[], Awaitable[None]] | None = None

    def _get_observation(self, name, default):
        scope = self._query_observations.get()
        return scope.get(name, default) if scope is not None else self.__dict__.get("_" + name, default)

    def _set_observation(self, name, value):
        scope = self._query_observations.get()
        if scope is not None:
            scope[name] = value
        else:
            self.__dict__["_" + name] = value

    # Query traces and hooks are task-local. Access/engine pauses and request
    # spacing remain shared by all platform lanes using the same search service.
    last_requests = property(lambda self: self._get_observation("last_requests", []),
                             lambda self, value: self._set_observation("last_requests", value))
    last_warnings = property(lambda self: self._get_observation("last_warnings", []),
                             lambda self, value: self._set_observation("last_warnings", value))
    last_dns_requests = property(lambda self: self._get_observation("last_dns_requests", []),
                                 lambda self, value: self._set_observation("last_dns_requests", value))
    last_discovery = property(lambda self: self._get_observation("last_discovery", {}),
                              lambda self, value: self._set_observation("last_discovery", value))
    request_hook = property(lambda self: self._get_observation("request_hook", None),
                            lambda self, value: self._set_observation("request_hook", value))

    def query_scope(self, request_hook):
        from contextlib import contextmanager
        @contextmanager
        def scoped():
            token = self._query_observations.set({"request_hook": request_hook,
                "last_requests": [], "last_warnings": [], "last_dns_requests": [], "last_discovery": {}})
            try:
                yield self
            finally:
                self._query_observations.reset(token)
        return scoped()

    @classmethod
    async def _bounded_response(cls, client, method, url, trace, **kwargs):
        # Bound the actual read, not just the already-buffered response. Search
        # endpoints are trusted server configuration; their content is untrusted.
        kwargs["headers"] = {**kwargs.get("headers", {}), "Accept-Encoding": "identity"}
        async with client.stream(method, url, **kwargs) as response:
            trace["http_status"] = response.status_code
            if response.status_code != 200 and response.status_code not in cls.read_error_statuses:
                return httpx.Response(response.status_code, headers=response.headers, content=b"")
            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                if response.status_code != 200:
                    return httpx.Response(response.status_code, headers=response.headers, content=b"")
                raise SearchError("invalid_response", "搜索响应使用非预期压缩，未解压读取")
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if response.status_code != 200 and len(body) + len(chunk) > 16384:
                    return httpx.Response(response.status_code, headers=response.headers, content=b"")
                if len(body) + len(chunk) > 2_000_000:
                    raise SearchError("invalid_response", "搜索响应超过允许大小")
                body.extend(chunk)
            trace["response_bytes"] = len(body)
            return httpx.Response(response.status_code, headers=response.headers, content=bytes(body))

    def observe_response(self, response, trace):
        """Provider-specific bounded diagnostics, never raw response headers."""

    def normalize_response(self, body):
        """Normalize a provider envelope without altering source URLs or text."""
        return body

    async def request(self, method: str, url: str, **kwargs) -> dict:
        if getattr(self, "quota_exhausted", False):
            raise SearchError("quota_exhausted", "搜索来源额度已用尽，未再次请求")
        if self.access_denied:
            raise SearchError("access_denied", "搜索服务此前拒绝访问；请修正权限或配置后重启，未再次请求")
        if time.monotonic() < self.paused_until:
            raise SearchError("rate_limited", "搜索来源仍在 Retry-After 暂停期内")
        for attempt in range(self.settings.search_max_retries + 1):
            async with self._request_start_lock:
                interval = self.settings.search_min_interval_seconds - (time.monotonic() - self.last_request_started)
                if interval > 0:
                    await asyncio.sleep(interval)
                if getattr(self, "quota_exhausted", False):
                    raise SearchError("quota_exhausted", "搜索来源在等待期间额度用尽，未发起该请求")
                if self.access_denied:
                    raise SearchError("access_denied", "搜索服务此前拒绝访问；已停止后续请求")
                if time.monotonic() < self.paused_until:
                    raise SearchError("rate_limited", "搜索来源仍在 Retry-After 暂停期内")
                # Another in-flight platform query may have observed a pause
                # while this request waited for the shared start interval.
                requested_engines = kwargs.get("params", {}).get("engines", "")
                if (requested_engines and any(time.monotonic() < getattr(self, "engine_pauses", {}).get(engine, 0)
                                              for engine in requested_engines.split(","))):
                    raise SearchError("upstream_engine_failed", "上游引擎在等待期间进入暂停期，未发起该请求")
                if not requested_engines and time.monotonic() < getattr(self, "default_group_pause_until", 0):
                    raise SearchError("upstream_engine_failed", "默认引擎组仍在暂停期，未发起该请求")
                if self.request_hook:
                    await self.request_hook()
                self.last_request_started = time.monotonic()
            trace = {"provider": self.name, "started_at": datetime.now(timezone.utc).isoformat(),
                     "retry_index": attempt, "status": "running"}
            if "params" in kwargs:
                trace["engines_requested"] = kwargs["params"].get("engines", "instance_defaults")
            self.last_requests.append(trace)
            started = time.monotonic()
            try:
                if self.client:
                    response = await self._bounded_response(self.client, method, url, trace, **kwargs)
                else:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.search_timeout_seconds, connect=5), follow_redirects=False, trust_env=False) as client:
                        response = await self._bounded_response(client, method, url, trace, **kwargs)
                trace["http_status"] = response.status_code
                self.observe_response(response, trace)
                if response.status_code == 429 or (response.status_code == 503 and "retry-after" in response.headers):
                    # Do not sleep past the job deadline, or retry another endpoint.
                    self.paused_until = time.monotonic() + retry_after_seconds(response.headers.get("retry-after"))
                    trace["retry_after_seconds"] = retry_after_seconds(response.headers.get("retry-after"))
                    raise SearchError("rate_limited", "搜索来源要求稍后重试，已按 Retry-After 暂停该来源")
                if response.status_code in {401, 403}:
                    self.access_denied = True
                    raise SearchError("access_denied", "搜索来源拒绝访问，请检查服务权限与 JSON 输出配置")
                if response.status_code != 200:
                    raise SearchError("search_unavailable", "搜索服务返回错误，未使用替代或演示数据")
                body = self.normalize_response(response.json())
                if not isinstance(body, dict) or not isinstance(body.get("results"), list):
                    raise SearchError("invalid_response", "搜索服务未返回有效的 JSON results")
                self.last_status = "available"
                trace["status"] = "completed"
                return body
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                trace.update(status="failed", error_type=type(exc).__name__, error_code="search_timeout")
                if attempt < self.settings.search_max_retries:
                    await asyncio.sleep(0.2)
                    continue
                self.last_status = "fault"
                raise SearchError("search_timeout", "搜索服务连接失败或超时") from None
            except (ValueError, TypeError):
                trace.update(status="failed", error_code="invalid_response")
                self.last_status = "fault"
                raise SearchError("invalid_response", "搜索服务未返回有效 JSON") from None
            except SearchError as exc:
                trace.update(status="failed", error_code=exc.code)
                self.last_status = "fault"
                raise
            except asyncio.CancelledError:
                trace.update(status="cancelled", error_code="request_cancelled")
                raise
            finally:
                trace["elapsed_seconds"] = round(time.monotonic() - started, 3)
        raise SearchError("search_unavailable", "搜索服务不可用")


class SearXNGProvider(HTTPProvider):
    name = "searxng"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        super().__init__(settings, client)
        self.engine_pauses: dict[str, float] = {}
        self.default_group_pause_until = 0.0
        self.engine_timeout_streaks: dict[str, int] = {}
        self.engine_timeout_observations: dict[str, int] = {}
        self.engine_timeout_cooldowns: dict[str, float] = {}

    def _observe_engine_timeouts(self, failures: list[dict], requested: list[str]) -> list[dict]:
        """Attribute only explicit observations to this requested engine group.

        Transport timeouts and implicit defaults cannot identify an upstream
        engine. Duplicate response rows are one observation, not two failures.
        """
        observations = []
        unaccounted_failure = any(failure["engine"] not in requested for failure in failures)
        for engine in dict.fromkeys(requested):
            matching = [failure for failure in failures if failure["engine"] == engine]
            if matching and all(failure["reason_code"] == "timeout" for failure in matching):
                streak = self.engine_timeout_streaks.get(engine, 0) + 1
                total = self.engine_timeout_observations.get(engine, 0) + 1
                self.engine_timeout_streaks[engine] = streak
                self.engine_timeout_observations[engine] = total
                row = {"engine": engine, "reason_code": "timeout", "consecutive_timeout_count": streak,
                       "observed_timeout_count": total, "cooldown_seconds": 0}
                if streak >= 2:
                    until = time.monotonic() + 60
                    self.engine_pauses[engine] = max(self.engine_pauses.get(engine, 0), until)
                    self.engine_timeout_cooldowns[engine] = until
                    row["cooldown_seconds"] = 60
                observations.append(row)
                for failure in matching:
                    failure.update(row)
            elif matching or not unaccounted_failure:
                # Normal (including empty) responses complete an observation.
                # Unknown engine failures must not imply this engine succeeded.
                previous = self.engine_timeout_streaks.pop(engine, 0)
                if previous:
                    observations.append({"engine": engine, "reason_code": "other_failure" if matching else "success",
                        "consecutive_timeout_count": 0, "observed_timeout_count": self.engine_timeout_observations.get(engine, 0),
                        "previous_consecutive_timeout_count": previous, "cooldown_seconds": 0})
        return observations

    def _failures(self, body: dict) -> list[dict]:
        """Retain exact known public SearXNG reasons, never arbitrary error bodies."""
        reasons = {
            "timeout": ("timeout", "上游搜索超时"),
            "too many requests": ("rate_limited", "上游限流"),
            "access denied": ("access_denied", "上游拒绝访问"),
            "captcha": ("captcha", "上游要求验证码"),
            "suspended": ("suspended", "SearXNG 已暂停该引擎"),
        }
        output = []
        for failure in body.get("unresponsive_engines", []):
            engine = failure[0] if isinstance(failure, list) and failure else "unknown"
            engine = engine if isinstance(engine, str) and re.fullmatch(r"[a-zA-Z0-9 ._-]{1,60}", engine) else "unknown"
            original = failure[1] if isinstance(failure, list) and len(failure) > 1 and isinstance(failure[1], str) else "unknown"
            code, label = reasons.get(original.lower(), ("unknown", "上游失败，具体原因未识别"))
            output.append({"code": "upstream_engine_failed", "engine": engine, "reason_code": code,
                           "reason": original if original.lower() in reasons else "unknown", "message": label,
                           "reason_sha256": hashlib.sha256(original.encode()).hexdigest()})
            if code in {"rate_limited", "captcha", "access_denied"}:
                self.engine_pauses[engine] = time.monotonic() + (300 if code == "rate_limited" else 3600)
        return output

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str], *, candidate_check=None) -> list[Candidate]:
        self.last_warnings = []
        self.last_requests = []
        if not self.settings.searxng_url:
            raise SearchError("configuration_error", "尚未配置 SEARXNG_URL，请接入自托管 SearXNG 并启用 JSON 输出")
        configured_engines = (*self.settings.searxng_engines, *self.settings.searxng_video_engines, *self.settings.searxng_fallback_engines)
        if any(engine.lower() in {"youtube", "bilibili"} for engine in configured_engines):
            raise SearchError("configuration_error", "未取得平台直接自动访问许可，不能启用 youtube/bilibili 直搜引擎；可由独立网页搜索服务发现链接")
        # A knowledge point must not override the server's engine/access policy
        # through SearXNG bang/category commands embedded in its text.
        query = re.sub(r"(^|\s)[!:]+(?=\S)", r"\1", query)
        # Site restrictions are expressed in q, as documented by SearXNG.
        if domain_filters and "site:" not in query:
            query = f"site:{domain_filters[0]} {query}"
        video_intent = bool(re.search(r"视频|\bvideo\b", query, re.I))
        course_scope = domain_filters == ["icourse163.org"]
        if course_scope and not self.settings.searxng_engines:
            raise SearchError("configuration_error", "MOOC 课程搜索尚未配置通用引擎；未使用视频引擎或未知默认组代替")
        primary = (self.settings.searxng_video_engines
            if not course_scope and video_intent and self.settings.searxng_video_engines else self.settings.searxng_engines)
        if not primary and self.settings.searxng_fallback_engines:
            raise SearchError("configuration_error", "使用备用引擎前须显式配置主引擎，避免未知默认组与备用组重叠")
        if not primary and time.monotonic() < self.default_group_pause_until:
            self.last_warnings = [{"code": "upstream_engine_failed", "engine": "instance_defaults",
                "reason_code": "suspended", "reason": "suspended", "message": "默认引擎组有访问限制，组成员未知，保守暂停整组以避免重试受限来源"}]
            raise SearchError("upstream_engine_failed", "默认搜索引擎组仍在访问限制暂停期；可显式配置已获许可的独立引擎")
        fallback = tuple(e for e in self.settings.searxng_fallback_engines if e not in primary)
        groups = [primary] + ([fallback] if fallback else [])
        items = []
        discovered = {}
        def select_observations(rows):
            if not candidate_check:
                return rows, len(rows)
            ranked = sorted(rows, key=lambda item: not candidate_check(item))
            canonical_rows = {}
            for item in ranked:
                try:
                    canonical = normalize_url(item.url)
                except UnsafeURL:
                    continue
                canonical_rows.setdefault(canonical, []).append(item)
            chosen = list(canonical_rows.values())[:limit]
            return [item for observations in chosen for item in observations], len(canonical_rows)
        for index, engines in enumerate(groups):
            active = list(dict.fromkeys(e for e in engines if time.monotonic() >= self.engine_pauses.get(e, 0)))
            for engine in dict.fromkeys(engines):
                if engine in active:
                    continue
                timeout_pause = (time.monotonic() < self.engine_timeout_cooldowns.get(engine, 0)
                                 and self.engine_pauses[engine] <= self.engine_timeout_cooldowns[engine])
                warning = {"code": "upstream_engine_failed", "engine": engine,
                    "reason_code": "timeout_cooldown" if timeout_pause else "suspended",
                    "reason": "timeout" if timeout_pause else "suspended",
                    "message": "已观察到连续引擎超时，短暂冷却中；未发起请求" if timeout_pause else "该引擎仍在上游限流或明确拒绝暂停期，未请求"}
                if timeout_pause:
                    warning.update(consecutive_timeout_count=self.engine_timeout_streaks.get(engine, 0),
                        observed_timeout_count=self.engine_timeout_observations.get(engine, 0),
                        cooldown_remaining_seconds=round(max(0, self.engine_pauses[engine] - time.monotonic()), 3))
                self.last_warnings.append(warning)
            if engines and not active:
                continue
            params = {"q": query, "format": "json", "language": {"zh": "zh-CN", "en": "en", "any": "all"}[language]}
            if active:
                params["engines"] = ",".join(active)
            try:
                body = await self.request("GET", self.settings.searxng_url.rstrip("/") + "/search", params=params)
            except SearchBudgetReached as exc:
                # An optional backup/retry cannot erase completed primary
                # observations. The caller distinguishes query and job stops.
                exc.partial_candidates = select_observations([
                    *discovered.values(), *exc.partial_candidates])[0]
                raise
            except SearchError as exc:
                # Authentication, service-wide denial and rate limiting are hard stops.
                if exc.code not in {"search_timeout", "search_unavailable"} or index == len(groups) - 1:
                    raise
                self.last_warnings.append({"code": exc.code, "engine": ",".join(active) or "instance_defaults", "message": exc.message})
                continue
            failures = self._failures(body)
            engine_health = self._observe_engine_timeouts(failures, active)
            if not primary and any(f["reason_code"] in {"rate_limited", "captcha", "access_denied"} for f in failures):
                self.default_group_pause_until = max(self.engine_pauses.values(), default=0)
            self.last_warnings.extend(failures)
            audit = {}
            items = parse_candidates(body["results"], self.name, query, 200 if candidate_check else limit, domain_filters, audit=audit)
            if candidate_check:
                # Rank only for source selection and recall; the final evidence
                # gate remains in JobService. Limit unique URLs, retaining all
                # observations for each chosen URL (including media evidence).
                items, audit["deduplicated_candidate_count"] = select_observations(items)
            self.last_requests[-1].update(upstream_warnings=failures, raw_candidate_count=len(body["results"]),
                                         candidate_count=len(items), fallback=index > 0, engine_health=engine_health, **audit)
            for item in items:
                # Distinct search observations for the same URL must survive:
                # a backup may supply the first relevant title or media type.
                # JobService deduplicates resources while storing both records.
                key = (item.url, item.title, item.snippet, item.resource_type_hint, item.type_source, tuple(item.source_engines))
                discovered.setdefault(key, item)
            relevant = sum(candidate_check(item) for item in items) if candidate_check else len(items)
            self.last_requests[-1]["topic_signal_count"] = relevant
            if items and not relevant:
                self.last_requests[-1]["content_status"] = "no_topic_signal"
                self.last_warnings.append({"code": "no_topic_signal", "engine": ",".join(active) or "instance_defaults",
                    "message": "搜索返回候选，但标题摘要未通过原知识点相关性规则；允许的独立来源继续检索"})
                continue
            if items:
                self.last_status = "available"
                return select_observations(list(discovered.values()))[0]
        if discovered:
            self.last_status = "available"
            return select_observations(list(discovered.values()))[0]
        if self.last_warnings:
            self.last_status = "fault"
            raise SearchError("upstream_engine_failed", "SearXNG 上游引擎故障且没有候选，不能确认正常无结果")
        self.last_status = "available"
        return items


class TavilyProvider(HTTPProvider):
    name = "tavily"
    read_error_statuses = frozenset({400, 401, 402, 403, 429, 432, 433})

    def observe_response(self, response, trace):
        if response.status_code in {402, 432, 433}:
            self.quota_exhausted = True
        if response.status_code not in self.read_error_statuses:
            return
        try:
            body = response.json()
        except (ValueError, TypeError):
            return
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict):
            return
        # Service messages and next_actions are untrusted prose and may echo
        # credentials. Retain only the numeric cooldown, never their text.
        seconds = error.get("retry_after_seconds")
        if (isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
                and 0 <= seconds <= 31_536_000 and math.isfinite(seconds)):
            trace["service_retry_after_seconds"] = seconds
            if response.status_code == 429:
                existing = retry_after_seconds(response.headers.get("retry-after"))
                response.headers["retry-after"] = str(max(seconds, existing))

    @property
    def auth_mode(self) -> str:
        if self.settings.tavily_api_key:
            return "api_key"
        return "keyless" if self.settings.tavily_allow_keyless else "unconfigured"

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str]) -> list[Candidate]:
        self.last_requests = []
        self.last_warnings = []
        if self.auth_mode == "unconfigured":
            raise SearchError("configuration_error", "已选择 Tavily，请启用 TAVILY_ALLOW_KEYLESS 免费试用或配置 TAVILY_API_KEY")
        if getattr(self, "quota_exhausted", False):
            raise SearchError("quota_exhausted", "Tavily 额度已用尽，已停止该来源；未切换账号或访问模式")
        payload = {"query": query, "max_results": min(limit, 20), "include_answer": False, "include_raw_content": False,
                   "search_depth": "basic", "auto_parameters": False, "include_usage": True}
        if language != "any":
            payload["language"] = "zh-cn" if language == "zh" else "en"
            payload["filter_by_language"] = False
        if domain_filters:
            payload["include_domains"] = domain_filters
            payload["include_domains_mode"] = "restrict"
        # Never send both headers: an API key overrides keyless access and uses
        # the account's budget. Missing keys do not silently opt into keyless.
        headers = ({"Authorization": "Bearer " + self.settings.tavily_api_key}
                   if self.auth_mode == "api_key" else {"X-Tavily-Access-Mode": "keyless"})
        try:
            body = await self.request("POST", "https://api.tavily.com/search", headers=headers, json=payload)
        except SearchError as exc:
            if self.last_requests and self.last_requests[-1].get("http_status") in {402, 432, 433}:
                self.quota_exhausted = True
                self.last_requests[-1]["error_code"] = "quota_exhausted"
                raise SearchError("quota_exhausted", "Tavily 额度或套餐限制，已停止该来源；未启用付费服务") from None
            raise
        finally:
            for trace in self.last_requests:
                trace.update(auth_mode=self.auth_mode, search_depth="basic")
        usage = body.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        if (isinstance(credits, (int, float)) and not isinstance(credits, bool)
                and 0 <= credits <= 1_000_000_000 and math.isfinite(credits)):
            self.last_requests[-1]["api_credits"] = credits
        audit = {}
        items = parse_candidates(body["results"], self.name, query, limit, domain_filters, audit=audit)
        self.last_requests[-1].update(raw_candidate_count=len(body["results"]), candidate_count=len(items), **audit)
        return items


class SerperProvider(HTTPProvider):
    """Google organic search only; no scrape endpoint, account or billing changes."""
    name = "serper"

    @property
    def auth_mode(self) -> str:
        return "api_key" if self.settings.serper_api_key else "unconfigured"

    def observe_response(self, response, trace):
        if response.status_code == 402:
            self.quota_exhausted = True

    def normalize_response(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("organic"), list):
            raise SearchError("invalid_response", "Serper 未返回有效的 organic 搜索结果")
        # Only organic search observations may become candidates. Knowledge
        # graphs, answer boxes and nested sitelinks are not course discoveries.
        return {"results": [{"title": item.get("title"), "url": item.get("link"),
                              "snippet": item.get("snippet")} if isinstance(item, dict) else item
                            for item in body["organic"]], "credits": body.get("credits")}

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str]) -> list[Candidate]:
        self.last_requests = []
        self.last_warnings = []
        if self.auth_mode == "unconfigured":
            raise SearchError("configuration_error", "已选择 Serper，请配置 SERPER_API_KEY；可使用官网免费试用额度")
        # Serper uses query operators instead of a structured domain filter.
        # Keep the original query as evidence; append only trusted domain names.
        if any(not isinstance(domain, str) or not re.fullmatch(r"[a-zA-Z0-9.-]+", domain)
               for domain in domain_filters):
            raise SearchError("configuration_error", "Serper 域名过滤配置无效")
        site_filter = " OR ".join("site:" + domain for domain in domain_filters)
        already_scoped = len(domain_filters) == 1 and re.search(
            r"(?<!\S)site:" + re.escape(domain_filters[0]) + r"(?=[/\s)]|$)", query, re.I)
        search_query = query + (" (" + site_filter + ")" if site_filter and not already_scoped else "")
        # Use the standard ten-result search tier, never an automatic larger
        # tier, pagination, retries on denial, or a source/account fallback.
        payload = {"q": search_query, "num": min(max(limit, 1), 10), "gl": "cn" if language == "zh" else "us"}
        if language != "any":
            payload["hl"] = "zh-cn" if language == "zh" else "en"
        try:
            body = await self.request("POST", "https://google.serper.dev/search",
                headers={"X-API-KEY": self.settings.serper_api_key}, json=payload)
        except SearchError:
            if getattr(self, "quota_exhausted", False):
                if self.last_requests:
                    self.last_requests[-1]["error_code"] = "quota_exhausted"
                raise SearchError("quota_exhausted", "Serper 额度已用尽，已停止该来源；未启用付费服务") from None
            raise
        finally:
            for trace in self.last_requests:
                trace.update(auth_mode=self.auth_mode, result_limit=payload["num"])
        credits = body.get("credits")
        if (isinstance(credits, (int, float)) and not isinstance(credits, bool)
                and 0 <= credits <= 1_000_000_000 and math.isfinite(credits)):
            self.last_requests[-1]["api_credits"] = credits
        audit = {}
        items = parse_candidates(body["results"], self.name, query, min(limit, 10), domain_filters, audit=audit)
        self.last_requests[-1].update(raw_candidate_count=len(body["results"]), candidate_count=len(items), **audit)
        return items


def build_provider(settings: Settings, *, fetcher=None, store=None, provider_name: str | None = None) -> SearchProvider:
    selected = provider_name or settings.search_provider
    if selected == "searxng":
        return SearXNGProvider(settings)
    if selected == "tavily":
        return TavilyProvider(settings)
    if selected == "serper":
        return SerperProvider(settings)
    if selected == "official_sitemap":
        from .official_sitemap import OfficialSitemapProvider
        return OfficialSitemapProvider(settings, fetcher=fetcher, store=store)
    raise SearchError("configuration_error", "SEARCH_PROVIDER 只支持 searxng、tavily、serper 或 official_sitemap")
