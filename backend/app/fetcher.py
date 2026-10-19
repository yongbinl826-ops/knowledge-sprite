"""Bounded static page fetching with DNS pinning, independent site policy and robots."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import re
import socket
import time
import zlib
from collections import Counter, deque
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit, urlunsplit

import httpx

from .extractor import MetadataExtractor
from .url_utils import UnsafeURL, assert_public_ip, host_matches, normalize_url, platform_for_url

# Optional per-task observers. Context tokens must be reset by callers; parallel
# detail tasks retain their own context and never inherit another search's budget.
NETWORK_OBSERVER: ContextVar[dict | None] = ContextVar("fetch_network_observer", default=None)
# Separate from per-provider observers so nested discovery cannot discard the job deadline.
FETCH_DEADLINE_AT: ContextVar[float | None] = ContextVar("fetch_job_deadline_at", default=None)


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
    bilibili_public_metadata: bool = False
    denied_hosts: tuple[str, ...] = ()
    global_concurrency: int = 5
    min_interval_seconds: float = 0.5
    robots_ttl_seconds: int = 3600
    dns_resolver: str = "system"
    phased_timeouts: bool = False
    body_idle_timeout_seconds: float = 5.0
    body_min_bytes_per_second: float = 32768.0
    body_timeout_cap_seconds: float = 20.0


@dataclass
class HTTPResult:
    status_code: int
    headers: dict[str, str]
    body: bytes
    url: str


class FetchStopped(Exception):
    def __init__(self, status: str, message: str, policy: dict | None = None, access_block: dict | None = None, blocked_target_url: str | None = None):
        super().__init__(message)
        self.status = status
        self.policy = policy
        self.access_block = access_block
        self.blocked_target_url = blocked_target_url


def retry_after_seconds(value: str, now: float | None = None) -> float:
    """Invalid/overflowing headers use a finite conservative default, never zero."""
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return 60.0
    return max(0.0, seconds) if math.isfinite(seconds) and seconds >= 0 else 60.0


PLATFORM_POLICY_REVIEWS = {
    "youtube": {
        "status": "explicit_permission_required", "reviewed_at": "2026-10-13",
        "source_url": "https://www.youtube.com/static?template=terms",
        "terms_date": "2023-12-15",
        "basis": "YouTube 官方服务条款 Permissions and Restrictions 第3项限制自动访问，例外为遵守 robots.txt 的公开搜索引擎或事先取得书面许可；本项目不是公开搜索引擎且未取得书面许可。",
    },
    "bilibili": {
        "status": "explicit_permission_required", "reviewed_at": "2026-10-17",
        "source_url": "https://www.bilibili.com/blackboard/protocal/licence.html",
        "section": "5.6(3)、1.5", "terms_date": "2025-04-30", "effective_at": "2025-05-07",
        "review_method": "browser_visible_terms",
        "evidence_artifact": "reports/platform-live-chain-20261017/bilibili-terms-visible.txt",
        "evidence_sha256": "870af0af794a5904a680d6ad288c944b59ece8a99461dc369a39c0a66374393c",
        "basis": "用户协议5.6(3)要求以自动程序、脚本等获取平台服务、内容或数据前取得明确书面许可；1.5同时涵盖未注册用户。本项目未取得该许可，在请求课程页面前停止。",
    },
    "icourse163": {
        "status": "public_course_metadata_only", "reviewed_at": "2026-10-17",
        "source_url": "https://www.icourse163.org/topics/mooc_privacy_service/",
        "section": "3.1、5.2.7", "terms_date": "2021-07-16", "effective_at": "2021-07-16",
        "review_method": "browser_visible_terms",
        "evidence_artifact": "reports/platform-live-chain-20261017/mooc-terms-visible.txt",
        "evidence_sha256": "409e4fc235f373cb896d135e7f981f25634f33102760a3bb66ecd1b5959a021b",
        "scope": "anonymous_https_course_html_get",
        "redirect_scope": "official_course_or_robots_paths_only",
        "script_execution": False,
        "basis": "协议3.1允许浏览课程信息；5.2.7涉及第三方工具、服务接入，未明确列出匿名公开课程HTML读取。当前仅读取公开/course/课程页响应自带的介绍与大纲，逐次检查robots和访问限制；不接入登录学习、选课、播放或私有API，不代表取得平台自动聚合的广泛许可。",
    },
    "xuetangx": {
        "status": "explicit_scraping_prohibition", "reviewed_at": "2026-10-13",
        "source_url": "https://www.xuetangx.com/app/protocol", "terms_date": "2021-01-05",
        "section": "网络行为准则",
        "basis": "官方用户协议“网络行为准则”明确约定不抓取和批量下载本产品内容；当前停止自动页面采集，保留搜索发现证据。公开课程可供用户访问不等于许可自动抓取。",
    },
}


def public_bilibili_metadata_url(url: str) -> bool:
    """Local opt-in scope: anonymous video HTML and its robots preflight only."""
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in {"www.bilibili.com", "bilibili.com"}:
            return False
        if parts.port not in {None, 443} or parts.fragment or parts.username is not None or parts.password is not None:
            return False
        if parts.path == "/robots.txt":
            return not parts.query
        if not re.fullmatch(r"/video/(?:BV[0-9A-Za-z]{10}|av[0-9]+)/?", parts.path):
            return False
        query = parse_qsl(parts.query, keep_blank_values=True)
        return not query or (len(query) == 1 and query[0][0] == "p" and re.fullmatch(r"[1-9][0-9]*", query[0][1]) is not None)
    except ValueError:
        return False


def public_mooc_metadata_url(url: str) -> bool:
    """Anonymous public course HTML only; unknown scope is not a site-wide ban.

    No account, learning, media, API, third-party host or arbitrary query route
    is admitted. A numeric tid retains a public course offering's identity.
    Robots is allowed solely as the independent protocol preflight resource.
    """
    from .mooc_urls import public_course_url
    if public_course_url(url) is not None:
        return True
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname in {"www.icourse163.org", "icourse163.org"}
                and parts.port in {None, 443} and parts.username is None and parts.password is None
                and parts.path == "/robots.txt" and not parts.query and not parts.fragment)
    except ValueError:
        return False


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
                observer = NETWORK_OBSERVER.get() or {}
                if observer.get("before_dns_http"):
                    await observer["before_dns_http"]()
                trace = {"started_at": utcnow(), "provider": "cloudflare_doh", "host": host,
                         "record_type": record_type, "status": "running", "http_status": None}
                if observer.get("dns_trace"):
                    observer["dns_trace"](trace)
                started = time.monotonic()
                try:
                    async with client.stream("GET", "https://1.1.1.1/dns-query", params={"name": host, "type": record_type},
                                         headers={"Host": "cloudflare-dns.com", "Accept": "application/dns-json", "Accept-Encoding": "identity"},
                                         extensions={"sni_hostname": "cloudflare-dns.com"}) as response:
                        trace["http_status"] = response.status_code
                        if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                            raise FetchStopped("dns_error", "Cloudflare DoH 未返回有效响应")
                        body = bytearray()
                        async for chunk in response.aiter_raw(chunk_size=4096):
                            if len(body) + len(chunk) > 65536:
                                raise FetchStopped("dns_error", "Cloudflare DoH 响应超过预算")
                            body.extend(chunk)
                        trace.update(bytes_read=len(body), source_sha256=hashlib.sha256(body).hexdigest())
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
                        trace["status"] = "completed"
                except BaseException as exc:
                    trace.update(status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed", error_type=type(exc).__name__)
                    raise
                finally:
                    trace.update(finished_at=utcnow(), elapsed_seconds=round(time.monotonic() - started, 3))
        if not addresses:
            raise FetchStopped("dns_error", "Cloudflare DoH 没有可用公网地址")
        return list(dict.fromkeys(addresses))


class PinnedHTTPClient:
    """A fresh numeric-IP connection per request; no proxy, cookies, or implicit redirects.

    HTTPX passes sni_hostname to httpcore for certificate validation against the
    original hostname. The TCP target is only the address already checked here.
    See https://www.encode.io/httpcore/extensions/#sni_hostname .

    Servers may ignore Accept-Encoding: identity. Supported content encodings
    are decoded incrementally, with independent wire and decoded byte limits.
    Trace bytes_read remains the wire count; body_sha256 describes the decoded
    entity prefix, while encoded_body_sha256 describes the wire body prefix.
    """
    def __init__(self, config: FetcherConfig):
        self.config = config
        for value in (config.body_idle_timeout_seconds, config.body_min_bytes_per_second,
                      config.body_timeout_cap_seconds):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Body transport budgets must be finite positive numbers")

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
        started = time.monotonic()
        trace = {"started_at": utcnow(), "status": "running", "http_status": None,
                 "phase": "before_connect", "phases": [], "bytes_read": 0,
                 "body_complete": False, "body_sha256": None, "max_bytes": max_bytes,
                 "content_encoding": None, "encoded_bytes_read": 0, "decoded_bytes_read": 0,
                 "body_sha256_basis": "decoded_entity_prefix",
                 "encoded_body_sha256": None, "encoded_body_sha256_basis": "wire_body_prefix",
                 "phased_timeouts": self.config.phased_timeouts}
        observer = NETWORK_OBSERVER.get() or {}
        if observer.get("transport_trace"):
            observer["transport_trace"](trace)
        allowed = {"connect_tcp", "start_tls", "send_request_headers", "send_request_body",
                   "receive_response_headers", "receive_response_body", "response_closed"}
        async def stage(name, info):
            # Never copy httpcore info: it may contain request headers or objects.
            pieces = name.split(".")
            if len(pieces) < 2 or pieces[-2] not in allowed or len(trace["phases"]) >= 32:
                return
            phase, state = pieces[-2:]
            row = {"phase": phase, "state": state, "at": utcnow(),
                   "elapsed_seconds": round(time.monotonic() - started, 6)}
            if state == "failed" and info.get("exception") is not None:
                row["error_type"] = type(info["exception"]).__name__
            trace["phases"].append(row)
            if state == "started" and phase != "response_closed":
                trace["phase"] = phase

        deadline = None
        digest = hashlib.sha256()
        encoded_digest = hashlib.sha256()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout_seconds),
                                         follow_redirects=False, trust_env=False,
                                         limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as client:
                async with asyncio.timeout(self.config.timeout_seconds if self.config.phased_timeouts else None) as deadline:
                    async with client.stream("GET", pinned, headers=headers,
                                             extensions={"sni_hostname": host, "trace": stage}) as response:
                        response_headers = dict(response.headers)
                        encoding = response.headers.get("content-encoding", "identity").strip().lower() or "identity"
                        trace.update(http_status=response.status_code, headers_at=utcnow(),
                            headers_elapsed_seconds=round(time.monotonic() - started, 6), phase="headers",
                            content_encoding=encoding)
                        if response.status_code in {301, 302, 303, 307, 308, 401, 403, 404, 410, 429} or response.status_code >= 500:
                            trace.update(status="completed", body_read="not_requested_status")
                            return HTTPResult(response.status_code, response_headers, b"", normalized)
                        if encoding not in {"identity", "gzip", "deflate"}:
                            raise FetchStopped("unsupported_encoding", f"暂不支持站点返回的内容编码：{encoding[:80]}")
                        decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding != "identity" else None
                        length = response.headers.get("content-length")
                        if length and length.isdigit() and int(length) > max_bytes:
                            raise FetchStopped("too_large", "页面超过采集字节预算")
                        size_basis = int(length) if length and length.isdigit() else max_bytes
                        body_seconds = min(self.config.body_timeout_cap_seconds,
                            self.config.body_idle_timeout_seconds + size_basis / self.config.body_min_bytes_per_second)
                        if self.config.phased_timeouts:
                            # One deadline from headers, never extended by chunks.
                            # Known size uses Content-Length; unknown size uses the
                            # validated byte cap. Idle allowance is a fixed startup
                            # margin, not an unlimited sliding throughput promise.
                            clock_now = asyncio.get_running_loop().time()
                            ends_at = min(clock_now + body_seconds,
                                started + self.config.timeout_seconds + self.config.body_timeout_cap_seconds)
                            job_deadline = FETCH_DEADLINE_AT.get()
                            if job_deadline is not None:
                                ends_at = min(ends_at, job_deadline)
                            body_seconds = max(0, ends_at - clock_now)
                            deadline.reschedule(ends_at)
                            trace.update(body_total_budget_seconds=body_seconds,
                                body_idle_budget_seconds=self.config.body_idle_timeout_seconds,
                                content_length=int(length) if length and length.isdigit() else None,
                                body_size_basis_bytes=size_basis, body_min_bytes_per_second=self.config.body_min_bytes_per_second,
                                body_budget_formula="min(cap, idle + size/min_rate, request_remaining, job_remaining)",
                                job_deadline_clipped=job_deadline is not None and ends_at == job_deadline)
                        trace["phase"] = "body"
                        body = bytearray()
                        iterator = response.aiter_raw().__aiter__()
                        while True:
                            try:
                                if self.config.phased_timeouts:
                                    try:
                                        chunk = await asyncio.wait_for(anext(iterator), self.config.body_idle_timeout_seconds)
                                    except asyncio.TimeoutError:
                                        trace["timeout_kind"] = "body_idle"
                                        raise
                                else:
                                    chunk = await anext(iterator)
                            except StopAsyncIteration:
                                break
                            encoded_digest.update(chunk)
                            encoded_size = trace["encoded_bytes_read"] + len(chunk)
                            trace.update(bytes_read=encoded_size, encoded_bytes_read=encoded_size,
                                encoded_body_sha256=encoded_digest.hexdigest())
                            if encoded_size > max_bytes:
                                raise FetchStopped("too_large", "页面传输内容超过采集字节预算")
                            pending = chunk
                            while pending:
                                if decoder is None:
                                    decoded, pending = pending, b""
                                else:
                                    # RFC 1952 permits concatenated gzip members. A
                                    # new member must independently pass its CRC and
                                    # length checks; trailing garbage is never ignored.
                                    if decoder.eof:
                                        if encoding != "gzip":
                                            raise FetchStopped("invalid_encoding", "压缩页面包含多余尾随数据")
                                        decoder = zlib.decompressobj(31)
                                    try:
                                        # Never call unbounded decompress/flush. The
                                        # single extra byte detects a decoded overflow
                                        # without allocating the expanded response.
                                        decoded = decoder.decompress(pending, max_bytes - len(body) + 1)
                                    except zlib.error as exc:
                                        raise FetchStopped("invalid_encoding", "压缩页面内容或校验值无效") from exc
                                    pending = decoder.unconsumed_tail or decoder.unused_data
                                digest.update(decoded)
                                trace.update(decoded_bytes_read=trace["decoded_bytes_read"] + len(decoded),
                                    body_sha256=digest.hexdigest())
                                if len(body) + len(decoded) > max_bytes:
                                    raise FetchStopped("too_large", "页面解压内容超过采集字节预算")
                                body.extend(decoded)
                        if decoder is not None and not decoder.eof:
                            raise FetchStopped("invalid_encoding", "压缩页面响应不完整")
                        if decoder is not None:
                            # HTTPResult.body is now the decoded entity. Keep wire
                            # encoding/count in trace, not misleading entity headers.
                            response_headers.pop("content-encoding", None)
                            response_headers.pop("transfer-encoding", None)
                            response_headers["content-length"] = str(len(body))
                        trace.update(status="completed", body_complete=True, body_sha256=digest.hexdigest(),
                            encoded_body_sha256=encoded_digest.hexdigest(),
                            body_completed_at=utcnow(), phase="complete")
                        return HTTPResult(response.status_code, response_headers, bytes(body), normalized)
        except BaseException as exc:
            trace.update(status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                         error_type=type(exc).__name__, stop_status=getattr(exc, "status", None))
            job_deadline = FETCH_DEADLINE_AT.get()
            if isinstance(exc, asyncio.CancelledError) and job_deadline is not None and asyncio.get_running_loop().time() >= job_deadline:
                trace["timeout_kind"] = "job_deadline"
            if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
                if deadline and deadline.expired():
                    trace["timeout_kind"] = ("job_deadline" if trace.get("job_deadline_clipped") else "body_total") if trace.get("headers_at") else "first_response"
                else:
                    trace.setdefault("timeout_kind", "transport_operation")
            raise
        finally:
            trace.update(finished_at=utcnow(), elapsed_seconds=round(time.monotonic() - started, 6),
                         partial_body=bool(trace["bytes_read"] and not trace["body_complete"]))


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
                        delay = float(value)
                        if math.isfinite(delay) and delay >= 0:
                            self.delay = max(self.delay, delay)
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
                    if self._matches(candidate, rule_variant):
                        literal = rule_variant[:-1] if rule_variant.endswith("$") else rule_variant
                        matches.append((len(literal.replace("*", "")), allow))
            if matches and not max(matches)[1]:
                return False
        return True

    @staticmethod
    def _matches(path: str, rule: str) -> bool:
        """Match literal segments in order, without regex wildcard backtracking."""
        anchored = rule.endswith("$")
        pattern = rule[:-1] if anchored else rule
        segments = pattern.split("*")
        if len(segments) == 1:
            return path == pattern if anchored else path.startswith(pattern)
        if not path.startswith(segments[0]):
            return False
        position = len(segments[0])
        middle = segments[1:-1] if anchored else segments[1:]
        for literal in middle:
            if literal:
                found = path.find(literal, position)
                if found < 0:
                    return False
                position = found + len(literal)
        if anchored:
            suffix = segments[-1]
            return path.endswith(suffix) and len(path) - len(suffix) >= position
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
        self._blocked_hosts: dict[str, dict] = {}
        self._last_request: dict[str, float] = {}
        self.request_trace: deque[dict] = deque(maxlen=512)
        self.trace_counts: Counter = Counter()

    def _trace(self, event: str, url: str, **fields):
        # Keep query values and exception messages out of operational diagnostics.
        parts = urlsplit(url)
        self.trace_counts[event] += 1
        record = {"event": event, "at": utcnow(), "host": parts.hostname,
            "url": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
            "url_sha256": hashlib.sha256(url.encode()).hexdigest(), **fields}
        self.request_trace.append(record)
        observer = NETWORK_OBSERVER.get() or {}
        if observer.get("target_trace"):
            observer["target_trace"](record)

    def _host_interval(self, host: str) -> float:
        minimum = self.config.min_interval_seconds
        if not math.isfinite(minimum) or minimum < 0:
            minimum = 0.5
        # Keep each origin's last known delay until that origin is refreshed.
        # An HTTP origin with no delay must not lower the HTTPS origin's rule.
        return max([minimum, *(rules.delay for origin, (_, rules) in self._robots.items()
                               if urlsplit(origin).hostname == host)])

    def _block_host(self, url: str, status: str, source: str) -> dict:
        host = urlsplit(url).hostname or ""
        record = self._blocked_hosts.setdefault(host, {"host": host, "trigger_url": url,
            "status": status, "source": source, "observed_at": utcnow(), "scope": "fetcher_instance_host"})
        self._trace("host_blocked", url, status=record["status"], source=record["source"])
        return record

    @staticmethod
    def _host_block_exception(record: dict) -> FetchStopped:
        return FetchStopped(record["status"], "已观察到该主机明确拒绝自动访问；本次采集器实例停止该主机后续页面请求", access_block=record)

    def _site_policy(self, url: str):
        host = urlsplit(url).hostname or ""
        if any(host_matches(host, domain) for domain in self.config.denied_hosts):
            raise FetchStopped("site_policy_blocked", "服务端管理员策略禁止本次采集；不代表已核验平台条款禁止")
        platform = "youtube" if any(host_matches(host, domain) for domain in ("youtube.com", "youtu.be")) else platform_for_url(url)
        review = PLATFORM_POLICY_REVIEWS.get(platform)
        if platform == "bilibili" and self.config.bilibili_public_metadata:
            if public_bilibili_metadata_url(url):
                return
            raise FetchStopped("policy_unreviewed", "本地自用模式仅读取匿名公开视频HTML；此目标超出视频元信息范围。", blocked_target_url=url)
        if review and review["status"] == "public_course_metadata_only":
            if public_mooc_metadata_url(url):
                return
            raise FetchStopped("policy_unreviewed", "此目标不在匿名公开课程HTML读取范围；不自动接入学习页、账号、播放或API路径。", review, blocked_target_url=url)
        if review and review["status"] in {"explicit_permission_required", "explicit_scraping_prohibition"}:
            # An unreviewed-host allow-list cannot override an explicit prohibition
            # or a permission requirement that this project has not satisfied.
            raise FetchStopped("site_policy_blocked", review["basis"], review, blocked_target_url=url)
        if review and not any(host_matches(host, domain) for domain in self.config.allowed_restricted_hosts):
            raise FetchStopped("policy_unreviewed", review["basis"] + " 当前仅保留搜索发现证据。", review, blocked_target_url=url)

    @staticmethod
    def _bilibili_redirect_scope(url: str, *, robots: bool = False):
        if not public_bilibili_metadata_url(url) or (robots and urlsplit(url).path != "/robots.txt"):
            raise FetchStopped("policy_unreviewed", "B站元信息读取的重定向超出公开视频范围；停止该目标请求。", blocked_target_url=url)

    @staticmethod
    def _mooc_redirect_scope(url: str, *, robots: bool = False):
        if not public_mooc_metadata_url(url) or (robots and urlsplit(url).path != "/robots.txt"):
            raise FetchStopped("policy_unreviewed", "公开MOOC读取的重定向超出已限定路径；不向第三方、学习页或API继续请求。",
                               PLATFORM_POLICY_REVIEWS["icourse163"], blocked_target_url=url)

    async def _request(self, url: str, max_bytes: int, *, kind: str = "page") -> HTTPResult:
        # Job cancellation surrounds DNS, pacing and HTTP and escapes the local
        # retry/source-failure handlers. A spent job is not a source fault.
        ends_at = FETCH_DEADLINE_AT.get()
        if ends_at is not None and asyncio.get_running_loop().time() >= ends_at:
            raise TimeoutError("job_deadline")
        async with asyncio.timeout_at(ends_at):
            return await self._request_with_local_limits(url, max_bytes, kind=kind)

    async def _request_with_local_limits(self, url: str, max_bytes: int, *, kind: str = "page") -> HTTPResult:
        host = urlsplit(url).hostname or ""
        async with self._hosts.setdefault(host, asyncio.Lock()):
            configured_retries = min(1, max(0, self.config.max_retries))
            retries = min(configured_retries, (NETWORK_OBSERVER.get() or {}).get("max_retries", configured_retries))
            for attempt in range(retries + 1):
                if host in self._blocked_hosts:
                    self._trace("blocked_before_request", url, kind=kind, attempt=attempt)
                    raise self._host_block_exception(self._blocked_hosts[host])
                if self._paused_until.get(host, 0) > time.monotonic():
                    self._trace("paused_before_request", url, kind=kind, attempt=attempt)
                    raise FetchStopped("rate_limited", "该站点处于 Retry-After 暂停期")
                remaining = self._last_request.get(host, -float("inf")) + self._host_interval(host) - time.monotonic()
                if remaining > 30:
                    raise FetchStopped("robots_delay", "站点抓取间隔超过本次等待预算")
                if remaining > 0:
                    self._trace("pacing_wait", url, kind=kind, attempt=attempt, seconds=remaining)
                    await asyncio.sleep(remaining)
                self._trace("dns_started", url, kind=kind, attempt=attempt)
                observer = NETWORK_OBSERVER.get() or {}
                if observer.get("before_resolve"):
                    await observer["before_resolve"](url)
                try:
                    addresses = await self.resolver(url, self.config.timeout_seconds)
                    for address in addresses:
                        assert_public_ip(address)
                except (FetchStopped, UnsafeURL) as exc:
                    self._trace("dns_failed", url, kind=kind, attempt=attempt, error_type=type(exc).__name__)
                    raise
                except asyncio.CancelledError:
                    self._trace("dns_cancelled", url, kind=kind, attempt=attempt)
                    raise
                self._trace("dns_completed", url, kind=kind, attempt=attempt, address_count=len(addresses))
                try:
                    response_limit = max_bytes
                    if observer.get("response_byte_limit"):
                        remaining_bytes = observer["response_byte_limit"]()
                        if isinstance(remaining_bytes, bool) or not isinstance(remaining_bytes, int) or remaining_bytes <= 0:
                            raise FetchStopped("budget_exceeded", "本次响应剩余字节预算不足")
                        response_limit = min(response_limit, remaining_bytes)
                    if observer.get("before_target_http"):
                        await observer["before_target_http"]()
                    self._last_request[host] = time.monotonic()
                    self._trace("http_started", url, kind=kind, attempt=attempt)
                    def transport_trace(trace):
                        self._trace("http_transport", url, kind=kind, attempt=attempt, transport=trace)
                        if observer.get("transport_trace"):
                            observer["transport_trace"](trace)
                    async def perform_request():
                        token = NETWORK_OBSERVER.set({**observer, "transport_trace": transport_trace})
                        try:
                            return await self.http.request(url, addresses, response_limit)
                        finally:
                            NETWORK_OBSERVER.reset(token)
                    # Default behavior keeps its original whole-response bound.
                    # Phased transport has a first-response plus a non-sliding
                    # bounded-body deadline; retain an outer safeguard for injected
                    # transports and cancellation, independently of the job deadline.
                    total_seconds = self.config.timeout_seconds + (self.config.body_timeout_cap_seconds if self.config.phased_timeouts else 0)
                    result = await asyncio.wait_for(perform_request(), total_seconds)
                    self._trace("http_completed", url, kind=kind, attempt=attempt, status_code=result.status_code, bytes_read=len(result.body))
                    if observer.get("response"):
                        observer["response"](result, kind)
                    if result.status_code == 403:
                        record = self._block_host(url, "robots_blocked" if kind == "robots" else "access_denied", "http.status.403")
                        raise self._host_block_exception(record)
                    if result.status_code == 429 or result.status_code == 503 and "retry-after" in result.headers:
                        seconds = retry_after_seconds(result.headers.get("retry-after", ""))
                        self._paused_until[host] = time.monotonic() + seconds
                        self._trace("host_paused", url, kind=kind, attempt=attempt, status_code=result.status_code, retry_after_seconds=seconds)
                        raise FetchStopped("rate_limited", f"站点返回 {result.status_code}；已按 Retry-After 暂停")
                    return result
                except (httpx.TimeoutException, httpx.ConnectError, asyncio.TimeoutError) as exc:
                    self._trace("http_failed", url, kind=kind, attempt=attempt, error_type=type(exc).__name__)
                    if attempt == retries:
                        raise FetchStopped("timeout" if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "network_error", "页面连接失败或超时") from exc
                    self._trace("retry_scheduled", url, kind=kind, attempt=attempt + 1)
                    await asyncio.sleep(0.25)
                except httpx.HTTPError as exc:
                    self._trace("http_failed", url, kind=kind, attempt=attempt, error_type=type(exc).__name__)
                    raise FetchStopped("network_error", "页面 HTTP 传输失败") from exc
                except FetchStopped as exc:
                    self._trace("http_stopped", url, kind=kind, attempt=attempt, status=exc.status)
                    raise
                except asyncio.CancelledError:
                    self._trace("http_cancelled", url, kind=kind, attempt=attempt)
                    raise
        raise FetchStopped("network_error", "页面请求未完成")

    async def _robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        mooc_scope = public_mooc_metadata_url(url)
        bili_scope = self.config.bilibili_public_metadata and public_bilibili_metadata_url(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        async with self._robots_locks.setdefault(origin, asyncio.Lock()):
            cached = self._robots.get(origin)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            current = origin + "/robots.txt"
            for hop in range(self.config.max_redirects + 1):
                current = normalize_url(current)
                if mooc_scope:
                    self._mooc_redirect_scope(current, robots=True)
                if bili_scope:
                    self._bilibili_redirect_scope(current, robots=True)
                self._site_policy(current)
                response = await self._request(current, min(self.config.max_bytes, 256_000), kind="robots")
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
                        page_status = self.extractor.extract(text, response.url, utcnow()).get("fetch_status")
                        if page_status in {"captcha", "access_denied"}:
                            raise self._host_block_exception(self._block_host(current, "robots_blocked", f"robots.html.{page_status}"))
                        raise FetchStopped("robots_unavailable", "robots.txt 返回 HTML；无法确认抓取规则")
                    if re.search(r"captcha|access denied|verify you are human|访问受限|验证码|禁止访问", text[:1000], re.I):
                        raise self._host_block_exception(self._block_host(current, "robots_blocked", "robots.access_denied_text"))
                    rules = RobotsRules(text, self.config.user_agent)
                elif response.status_code in {401, 403}:
                    raise FetchStopped("robots_blocked", "robots.txt 返回访问限制，停止页面采集")
                elif (response.status_code == 400 and origin == "https://cdn.jsdelivr.net" and hop == 0
                      and current == response.url == "https://cdn.jsdelivr.net/robots.txt"
                      and response.headers.get("content-type", "").split(";", 1)[0].lower() == "text/plain"
                      and "retry-after" not in response.headers
                      and not {"www-authenticate", "proxy-authenticate"}.intersection(response.headers)
                      and response.body.strip() == b"Invalid URL. The URL structure is /project/version/file.js"):
                    # Reviewed routing error at the robots resource, not access
                    # denial. RFC 9309 2.3.1.3 allows unavailable robots handling;
                    # content policy, declared assets and all access guards still apply.
                    rules = RobotsRules("", self.config.user_agent)
                    self._trace("robots_unavailable_4xx", response.url, kind="robots", status_code=400,
                        reason="reviewed_cdn_route_error", decision="no_rep_rules_available",
                        source_sha256=hashlib.sha256(response.body).hexdigest())
                else:
                    raise FetchStopped("robots_unavailable", "robots.txt 获取失败，停止页面采集")
                self._robots[origin] = (time.monotonic() + self.config.robots_ttl_seconds, rules)
                return rules
        raise FetchStopped("robots_unavailable", "robots.txt 无法确认")

    async def fetch(self, url: str) -> HTTPResult:
        if not self.config.enabled:
            raise FetchStopped("disabled", "页面补全已关闭")
        async with self._global:
            current = normalize_url(url)
            mooc_scope = public_mooc_metadata_url(current)
            bili_scope = self.config.bilibili_public_metadata and public_bilibili_metadata_url(current)
            for hop in range(self.config.max_redirects + 1):
                if mooc_scope:
                    self._mooc_redirect_scope(current)
                if bili_scope:
                    self._bilibili_redirect_scope(current)
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
            renderer = getattr(self, "renderer", None)
            if (renderer is not None and renderer.config.enabled
                    and (urlsplit(response.url).hostname or "").lower() in renderer.config.allowed_hosts
                    and extracted.get("fetch_status") in {"fetched", "javascript_required"}
                    and not extracted.get("chapters")):
                rendered = await renderer.render(self, response)
                from dataclasses import asdict
                diagnostics = asdict(rendered)
                diagnostics.pop("html", None)
                diagnostics["static_chapter_count"] = len(extracted.get("chapters", []))
                diagnostics["added_fields"] = []
                if rendered.status == "rendered" and rendered.html:
                    dynamic = self.extractor.extract(rendered.html, response.url, resource["fetched_at"])
                    if dynamic.get("fetch_status") in {"captcha", "access_denied", "login_required", "not_found", "error_page"}:
                        extracted["fetch_status"] = dynamic["fetch_status"]
                        diagnostics["page_status"] = dynamic["fetch_status"]
                        if dynamic.get("requires_login") is True:
                            extracted["requires_login"] = True
                        acquisition = {key: diagnostics.get(key) for key in
                            ("acquisition", "render_id", "source_sha256", "manifest_sha256", "dom_sha256")}
                        access_id = "ev_" + hashlib.sha256(f"{response.url}|{rendered.dom_sha256}|{dynamic['fetch_status']}".encode()).hexdigest()[:20]
                        extracted["evidence"].append(dict(acquisition, id=access_id, evidence_id=access_id,
                            kind="page", url=response.url, field="fetch_status", source="html.rendered_access_gate",
                            text=dynamic["fetch_status"], fetched_at=resource["fetched_at"]))
                        extracted["field_provenance"]["fetch_status"] = dict(acquisition,
                            evidence_id=access_id, source="html.rendered_access_gate", url=response.url)
                    if dynamic.get("fetch_status") == "fetched":
                        fields = set()
                        for key, provenance in dynamic.get("field_provenance", {}).items():
                            value = dynamic.get(key)
                            previous = extracted.get(key)
                            previous_source = extracted.get("field_provenance", {}).get(key, {}).get("source", "")
                            if value == previous or value is None:
                                continue
                            fills_missing = previous in (None, "", [], "unknown", "none")
                            replaces_generic = key in {"title", "description", "author"} and (
                                previous_source.startswith("meta.") or previous_source in {"html.title", "html.h1"}
                            ) and provenance.get("source", "").startswith("html.") and provenance.get("source") not in {"html.title", "html.h1"}
                            if fills_missing or replaces_generic:
                                fields.add(key)
                        if "author_role" in fields:
                            author_provenance = (dynamic if "author" in fields else extracted).get("field_provenance", {}).get("author", {})
                            if author_provenance.get("source") != dynamic["field_provenance"]["author_role"].get("source"):
                                fields.discard("author_role")
                        # Rendering is enrichment only: missing/failed dynamic facts
                        # cannot remove a previously observed static field.
                        for key in fields:
                            extracted[key] = dynamic[key]
                            extracted["field_provenance"][key] = dynamic["field_provenance"][key]
                        acquisition = {key: diagnostics.get(key) for key in
                            ("acquisition", "render_id", "source_sha256", "manifest_sha256", "dom_sha256")}
                        dynamic_evidence = [dict(item, **acquisition) for item in dynamic.get("evidence", [])
                            if item.get("field") in fields or ("chapters" in fields and item.get("field", "").startswith("chapters."))]
                        extracted["evidence"].extend(dynamic_evidence)
                        for key in fields:
                            extracted["field_provenance"][key].update(acquisition)
                        if "chapters" in fields:
                            extracted["metadata_evidence_level"] = "catalog"
                            extracted["catalog_kind"] = dynamic.get("catalog_kind")
                            extracted["chapters"] = [dict(chapter, **acquisition) for chapter in dynamic["chapters"]]
                        if fields:
                            extracted["fetch_status"] = "fetched"
                        diagnostics["added_fields"] = sorted(fields)
                        diagnostics["rendered_chapter_count"] = len(dynamic.get("chapters", []))
                resource["render_diagnostics"] = diagnostics
            followup = extracted.pop("_catalog_followup", None)
            resource["field_provenance"].update(extracted.pop("field_provenance", {}))
            resource["evidence"].extend(extracted.pop("evidence", []))
            resource.update(extracted)
            if resource["fetch_status"] in {"captcha", "access_denied"}:
                record = self._block_host(response.url, resource["fetch_status"], f"html.{resource['fetch_status']}")
                self._record_host_block(resource, record)
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
            if exc.access_block:
                self._record_host_block(resource, exc.access_block)
            if exc.policy:
                policy_id = "ev_" + hashlib.sha256(json.dumps(exc.policy, sort_keys=True).encode()).hexdigest()[:20]
                resource["evidence"].append({"id": policy_id, "evidence_id": policy_id, "kind": "site_policy",
                    "url": exc.policy["source_url"], "source": "official_policy_review", "field": "fetch_status",
                    "text": exc.policy["basis"], "reviewed_at": exc.policy["reviewed_at"], "terms_date": exc.policy.get("terms_date"),
                    "policy_status": exc.policy["status"], "blocked_target_url": exc.blocked_target_url,
                    "restricted_target_request_sent": False, "restricted_target_http_status": None,
                    **{key: exc.policy.get(key) for key in ("section", "effective_at", "review_method", "evidence_artifact", "evidence_sha256")}})
                resource["field_provenance"]["fetch_status"] = {"evidence_id": policy_id, "source": "official_policy_review", "url": exc.policy["source_url"]}
        return resource

    @staticmethod
    def _record_host_block(resource: dict, record: dict):
        evidence_id = "ev_" + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:20]
        resource["field_provenance"]["fetch_status"] = {"evidence_id": evidence_id,
            "source": "observed_host_access_restriction", "url": record["trigger_url"]}
        resource["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "access_restriction",
            "field": "fetch_status", "url": record["trigger_url"], "source": record["source"],
            "observed_at": record["observed_at"], "text": json.dumps(record, ensure_ascii=False, sort_keys=True)})

    @staticmethod
    def _record_access_evidence(resource: dict, url: str, source: str):
        evidence_id = "ev_" + hashlib.sha256(f"{url}|requires_login|{source}".encode()).hexdigest()[:20]
        resource["field_provenance"]["requires_login"] = {"evidence_id": evidence_id, "source": source, "url": url,
                                                          "fetched_at": resource["fetched_at"]}
        resource["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "page", "url": url,
                                     "field": "requires_login", "source": source, "text": "当前页面返回登录限制；资源内容仍未核验",
                                     "fetched_at": resource["fetched_at"]})
