"""Bounded discovery regression; synthetic responses never enter live results."""
import asyncio
import httpx
import pytest

from backend.app.config import Settings, course_domains
from backend.app.models import SearchRequest
from backend.app.providers import SearchError, SearXNGProvider, retry_after_seconds
from backend.app.queries import generate_queries


def test_open_source_query_is_bounded_supplement_not_seeded_courses():
    request = SearchRequest(knowledge_points=["an unseen arbitrary topic"], language="en")
    queries = generate_queries("point", request.knowledge_points[0], request, ["extra keywords"],
                               open_course_domains=("ocw.mit.edu", "open.edu"))
    assert len(queries) == 6
    assert len([q for q in queries if not q.domain_filters]) == 2
    assert all(request.knowledge_points[0] in q.query for q in queries)
    assert queries[-1].domain_filters == ["ocw.mit.edu", "open.edu"]
    assert "site:ocw.mit.edu OR site:open.edu" in queries[-1].query
    assert "extra keywords" in queries[1].query
    assert all("/courses/" not in q.query for q in queries)
    assert course_domains("!youtube,https://evil.test/path,ocw.mit.edu,OPEN.EDU,more.test") == ("ocw.mit.edu", "open.edu")


@pytest.mark.parametrize("value", ["nan", "inf", "-2", "1e999", "not a date", None])
def test_search_retry_after_is_finite(value):
    assert retry_after_seconds(value) == 60


@pytest.mark.asyncio
async def test_search_503_retry_after_pauses_without_fallback():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(503, headers={"Retry-After": "120"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://test", searxng_engines=("a",),
            searxng_fallback_engines=("b",), search_min_interval_seconds=0), client)
        for query in ["one", "two"]:
            with pytest.raises(SearchError, match="暂停"):
                await provider.search(query, "en", 6, [])
    assert len(calls) == 1


class CountedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.reads, self.closed = 0, False
    async def __aiter__(self):
        for _ in range(100):
            self.reads += 1
            yield b"x" * 65536
    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_search_response_limit_stops_stream_and_closes_it():
    stream = CountedStream()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://test"), client)
        with pytest.raises(SearchError, match="超过"):
            await provider.search("topic", "en", 6, [])
    assert stream.reads == 31 and stream.closed


@pytest.mark.asyncio
async def test_search_cancel_closes_stream_and_records_cancelled():
    started, closed = asyncio.Event(), asyncio.Event()
    class WaitingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unused"
        async def aclose(self):
            closed.set()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=WaitingStream()))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://test"), client)
        task = asyncio.create_task(provider.search("topic", "en", 6, []))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set() and provider.last_requests[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_fetcher_redirect_binds_course_to_safe_response_not_declared_canonical():
    """Exercise actual Fetcher redirect/extractor/ranking flow with isolated HTTP."""
    from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult
    from backend.app.ranking import has_course_page
    from backend.app.resource_identity import derive_course_identity
    original = "http://learning.example.org/old-course"
    resolved = "https://learning.example.org/course/python"
    calls, resolutions = [], []

    async def resolver(url, timeout):
        resolutions.append(url)
        return ["93.184.216.34"]

    class OfflineHTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            assert addresses == ["93.184.216.34"]
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            if url == original:
                return HTTPResult(301, {"location": resolved}, b"", url)
            assert url == resolved
            body = b'<html><head><link rel="canonical" href="https://unrelated.example.org/forged"><script type="application/ld+json">{"@type":"Course","name":"Python lists course"}</script></head><body><main>Python lists course with exercises and a public introduction.</main></body></html>'
            return HTTPResult(200, {"content-type": "text/html"}, body, url)

    fetcher = Fetcher(FetcherConfig(max_retries=0, min_interval_seconds=0), resolver=resolver, http_client=OfflineHTTP())
    resource = await fetcher.enrich({"url": original, "title": "Python lists", "source": "isolated_fixture"})
    evidence = resource["evidence"]
    assert resource["fetch_status"] == "fetched" and resource["resolved_url"] == resolved
    assert resource["url"] == original and has_course_page(resource, evidence)
    assert derive_course_identity(resource, evidence)["family_url"] == resolved
    assert resource["video_evidence_status"] == "none"
    assert resolved in resolutions and calls == ["http://learning.example.org/robots.txt", original,
        "https://learning.example.org/robots.txt", resolved]
    assert not any("unrelated.example.org" in url for url in calls)
