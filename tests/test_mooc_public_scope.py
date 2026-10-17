"""Public-course reads may proceed; learning/API/auth remain outside scope."""
import pytest
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, public_mooc_metadata_url
from backend.app.url_utils import normalize_url

ORIGIN = "https://www.icourse163.org"
COURSE = ORIGIN + "/course/PKU-1003479006"
PAGE = b'<html><title>Public Python course</title><h1>Public Python course</h1><p>Course introduction available without signing in.</p></html>'


@pytest.mark.parametrize("url", [COURSE, COURSE+"/", COURSE+"?tid=1470359605", ORIGIN+"/course/-1462245166", "https://icourse163.org/course/BIT-1001871002"])
@pytest.mark.asyncio
async def test_public_html_reaches_robots_and_real_transport_without_credentials(url):
    calls = []
    origin = url.split("/course/")[0]
    class HTTP:
        async def request(self, target, addresses, max_bytes):
            calls.append(target)
            if target.endswith("/robots.txt"):
                return HTTPResult(404, {"content-type":"text/html"}, b"", target)
            assert target == url
            return HTTPResult(200, {"content-type":"text/html"}, PAGE, target)
    async def dns(target, timeout):
        return ["93.184.216.34"]
    fetcher = Fetcher(FetcherConfig(min_interval_seconds=0, max_retries=0), resolver=dns, http_client=HTTP())
    result = await fetcher.enrich({"url":url})
    assert result["fetch_status"] == "fetched" and calls == [origin+"/robots.txt", url]
    assert result["chapters"] == [] and result["requires_login"] is None


@pytest.mark.parametrize("url", [
    ORIGIN+"/learn/PKU-1003479006", ORIGIN+"/spoc/learn/a", ORIGIN+"/j/courseBean.getCourseDetail.rpc",
    ORIGIN+"/dwr/call/plaincall/CourseBean.getLastLearnedMocTermDto.dwr", ORIGIN+"/api/course/1003479006",
    ORIGIN+"/login", ORIGIN+"/home.htm", ORIGIN+"/course/a", COURSE+"?token=x", COURSE+"?tid=x",
    COURSE+"?tid=1&tid=2", COURSE+"#learn", "http://www.icourse163.org/course/PKU-1003479006",
    "https://account.icourse163.org/course/PKU-1003479006", ORIGIN+"/%63ourse/PKU-1003479006",
    ORIGIN+"/course/PKU-１２３４", COURSE+"?tid=１２３４",
])
@pytest.mark.asyncio
async def test_nonpublic_paths_never_reach_dns_even_with_broad_host_allowlist(url):
    async def unexpected_dns(*args):
        raise AssertionError("Scope-restricted path must not resolve")
    fetcher = Fetcher(FetcherConfig(allowed_restricted_hosts=("icourse163.org",)), resolver=unexpected_dns)
    assert not public_mooc_metadata_url(url)
    result = await fetcher.enrich({"url":url})
    assert result["fetch_status"] == "policy_unreviewed"
    record = next(row for row in result["evidence"] if row["kind"] == "site_policy")
    assert record["blocked_target_url"] == normalize_url(url) and record["restricted_target_request_sent"] is False


@pytest.mark.parametrize("barrier", ["robots", "redirect", "captcha", "login"])
@pytest.mark.asyncio
async def test_public_scope_does_not_override_actual_access_barriers(barrier):
    calls = []
    class HTTP:
        async def request(self, target, addresses, max_bytes):
            calls.append(target)
            if target.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type":"text/plain"}, b"User-agent: *\nDisallow: /course/" if barrier == "robots" else b"User-agent: *\nAllow: /", target)
            assert target == COURSE, "No redirected or private target may be fetched"
            if barrier == "redirect":
                return HTTPResult(302, {"location":ORIGIN+"/learn/PKU-1003479006"}, b"", target)
            body = b'<html><title>Verify you are human</title><p>captcha</p></html>' if barrier == "captcha" else b'<html><title>Login</title><form><input type="password"></form><p>Please sign in to continue</p></html>'
            return HTTPResult(200, {"content-type":"text/html"}, body, target)
    async def dns(target, timeout):
        assert target in {COURSE,ORIGIN+"/robots.txt"}
        return ["93.184.216.34"]
    fetcher=Fetcher(FetcherConfig(min_interval_seconds=0,max_retries=0),resolver=dns,http_client=HTTP())
    result=await fetcher.enrich({"url":COURSE})
    assert result["fetch_status"] == {"robots":"robots_blocked","redirect":"policy_unreviewed","captcha":"captcha","login":"login_required"}[barrier]
    assert len(calls) == (1 if barrier == "robots" else 2)
    assert not result["chapters"]


@pytest.mark.parametrize("robots_redirect", [True, False])
@pytest.mark.asyncio
async def test_mooc_redirect_cannot_escape_to_other_public_hosts(robots_redirect):
    calls = []
    outside = "https://courses.example.org/course/external"
    class HTTP:
        async def request(self, target, addresses, max_bytes):
            calls.append(target)
            assert target in {COURSE, ORIGIN+"/robots.txt"}
            if robots_redirect or target == COURSE:
                return HTTPResult(302, {"location": outside}, b"", target)
            return HTTPResult(404, {}, b"", target)
    async def dns(target, timeout):
        assert target in {COURSE, ORIGIN+"/robots.txt"}, "Foreign redirect must stop before DNS"
        return ["93.184.216.34"]
    fetcher=Fetcher(FetcherConfig(min_interval_seconds=0,max_retries=0),resolver=dns,http_client=HTTP())
    result=await fetcher.enrich({"url":COURSE})
    assert result["fetch_status"] == "policy_unreviewed"
    assert len(calls) == (1 if robots_redirect else 2)
    record=next(row for row in result["evidence"] if row["kind"] == "site_policy")
    assert record["blocked_target_url"] == outside and record["restricted_target_request_sent"] is False
