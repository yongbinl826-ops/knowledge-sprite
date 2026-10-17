"""Narrow reviewed CDN route-error handling; all I/O is in memory."""
import pytest
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, FetchStopped

CDN = "https://cdn.jsdelivr.net"
BODY = b"Invalid URL. The URL structure is /project/version/file.js"

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["exact", "other_origin", "redirect_from_other", "cdn_redirect", "html", "denial", "retry", "www-authenticate", "proxy-authenticate", "401", "403", "429", "500"])
async def test_only_exact_initial_cdn_robots_route_error_is_unavailable(case):
    origin = "https://public.example.org" if case in {"other_origin", "redirect_from_other"} else CDN
    calls = []
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if case == "redirect_from_other" and len(calls) == 1:
                return HTTPResult(302, {"location": CDN + "/robots.txt"}, b"", url)
            if case == "cdn_redirect" and len(calls) == 1:
                return HTTPResult(302, {"location": CDN + "/robots.txt"}, b"", url)
            return HTTPResult(int(case) if case.isdigit() else 400,
                {"content-type": "text/html" if case == "html" else "text/plain", **({"retry-after": "60"} if case == "retry" else {}),
                 **({case: 'Basic realm="restricted"'} if case.endswith("authenticate") else {})},
                BODY + (b" Access denied" if case == "denial" else b""), url)
    async def dns(*args): return ["9.9.9.9"]
    f = Fetcher(FetcherConfig(min_interval_seconds=0, max_retries=0), resolver=dns, http_client=HTTP())
    if case == "exact":
        assert (await f._robots_for(origin + "/file.js")).allowed(origin + "/file.js")
        assert any(r["event"] == "robots_unavailable_4xx" for r in f.request_trace)
    else:
        with pytest.raises(FetchStopped): await f._robots_for(origin + "/file.js")
        assert origin not in f._robots
