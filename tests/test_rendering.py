"""Isolated production bridge tests. All Fetcher HTTP and DNS are in-memory.

The two Edge cases execute only inline, audited test strings; no live site script.
"""
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import replace

import pytest

from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER
from backend.app.rendering import RenderConfig, SafeRenderer, declared_assets


ORIGIN = "https://renderer.example.org"
ENTRY = ORIGIN + "/course/"
CDN = "https://cdn.example.org"
BASE = RenderConfig(enabled=True, allowed_hosts=("renderer.example.org",), timeout_seconds=45, settle_ms=100)


def response(url, body=b"", mime="text/html", status=200, **headers):
    return HTTPResult(status, {"content-type": mime, **headers}, body if isinstance(body, bytes) else body.encode(), url)


class MemoryHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def request(self, url, addresses, max_bytes):
        self.requests.append((url, max_bytes))
        assert url in self.responses, "No fixture response: no network fallback is available"
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = await value()
        if len(value.body) > max_bytes:
            raise ValueError("body exceeds the passed Fetcher byte cap")
        return value


async def dns(url, timeout):
    return ["93.184.216.34"]


async def fixture(html="<title>Static</title>", resources=None, resolver=dns, headers=None):
    sources = {ENTRY: response(ENTRY, html, **(headers or {})),
        ORIGIN + "/robots.txt": response(ORIGIN + "/robots.txt", "User-agent: *\nAllow: /\n", "text/plain")}
    sources.update(resources or {})
    http = MemoryHTTP(sources)
    fetcher = Fetcher(FetcherConfig(min_interval_seconds=0, max_retries=0), resolver=resolver, http_client=http)
    value = await fetcher.fetch(ENTRY)
    http.requests.clear()
    return fetcher, http, value


class StubRenderer(SafeRenderer):
    def __init__(self, config=BASE, workers=None):
        super().__init__(config)
        self.workers = list(workers or [{"status": "rendered", "html": "<h1>Course</h1>"}])
        self.payloads = []

    async def _worker(self, payload, result):
        self.payloads.append(payload)
        return self.workers.pop(0)


def blocked(url, kind="fetch", method="GET"):
    return {"status": "render_dependency_blocked", "blocked_requests": [
        {"reason": "resource_not_preapproved", "url": url, "kind": kind, "method": method}]}


def test_disabled_and_unlisted_host_never_start_worker():
    async def run():
        fetcher, http, value = await fixture()
        for config, expected in [(RenderConfig(), "disabled"), (replace(BASE, allowed_hosts=()), "render_host_not_enabled")]:
            renderer = StubRenderer(config)
            assert (await renderer.render(fetcher, value)).status == expected
            assert renderer.payloads == []
        assert http.requests == []
    asyncio.run(run())


@pytest.mark.parametrize("usage", ["scripts", "fetch_get", "fetch_post", "navigation", "unknown_script"])
def test_real_edge_optional_mit_scripts_are_zero_fetch_and_other_uses_still_fail(usage):
    async def run():
        entry = "https://ocw.mit.edu/courses/example/"
        appzi = "https://w.appzi.io/w.js?token=offline-test"
        code = "document.querySelector('h1').textContent='Probability course';"
        if usage == "scripts":
            extra = f'<script async src="{appzi}"></script>'
            code += "const s=document.createElement('script');s.src='https://www.googletagmanager.com/gtm.js?id=offline';document.head.appendChild(s);"
        else:
            extra = ""
            code += {"fetch_get": f"fetch('{appzi}').catch(()=>{{}});",
                "fetch_post": f"fetch('{appzi}',{{method:'POST'}}).catch(()=>{{}});",
                "navigation": f"location.href='{appzi}';",
                "unknown_script": "const s=document.createElement('script');s.src='https://w.appzi.io/unknown.js';document.head.appendChild(s);"}[usage]
        html = f"<h1>Loading</h1>{extra}<script>{code}</script>"
        http = MemoryHTTP({})
        fetcher = Fetcher(FetcherConfig(min_interval_seconds=0), resolver=dns, http_client=http)
        renderer = SafeRenderer(replace(BASE, allowed_hosts=("ocw.mit.edu",), settle_ms=300))
        result = await renderer.render(fetcher, response(entry, html))
        assert http.requests == [] and result.target_requests == result.doh_requests == 0
        assert result.source_sha256 == hashlib.sha256(html.encode()).hexdigest()
        assert all(row["kind"] == "document" for row in result.fulfilled_requests)
        if usage == "scripts":
            assert result.status == "rendered" and "Probability course" in result.html
            assert len(result.excluded_optional_assets) == 1
            assert len([r for r in result.blocked_requests if r["reason"] == "optional_integration_blocked" and r["fatal"] is False]) == 2
        else:
            assert result.status == "render_dependency_blocked"
            assert any(r["fatal"] for r in result.blocked_requests)
    asyncio.run(run())


@pytest.mark.parametrize("url", ["https://www.bilibili.com/video/BV1234567890", "https://www.icourse163.org/course/TEST-123"])
def test_allowlist_does_not_override_platform_policy(url):
    async def run():
        fetcher, _, value = await fixture()
        value.url = url
        renderer = StubRenderer(replace(BASE, allowed_hosts=(url.split('/')[2],)))
        assert (await renderer.render(fetcher, value)).status == ("render_scope_blocked" if "icourse163.org" in url else "site_policy_blocked")
        assert renderer.payloads == []
    asyncio.run(run())


@pytest.mark.parametrize("src", ["https://evil.example.org/a.js", "http://127.0.0.1/a.js", "https://user:pass@renderer.example.org/a.js", "/login/a.js"])
def test_declared_asset_security_blocks_before_http(src):
    async def run():
        fetcher, http, value = await fixture(f'<script src="{src}"></script>')
        renderer = StubRenderer()
        assert (await renderer.render(fetcher, value)).status in {"unsafe_url", "render_scope_blocked"}
        assert http.requests == [] and renderer.payloads == []
    asyncio.run(run())


def test_explicit_cdn_only_declared_and_hooks_preserved():
    async def run():
        script = CDN + "/actual.js"
        fetcher, http, value = await fixture(f'<script src="{script}"></script>', {
            CDN + "/robots.txt": response(CDN + "/robots.txt", "User-agent: *\nAllow: /\n", "text/plain"),
            script: response(script, "window.ready=true", "application/javascript")})
        seen = []
        async def target(): seen.append("http")
        parent = {"before_target_http": target, "response": lambda value, kind: seen.append(kind)}
        token = NETWORK_OBSERVER.set(parent)
        try:
            renderer = StubRenderer(replace(BASE, asset_hosts=("cdn.example.org",)))
            result = await renderer.render(fetcher, value)
            assert NETWORK_OBSERVER.get() is parent
        finally: NETWORK_OBSERVER.reset(token)
        assert result.status == "rendered" and result.target_requests == 2
        assert len([x for x in seen if x == "http"]) == 2
        assert [x[0] for x in http.requests] == [CDN + "/robots.txt", script]
        assert result.source_sha256 == hashlib.sha256(value.body).hexdigest()
        assert result.dom_sha256 == hashlib.sha256(result.html.encode()).hexdigest()
        assert result.manifest[-1]["discovery"] == "script[src]"
        assert result.isolation["process_network_egress"] == "unknown"
    asyncio.run(run())


def test_two_pass_only_actual_get_data_and_same_budgets():
    async def run():
        data = ORIGIN + "/course/content.md"
        fetcher, http, value = await fixture("<script>fetch('content.md')</script>", {data: response(data, "# Synthetic", "text/plain")})
        renderer = StubRenderer(workers=[blocked(data), {"status": "rendered", "html": "<h1>Synthetic</h1>"}])
        result = await renderer.render(fetcher, value)
        assert result.status == "rendered" and len(result.passes) == 2
        assert [row[0] for row in http.requests] == [data]
        assert result.target_requests == 1 and result.total_bytes == len(value.body) + len(b"# Synthetic")
        assert result.passes[0]["manifest_sha256"] != result.passes[1]["manifest_sha256"]
        assert result.manifest[-1]["discovery"] == "observed_first_pass_GET_text_request"
    asyncio.run(run())


def test_real_edge_replays_primary_before_following_offline_failure_fallback():
    async def run():
        data, fallback = ORIGIN + "/course/README.md", ORIGIN + "/_404.md"
        html = """<h1>Loading</h1><script>
            fetch('README.md').then(r=>r.text()).then(t=>document.querySelector('h1').textContent=t)
                .catch(()=>fetch('/_404.md'));
            </script>"""
        fetcher, http, value = await fixture(html, {data: response(data, "Course lessons", "text/plain")})
        result = await SafeRenderer(replace(BASE, settle_ms=300)).render(fetcher, value)
        assert result.status == "rendered" and "Course lessons" in result.html
        assert len(result.passes) == 2 and [r[0] for r in http.requests] == [data]
        assert any(r["requested_url"] == fallback for r in result.deferred_observed_dependencies)
        assert any(r["url"] == fallback for r in result.passes[0]["blocked_requests"])
        assert not any(r["url"] == fallback for r in result.passes[1]["blocked_requests"])
    asyncio.run(run())


@pytest.mark.parametrize("url,kind,method", [(ORIGIN + "/api", "fetch", "GET"),
    (ORIGIN + "/secret.json?token=x", "fetch", "GET"), (ORIGIN + "/login/data.json", "fetch", "GET"),
    (ORIGIN + "/data.json", "fetch", "POST"), (ORIGIN + "/late.js", "script", "GET"),
    ("https://evil.example.org/data.json", "fetch", "GET")])
def test_no_guessed_or_out_of_scope_data_followup(url, kind, method):
    async def run():
        fetcher, http, value = await fixture()
        renderer = StubRenderer(workers=[blocked(url, kind, method)])
        result = await renderer.render(fetcher, value)
        assert result.status == "render_dependency_blocked"
        assert http.requests == [] and len(result.passes) == 1
    asyncio.run(run())


@pytest.mark.parametrize("failure", [
    {"reason":"non_get", "method":"POST", "kind":"fetch", "url":ORIGIN + "/README.md"},
    {"reason":"navigation_or_frame", "method":"GET", "kind":"document", "url":ORIGIN + "/README.md"},
    {"reason":"resource_not_preapproved", "method":"GET", "kind":"script", "url":ORIGIN + "/unknown.js"},
    {"reason":"csp_connect-src", "url":"https://w.appzi.io/w.js"},
    {"reason":"worker"},
])
def test_first_pass_critical_failure_cannot_be_hidden_by_successful_replay(failure):
    async def run():
        data = ORIGIN + "/README.md"
        fetcher, http, value = await fixture(resources={data:response(data,"text","text/plain")})
        first = blocked(data)
        first["blocked_requests"].append({**failure,"fatal":True})
        renderer = StubRenderer(workers=[first,{"status":"rendered","html":"<h1>False success</h1>"}])
        result = await renderer.render(fetcher,value)
        assert result.status == "render_dependency_blocked" and result.html is None
        assert len(result.passes) == 1 and http.requests == []
    asyncio.run(run())


def test_exact_renderer_entry_restriction_stops_other_page_before_worker():
    async def run():
        fetcher,http,value=await fixture()
        renderer=StubRenderer(replace(BASE,allowed_entries=(ENTRY + "other/",)))
        assert (await renderer.render(fetcher,value)).status == "render_entry_not_enabled"
        assert http.requests == [] and renderer.payloads == []
        renderer=StubRenderer(replace(BASE,allowed_entries=(ENTRY,)))
        assert (await renderer.render(fetcher,value)).status == "rendered"
    asyncio.run(run())


@pytest.mark.parametrize("path", ["/Other-Curriculum/README.md", "/course/../Other/README.md", "/course/%2e%2e/Other/README.md", "/course/%252e%252e/Other/README.md"])
def test_exact_entry_data_stays_in_course_subtree_before_http(path):
    async def run():
        fetcher,http,value=await fixture()
        renderer=StubRenderer(replace(BASE,allowed_entries=(ENTRY,)),workers=[blocked(ORIGIN+path)])
        assert (await renderer.render(fetcher,value)).status == "render_scope_blocked"
        assert http.requests == []
    asyncio.run(run())


@pytest.mark.parametrize("declaration", ["data", "script"])
def test_exact_entry_dependency_redirect_stops_before_other_project_dns(declaration):
    async def run():
        first, other = ENTRY+"a.md", ORIGIN+"/Other-Curriculum/README.md"
        fetcher,http,value=await fixture("<script src='a.md'></script>" if declaration=="script" else "<h1>Page</h1>",
            {first:response(first,status=302,location=other)})
        renderer=StubRenderer(replace(BASE,allowed_entries=(ENTRY,)),workers=[blocked(first)])
        assert (await renderer.render(fetcher,value)).status == "render_scope_blocked"
        assert [r[0] for r in http.requests] == [first]
    asyncio.run(run())


def test_second_pass_missing_is_incomplete_never_third_fetch():
    async def run():
        one, two = ORIGIN + "/one.md", ORIGIN + "/two.md"
        fetcher, http, value = await fixture(resources={one: response(one, "one", "text/plain")})
        renderer = StubRenderer(workers=[blocked(one), blocked(two)])
        result = await renderer.render(fetcher, value)
        assert result.status == "render_incomplete" and len(result.passes) == 2
        assert [r[0] for r in http.requests] == [one]
    asyncio.run(run())


@pytest.mark.parametrize("target", ["https://evil.example.org/script.js", "http://127.0.0.1/script.js", ORIGIN + "/login/script.js"])
def test_asset_redirect_scope_stops_before_destination_request(target):
    async def run():
        script = ORIGIN + "/a.js"
        fetcher, http, value = await fixture('<script src="/a.js"></script>', {
            script: response(script, status=302, location=target)})
        renderer = StubRenderer()
        result = await renderer.render(fetcher, value)
        assert result.status in {"unsafe_url", "render_scope_blocked"}
        assert [r[0] for r in http.requests] == [script] and renderer.payloads == []
    asyncio.run(run())


def test_asset_dns_rebinding_and_robots_denial_not_bypassed():
    async def run():
        fetcher, http, value = await fixture('<script src="/a.js"></script>')
        async def private(url, timeout): return ["127.0.0.1"]
        fetcher.resolver = private
        assert (await StubRenderer().render(fetcher, value)).status == "unsafe_url"
        assert http.requests == []
    asyncio.run(run())


def test_request_byte_and_resource_budgets_do_not_fall_back():
    async def run():
        scripts = {ORIGIN + f"/{x}.js": response(ORIGIN + f"/{x}.js", "x" * 20, "text/javascript") for x in ("a", "b")}
        fetcher, http, value = await fixture('<script src="/a.js"></script><script src="/b.js"></script>', scripts)
        result = await StubRenderer(replace(BASE, max_target_requests=1)).render(fetcher, value)
        assert result.status == "render_request_budget" and len(http.requests) == 1
        http.requests.clear()
        result = await StubRenderer(replace(BASE, max_total_bytes=len(value.body) + 10)).render(fetcher, value)
        assert result.status != "rendered" and http.requests[0][1] == 10
        http.requests.clear()
        result = await StubRenderer(replace(BASE, max_resources=1)).render(fetcher, value)
        assert result.status == "render_resource_budget" and http.requests == []
    asyncio.run(run())


def test_cancellation_and_total_deadline_during_prefetch():
    async def run():
        started = asyncio.Event()
        async def hang(): started.set(); await asyncio.sleep(60)
        fetcher, _, value = await fixture('<script src="/a.js"></script>', {ORIGIN + "/a.js": hang})
        renderer = StubRenderer()
        task = asyncio.create_task(renderer.render(fetcher, value))
        await started.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert renderer.last_result.status == "cancelled" and NETWORK_OBSERVER.get() is None
        timed = await StubRenderer(replace(BASE, timeout_seconds=1)).render(fetcher, value)
        assert timed.status == "render_timeout"
    asyncio.run(run())


def test_real_edge_two_pass_actual_script_creates_course_and_two_chapters():
    async def run():
        script, data = CDN + "/actual.js", ORIGIN + "/course/content.json"
        code = "fetch('content.json').then(r=>r.json()).then(data=>{const s=document.createElement('script');s.type='application/ld+json';s.textContent=JSON.stringify(data);document.head.append(s)}).catch(()=>{});"
        course = {"@context": "https://schema.org", "@type": "Course", "name": "Synthetic dynamic course", "hasPart": [
            {"@type": "CreativeWork", "name": "Lists"}, {"@type": "CreativeWork", "name": "Iteration"}]}
        fetcher, http, value = await fixture(f'<html><head><script src="{script}"></script></head><body><img src="/passive.png"></body></html>', {
            CDN + "/robots.txt": response(CDN + "/robots.txt", "User-agent: *\nAllow: /\n", "text/plain"),
            script: response(script, code, "application/javascript"), data: response(data, json.dumps(course), "application/json")})
        result = await SafeRenderer(replace(BASE, asset_hosts=("cdn.example.org",), settle_ms=200)).render(fetcher, value)
        assert result.status == "rendered", result.as_dict()
        assert "Synthetic dynamic course" in result.html and "Lists" in result.html and "Iteration" in result.html
        assert len(result.passes) == 2 and result.target_requests == 3
        assert [r[0] for r in http.requests] == [CDN + "/robots.txt", script, data]
        assert result.cleanup["node_exited"] is True and result.cleanup["edge_main_exit_observed"] is True
        assert result.cleanup["all_descendant_processes_exited"] == "unknown"
    asyncio.run(run())


def test_real_edge_source_csp_preserved_and_inline_eval_not_enabled():
    async def run():
        fetcher, http, value = await fixture('<script>document.title="forbidden"</script>', headers={"content-security-policy": "script-src 'none'"})
        result = await SafeRenderer(BASE).render(fetcher, value)
        assert result.status == "render_dependency_blocked", result.as_dict()
        assert any(row["reason"].startswith("csp_script") for row in result.blocked_requests)
        assert http.requests == [] and result.cleanup["node_exited"] is True
    asyncio.run(run())


def test_nonreading_child_drain_cancellation_has_bounded_cleanup(tmp_path, monkeypatch):
    # This stand-in owns only its own process and never starts a browser/network.
    import backend.app.rendering as module
    sleeper = tmp_path / "nonreading_worker.py"
    sleeper.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(module, "WORKER", sleeper)
    async def run():
        fetcher, _, value = await fixture("<html>" + "x" * 600000 + "</html>")
        renderer = SafeRenderer(replace(BASE, node_executable=sys.executable, timeout_seconds=1))
        started = time.monotonic()
        result = await renderer.render(fetcher, value)
        assert result.status == "render_timeout"
        assert result.cleanup["forced_tree_cleanup_requested"] is True
        assert result.cleanup["node_exited"] is True
        assert time.monotonic() - started < 10
    asyncio.run(run())


def test_real_edge_cancel_after_ready_propagates_and_waits_owned_node_exit():
    async def run():
        fetcher, _, value = await fixture("<title>Cancellation fixture</title>")
        renderer = SafeRenderer(replace(BASE, settle_ms=2000))
        task = asyncio.create_task(renderer.render(fetcher, value))
        async with asyncio.timeout(20):
            while not (renderer.last_result and renderer.last_result.cleanup.get("worker_ready")):
                if task.done(): pytest.fail(str(task.result().as_dict()))
                await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert renderer.last_result.status == "cancelled"
        assert renderer.last_result.cleanup["node_exited"] is True
        assert renderer.last_result.cleanup["all_descendant_processes_exited"] == "unknown"
    asyncio.run(run())
