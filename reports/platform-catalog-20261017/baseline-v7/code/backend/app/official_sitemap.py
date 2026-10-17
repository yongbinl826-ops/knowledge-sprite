"""Optional MIT index discovery. No reports, seeds, guessed course URLs or browser.

Sitemap URL words are low-confidence recall evidence only. JobService requires
independent fetched page coverage before displaying these candidates.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import re
import time
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from .config import Settings
from .fetcher import Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER, utcnow
from .models import Candidate
from .providers import SearchError
from .ranking import tokens
from .url_utils import UnsafeURL, normalize_url

ENTRY = "https://ocw.mit.edu/search/"
ORIGIN = "https://ocw.mit.edu"
VERSION = 1
MAX_XML_BYTES = 1_000_000
MAX_LOCATIONS = 10_000


def official_url(value: str) -> str | None:
    try:
        result = normalize_url(value)
        parts = urlsplit(result)
        if parts.scheme == "https" and parts.hostname == "ocw.mit.edu" and parts.port in (None, 443) and not parts.query:
            return result
    except (TypeError, ValueError, UnsafeURL):
        pass
    return None


def topic_terms(value: str) -> set[str]:
    # Use the original user point, never template stripping or model expansions.
    # Preserve standalone version numerals as well as the ranker's language tokens.
    value = re.sub(r"\bpython(?=\d+(?:\.\d+)*\b)", "python ", value, flags=re.I)
    numeric = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)*(?![\w.])", value))
    versioned_names = set(re.findall(r"\b[a-z][a-z0-9.+#]*\d[a-z0-9.+#]*", value.lower()))
    return tokens(value) | numeric | versioned_names


def path_words(url: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    # An observed path yields lexical words, not a fetched page title.
    return re.sub(r"[-_/]+", " ", unquote("/".join(parts[1:])))


def covers_original_topic(topic: str, text: str, version: str = "") -> bool:
    wanted = topic_terms(topic)
    if not wanted or not wanted <= topic_terms(text):
        return False
    normalized_text = re.sub(r"\bpython(?=\d+(?:\.\d+)*\b)", "python ", text, flags=re.I)
    if version.strip() and not re.search(r"(?<![\w.])" + re.escape(version.strip()) + r"(?![\w.])", normalized_text, re.I):
        return False
    return True


def parse_sitemap(body: bytes, expected: str) -> list[str]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SearchError("invalid_response", "官方站点地图必须为 UTF-8 XML") from None
    if len(body) > MAX_XML_BYTES or "\x00" in text or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise SearchError("invalid_response", "官方站点地图超过限制或含不支持的 XML 声明")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        raise SearchError("invalid_response", "官方站点地图 XML 无法解析") from None
    if root.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}" + expected:
        raise SearchError("invalid_response", "官方站点地图类型不符合预期")
    group = "sitemap" if expected == "sitemapindex" else "url"
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    nodes = root.findall(namespace + group)
    if len(nodes) > MAX_LOCATIONS:
        raise SearchError("invalid_response", "官方站点地图条目超过预算")
    locations = []
    for node in nodes:
        values = node.findall(namespace + "loc")
        if len(values) == 1 and values[0].text:
            value = official_url(values[0].text.strip())
            if value and value not in locations:
                locations.append(value)
    return locations


class OfficialSitemapProvider:
    name = "official_sitemap"
    cache_identity = "mit-robots-declared-sitemaps-v1"

    def __init__(self, settings: Settings, *, fetcher: Fetcher | None = None, store=None):
        self.settings = settings
        self.fetcher = fetcher or Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
            timeout_seconds=settings.fetch_timeout_seconds, max_retries=0,
            global_concurrency=settings.global_concurrency, dns_resolver=settings.dns_resolver,
            min_interval_seconds=settings.fetch_min_interval_seconds, denied_hosts=settings.denied_fetch_hosts,
            allowed_restricted_hosts=settings.allowed_restricted_hosts,
            phased_timeouts=settings.fetch_phased_timeouts,
            body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
            body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
            body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
        self.store = store
        self.memory_cache: dict[str, tuple[float, dict]] = {}
        self.request_hook = None
        self.dns_request_hook = None
        self.budget_check_hook = None
        self.last_status = "configured"
        self.last_requests: list[dict] = []
        self.last_dns_requests: list[dict] = []
        self.last_warnings: list[dict] = []
        self.last_discovery: dict = {}
        self._captured_robots: list[dict] = []
        self._hard_stopped = False
        self._stopped_code = None

    def _key(self, url):
        data = {"url": url, "version": VERSION, "max_bytes": MAX_XML_BYTES,
            "ttl": self.settings.official_sitemap_cache_ttl,
            "dns": self.settings.dns_resolver, "enabled": self.settings.fetch_enabled,
            "denied_hosts": self.settings.denied_fetch_hosts,
            "allowed_hosts": self.settings.allowed_restricted_hosts}
        if self.store:
            return self.store.cache_key("official_sitemap", data)
        import json
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _get(self, url):
        key = self._key(url)
        if self.store:
            cached = self.store.cache_get(key)
            return deepcopy(cached["data"]) | {"cache_hit": True} if cached else None
        row = self.memory_cache.get(key)
        return deepcopy(row[1]) | {"cache_hit": True} if row and row[0] > time.monotonic() else None

    def _put(self, url, value):
        ttl = self.settings.official_sitemap_cache_ttl
        if ttl <= 0:
            return
        key = self._key(url)
        if self.store:
            self.store.cache_set(key, "official_sitemap", value, ttl)
        else:
            if len(self.memory_cache) >= 64:
                self.memory_cache.pop(next(iter(self.memory_cache)))
            self.memory_cache[key] = (time.monotonic() + ttl, deepcopy(value))

    async def _before_resolve(self, url):
        if not official_url(url):
            raise FetchStopped("scope_blocked", "官方发现仅允许 MIT 同源 HTTPS 路径")
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
            self.last_requests.append({"provider": self.name, "started_at": event["at"], "url": event["url"],
                "kind": event.get("kind"), "status": "running", "retry_index": event.get("attempt", 0)})
        elif event["event"] in {"http_completed", "http_failed", "http_stopped", "http_cancelled"}:
            record = next((row for row in reversed(self.last_requests) if row["url"] == event["url"]), None)
            if record:
                record.update(finished_at=event["at"], status={"http_completed": "completed", "http_cancelled": "cancelled"}.get(event["event"], "failed"))
                if "status_code" in event:
                    record["http_status"] = event["status_code"]
                if "error_type" in event:
                    record["error_type"] = event["error_type"]
                if "bytes_read" in event:
                    record["bytes_read"] = event["bytes_read"]

    def _capture(self, response, kind):
        if self.last_requests:
            self.last_requests[-1]["source_sha256"] = hashlib.sha256(response.body).hexdigest()
        if kind == "robots" and response.status_code == 200:
            self._captured_robots.append({"url": response.url, "body": response.body})

    @staticmethod
    def _document(response, locations):
        return {"source_url": response.url, "source_sha256": hashlib.sha256(response.body).hexdigest(),
            "observed_at": utcnow(), "locations": locations, "cache_hit": False}

    async def _index(self):
        saved = self._get(ORIGIN + "/robots.txt")
        if saved:
            declaration = saved
        else:
            await self.fetcher._robots_for(ENTRY)
            if self._captured_robots:
                source = self._captured_robots[-1]
            else:
                # Another task may have already parsed robots. Fetch its real body
                # once instead of inventing or reconstructing Sitemap declarations.
                response = await self.fetcher.fetch(ORIGIN + "/robots.txt")
                if response.status_code in {401, 403, 429}:
                    raise SearchError("access_denied", "官方 robots 返回访问限制")
                if response.status_code != 200:
                    raise SearchError("search_unavailable", "官方 robots 未返回可读取声明")
                source = {"url": response.url, "body": response.body}
            sitemaps = []
            for line in source["body"].decode("utf-8-sig", errors="replace").splitlines():
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0].strip().lower() == "sitemap":
                    value = official_url(parts[1].strip())
                    if value and value not in sitemaps:
                        sitemaps.append(value)
            declaration = {"source_url": source["url"], "source_sha256": hashlib.sha256(source["body"]).hexdigest(),
                "observed_at": utcnow(), "locations": sitemaps[:10], "cache_hit": False}
            self._put(ORIGIN + "/robots.txt", declaration)
        self.last_discovery["robots"] = declaration
        if not declaration["locations"]:
            return None
        root_url = declaration["locations"][0]
        cached = self._get(root_url)
        if cached:
            return cached
        response = await self.fetcher.fetch(root_url)
        if response.status_code in {401, 403, 429}:
            raise SearchError("access_denied", "官方站点地图返回访问限制")
        if response.status_code != 200:
            raise SearchError("search_unavailable", "官方站点地图读取失败，未尝试替代入口")
        document = self._document(response, parse_sitemap(response.body, "sitemapindex"))
        self._put(root_url, document)
        return document

    async def search(self, query: str, language: str, limit: int, domain_filters: list[str], *, technical_version: str = "") -> list[Candidate]:
        self.last_requests, self.last_dns_requests, self.last_warnings = [], [], []
        self.last_discovery = {"topic": query, "technical_version": technical_version, "scope": "MIT-only URL-word discovery; independent page evidence required", "children": []}
        self._captured_robots = []
        if domain_filters and not any("ocw.mit.edu" == domain or "ocw.mit.edu".endswith("." + domain) for domain in domain_filters):
            self.last_discovery["stop_reason"] = "domain_filter_excludes_official_source"
            return []
        if self._stopped_code:
            raise SearchError(self._stopped_code, "官方来源此前读取受限或失败，当前服务生命周期内不再请求")
        if not self.settings.fetch_enabled:
            raise SearchError("configuration_error", "官方站点地图发现需要启用允许的公开元信息读取")
        wanted = topic_terms(query)
        if not wanted:
            return []
        token = NETWORK_OBSERVER.set({"before_resolve": self._before_resolve,
            "before_target_http": self._target_count, "before_dns_http": self._dns_count,
            "target_trace": self._trace, "dns_trace": self.last_dns_requests.append, "response": self._capture, "max_retries": 0})
        try:
            self.fetcher._site_policy(ENTRY)
            if "ocw.mit.edu" in self.fetcher._blocked_hosts:
                raise FetchStopped("access_denied", "官方来源此前已有明确访问限制")
            index = await self._index()
            self.last_discovery["index"] = ({k: v for k, v in index.items() if k != "locations"} | {"location_count": len(index["locations"])}) if index else None
            if not index:
                self.last_status = "available"
                return []
            # Never widen a fine-grained point to a generic subject. Only complete
            # point-word coverage in the observed course slug opens a child index.
            children = [url for url in index["locations"] if re.fullmatch(r"/courses/[^/]+/sitemap\.xml", urlsplit(url).path)
                and covers_original_topic(query, path_words(url), technical_version)]
            children.sort(key=lambda url: (len(topic_terms(path_words(url)) - wanted), url))
            results = []
            for child in children[:self.settings.official_sitemap_children_per_query]:
                document = self._get(child)
                if not document:
                    response = await self.fetcher.fetch(child)
                    if response.status_code in {401, 403, 429}:
                        raise SearchError("access_denied", "官方课程子站点地图返回访问限制")
                    if response.status_code != 200:
                        raise SearchError("search_unavailable", "官方课程子站点地图读取失败")
                    document = self._document(response, parse_sitemap(response.body, "urlset"))
                    self._put(child, document)
                self.last_discovery["children"].append({k: v for k, v in document.items() if k != "locations"} | {"location_count": len(document["locations"])})
                course_path = urlsplit(child).path.rsplit("/", 1)[0] + "/"
                observed = [url for url in document["locations"] if urlsplit(url).path.startswith(course_path)
                    and not re.search(r"\.(?:xml|pdf|zip|mp4|mp3|jpg|png|webm|csv)$", urlsplit(url).path, re.I)
                    and covers_original_topic(query, path_words(url), technical_version)]
                # Prefer an observed course entry, then a shallow actual resource.
                observed.sort(key=lambda url: (urlsplit(url).path != course_path, urlsplit(url).path.count("/"), url))
                for url in observed[:min(1, max(0, limit - len(results)))]:
                    lexical = path_words(url).strip()
                    evidence = {"kind": "sitemap_loc", "source_url": document["source_url"], "source_sha256": document["source_sha256"],
                        "observed_url": url, "observed_at": document["observed_at"], "cache_hit": document["cache_hit"],
                        "index_url": index["source_url"], "index_sha256": index["source_sha256"],
                        "robots_url": self.last_discovery["robots"]["source_url"], "title_basis": "url_path_words", "confidence": "low"}
                    results.append(Candidate(id=hashlib.sha256(f"{self.name}\0{query}\0{url}".encode()).hexdigest()[:24],
                        title=lexical[:600], url=url, snippet="官方站点地图中实际出现的链接；名称由 URL 路径词推得，页面标题与教学覆盖尚未核验。来源：" + document["source_url"],
                        source=self.name, query=query, discovery_evidence=evidence))
                if len(results) >= limit:
                    break
            self.last_status = "available"
            self.last_discovery.update(matching_child_indexes=len(children), candidate_count=len(results))
            return results
        except FetchStopped as exc:
            self.last_status = "fault"
            if exc.status in {"robots_blocked", "site_policy_blocked", "access_denied", "rate_limited", "captcha"}:
                self._hard_stopped = True
            code = "access_denied" if self._hard_stopped else "search_timeout" if exc.status in {"timeout", "dns_error"} else "search_unavailable"
            self._stopped_code = code
            raise SearchError(code, "官方发现读取受限或失败，已保留请求记录；未绕过或更换入口") from None
        except SearchError as exc:
            self.last_status = "fault"
            self._stopped_code = exc.code
            raise
        finally:
            NETWORK_OBSERVER.reset(token)
