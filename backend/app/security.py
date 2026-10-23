"""Bounded HTTP ingress for the single-user, single-process application.

This is a local access boundary, not user authentication. An internet deployment
still needs a trusted authenticated reverse proxy and a separate threat review.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import time
from collections import deque
from urllib.parse import urlsplit
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from .config import Settings


logger = logging.getLogger("knowledge_sprite.http")


class RequestSecurityMiddleware:
    """Pure ASGI: cap a streamed body before FastAPI parses or stores it."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings
        # One process owns both this limiter and the persistent job queues.
        self.writes: deque[float] = deque()
        self.event_streams = 0

    @staticmethod
    def response_headers(path: str, request_id: str) -> dict[str, str]:
        headers = {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' https: data:; connect-src 'self'; font-src 'self'; "
                "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
        }
        if path.startswith("/api/") or path.startswith("/health"):
            headers["Cache-Control"] = "no-store"
        return headers

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope.get("path", "")
        headers = Headers(scope=scope)
        status = 500
        response_started = False
        stream_slot = False

        async def secure_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                response_headers = MutableHeaders(scope=message)
                for key, value in self.response_headers(path, request_id).items():
                    response_headers[key] = value
                if status >= 400:
                    response_headers["Cache-Control"] = "no-store"
            await send(message)

        async def reject(code: str, message: str, code_status: int, retry_after: int | None = None):
            extra = {"Retry-After": str(retry_after)} if retry_after else {}
            await JSONResponse({"detail": message, "code": code, "request_id": request_id},
                               status_code=code_status, headers=extra)(scope, receive, secure_send)

        try:
            # Host is checked even on GET: CORS alone does not stop DNS rebinding.
            host_values = headers.getlist("host")
            try:
                authority = urlsplit("http://" + host_values[0]) if len(host_values) == 1 else None
                host = authority.hostname if authority else None
                valid_host = bool(authority and host in self.settings.allowed_hosts and
                    authority.username is None and authority.password is None and
                    not authority.path and not authority.query and not authority.fragment and
                    authority.port != 0 and not any(char.isspace() for char in host_values[0]))
            except ValueError:
                valid_host = False
            if not valid_host:
                await reject("untrusted_host", "请求主机不在允许列表中。", 400)
                return
            if (self.settings.app_mode == "mobile" and path.startswith("/api/")
                    and not path.startswith("/api/mobile/") and path != "/api/capabilities"):
                await reject("not_found", "接口不存在。", 404)
                return
            if self.settings.local_only:
                client = scope.get("client")
                try:
                    local = bool(client and ipaddress.ip_address(client[0]).is_loopback)
                except ValueError:
                    local = False
                if not local:
                    await reject("local_access_only", "当前服务仅允许本机访问。", 403)
                    return
            if len(scope.get("raw_path", b"")) + len(scope.get("query_string", b"")) > 8192:
                await reject("uri_too_long", "请求地址过长。", 414)
                return
            origin_values = headers.getlist("origin")
            own_origin = f"{scope.get('scheme', 'http')}://{host_values[0]}"
            native_origins = self.settings.mobile_origins if self.settings.app_mode == "mobile" else ()
            if origin_values and (len(origin_values) != 1 or
                origin_values[0] not in {*self.settings.cors_origins, *native_origins, own_origin}):
                await reject("untrusted_origin", "该网页来源无权访问本地项目。", 403)
                return
            if path.startswith("/api/") and not origin_values and headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                await reject("cross_site_request", "请从应用页面发起操作。", 403)
                return
            lengths = headers.getlist("content-length")
            if lengths and (len(lengths) != 1 or len(lengths[0]) > 20 or
                            not lengths[0].isascii() or not lengths[0].isdigit()):
                await reject("invalid_content_length", "请求长度无效。", 400)
                return
            if lengths and int(lengths[0]) > self.settings.max_request_body_bytes:
                await reject("request_too_large", "请求内容过大，请缩短需求或分阶段提交。", 413)
                return
            if headers.get("content-encoding", "identity").lower() != "identity":
                await reject("unsupported_encoding", "请发送未压缩的 JSON 请求。", 415)
                return
            body = bytearray()
            try:
                async with asyncio.timeout(self.settings.request_body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            status = 499
                            return
                        if message["type"] != "http.request":
                            continue
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > self.settings.max_request_body_bytes:
                            await reject("request_too_large", "请求内容过大，请缩短需求或分阶段提交。", 413)
                            return
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await reject("request_body_timeout", "接收请求超时，请重试。", 408)
                return
            if lengths and len(body) != int(lengths[0]):
                await reject("invalid_content_length", "请求长度与内容不一致。", 400)
                return
            method = scope["method"]
            if path.startswith("/api/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
                content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if body and content_type != "application/json":
                    await reject("json_required", "此接口仅接受 application/json。", 415)
                    return
                # Cancellation must remain available even after write admission fills.
                if not path.endswith("/cancel"):
                    current = time.monotonic()
                    while self.writes and current - self.writes[0] >= 60:
                        self.writes.popleft()
                    if len(self.writes) >= self.settings.api_write_limit_per_minute:
                        retry = max(1, math.ceil(60 - (current - self.writes[0])))
                        await reject("api_write_rate_limited", "操作过于频繁，请稍后重试。", 429, retry)
                        return
                    self.writes.append(current)
            if method == "GET" and path.startswith("/api/") and path.endswith("/events"):
                # No await between checking and reserving on this process's loop.
                # Bound idle subscribers before the first expensive projection.
                if self.event_streams >= self.settings.max_event_streams:
                    await reject("event_streams_full", "实时连接已达上限，请稍后重试。", 429, 2)
                    return
                self.event_streams += 1
                stream_slot = True
            sent_body = False

            async def bounded_receive():
                nonlocal sent_body
                if not sent_body:
                    sent_body = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            try:
                await self.app(scope, bounded_receive, secure_send)
            except Exception as exc:
                logger.error("http_failure request_id=%s error_type=%s", request_id, type(exc).__name__)
                if response_started:
                    raise
                await reject("internal_error", "服务暂时异常，请保留请求编号并稍后重试。", 500)
        finally:
            if stream_slot:
                self.event_streams -= 1
            # Never log user text, raw URL/query, IP, Origin, headers or exception values.
            route = getattr(scope.get("route"), "path", "<unmatched>")
            logger.info("http_request request_id=%s method=%s route=%s status=%s duration_ms=%s",
                        request_id, scope.get("method", ""), route, status,
                        round((time.monotonic() - started) * 1000))
