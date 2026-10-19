"""Bounded discovery from freeCodeCamp's public HTML article/tag directory.

Only observed article-card links become candidates. A directory/tag is never
video or teaching evidence; the independent detail and ranking gates still run.
No private API, guessed article/video URL, browser, playback or model is used.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .config import Settings
from .extractor import detect_access_page
from .fetcher import Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER, retry_after_seconds, utcnow
from .models import Candidate
from .providers import SearchBudgetReached, SearchError
from .url_utils import UnsafeURL, normalize_url


ORIGIN = "https://www.freecodecamp.org"
VIDEO_DIRECTORY = ORIGIN + "/news/tag/youtube/"
VERSION = 1
MAX_INDEX_BYTES = 750_000
MAX_TOTAL_BYTES = 1_550_000


def index_url(value: str) -> str | None:
    try:
        url = normalize_url(value)
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname == "www.freecodecamp.org" and
            parts.port in (None, 443) and not parts.query and not parts.fragment and
            (parts.path == "/robots.txt" or re.fullmatch(r"/news/tag/[a-z][a-z0-9-]{1,39}/", parts.path))):
            return url
    except (ValueError, TypeError, UnsafeURL):
        pass
    return None


def article_url(value: str, base: str) -> str | None:
    try:
        url = normalize_url(urljoin(base, value))
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname == "www.freecodecamp.org" and
            parts.port in (None, 443) and not parts.query and not parts.fragment and
            re.fullmatch(r"/news/[a-z0-9][a-z0-9-]{0,239}/", parts.path)):
            return url
    except (ValueError, TypeError, UnsafeURL):
        pass
    return None


def parse_index(body: bytes, source_url: str) -> dict:
    if not index_url(source_url) or "/news/tag/" not in source_url or len(body) > MAX_INDEX_BYTES or b"\x00" in body:
        raise SearchError("invalid_response", "公开目录响应超过范围或大小限制")
    soup = BeautifulSoup(body, "html.parser")
    access = detect_access_page(soup, source_url)
    if access in {"captcha", "access_denied", "login_required"}:
        raise FetchStopped(access, "公开目录显示访问限制，停止该来源")
    cards, seen = [], set()
    for article in soup.select("article.post-card")[:60]:
        anchor = article.select_one("h2.post-card-title a[href], h3.post-card-title a[href]")
        if anchor is None:
            continue
        url = article_url(str(anchor.get("href", "")), source_url)
        title = " ".join(anchor.get_text(" ", strip=True).split())[:600]
        if not url or url in seen or not title:
            continue
        seen.add(url)
        excerpt = article.select_one(".post-card-excerpt")
        tags = [" ".join(node.get_text(" ", strip=True).split()).lstrip("#")[:100]
                for node in article.select(".post-card-tags a")[:6]]
        cards.append({"url": url, "title": title, "snippet": excerpt.get_text(" ", strip=True)[:1600] if excerpt else "",
                      "tags": tags})
    tags = []
    for anchor in soup.select("a[href]")[:1000]:
        observed = index_url(urljoin(source_url, str(anchor.get("href", ""))))
        if observed and observed not in tags and "/tag/" in observed:
            tags.append(observed)
    return {"source_url": source_url, "source_sha256": hashlib.sha256(body).hexdigest(),
            "observed_at": utcnow(), "cards": cards, "tags": tags[:100], "cache_hit": False}


class PublicCatalogProvider:
    name = "public_catalog"
    cache_identity = "freecodecamp-public-tag-cards-v1"

    def __init__(self, settings: Settings, *, fetcher=None, store=None):
        self.settings, self.store = settings, store
        self.fetcher = fetcher or Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
            timeout_seconds=settings.fetch_timeout_seconds, max_retries=0, dns_resolver=settings.dns_resolver,
            global_concurrency=settings.global_concurrency, min_interval_seconds=settings.fetch_min_interval_seconds,
            denied_hosts=settings.denied_fetch_hosts, allowed_restricted_hosts=settings.allowed_restricted_hosts))
        self.memory_cache = {}
        self.request_hook = self.dns_request_hook = self.budget_check_hook = None
        self.last_requests, self.last_dns_requests, self.last_warnings = [], [], []
        self.last_discovery = {}
        self.last_status = "configured"
        self._total_bytes = 0
        self._hard_stopped = None
        self._cooldown_until = 0.0
        self._last_rate_limit_delay = None

    def _key(self, url):
        fields = {"url": url, "version": VERSION, "ttl": self.settings.search_cache_ttl,
            "enabled": self.settings.fetch_enabled, "dns": self.settings.dns_resolver,
            "denied": self.settings.denied_fetch_hosts, "allowed": self.settings.allowed_restricted_hosts}
        if self.store:
            return self.store.cache_key("public_catalog", fields)
        import json
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

    def _get(self, url):
        key = self._key(url)
        row = self.store.cache_get(key) if self.store else None
        if row:
            return deepcopy(row["data"]) | {"cache_hit": True}
        row = self.memory_cache.get(key)
        return deepcopy(row[1]) | {"cache_hit": True} if row and row[0] > time.monotonic() else None

    def _put(self, url, value):
        ttl = self.settings.search_cache_ttl
        if ttl <= 0:
            return
        key = self._key(url)
        if self.store:
            self.store.cache_set(key, "public_catalog", value, ttl)
        else:
            if len(self.memory_cache) >= 32:
                self.memory_cache.pop(next(iter(self.memory_cache)))
            self.memory_cache[key] = (time.monotonic() + ttl, deepcopy(value))

    async def _before_resolve(self, url):
        if not index_url(url):
            raise FetchStopped("scope_blocked", "公开目录发现仅限已声明同站标签HTML与robots")
        if self.budget_check_hook:
            await self.budget_check_hook()

    async def _target_count(self):
        if self.request_hook:
            await self.request_hook()

    async def _dns_count(self):
        if self.budget_check_hook:
            await self.budget_check_hook()
        if self.dns_request_hook:
            await self.dns_request_hook()

    def _trace(self, event):
        if event["event"] == "http_started":
            self.last_requests.append({"provider": self.name, "url": event["url"], "started_at": event["at"],
                                       "kind": event.get("kind"), "status": "running"})
        elif event["event"] in {"http_completed", "http_failed", "http_stopped", "http_cancelled"}:
            row = next((row for row in reversed(self.last_requests) if row["url"] == event["url"]), None)
            if row is not None:
                row.update(status="completed" if event["event"] == "http_completed" else "failed", finished_at=event["at"])
                if "status_code" in event:
                    row["http_status"] = event["status_code"]

    def _capture(self, response, _kind):
        self._total_bytes += len(response.body)
        if response.status_code == 429 or response.status_code == 503 and "retry-after" in response.headers:
            self._last_rate_limit_delay = retry_after_seconds(response.headers.get("retry-after", ""))
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + self._last_rate_limit_delay)
        if self.last_requests:
            self.last_requests[-1].update(response_bytes=len(response.body), source_sha256=hashlib.sha256(response.body).hexdigest())

    def _select_candidates(self, documents, query, tool, limit):
        wanted = set(re.findall(r"[a-z][a-z0-9_.+#-]*", query.casefold())) - {"video", "tutorial", "course", "lesson", tool.casefold()}
        rows = []
        for document in documents:
            for card in document["cards"]:
                observed = " ".join([card["title"], card["snippet"], *card["tags"]])
                if not re.search(r"(?<![A-Za-z0-9_.+#])" + re.escape(tool) + r"(?![A-Za-z0-9_.+#])", observed, re.I):
                    continue
                words = set(re.findall(r"[a-z][a-z0-9_.+#-]*", observed.casefold()))
                # Directory placement/course wording only prioritize a bounded
                # detail probe. They never establish video identity or coverage.
                priority = (len(words & wanted), document["source_url"] == VIDEO_DIRECTORY,
                            bool(re.search(r"\b(?:course|tutorial|learn|crash course)\b", card["title"], re.I)))
                rows.append((priority, card, document))
        seen, results = set(), []
        for _, card, document in sorted(rows, key=lambda row: (tuple(-int(part) for part in row[0]), row[1]["url"])):
            if card["url"] in seen or len(results) >= min(6, limit):
                continue
            seen.add(card["url"])
            results.append(Candidate(id=hashlib.sha256((self.name + "\0" + query + "\0" + card["url"]).encode()).hexdigest()[:24],
                title=card["title"], url=card["url"], snippet=card["snippet"], source=self.name, query=query,
                discovery_evidence={"kind": "public_catalog_link", "source_url": document["source_url"],
                    "source_sha256": document["source_sha256"], "observed_at": document["observed_at"],
                    "cache_hit": document["cache_hit"], "observed_url": card["url"], "observed_tags": card["tags"],
                    "confidence": "low", "independent_detail_required": True}))
        return results

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str], *,
                     original_point: str | None = None, technical_version: str = "") -> list[Candidate]:
        self.last_requests, self.last_dns_requests, self.last_warnings = [], [], []
        self._total_bytes = 0
        self._last_rate_limit_delay = None
        self.last_discovery = {"scope": "public HTML tag cards; detail verification required", "indexes": []}
        if domain_filters and not any("www.freecodecamp.org" == domain or "www.freecodecamp.org".endswith("." + domain) for domain in domain_filters):
            return []
        if not self.settings.fetch_enabled or limit <= 0:
            return []
        if self._hard_stopped or self._cooldown_until > time.monotonic():
            self.last_status = "fault"
            self.last_discovery.update(source_stopped=True, stop_reason=self._hard_stopped or "rate_limited",
                                       cooldown_remaining_seconds=max(0, round(self._cooldown_until - time.monotonic(), 3)))
            raise SearchError("access_denied", "公开目录来源已停止或处于站点冷却期；未换路径重试")
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9+#._-]{1,40})(?![A-Za-z0-9_])", original_point or query)
        if match is None:
            return []
        tool = match[1]
        # This is a public category route, never a candidate/video address. A
        # 404 yields no cards. Candidate links must still be observed in HTML.
        tool_index = ORIGIN + "/news/tag/" + tool.lower() + "/"
        indexes = [tool_index, VIDEO_DIRECTORY] if index_url(tool_index) else [VIDEO_DIRECTORY]
        documents, results = [], []
        token = NETWORK_OBSERVER.set({"before_resolve": self._before_resolve, "before_target_http": self._target_count,
            "before_dns_http": self._dns_count, "target_trace": self._trace, "dns_trace": self.last_dns_requests.append,
            "response": self._capture, "response_byte_limit": lambda: min(MAX_INDEX_BYTES, MAX_TOTAL_BYTES - self._total_bytes), "max_retries": 0})
        try:
            for url in dict.fromkeys(indexes):
                document = self._get(url)
                if document is None:
                    try:
                        response = await self.fetcher.fetch(url)
                    except FetchStopped as exc:
                        # A failed category request may still leave the second
                        # public index available. Access restrictions/cooldowns
                        # must stop the source, never trigger alternate paths.
                        if exc.status in {"timeout", "network_error"} and url != indexes[-1]:
                            self.last_warnings.append({"code": "search_unavailable", "message": "公开分类目录网络超时或连接失败，继续有界公开索引；未绕过访问限制"})
                            self.last_discovery["indexes"].append({"source_url": url, "status": exc.status})
                            continue
                        raise
                    if response.status_code == 404:
                        document = {"source_url": response.url, "source_sha256": hashlib.sha256(response.body).hexdigest(),
                                    "observed_at": utcnow(), "cards": [], "tags": [], "cache_hit": False}
                    elif response.status_code == 200:
                        if not any(content_type in response.headers.get("content-type", "").lower()
                                   for content_type in ("text/html", "application/xhtml+xml")):
                            raise SearchError("invalid_response", "公开目录未返回HTML，停止当前发现")
                        document = parse_index(response.body, response.url)
                    else:
                        raise SearchError("access_denied" if response.status_code in {401, 403, 429} else "search_unavailable", "公开目录当前不可读取，未绕过访问限制")
                    self._put(url, document)
                documents.append(document)
                self.last_discovery["indexes"].append({key: value for key, value in document.items() if key not in {"cards", "tags"}} |
                    {"observed_card_count": len(document["cards"])})
            results = self._select_candidates(documents, query, tool, limit)
            self.last_status = "available"
            self.last_discovery["candidate_count"] = len(results)
            return results
        except SearchBudgetReached as exc:
            exc.partial_candidates = [*self._select_candidates(documents, query, tool, limit), *exc.partial_candidates]
            self.last_discovery["budget_stopped"] = True
            raise
        except FetchStopped as exc:
            self.last_status = "fault"
            restricted = {"robots_blocked", "site_policy_blocked", "access_denied", "rate_limited", "captcha", "login_required"}
            code = "access_denied" if exc.status in restricted else "search_unavailable"
            if exc.status == "rate_limited":
                if self._last_rate_limit_delay is None:
                    self._cooldown_until = max(self._cooldown_until, time.monotonic() + 60)
            elif exc.status in restricted:
                self._hard_stopped = exc.status
            if exc.status in restricted:
                self.last_discovery.update(source_stopped=True, stop_reason=exc.status)
            partial = self._select_candidates(documents, query, tool, limit)
            if partial:
                self.last_warnings = [{"code": code, "message": "公开目录后续读取受限；仅保留此前真实观察，未绕过限制"}]
                return partial
            raise SearchError(code, "公开目录读取受限或失败，未使用隐藏API或替代访问") from None
        except SearchError as exc:
            self.last_status = "fault"
            if exc.code == "access_denied":
                self._hard_stopped = "http_access_denied"
                self.last_discovery.update(source_stopped=True, stop_reason=self._hard_stopped)
            partial = self._select_candidates(documents, query, tool, limit)
            if partial:
                self.last_warnings = [{"code": exc.code, "message": exc.message}]
                return partial
            raise
        finally:
            NETWORK_OBSERVER.reset(token)
