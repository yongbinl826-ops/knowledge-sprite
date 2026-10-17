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
from .url_utils import UnsafeURL, normalize_url


class SearchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


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
        results.append(Candidate(id=hashlib.sha256(f"{provider}\0{query}\0{url}".encode()).hexdigest()[:24],
                                 title=title[:600], url=url[:4096], snippet=snippet[:4000], source=provider, query=query,
                                 source_engines=engines, resource_type_hint="video" if video_result else "unknown",
                                 type_source="search_template" if video_result else None))
        record(index, "accepted", url)
    return results


class HTTPProvider:
    name = "unknown"
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings, self.client = settings, client
        self.paused_until = 0.0
        self.access_denied = False
        self.last_request_started = 0.0
        self.last_status = "configured"
        self.last_warnings: list[dict] = []
        self.last_requests: list[dict] = []
        self.request_hook: Callable[[], Awaitable[None]] | None = None

    @staticmethod
    async def _bounded_response(client, method, url, trace, **kwargs):
        # Bound the actual read, not just the already-buffered response. Search
        # endpoints are trusted server configuration; their content is untrusted.
        kwargs["headers"] = {**kwargs.get("headers", {}), "Accept-Encoding": "identity"}
        async with client.stream(method, url, **kwargs) as response:
            trace["http_status"] = response.status_code
            if response.status_code != 200:
                return httpx.Response(response.status_code, headers=response.headers, content=b"")
            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise SearchError("invalid_response", "搜索响应使用非预期压缩，未解压读取")
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(body) + len(chunk) > 2_000_000:
                    raise SearchError("invalid_response", "搜索响应超过允许大小")
                body.extend(chunk)
            trace["response_bytes"] = len(body)
            return httpx.Response(response.status_code, headers=response.headers, content=bytes(body))

    async def request(self, method: str, url: str, **kwargs) -> dict:
        if self.access_denied:
            raise SearchError("access_denied", "搜索服务此前拒绝访问；请修正权限或配置后重启，未再次请求")
        if time.monotonic() < self.paused_until:
            raise SearchError("rate_limited", "搜索来源仍在 Retry-After 暂停期内")
        for attempt in range(self.settings.search_max_retries + 1):
            interval = self.settings.search_min_interval_seconds - (time.monotonic() - self.last_request_started)
            if interval > 0:
                await asyncio.sleep(interval)
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
                body = response.json()
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
        primary = self.settings.searxng_video_engines if video_intent and self.settings.searxng_video_engines else self.settings.searxng_engines
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
            active = [e for e in engines if time.monotonic() >= self.engine_pauses.get(e, 0)]
            if engines and not active:
                self.last_warnings.append({"code": "upstream_engine_failed", "engine": ",".join(engines),
                    "reason_code": "suspended", "reason": "suspended", "message": "该引擎组仍在限流或访问拒绝暂停期，未重试"})
                continue
            params = {"q": query, "format": "json", "language": {"zh": "zh-CN", "en": "en", "any": "all"}[language]}
            if active:
                params["engines"] = ",".join(active)
            try:
                body = await self.request("GET", self.settings.searxng_url.rstrip("/") + "/search", params=params)
            except SearchError as exc:
                # Authentication, service-wide denial and rate limiting are hard stops.
                if exc.code not in {"search_timeout", "search_unavailable"} or index == len(groups) - 1:
                    raise
                self.last_warnings.append({"code": exc.code, "engine": ",".join(active) or "instance_defaults", "message": exc.message})
                continue
            failures = self._failures(body)
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
                                         candidate_count=len(items), fallback=index > 0, **audit)
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
    async def search(self, query: str, language: str, limit: int, domain_filters: list[str]) -> list[Candidate]:
        self.last_requests = []
        self.last_warnings = []
        if not self.settings.tavily_api_key:
            raise SearchError("configuration_error", "已选择 Tavily，但尚未配置 TAVILY_API_KEY")
        payload = {"query": query, "max_results": min(limit, 20), "include_answer": False, "include_raw_content": False,
                   "search_depth": "basic", "auto_parameters": False}
        if language != "any":
            payload["language"] = "zh-cn" if language == "zh" else "en"
            payload["filter_by_language"] = False
        if domain_filters:
            payload["include_domains"] = domain_filters
        body = await self.request("POST", "https://api.tavily.com/search", headers={"Authorization": "Bearer " + self.settings.tavily_api_key}, json=payload)
        audit = {}
        items = parse_candidates(body["results"], self.name, query, limit, domain_filters, audit=audit)
        self.last_requests[-1].update(raw_candidate_count=len(body["results"]), candidate_count=len(items), **audit)
        return items


def build_provider(settings: Settings, *, fetcher=None, store=None) -> SearchProvider:
    if settings.search_provider == "searxng":
        return SearXNGProvider(settings)
    if settings.search_provider == "tavily":
        return TavilyProvider(settings)
    if settings.search_provider == "official_sitemap":
        from .official_sitemap import OfficialSitemapProvider
        return OfficialSitemapProvider(settings, fetcher=fetcher, store=store)
    raise SearchError("configuration_error", "SEARCH_PROVIDER 只支持 searxng、tavily 或 official_sitemap")
