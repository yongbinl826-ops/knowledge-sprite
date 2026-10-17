"""Bounded static page fetching with DNS pinning, independent site policy and robots."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from .extractor import MetadataExtractor
from .url_utils import UnsafeURL, assert_public_ip, host_matches, normalize_url, platform_for_url


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FetcherConfig:
    enabled: bool = True
    max_bytes: int = 1_000_000
    timeout_seconds: float = 8.0
    max_redirects: int = 3
    max_retries: int = 1
    user_agent: str = "ProjectLearningDiscovery/0.1"
    allowed_restricted_hosts: tuple[str, ...] = ()
    denied_hosts: tuple[str, ...] = ()
    global_concurrency: int = 5
    robots_ttl_seconds: int = 3600
    dns_resolver: str = "system"


@dataclass
class HTTPResult:
    status_code: int
    headers: dict[str, str]
    body: bytes
    url: str


class FetchStopped(Exception):
    def __init__(self, status: str, message: str, policy: dict | None = None):
        super().__init__(message)
        self.status = status
        self.policy = policy


PLATFORM_POLICY_REVIEWS = {
    "youtube": {
        "status": "explicit_permission_required", "reviewed_at": "2026-10-13",
        "source_url": "https://www.youtube.com/static?template=terms",
        "terms_date": "2023-12-15",
        "basis": "YouTube 官方服务条款 Permissions and Restrictions 第3项限制自动访问，例外为遵守 robots.txt 的公开搜索引擎或事先取得书面许可；本项目不是公开搜索引擎且未取得书面许可。",
    },
    "bilibili": {
        "status": "explicit_permission_required", "reviewed_at": "2026-10-13",
        "source_url": "https://www.bilibili.com/blackboard/protocal/licence.html",
        "basis": "官方用户使用协议第5.6(3)条要求自动获取平台服务、内容或数据前取得明确书面许可；本项目未取得该许可。",
    },
    "icourse163": {
        "status": "unreviewed_permission_scope", "reviewed_at": "2026-10-13",
        "source_url": "https://www.icourse163.org/topics/mooc_privacy_service/",
        "basis": "官方协议第3.1条允许浏览课程信息，第5.2.7条限制未经许可的第三方工具接入；本项目自动元信息采集的许可范围尚未确认。",
    },
    "xuetangx": {
        "status": "explicit_scraping_prohibition", "reviewed_at": "2026-10-13",
        "source_url": "https://www.xuetangx.com/app/protocol", "terms_date": "2021-01-05",
        "section": "网络行为准则",
        "basis": "官方用户协议“网络行为准则”明确约定不抓取和批量下载本产品内容；当前停止自动页面采集，保留搜索发现证据。公开课程可供用户访问不等于许可自动抓取。",
    },
}


async def public_addresses(url: str, timeout: float = 8) -> list[str]:
    """Validate every DNS answer, then pass the numeric addresses to the transport."""
    url = normalize_url(url)
    parts = urlsplit(url)
    try:
        values = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM), timeout)
    except (socket.gaierror, asyncio.TimeoutError) as exc:
        raise FetchStopped("dns_error", "公网域名解析失败或超时") from exc
    addresses = list(dict.fromkeys(assert_public_ip(item[4][0]) for item in values))
    if not addresses:
        raise FetchStopped("dns_error", "域名没有可用地址")
    return addresses


class CloudflareDoHResolver:
    """Optional fixed trusted DNS transport; never configurable from request data.

    Uses the documented JSON API, queries A + AAAA, validates all address answers,
    and has no fallback or redirect. The local DNS/proxy configuration is unchanged.
    https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
    """
    async def __call__(self, url: str, timeout: float = 8) -> list[str]:
        host = urlsplit(normalize_url(url)).hostname or ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return [assert_public_ip(host)]
        try:
            return await asyncio.wait_for(self._resolve(host, timeout), timeout)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, UnsafeURL):
                raise
            raise FetchStopped("dns_error", "Cloudflare DoH 解析失败或超时；未回退其他解析服务") from exc

    async def _resolve(self, host: str, timeout: float) -> list[str]:
        addresses: list[str] = []
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False,
                                     limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)) as client:
            for record_type in ("A", "AAAA"):
                async with client.stream("GET", "https://1.1.1.1/dns-query", params={"name": host, "type": record_type},
                                         headers={"Host": "cloudflare-dns.com", "Accept": "application/dns-json", "Accept-Encoding": "identity"},
                                         extensions={"sni_hostname": "cloudflare-dns.com"}) as response:
                    if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                        raise FetchStopped("dns_error", "Cloudflare DoH 未返回有效响应")
                    body = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=4096):
                        if len(body) + len(chunk) > 65536:
                            raise FetchStopped("dns_error", "Cloudflare DoH 响应超过预算")
                        body.extend(chunk)
                    payload = json.loads(body)
                    if not isinstance(payload, dict) or payload.get("Status") != 0 or payload.get("TC") is True:
                        raise FetchStopped("dns_error", "Cloudflare DoH 返回域名错误或不完整响应")
                    questions = payload.get("Question")
                    if not isinstance(questions, list) or not questions or not isinstance(questions[0], dict) or questions[0].get("name", "").rstrip(".").lower() != host:
                        raise FetchStopped("dns_error", "Cloudflare DoH 响应域名不一致")
                    answers = payload.get("Answer", [])
                    if not isinstance(answers, list):
                        raise FetchStopped("dns_error", "Cloudflare DoH 地址结构无效")
                    for answer in answers:
                        if isinstance(answer, dict) and answer.get("type") in {1, 28}:
                            addresses.append(assert_public_ip(answer.get("data", "")))
        if not addresses:
            raise FetchStopped("dns_error", "Cloudflare DoH 没有可用公网地址")
        return list(dict.fromkeys(addresses))


class PinnedHTTPClient:
    """A fresh numeric-IP connection per request; no proxy, cookies, or implicit redirects.

    HTTPX passes sni_hostname to httpcore for certificate validation against the
    original hostname. The TCP target is only the address already checked here.
    See https://www.encode.io/httpcore/extensions/#sni_hostname .
    """
    def __init__(self, config: FetcherConfig):
        self.config = config

    async def request(self, url: str, addresses: list[str], max_bytes: int) -> HTTPResult:
        normalized = normalize_url(url)
        original = httpx.URL(normalized)
        # Revalidate injected/resolved addresses so no later accidental caller bypasses the guard.
        address = assert_public_ip(addresses[0])
        pinned = original.copy_with(host=address, fragment=None)
        host = original.raw_host.decode("ascii")
        authority = f"[{host}]" if ":" in host else host
        if original.port not in {None, 80 if original.scheme == "http" else 443}:
            authority += f":{original.port}"
        headers = {"Host": authority, "User-Agent": self.config.user_agent,
                   "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                   "Accept-Encoding": "identity"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout_seconds),
                                     follow_redirects=False, trust_env=False,
                                     limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as client:
            async with client.stream("GET", pinned, headers=headers, extensions={"sni_hostname": host}) as response:
                response_headers = dict(response.headers)
                if response.status_code in {301, 302, 303, 307, 308, 401, 403, 404, 410, 429} or response.status_code >= 500:
                    return HTTPResult(response.status_code, response_headers, b"", normalized)
                if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    # Reject unsolicited compression to bound both decoded and wire bytes.
                    raise FetchStopped("unsupported_encoding", "站点忽略无压缩请求，已停止读取")
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise FetchStopped("too_large", "页面超过采集字节预算")
                body = bytearray()
                async for chunk in response.aiter_raw(chunk_size=16384):
                    if len(body) + len(chunk) > max_bytes:
                        raise FetchStopped("too_large", "页面超过采集字节预算")
                    body.extend(chunk)
                return HTTPResult(response.status_code, response_headers, bytes(body), normalized)


class RobotsRules:
    """Small conservative robots reader: groups, longest path, wildcard/$ and delay.

    Unknown directives convey no permission. Site policy remains an independent gate.
    Both raw and percent-decoded paths must be allowed to avoid encoded-path bypass.
    """
    def __init__(self, text: str, user_agent: str):
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        directives: list[tuple[str, str]] = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (piece.strip() for piece in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
            elif agents:
                directives.append((key, value))
        if agents:
            groups.append((agents, directives))
        token = user_agent.split("/", 1)[0].lower()
        specific = [(max((len(agent) for agent in agents if agent != "*" and agent in token), default=0), rules)
                    for agents, rules in groups]
        best = max((length for length, _ in specific), default=0)
        selected = [rules for length, rules in specific if length == best] if best else [rules for agents, rules in groups if "*" in agents]
        self.rules: list[tuple[bool, str]] = []
        self.delay = 0.0
        for directives in selected:
            for key, value in directives:
                if key in {"allow", "disallow"} and value:
                    self.rules.append((key == "allow", value))
                elif key == "crawl-delay":
                    try:
                        self.delay = max(self.delay, float(value))
                    except ValueError:
                        pass
                elif key == "request-rate" and re.fullmatch(r"\d+/\d+", value):
                    requests, seconds = map(int, value.split("/"))
                    if requests:
                        self.delay = max(self.delay, seconds / requests)

    def allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        for candidate in {path, unquote(path)}:
            matches = []
            for allow, rule in self.rules:
                for rule_variant in {rule, unquote(rule)}:
                    pattern = "^" + re.escape(rule_variant.rstrip("$")).replace(r"\*", ".*") + ("$" if rule_variant.endswith("$") else "")
                    if re.search(pattern, candidate):
                        matches.append((len(rule_variant.replace("*", "").rstrip("$")), allow))
            if matches and not max(matches)[1]:
                return False
        return True


class Fetcher:
    def __init__(self, config: FetcherConfig | None = None, *,
                 resolver: Callable[..., Awaitable[list[str]]] | None = None,
                 http_client: PinnedHTTPClient | None = None):
        self.config = config or FetcherConfig()
        if self.config.dns_resolver not in {"system", "cloudflare_doh"}:
            raise ValueError("dns_resolver must be system or cloudflare_doh")
        self.resolver = resolver or (CloudflareDoHResolver() if self.config.dns_resolver == "cloudflare_doh" else public_addresses)
        self.http = http_client or PinnedHTTPClient(self.config)
        self.extractor = MetadataExtractor()
        self._global = asyncio.Semaphore(max(1, min(5, self.config.global_concurrency)))
        self._hosts: dict[str, asyncio.Lock] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, tuple[float, RobotsRules]] = {}
        self._paused_until: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._delays: dict[str, float] = {}

    def _site_policy(self, url: str):
        host = urlsplit(url).hostname or ""
        if any(host_matches(host, domain) for domain in self.config.denied_hosts):
            raise FetchStopped("site_policy_blocked", "服务端管理员策略禁止本次采集；不代表已核验平台条款禁止")
        platform = "youtube" if any(host_matches(host, domain) for domain in ("youtube.com", "youtu.be")) else platform_for_url(url)
        review = PLATFORM_POLICY_REVIEWS.get(platform)
        if review and review["status"] in {"explicit_permission_required", "explicit_scraping_prohibition"}:
            # An unreviewed-host allow-list cannot override an explicit prohibition
            # or a permission requirement that this project has not satisfied.
            raise FetchStopped("site_policy_blocked", review["basis"], review)
        if review and not any(host_matches(host, domain) for domain in self.config.allowed_restricted_hosts):
            raise FetchStopped("policy_unreviewed", review["basis"] + " 当前仅保留搜索发现证据。", review)

    async def _request(self, url: str, max_bytes: int) -> HTTPResult:
        host = urlsplit(url).hostname or ""
        async with self._hosts.setdefault(host, asyncio.Lock()):
            if self._paused_until.get(host, 0) > time.monotonic():
                raise FetchStopped("rate_limited", "该站点处于 Retry-After 暂停期")
            delay = self._delays.get(host, 0)
            remaining = self._last_request.get(host, 0) + delay - time.monotonic()
            if remaining > 30:
                raise FetchStopped("robots_delay", "站点抓取间隔超过本次等待预算")
            if remaining > 0:
                await asyncio.sleep(remaining)
            for attempt in range(min(1, max(0, self.config.max_retries)) + 1):
                addresses = await self.resolver(url, self.config.timeout_seconds)
                for address in addresses:
                    assert_public_ip(address)
                try:
                    self._last_request[host] = time.monotonic()
                    # A wall deadline also bounds slow trickle responses and DNS.
                    result = await asyncio.wait_for(self.http.request(url, addresses, max_bytes), self.config.timeout_seconds)
                    if result.status_code == 429:
                        seconds = 60.0
                        retry = result.headers.get("retry-after", "")
                        try:
                            seconds = max(0, float(retry))
                        except ValueError:
                            try:
                                seconds = max(0, parsedate_to_datetime(retry).timestamp() - time.time())
                            except (TypeError, ValueError, OverflowError):
                                pass
                        self._paused_until[host] = time.monotonic() + seconds
                        raise FetchStopped("rate_limited", "站点返回 429；已按 Retry-After 暂停")
                    return result
                except (httpx.TimeoutException, httpx.ConnectError, asyncio.TimeoutError) as exc:
                    if attempt == min(1, max(0, self.config.max_retries)):
                        raise FetchStopped("timeout" if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "network_error", "页面连接失败或超时") from exc
                    await asyncio.sleep(0.25)
                except httpx.HTTPError as exc:
                    raise FetchStopped("network_error", "页面 HTTP 传输失败") from exc
        raise FetchStopped("network_error", "页面请求未完成")

    async def _robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        async with self._robots_locks.setdefault(origin, asyncio.Lock()):
            cached = self._robots.get(origin)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            current = origin + "/robots.txt"
            for hop in range(self.config.max_redirects + 1):
                current = normalize_url(current)
                self._site_policy(current)
                response = await self._request(current, min(self.config.max_bytes, 256_000))
                if response.status_code in {301, 302, 303, 307, 308}:
                    if hop == self.config.max_redirects or not response.headers.get("location"):
                        raise FetchStopped("robots_unavailable", "robots.txt 重定向无法确认")
                    current = urljoin(current, response.headers["location"])
                    continue
                if response.status_code in {404, 410}:
                    rules = RobotsRules("", self.config.user_agent)
                elif response.status_code == 200:
                    text = response.body.decode("utf-8-sig", errors="replace")
                    if "<html" in text[:1000].lower() or "<form" in text[:1000].lower():
                        raise FetchStopped("robots_unavailable", "robots.txt 返回 HTML；无法确认抓取规则")
                    if re.search(r"captcha|access denied|verify you are human|访问受限|验证码|禁止访问", text[:1000], re.I):
                        raise FetchStopped("robots_blocked", "robots.txt 返回明确访问限制")
                    rules = RobotsRules(text, self.config.user_agent)
                elif response.status_code in {401, 403}:
                    raise FetchStopped("robots_blocked", "robots.txt 返回访问限制，停止页面采集")
                else:
                    raise FetchStopped("robots_unavailable", "robots.txt 获取失败，停止页面采集")
                self._robots[origin] = (time.monotonic() + self.config.robots_ttl_seconds, rules)
                self._delays[parts.hostname or ""] = rules.delay
                return rules
        raise FetchStopped("robots_unavailable", "robots.txt 无法确认")

    async def fetch(self, url: str) -> HTTPResult:
        if not self.config.enabled:
            raise FetchStopped("disabled", "页面补全已关闭")
        async with self._global:
            current = normalize_url(url)
            for hop in range(self.config.max_redirects + 1):
                self._site_policy(current)
                rules = await self._robots_for(current)
                if not rules.allowed(current):
                    raise FetchStopped("robots_blocked", "robots.txt 禁止读取此路径")
                response = await self._request(current, self.config.max_bytes)
                if response.status_code in {301, 302, 303, 307, 308}:
                    if hop == self.config.max_redirects or not response.headers.get("location"):
                        raise FetchStopped("redirect_limit", "页面重定向超过预算或缺少地址")
                    current = normalize_url(urljoin(current, response.headers["location"]))
                    continue
                return response
        raise FetchStopped("redirect_limit", "页面重定向未完成")

    async def enrich(self, candidate: dict, *, catalog_budget_hook: Callable[[], Awaitable[bool]] | None = None) -> dict:
        raw_url = candidate.get("url", "")
        resource = {"title": candidate.get("title") or None, "url": raw_url, "canonical_url": raw_url,
                    "platform": platform_for_url(raw_url), "resource_type": "unknown", "video_evidence_status": "none", "author": None,
                    "description": candidate.get("snippet") or candidate.get("content") or None, "language": None,
                    "duration_seconds": None, "published_at": None, "discovered_at": candidate.get("discovered_at") or utcnow(),
                    "fetched_at": None, "fetch_status": "not_fetched", "metadata_evidence_level": "search",
                    "requires_login": None, "requires_payment": None, "requires_enrollment": None,
                    "chapters": [], "field_provenance": {}, "evidence": [], "catalog_pages_completed": 0}
        evidence_id = "ev_" + hashlib.sha256(f"search|{raw_url}|{candidate.get('query')}|{candidate.get('source')}".encode()).hexdigest()[:20]
        origin_kind = "page_link" if candidate.get("source") == "fetched_page_link" else "search"
        search_evidence = {"id": evidence_id, "evidence_id": evidence_id, "kind": origin_kind, "url": raw_url,
                           "source": candidate.get("source"), "query": candidate.get("query"),
                           "source_url": candidate.get("source_url"),
                           "text": " ".join(str(item or "") for item in (candidate.get("title"), resource["description"])),
                           "discovered_at": resource["discovered_at"]}
        resource["evidence"].append(search_evidence)
        for field in ("title", "url", "description"):
            if resource[field] is not None:
                resource["field_provenance"][field] = {"evidence_id": evidence_id, "source": origin_kind, "url": raw_url}
        try:
            normalized = normalize_url(raw_url)
            resource["url"] = resource["canonical_url"] = normalized
            response = await self.fetch(normalized)
            resource["fetched_at"] = utcnow()
            status = {401: "login_required", 403: "access_denied", 404: "not_found", 410: "not_found"}.get(response.status_code)
            if status or response.status_code != 200:
                resource["fetch_status"] = status or "http_error"
                if status == "login_required":
                    resource["requires_login"] = True
                    self._record_access_evidence(resource, response.url, "http.status.401")
                return resource
            content_type = response.headers.get("content-type", "").lower()
            if not any(value in content_type for value in ("text/html", "application/xhtml+xml")):
                resource["fetch_status"] = "unsupported_content"
                return resource
            encoding = re.search(r"charset\s*=\s*([\w-]+)", content_type)
            try:
                html = response.body.decode(encoding.group(1) if encoding else "utf-8", errors="replace")
            except LookupError:
                html = response.body.decode("utf-8", errors="replace")
            extracted = self.extractor.extract(html, response.url, resource["fetched_at"])
            followup = extracted.pop("_catalog_followup", None)
            resource["field_provenance"].update(extracted.pop("field_provenance", {}))
            resource["evidence"].extend(extracted.pop("evidence", []))
            resource.update(extracted)
            if resource["requires_login"] is True:
                self._record_access_evidence(resource, response.url, "html.login_gate")
            # Preserve the discovered direct chapter/video entry; final URL is evidence, not an unsafe canonical tag.
            resource["resolved_url"] = response.url
            if followup and not resource["chapters"]:
                resource["catalog_fetch_status"] = "not_attempted"
                if catalog_budget_hook is not None:
                    if await catalog_budget_hook():
                        # No callback passed into the child: this is a hard one-page
                        # same-course navigation limit, never recursive crawling.
                        catalog = await self.enrich({"url": followup["url"], "title": followup["link_text"],
                            "source": "fetched_page_link", "source_url": response.url, "query": None, "discovered_at": utcnow()})
                        resource["catalog_pages_completed"] = 1
                        resource["catalog_fetch_status"] = catalog["fetch_status"]
                        resource["evidence"].extend(catalog["evidence"])
                        if catalog["chapters"] and catalog["metadata_evidence_level"] == "catalog":
                            resource["chapters"] = catalog["chapters"]
                            resource["catalog_kind"] = catalog.get("catalog_kind")
                            resource["metadata_evidence_level"] = "catalog"
                            resource["field_provenance"]["chapters"] = catalog["field_provenance"]["chapters"]
                            if catalog.get("video_evidence_status") == "page_verified":
                                resource["video_evidence_status"] = "page_verified"
                                resource["field_provenance"]["video_evidence_status"] = catalog["field_provenance"]["video_evidence_status"]
                    else:
                        resource["catalog_fetch_status"] = "budget_limited"
        except UnsafeURL as exc:
            resource["fetch_status"] = "unsafe_url"
            resource["fetch_error"] = str(exc)
            # Never expose a dangerous scheme/private URL as a clickable course link.
            try:
                normalize_url(raw_url)
            except UnsafeURL:
                resource["url"] = resource["canonical_url"] = ""
        except FetchStopped as exc:
            resource["fetch_status"] = exc.status
            resource["fetch_error"] = str(exc)
            if exc.policy:
                policy_id = "ev_" + hashlib.sha256(json.dumps(exc.policy, sort_keys=True).encode()).hexdigest()[:20]
                resource["evidence"].append({"id": policy_id, "evidence_id": policy_id, "kind": "site_policy",
                    "url": exc.policy["source_url"], "source": "official_policy_review", "field": "fetch_status",
                    "text": exc.policy["basis"], "reviewed_at": exc.policy["reviewed_at"], "terms_date": exc.policy.get("terms_date"),
                    "policy_status": exc.policy["status"]})
                resource["field_provenance"]["fetch_status"] = {"evidence_id": policy_id, "source": "official_policy_review", "url": exc.policy["source_url"]}
        return resource

    @staticmethod
    def _record_access_evidence(resource: dict, url: str, source: str):
        evidence_id = "ev_" + hashlib.sha256(f"{url}|requires_login|{source}".encode()).hexdigest()[:20]
        resource["field_provenance"]["requires_login"] = {"evidence_id": evidence_id, "source": source, "url": url,
                                                          "fetched_at": resource["fetched_at"]}
        resource["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "page", "url": url,
                                     "field": "requires_login", "source": source, "text": "当前页面返回登录限制；资源内容仍未核验",
                                     "fetched_at": resource["fetched_at"]})
