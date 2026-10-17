"""Offline transport timing regression; no external HTTP, SQLite or saved fixtures."""
import asyncio
from dataclasses import replace
import hashlib

import httpx
import pytest

from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER, FETCH_DEADLINE_AT, PinnedHTTPClient

URL = "https://ocw.mit.edu/sitemap.xml"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, values):
        self.values, self.closed = values, False

    async def __aiter__(self):
        for pause, body in self.values:
            await asyncio.sleep(pause)
            yield body

    async def aclose(self):
        self.closed = True


def install(monkeypatch, handler):
    from backend.app import fetcher as module
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(module.httpx, "AsyncClient", client)


def config(**kwargs):
    return replace(FetcherConfig(phased_timeouts=True, timeout_seconds=0.10,
        body_idle_timeout_seconds=0.07, body_timeout_cap_seconds=0.50,
        body_min_bytes_per_second=100, min_interval_seconds=0, max_retries=0), **kwargs)


async def public_dns(*args):
    return ["9.9.9.9"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [True, False])
async def test_size_budget_accepts_continuous_slow_stream_without_sliding_deadline(monkeypatch, declared):
    body = Chunks([(0.03, b"xxxx")] * 8)
    install(monkeypatch, lambda _: httpx.Response(200,
        headers={"content-length": "32"} if declared else {}, stream=body))
    f = Fetcher(config(), resolver=public_dns)
    assert (await f._request(URL, 40)).body == b"x" * 32
    trace = next(e["transport"] for e in f.request_trace if e["event"] == "http_transport")
    assert trace["content_length"] == (32 if declared else None)
    assert trace["body_size_basis_bytes"] == (32 if declared else 40)
    assert trace["body_total_budget_seconds"] == pytest.approx(0.39 if declared else 0.47, abs=0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["expired", "dns", "headers", "body"])
async def test_job_deadline_covers_every_stage_and_expired_never_resolves(monkeypatch, stage):
    calls = []
    async def resolver(*args):
        calls.append("dns")
        if stage == "dns": await asyncio.sleep(1)
        return ["9.9.9.9"]
    async def handler(_):
        calls.append("http")
        if stage == "headers": await asyncio.sleep(1)
        return httpx.Response(200, stream=Chunks([(0, b"part"), (0.1, b"late")]))
    install(monkeypatch, handler)
    f = Fetcher(config(body_idle_timeout_seconds=0.5), resolver=resolver)
    token = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + (-1 if stage == "expired" else 0.035))
    try:
        with pytest.raises(TimeoutError): await f._request(URL, 100)
        assert not f._blocked_hosts
        assert len(calls) == (0 if stage == "expired" else 1 if stage == "dns" else 2)
    finally:
        FETCH_DEADLINE_AT.reset(token)


@pytest.mark.asyncio
async def test_separate_header_body_budget_completes_stream_exceeding_old_total(monkeypatch):
    bodies = []
    async def handler(request):
        assert request.url.host == "9.9.9.9"
        assert request.headers["host"] == "ocw.mit.edu"
        assert request.extensions["sni_hostname"] == "ocw.mit.edu"
        assert "range" not in request.headers
        await request.extensions["trace"]("connection.connect_tcp.started", {"secret": "do-not-record"})
        await asyncio.sleep(0.07)
        await request.extensions["trace"]("connection.connect_tcp.complete", {"return_value": object()})
        body = Chunks([(0.04, b"first"), (0.04, b"second")])
        bodies.append(body)
        return httpx.Response(200, headers={"content-length": "11"}, stream=body)
    install(monkeypatch, handler)
    f = Fetcher(config(), resolver=public_dns)
    result = await f._request(URL, 100)
    assert result.body == b"firstsecond" and bodies[-1].closed
    trace = next(e["transport"] for e in f.request_trace if e["event"] == "http_transport")
    assert trace["status"] == "completed" and trace["body_complete"]
    assert trace["body_total_budget_seconds"] == pytest.approx(0.18, abs=0.01)
    assert trace["bytes_read"] == 11 and trace["body_sha256"] == hashlib.sha256(result.body).hexdigest()
    assert trace["http_status"] == 200 and trace["headers_at"]
    assert trace["phases"][0]["phase"] == "connect_tcp" and "do-not-record" not in str(trace)
    assert NETWORK_OBSERVER.get() is None
    legacy = Fetcher(config(phased_timeouts=False), resolver=public_dns)
    with pytest.raises(FetchStopped) as exc:
        await legacy._request(URL, 100)
    assert exc.value.status == "timeout" and bodies[-1].closed


@pytest.mark.asyncio
async def test_first_response_timeout_is_known_and_not_mistaken_for_body(monkeypatch):
    async def handler(request):
        await request.extensions["trace"]("connection.start_tls.started", {})
        await asyncio.sleep(2)
    install(monkeypatch, handler)
    f = Fetcher(config(), resolver=public_dns)
    with pytest.raises(FetchStopped) as exc:
        await f._request(URL, 100)
    assert exc.value.status == "timeout"
    trace = next(e["transport"] for e in f.request_trace if e["event"] == "http_transport")
    assert trace["timeout_kind"] == "first_response" and trace["phase"] == "start_tls"
    assert trace["http_status"] is None and trace["bytes_read"] == 0
    assert "headers_at" not in trace and f.trace_counts["http_started"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["idle", "total"])
async def test_partial_stream_timeout_preserves_hash_but_returns_no_body(monkeypatch, failure):
    body = Chunks([(0, b"partial"), (1, b"late")]) if failure == "idle" else Chunks([(0.03, b"x")] * 20)
    install(monkeypatch, lambda _: httpx.Response(200, stream=body))
    f = Fetcher(config(body_timeout_cap_seconds=0.12), resolver=public_dns)
    with pytest.raises(FetchStopped) as exc:
        await f._request(URL, 100)
    assert exc.value.status == "timeout" and body.closed
    trace = next(e["transport"] for e in f.request_trace if e["event"] == "http_transport")
    assert trace["timeout_kind"] == f"body_{failure}"
    assert trace["http_status"] == 200 and trace["bytes_read"] > 0 and trace["body_sha256"]
    assert trace["partial_body"] and not trace["body_complete"]
    assert f.trace_counts["http_completed"] == 0 and f.trace_counts["http_started"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [None, "999", "2"])
async def test_body_byte_budget_not_relaxed_by_content_length(monkeypatch, length):
    body = Chunks([(0, b"x" * 20)])
    install(monkeypatch, lambda _: httpx.Response(200, headers={} if length is None else {"content-length": length}, stream=body))
    f = Fetcher(config(), resolver=public_dns)
    with pytest.raises(FetchStopped) as exc:
        await f._request(URL, 10)
    assert exc.value.status == "too_large" and body.closed
    trace = next(e["transport"] for e in f.request_trace if e["event"] == "http_transport")
    assert trace["body_complete"] is False
    assert trace["bytes_read"] == (0 if length == "999" else 20)


@pytest.mark.asyncio
async def test_external_cancellation_propagates_and_closes_stream(monkeypatch):
    body = Chunks([(0, b"partial"), (3, b"late")])
    install(monkeypatch, lambda _: httpx.Response(200, stream=body))
    f = Fetcher(config(body_idle_timeout_seconds=1), resolver=public_dns)
    task = asyncio.create_task(f._request(URL, 100))
    for _ in range(50):
        traces = [e["transport"] for e in f.request_trace if e["event"] == "http_transport"]
        if traces and traces[0]["bytes_read"]:
            break
        await asyncio.sleep(0.002)
    assert traces[0]["bytes_read"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert body.closed and traces[0]["status"] == "cancelled"
    assert f.trace_counts["http_cancelled"] == 1 and "timeout_kind" not in traces[0]
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_optional_response_byte_limit_caps_transport_each_request(monkeypatch):
    body = Chunks([(0, b"four")])
    install(monkeypatch, lambda _: httpx.Response(200, stream=body))
    limits, traces = [3], []
    token = NETWORK_OBSERVER.set({"response_byte_limit": lambda: limits[0], "transport_trace": traces.append})
    try:
        f = Fetcher(config(), resolver=public_dns)
        with pytest.raises(FetchStopped) as exc:
            await f._request(URL, 100)
        assert exc.value.status == "too_large" and traces[0]["max_bytes"] == 3
        limits[0] = 0
        with pytest.raises(FetchStopped) as exc:
            await f._request(URL, 100)
        assert exc.value.status == "budget_exceeded" and f.trace_counts["http_started"] == 1
    finally:
        NETWORK_OBSERVER.reset(token)


@pytest.mark.parametrize("field", ["body_idle_timeout_seconds", "body_min_bytes_per_second", "body_timeout_cap_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan")])
def test_transport_rejects_nonfinite_and_nonpositive_phase_limits(field, value):
    with pytest.raises(ValueError):
        PinnedHTTPClient(config(**{field: value}))


@pytest.mark.asyncio
async def test_new_runner_caps_xml_and_retains_actual_200_on_partial_failure(monkeypatch):
    from scripts.verify_mit_transport_revision import PhasedAuditedHTTP
    from scripts.verify_official_discovery import NetworkAudit
    body = Chunks([(0, b"partial"), (1, b"late")])
    install(monkeypatch, lambda _: httpx.Response(200, stream=body))
    audit = NetworkAudit(target_limit=6, dns_limit=12)
    transport = PhasedAuditedHTTP(audit, PinnedHTTPClient(config()), xml_max_bytes=80)
    with pytest.raises(TimeoutError):
        await transport.request(URL, ["9.9.9.9"], 5000)
    assert len(audit.target) == 1 and audit.stopped == "target_error"
    row = audit.target[0]
    assert row["max_bytes"] == 80 and row["status_code"] == 200
    assert row["error_type"] == "TimeoutError" and row["body_complete"] is False
    assert row["bytes_read"] == 7 and row["partial_body_sha256"] == hashlib.sha256(b"partial").hexdigest()
    assert "source_sha256" not in row and "source_file" not in row
    assert row["transport"]["timeout_kind"] == "body_idle" and NETWORK_OBSERVER.get() is None
    with pytest.raises(FetchStopped):
        await transport.request(URL, ["9.9.9.9"], 5000)
    assert len(audit.target) == 1
