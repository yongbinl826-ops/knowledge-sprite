"""Opt-in bounded DOM rendering through preapproved Fetcher resource bytes.

The browser cannot retrieve missing resources. No fixtures, reports, guessed API
endpoints, credentials, or media are inputs to this production bridge.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import posixpath
from pathlib import Path
import re
import time
from urllib.parse import urldefrag, urljoin, urlsplit, unquote
import uuid

from bs4 import BeautifulSoup

from .extractor import detect_access_page
from .fetcher import Fetcher, FetchStopped, HTTPResult, NETWORK_OBSERVER, PLATFORM_POLICY_REVIEWS
from .url_utils import UnsafeURL, normalize_url, platform_for_url


WORKER = Path(__file__).resolve().parents[1] / "renderer_worker" / "worker.mjs"
LOGIN_PATH = re.compile(r"/(?:login|logout|sign-?in|sign-?up|register|oauth|auth|account|enroll|payment|checkout)(?:/|$)", re.I)
SCRIPT_TYPES = {"", "module", "text/javascript", "application/javascript", "application/ecmascript", "text/ecmascript"}
JS_MIME = {"text/javascript", "application/javascript", "application/ecmascript", "text/ecmascript"}


@dataclass(frozen=True)
class RenderConfig:
    enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    allowed_entries: tuple[str, ...] = ()
    asset_hosts: tuple[str, ...] = ()
    max_observed_data_resources: int = 2
    max_resources: int = 6
    max_target_requests: int = 12
    max_doh_requests: int = 24
    max_total_bytes: int = 2_000_000
    max_dom_bytes: int = 1_000_000
    timeout_seconds: float = 20
    settle_ms: int = 500
    node_executable: str = "node"


@dataclass
class RenderResult:
    status: str
    html: str | None = None
    render_id: str = field(default_factory=lambda: "render_" + uuid.uuid4().hex)
    acquisition: str = "offline_rendered_dom"
    source_url: str | None = None
    source_sha256: str | None = None
    manifest_sha256: str | None = None
    dom_sha256: str | None = None
    manifest: list[dict] = field(default_factory=list)
    excluded_optional_assets: list[dict] = field(default_factory=list)
    deferred_observed_dependencies: list[dict] = field(default_factory=list)
    target_requests: int = 0
    doh_requests: int = 0
    total_bytes: int = 0
    blocked_requests: list[dict] = field(default_factory=list)
    fulfilled_requests: list[dict] = field(default_factory=list)
    passes: list[dict] = field(default_factory=list)
    partial_response_bytes: str = "not_in_complete_response_byte_total"
    cleanup: dict = field(default_factory=lambda: {"node_exited": None, "edge_main_exit_observed": None,
        "all_descendant_processes_exited": "unknown"})
    isolation: dict = field(default_factory=lambda: {"browser_http": "manifest_fulfill_only",
        "process_network_egress": "unknown", "webrtc_udp_egress": "unknown"})
    error: str | None = None
    elapsed_seconds: float = 0

    def as_dict(self):
        return asdict(self)


def _origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def _safe_url(url: str, origin: tuple[str, str]) -> str:
    value = normalize_url(url)
    if _origin(value) != origin or LOGIN_PATH.search(urlsplit(value).path):
        raise FetchStopped("render_scope_blocked", "渲染仅允许同源公开页面及实际声明资产，不访问登录或交易入口")
    return urldefrag(value)[0]


def optional_analytics_asset(url: str, page_url: str) -> bool:
    """Only observed MIT feedback/analytics integrations; never a network allowlist."""
    target, page = urlsplit(url), urlsplit(page_url)
    return page.hostname == "ocw.mit.edu" and target.scheme == "https" and (target.hostname, target.path) in {
        ("w.appzi.io", "/w.js"), ("www.googletagmanager.com", "/gtm.js"),
        ("www.googletagmanager.com", "/gtag/js")}


def declared_assets(html: str, page_url: str, max_resources: int, asset_hosts: tuple[str, ...] = (),
                    excluded: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """Only actual script/src and stylesheet/href declarations, never guessed APIs."""
    soup = BeautifulSoup(html, "html.parser")
    origin = _origin(page_url)
    base = page_url
    if soup.base and soup.base.get("href"):
        base = _safe_url(urljoin(page_url, soup.base["href"]), origin)
    assets, inline_hashes, seen = [], [], set()
    for node in soup.find_all(["script", "link"]):
        if node.name == "script":
            if str(node.get("type", "")).lower().strip() not in SCRIPT_TYPES:
                continue
            raw, kind = node.get("src"), "script"
            if not raw:
                code = node.string or node.get_text()
                code = code.replace("\r\n", "\n").replace("\r", "\n")
                inline_hashes.append("sha256-" + base64.b64encode(hashlib.sha256(code.encode()).digest()).decode())
                continue
        else:
            if "stylesheet" not in node.get("rel", []):
                continue
            raw, kind = node.get("href"), "stylesheet"
        if not isinstance(raw, str) or not raw.strip():
            continue
        requested = urldefrag(urljoin(base, raw.strip()))[0]
        normalized = normalize_url(requested)
        if kind == "script" and optional_analytics_asset(normalized, page_url):
            if excluded is not None:
                excluded.append({"url": requested, "kind": kind, "reason": "optional_feedback_or_analytics",
                    "action": "not_fetched_browser_blocked", "original_html_unchanged": True})
            continue
        if _origin(normalized) != origin and (urlsplit(normalized).hostname not in asset_hosts or urlsplit(normalized).scheme != "https"):
            raise FetchStopped("render_scope_blocked", "入口声明的跨源脚本/样式未在允许名单中")
        normalized = _safe_url(normalized, _origin(normalized))
        if requested in seen:
            continue
        seen.add(requested)
        if len(assets) >= max_resources:
            raise FetchStopped("render_resource_budget", "页面实际声明资产超过渲染资源预算")
        assets.append({"requested_url": requested, "fetch_url": normalized, "kind": kind,
                       "declaration": "script[src]" if kind == "script" else "link[rel=stylesheet]"})
    return assets, list(dict.fromkeys(inline_hashes))


class SafeRenderer:
    def __init__(self, config: RenderConfig | None = None):
        self.config = config or RenderConfig()
        self.last_result: RenderResult | None = None

    async def render(self, fetcher: Fetcher, response: HTTPResult) -> RenderResult:
        result = RenderResult(status="disabled")
        self.last_result = result
        if not self.config.enabled:
            return result
        started = time.monotonic()
        try:
            if not (1 <= self.config.max_resources <= 20 and 1 <= self.config.max_target_requests <= 40
                    and 1 <= self.config.max_doh_requests <= 80 and 1 <= self.config.max_total_bytes <= 8_000_000
                    and 1 <= self.config.max_dom_bytes <= 2_000_000 and 1 <= self.config.timeout_seconds <= 120
                    and 0 <= self.config.max_observed_data_resources <= 2
                    and 0 <= self.config.settle_ms <= 2000):
                raise FetchStopped("render_configuration_error", "渲染预算配置无效")
            # The deadline covers preparation, resource fetches, startup and DOM work.
            # Cleanup has a separate bounded grace period; it is never called zero-time.
            async with asyncio.timeout(self.config.timeout_seconds):
                await self._prepare_and_run(fetcher, response, result)
        except asyncio.CancelledError:
            result.status, result.error = "cancelled", "任务取消，渲染与所拥有的进程清理已等待"
            raise
        except TimeoutError:
            result.status, result.error = "render_timeout", "渲染总工作期限耗尽；清理宽限独立记录"
        except (FetchStopped, UnsafeURL) as exc:
            result.status = getattr(exc, "status", "unsafe_url")
            result.error = str(exc)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            result.status, result.error = "render_failed", type(exc).__name__
        finally:
            result.elapsed_seconds = round(time.monotonic() - started, 3)
        return result

    async def _prepare_and_run(self, fetcher, response, result):
        source = normalize_url(response.url)
        host = urlsplit(source).hostname or ""
        if host not in self.config.allowed_hosts:
            raise FetchStopped("render_host_not_enabled", "该来源未在服务端渲染允许名单中")
        if self.config.allowed_entries and source not in self.config.allowed_entries:
            raise FetchStopped("render_entry_not_enabled", "该课程入口未在服务端渲染精确允许名单中")
        fetcher._site_policy(source)
        if platform_for_url(source) == "bilibili" and fetcher.config.bilibili_public_metadata:
            raise FetchStopped("render_scope_blocked", "B站本地自用范围只读匿名HTML元信息和目录，不执行脚本或加载播放器")
        if PLATFORM_POLICY_REVIEWS.get(platform_for_url(source), {}).get("status") == "public_course_metadata_only":
            raise FetchStopped("render_scope_blocked", "当前MOOC范围只读匿名公开HTML中的元信息和大纲，不执行脚本或加载JS子资源")
        _safe_url(source, _origin(source))
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if response.status_code != 200 or mime not in {"text/html", "application/xhtml+xml"}:
            raise FetchStopped("render_invalid_document", "渲染入口必须是安全Fetcher已成功读取的HTML")
        if len(response.body) > self.config.max_total_bytes:
            raise FetchStopped("render_byte_budget", "入口HTML超过渲染总字节预算")
        # Only UTF-8 is supported in this first bridge; never guess an encoding.
        encoding = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", response.headers.get("content-type", ""), re.I)
        if encoding and encoding[1].lower() not in {"utf-8", "utf8"}:
            raise FetchStopped("render_unsupported_encoding", "渲染入口当前仅支持UTF-8")
        html = response.body.decode("utf-8-sig")
        access = detect_access_page(BeautifulSoup(html, "html.parser"), source)
        if access:
            raise FetchStopped(access, "入口包含登录、验证或访问限制，未尝试渲染绕过")
        result.source_url, result.source_sha256 = source, hashlib.sha256(response.body).hexdigest()
        result.total_bytes = len(response.body)
        assets, inline_hashes = declared_assets(html, source, self.config.max_resources, self.config.asset_hosts,
            result.excluded_optional_assets)
        payload_assets = [{"requested_url": source, "url": source, "kind": "document", "mime": "text/html",
                           "csp": response.headers.get("content-security-policy", ""),
                           "body_b64": base64.b64encode(response.body).decode()}]
        result.manifest.append({"requested_url": source, "url": source, "kind": "document", "bytes": len(response.body),
                                "sha256": result.source_sha256, "discovery": "initial_safe_fetcher_response"})
        parent = NETWORK_OBSERVER.get() or {}
        active_origin = _origin(source)
        def check_entry_subtree(url, *, robots=False):
            if not self.config.allowed_entries or _origin(url) != _origin(source):
                return
            parts = urlsplit(url)
            if robots and parts.path == "/robots.txt" and not parts.query:
                return
            source_path = urlsplit(source).path
            prefix = source_path if source_path.endswith("/") else source_path.rsplit("/", 1)[0] + "/"
            decoded = unquote(parts.path)
            path = posixpath.normpath(decoded)
            if "\\" in decoded or re.search(r"%[0-9a-f]{2}", decoded, re.I) or not (path + "/").startswith(prefix):
                raise FetchStopped("render_scope_blocked", "课程依赖或重定向超出已启用入口的路径范围")
        async def before_resolve(url):
            _safe_url(url, active_origin)
            check_entry_subtree(url, robots=True)
            if parent.get("before_resolve"):
                await parent["before_resolve"](url)
        async def target():
            if result.target_requests >= self.config.max_target_requests:
                raise FetchStopped("render_request_budget", "渲染目标HTTP预算耗尽")
            if parent.get("before_target_http"):
                await parent["before_target_http"]()
            result.target_requests += 1
        async def dns():
            if result.doh_requests >= self.config.max_doh_requests:
                raise FetchStopped("render_dns_budget", "渲染DoH预算耗尽")
            if parent.get("before_dns_http"):
                await parent["before_dns_http"]()
            result.doh_requests += 1
        def byte_limit():
            remaining = self.config.max_total_bytes - result.total_bytes
            if parent.get("response_byte_limit"):
                remaining = min(remaining, parent["response_byte_limit"]())
            return remaining
        def received(value, kind):
            result.total_bytes += len(value.body)
            if parent.get("response"):
                parent["response"](value, kind)
            if result.total_bytes > self.config.max_total_bytes:
                raise FetchStopped("render_byte_budget", "渲染总字节预算耗尽")
        token = NETWORK_OBSERVER.set({**parent, "before_resolve": before_resolve, "before_target_http": target,
            "before_dns_http": dns, "response_byte_limit": byte_limit, "response": received, "max_retries": 0})
        async def fetch_asset(asset):
            nonlocal active_origin
            check_entry_subtree(asset["fetch_url"])
            active_origin = _origin(asset["fetch_url"])
            value = await fetcher.fetch(asset["fetch_url"])
            final_url = _safe_url(value.url, active_origin)
            check_entry_subtree(final_url)
            content_type = value.headers.get("content-type", "").split(";", 1)[0].lower()
            allowed_mime = (JS_MIME if asset["kind"] == "script" else {"text/css"} if asset["kind"] == "stylesheet"
                else {"text/plain", "text/markdown", "text/x-markdown", "application/json"})
            if value.status_code != 200 or content_type not in allowed_mime:
                raise FetchStopped("render_asset_rejected", "实际声明或观察资产未返回允许的状态及内容类型")
            entry = {"requested_url": asset["requested_url"], "url": final_url, "kind": asset["kind"],
                     "mime": content_type, "body_b64": base64.b64encode(value.body).decode()}
            payload_assets.append(entry)
            result.manifest.append({k: v for k, v in entry.items() if k != "body_b64"} | {
                "bytes": len(value.body), "sha256": hashlib.sha256(value.body).hexdigest(),
                "discovery": asset["declaration"]})
        try:
            # Await serially within the caller's existing task/network slot.
            for asset in assets:
                await fetch_asset(asset)
            for pass_index in range(2):
                result.manifest_sha256 = hashlib.sha256(json.dumps(result.manifest, sort_keys=True).encode()).hexdigest()
                payload = {"entry_url": source, "resources": payload_assets, "inline_hashes": inline_hashes,
                    "asset_hosts": list(self.config.asset_hosts),
                    "max_dom_bytes": self.config.max_dom_bytes, "max_total_bytes": self.config.max_total_bytes,
                    "settle_ms": self.config.settle_ms, "timeout_ms": int(self.config.timeout_seconds * 1000)}
                worker = await self._worker(payload, result)
                blocked = worker.get("blocked_requests", [])
                result.blocked_requests.extend(blocked)
                result.fulfilled_requests.extend(worker.get("fulfilled_requests", []))
                result.passes.append({"pass": pass_index + 1, "status": worker.get("status"),
                    "manifest_sha256": result.manifest_sha256, "blocked_requests": blocked,
                    "fulfilled_requests": worker.get("fulfilled_requests", []),
                    "edge_main_exit_observed": worker.get("edge_main_exit_observed")})
                result.cleanup.update(edge_main_exit_observed=worker.get("edge_main_exit_observed"))
                result.status = worker.get("status", "render_failed")
                if result.status == "rendered":
                    result.html = worker["html"]
                    result.dom_sha256 = hashlib.sha256(result.html.encode()).hexdigest()
                    break
                if pass_index or result.status != "render_dependency_blocked":
                    if pass_index and result.status == "render_dependency_blocked":
                        result.status = "render_incomplete"
                    break
                observed = []
                for item in blocked:
                    url = item.get("url", "")
                    if item.get("reason") != "resource_not_preapproved" or item.get("method") != "GET" or item.get("kind") not in {"fetch", "xhr"}:
                        continue
                    parts = urlsplit(url)
                    if parts.query or not parts.path.lower().endswith((".md", ".json")):
                        continue
                    try:
                        safe = _safe_url(url, _origin(source))
                    except (FetchStopped, UnsafeURL):
                        continue
                    if safe != url or any(row["requested_url"] == url for row in payload_assets + observed):
                        continue
                    observed.append({"requested_url": url, "fetch_url": safe, "kind": "data", "declaration": "observed_first_pass_GET_text_request"})
                eligible_urls = {asset["requested_url"] for asset in observed}
                hard_failure = any(item.get("fatal", True) and not (
                    item.get("reason") == "resource_not_preapproved" and item.get("method") == "GET"
                    and item.get("kind") in {"fetch", "xhr"} and item.get("url") in eligible_urls)
                    for item in blocked)
                if hard_failure or not observed or self.config.max_observed_data_resources == 0 or len(assets) + 1 > self.config.max_resources:
                    break
                # A blocked primary request can trigger a fallback (e.g. a 404
                # template) solely because this first pass is deliberately offline.
                # Resolve the first actual dependency and replay before treating
                # later failures as independent requirements. The second pass is
                # final: any still-missing core dependency yields incomplete.
                result.deferred_observed_dependencies.extend({**asset,
                    "reason": "replay_primary_before_following_failure_cascade"} for asset in observed[1:])
                await fetch_asset(observed[0])
        finally:
            NETWORK_OBSERVER.reset(token)

    async def _worker(self, payload, result):
        process = None
        readers = []
        try:
            process = await asyncio.create_subprocess_exec(self.config.node_executable, str(WORKER),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=self.config.max_dom_bytes * 6 + 100000)
            result.cleanup["node_pid"] = process.pid
            process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()
            async def bounded_read(stream, maximum, readiness=False):
                chunks, consumed = [], 0
                first_line = b""
                while chunk := await stream.read(min(65536, maximum + 1 - consumed)):
                    consumed += len(chunk)
                    if consumed > maximum:
                        raise RuntimeError("renderer_output_budget")
                    chunks.append(chunk)
                    if readiness and len(first_line) <= 8192:
                        first_line += chunk
                        if b"\n" in first_line:
                            event = json.loads(first_line.split(b"\n", 1)[0])
                            if event.get("event") == "ready":
                                result.cleanup.update(worker_ready=True, edge_pid=event.get("edge_pid"))
                            readiness = False
                return b"".join(chunks)
            readers = [asyncio.create_task(bounded_read(process.stdout, self.config.max_dom_bytes * 6 + 100000, True)),
                       asyncio.create_task(bounded_read(process.stderr, 10000))]
            output, errors = await asyncio.gather(*readers)
            await process.wait()
            if errors or process.returncode != 0:
                raise RuntimeError("renderer_protocol_failed")
            lines = output.splitlines()
            if not 1 <= len(lines) <= 2:
                raise ValueError("renderer_protocol_failed")
            message = json.loads(lines[-1])
            if not isinstance(message, dict):
                raise ValueError("renderer_protocol_failed")
            return message
        finally:
            if process is not None:
                await self._cleanup(process, result)
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)

    async def _cleanup(self, process, result):
        result.cleanup.setdefault("forced_tree_cleanup_requested", False)
        if process.returncode is None:
            try:
                async def graceful():
                    process.stdin.write(b'{"cancel":true}\n')
                    await process.stdin.drain()
                    await process.wait()
                # Includes a potentially blocked stdin drain, not just wait().
                await asyncio.wait_for(graceful(), 3)
            except (BrokenPipeError, ConnectionResetError, TimeoutError, ValueError):
                if process.returncode is None:
                    result.cleanup["forced_tree_cleanup_requested"] = True
                    if os.name == "nt":
                        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                        try:
                            await asyncio.wait_for(killer.wait(), 3)
                        except TimeoutError:
                            killer.kill()
                    else:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    try:
                        await asyncio.wait_for(process.wait(), 3)
                    except TimeoutError:
                        pass
        result.cleanup["node_exited"] = process.returncode is not None
