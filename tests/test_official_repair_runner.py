"""Repair-runner budget wrappers, with local synthetic HTTP only."""
import asyncio
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER
from backend.app.official_sitemap import OfficialSitemapProvider, ORIGIN
from backend.app.providers import SearchError
from scripts.verify_official_discovery import AuditedDNS, AuditedHTTP, NetworkAudit


class Bytes(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body
    async def __aiter__(self):
        yield self.body


def mock_dns(monkeypatch, responder=None):
    from backend.app import fetcher as module
    original = httpx.AsyncClient
    def default(request):
        payload = {"Status": 0, "Question": [{"name": "ocw.mit.edu", "type": 1}],
            "Answer": [{"type": 1, "data": "9.9.9.9"}] if request.url.params["type"] == "A" else []}
        return httpx.Response(200, stream=Bytes(json.dumps(payload).encode()))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(responder or default), **kwargs))


@pytest.mark.asyncio
async def test_independent_wrappers_bound_robot_redirect_index_and_provider_context(monkeypatch):
    mock_dns(monkeypatch)
    audit = NetworkAudit(target_limit=3, dns_limit=6)
    calls = []
    class Transport:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(302, {"location": "/public-robots.txt"}, b"", url)
            if url.endswith("/public-robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /\nSitemap: https://ocw.mit.edu/root.xml", url)
            return HTTPResult(200, {"content-type": "application/xml"}, b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://ocw.mit.edu/courses/probability/sitemap.xml</loc></sitemap></sitemapindex>', url)
    fetcher = Fetcher(FetcherConfig(max_retries=0, min_interval_seconds=0, global_concurrency=1),
        http_client=AuditedHTTP(audit, Transport()), resolver=AuditedDNS(audit))
    provider = OfficialSitemapProvider(Settings(), fetcher=fetcher)
    search_count = []
    async def count():
        search_count.append(1)
    provider.request_hook = count
    with pytest.raises(SearchError):
        await provider.search("probability", "en", 5, [])
    assert len(audit.target) == len(calls) == len(search_count) == 3
    assert len(audit.dns) == len(provider.last_dns_requests) == 6
    assert [row["status_code"] for row in audit.target] == [302, 200, 200]
    assert all(row["http_status"] == 200 for row in audit.dns)
    assert not any(url.endswith("/courses/probability/sitemap.xml") for url in calls)
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_dns_cap_counts_actual_first_request_only_on_error(monkeypatch):
    mock_dns(monkeypatch, lambda _: httpx.Response(503, stream=Bytes(b"")))
    audit = NetworkAudit(target_limit=12, dns_limit=24)
    with pytest.raises(Exception):
        await AuditedDNS(audit)(ORIGIN + "/search/")
    assert len(audit.dns) == 1 and audit.dns[0]["http_status"] == 503
    assert audit.dns[0]["status"] == "failed" and audit.target == []
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_detail_and_catalog_use_same_total_wrapper_without_search_counter(monkeypatch):
    mock_dns(monkeypatch)
    audit = NetworkAudit(target_limit=2, dns_limit=4)
    class Transport:
        async def request(self, url, addresses, max_bytes):
            return HTTPResult(200, {}, b"User-agent: *\nAllow: /" if url.endswith("robots.txt") else b"<html>course</html>", url)
    fetcher = Fetcher(FetcherConfig(max_retries=0, min_interval_seconds=0, global_concurrency=1),
        http_client=AuditedHTTP(audit, Transport()), resolver=AuditedDNS(audit))
    response = await fetcher.fetch(ORIGIN + "/courses/example/")
    assert response.status_code == 200
    with pytest.raises(Exception):
        await fetcher.fetch(ORIGIN + "/courses/example/video_galleries/videos/")
    assert len(audit.target) == 2 and len(audit.dns) == 4
    assert NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_repair_blocks_off_origin_before_dns_and_stops_after_denial(monkeypatch, status):
    mock_dns(monkeypatch)
    audit = NetworkAudit()
    with pytest.raises(Exception):
        await AuditedDNS(audit)("https://example.org/redirect")
    assert audit.dns == [] and audit.target == [] and audit.stopped == "outside_approved_origin"
    audit = NetworkAudit()
    class Denied:
        async def request(self, url, addresses, max_bytes):
            return HTTPResult(status, {"retry-after": "60"} if status == 503 else {}, b"", url)
    transport = AuditedHTTP(audit, Denied())
    response = await transport.request(ORIGIN + "/courses/observed/", ["9.9.9.9"], 1000)
    assert response.status_code == status
    with pytest.raises(Exception):
        await AuditedDNS(audit)(ORIGIN + "/next")
    assert len(audit.target) == 1 and audit.dns == [] and audit.stopped == f"target_http_{status}"
