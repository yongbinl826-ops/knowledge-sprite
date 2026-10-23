"""Independent synthetic mobile API checks. Never write task capabilities to evidence.

The application/server fixture supplies deterministic upstream mocks. This module
only accepts a caller-owned loopback/ASGI client; it never contacts a supplier.
"""
from __future__ import annotations

import base64
import asyncio
import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import secrets
import socket
import time
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


class LoopbackOnly:
    """Deny real non-loopback DNS/TCP/UDP before transport; restore on exit."""
    def __init__(self):
        self.blocked, self.patches = 0, []

    @staticmethod
    def allowed(host):
        if host in {None, "localhost", b"localhost"}: return True
        try:
            return ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host).is_loopback
        except (ValueError, TypeError): return False

    def __enter__(self):
        dns, connect, connect_ex, sendto = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto
        def check(host):
            if not self.allowed(host):
                self.blocked += 1
                raise PermissionError("mobile fixture forbids external transport")
        def safe_dns(host, *args, **kwargs):
            check(host)
            return dns(host, *args, **kwargs)
        def safe_connect(sock, address):
            if isinstance(address, tuple): check(address[0])
            return connect(sock, address)
        def safe_connect_ex(sock, address):
            if isinstance(address, tuple): check(address[0])
            return connect_ex(sock, address)
        def safe_sendto(sock, data, *args):
            if isinstance(args[-1], tuple): check(args[-1][0])
            return sendto(sock, data, *args)
        for target, value in [("socket.getaddrinfo", safe_dns), ("socket.socket.connect", safe_connect),
                              ("socket.socket.connect_ex", safe_connect_ex), ("socket.socket.sendto", safe_sendto)]:
            replacement = patch(target, value)
            replacement.start()
            self.patches.append(replacement)
        return self

    def __exit__(self, *_):
        for replacement in reversed(self.patches): replacement.stop()


def capability():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


@dataclass
class Ticket:
    task_id: str
    cap: str = field(repr=False)

    @classmethod
    def fresh(cls):
        return cls(str(uuid4()), capability())

    @property
    def path(self):
        return "/api/mobile/tasks/" + self.task_id

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.cap}


class Checks:
    def __init__(self):
        self.rows = []
        self.requests = []

    def check(self, name, condition, **public_details):
        self.rows.append({"name": name, "pass": bool(condition), **public_details})

    async def request(self, client, method, path, label, **kwargs):
        assert path.startswith("/api/") or path.startswith("/health")
        started = time.perf_counter()
        response = await client.request(method, path, **kwargs)
        # Deliberately exclude URL, headers, payload and raw response from logs.
        self.requests.append({"label": label, "method": method,
            "status": response.status_code,
            "milliseconds": round((time.perf_counter() - started) * 1000, 3),
            "retry_after": response.headers.get("Retry-After")})
        return response

    def receipt(self):
        return {"checks": self.rows, "requests": self.requests,
                "passed": all(row["pass"] for row in self.rows),
                "real_supplier_http": 0, "real_model_calls": 0,
                "capability_values_in_receipt": False}


def error_shape(response):
    value = response.json()
    return {key: value[key] for key in value if key != "request_id"}


async def capability_protocol(client, checks):
    """Run while the fixture holds source requests, so both tasks remain live."""
    first, second, unknown = Ticket.fresh(), Ticket.fresh(), Ticket.fresh()
    body = {"kind": "direct_search", "request": {
        "knowledge_points": ["Python list indexing"],
        "project_context": "SYNTHETIC_PRIVATE_MOBILE_A",
        "preferred_platforms": ["bilibili"]}}
    a = await checks.request(client, "POST", first.path, "create_A", headers=first.headers, json=body)
    b = await checks.request(client, "POST", second.path, "create_B_same_payload", headers=second.headers, json=body)
    checks.check("two_task_creation", a.status_code == b.status_code == 202)
    repeated = await checks.request(client, "POST", first.path, "idempotent_A", headers=first.headers, json=body)
    checks.check("same_cap_payload_idempotent", repeated.status_code in {200, 202}
                 and repeated.json().get("task_id") == first.task_id)
    changed = json.loads(json.dumps(body))
    changed["request"]["project_context"] = "SYNTHETIC_PRIVATE_CHANGED"
    conflict = await checks.request(client, "POST", first.path, "changed_payload", headers=first.headers, json=changed)
    checks.check("same_task_changed_payload_409", conflict.status_code == 409)

    missing = await checks.request(client, "GET", unknown.path, "unknown_cap", headers=unknown.headers)
    failures = []
    for method, suffix in [("GET", ""), ("POST", "/cancel")]:
        wrong = await checks.request(client, method, first.path + suffix, "cross_cap_" + method,
            headers=second.headers)
        failures.append(wrong)
    wrong_post = await checks.request(client, "POST", first.path, "wrong_cap_POST", headers=second.headers, json=body)
    failures.append(wrong_post)
    for label, headers in [
        ("missing_header", {}),
        ("malformed_scheme", {"Authorization": "Basic " + first.cap}),
        ("malformed_size", {"Authorization": "Bearer short"}),
        ("noncanonical_encoding", {"Authorization": "Bearer " + "A" * 42 + "B"}),
        ("duplicate_header", [("Authorization", "Bearer " + first.cap), ("Authorization", "Bearer " + second.cap)]),
    ]:
        failures.append(await checks.request(client, "GET", first.path, label, headers=headers))
    failures.append(await checks.request(client, "GET", first.path + "?token=" + first.cap, "query_token_no_auth"))
    checks.check("cap_errors_uniform_404", missing.status_code == 404 and all(
        response.status_code == 404 and error_shape(response) == error_shape(missing)
        for response in failures))

    visible = await checks.request(client, "GET", first.path, "authorized_read", headers=first.headers)
    checks.check("authorized_read_and_no_token_reflection", visible.status_code == 200
                 and visible.json().get("task_id") == first.task_id
                 and all(ticket.cap not in visible.text for ticket in [first, second]))
    expiry = visible.json().get("expires_at")
    again = await checks.request(client, "GET", first.path, "non_sliding_read", headers=first.headers)
    checks.check("expiry_not_sliding_on_read", bool(expiry) and again.json().get("expires_at") == expiry)
    cancelled = await checks.request(client, "POST", first.path + "/cancel", "cancel_A", headers=first.headers)
    remaining = await checks.request(client, "GET", second.path, "B_after_A_cancel", headers=second.headers)
    checks.check("A_cancel_does_not_cancel_B", cancelled.status_code == 200
                 and remaining.status_code == 200 and remaining.json().get("status") != "cancelled")
    return first, second


async def ingress_and_legacy(client, checks, max_body_bytes):
    for method, path in [
        ("GET", "/api/projects"), ("POST", "/api/projects"),
        ("GET", "/api/projects/known"), ("POST", "/api/projects/known/analyze"),
        ("GET", "/api/projects/known/results"), ("POST", "/api/projects/known/cancel"),
        ("POST", "/api/search-jobs"), ("GET", "/api/search-jobs/known"),
        ("GET", "/api/search-jobs/known/results"), ("POST", "/api/search-jobs/known/cancel"),
        ("GET", "/api/mobile/tasks"),
    ]:
        response = await checks.request(client, method, path, "disabled_route_" + method)
        checks.check("disabled_" + method + "_" + path, response.status_code == 404)
    malformed = [
        {"kind": "direct_search", "request": {"knowledge_points": ["Python list"], "url": "http://127.0.0.1/private"}},
        {"kind": "direct_search", "request": {"knowledge_points": ["Python list"]}, "project_id": "cross-device"},
        {"kind": "analysis", "input": {"name": "synthetic", "requirements": "test", "progress": {"__proto__": True}}},
        {"kind": ["analysis"], "input": {"name": "synthetic", "requirements": "test"}},
    ]
    for index, body in enumerate(malformed):
        ticket = Ticket.fresh()
        response = await checks.request(client, "POST", ticket.path, "strict_body_" + str(index),
                                        headers=ticket.headers, json=body)
        checks.check("strict_envelope_" + str(index), response.status_code == 422)
        checks.check("invalid_not_created_" + str(index),
            (await checks.request(client, "GET", ticket.path, "invalid_task_read", headers=ticket.headers)).status_code == 404)
    ticket = Ticket.fresh()
    response = await checks.request(client, "POST", ticket.path, "large_body",
        headers={**ticket.headers, "Content-Type": "application/json"}, content=b" " * (max_body_bytes + 1))
    checks.check("large_body_413", response.status_code == 413)
    for method in ["POST", "PUT", "DELETE"]:
        response = await checks.request(client, method, "/api/mobile/courses", "public_read_only_" + method, json={"title": "SYNTHETIC_PRIVATE"})
        checks.check("no_anonymous_public_write_" + method, response.status_code in {404, 405})


def public_rows_do_not_contain_private_markers(connection, private_markers):
    """A synthetic-output SQLite check; never call this on a user database."""
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        # Table names originate from sqlite_master, never a client identifier.
        escaped = table.replace('"', '""')
        rows = connection.execute('SELECT * FROM "' + escaped + '"').fetchall()
        encoded = json.dumps([list(row) for row in rows], ensure_ascii=False, default=str)
        if any(marker in encoded for marker in private_markers):
            return False
    return True


def hash_public_source(source_root):
    return {path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (source_root / "backend/app").rglob("*.py")}


def synthetic_analysis():
    return {"scope": "Synthetic local data lookup", "technical_plan": "Python",
        "assumptions": ["Synthetic input; no real student information"],
        "functions": [{"id": "F1", "name": "Data lookup", "original_requirement": "Read and query synthetic data",
                       "acceptance_criteria": "Display a lookup result"}],
        "knowledge_points": [{"id": "K" + str(index + 1), "name": title,
            "technology": "Python", "description": "Reusable professional concept", "function_ids": ["F1"],
            "why_needed": "Read synthetic collections", "learning_goal": "Understand this concept",
            "necessity": "required", "prerequisite_ids": [], "learning_order": index + 1,
            "selection": "learn"} for index, title in enumerate(["列表", "字典"])]}


def fixture_page(url, title="Synthetic public Python list course"):
    bvid = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    state = {"videoData": {"bvid": bvid, "title": title,
        "desc": "Synthetic source metadata for a local UI fixture. No real course or playback is claimed.",
        "owner": {"name": "Synthetic public author"},
        "pages": [{"page": 1, "part": title, "duration": 120, "cid": 123}]}}
    return "<html><body><script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script></body></html>"


class FixtureWorld:
    def __init__(self, httpx, controls=None):
        self.httpx = httpx
        self.controls = dict(controls or {})
        self.analysis_gate = asyncio.Event()
        self.search_gate = asyncio.Event()
        self.analysis_entered = asyncio.Event()
        self.search_entered = asyncio.Event()
        if not self.controls.get("hold_analysis"): self.analysis_gate.set()
        if not self.controls.get("hold_search"): self.search_gate.set()
        self.calls = []
        self.logical_model_calls = 0
        self.metadata_calls = 0
        self.active = {"analysis": 0, "search": 0}
        self.maximum = {"analysis": 0, "search": 0}

    async def respond(self, request):
        assert request.url.host in {"mock-llm.invalid", "mock-search.invalid"}, "undeclared mock destination"
        kind = "analysis" if request.url.host == "mock-llm.invalid" else "search"
        self.calls.append(kind)
        self.active[kind] += 1
        self.maximum[kind] = max(self.maximum[kind], self.active[kind])
        try:
            gate, entered = (self.analysis_gate, self.analysis_entered) if kind == "analysis" else (self.search_gate, self.search_entered)
            entered.set()
            await gate.wait()
            await asyncio.sleep(.02)
            if self.controls.pop("fail_next_" + kind, False):
                return self.httpx.Response(503, json={"error": "synthetic failure"})
            if kind == "analysis":
                return self.httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                    "message": {"content": json.dumps(synthetic_analysis())}}]})
            rows = [] if self.controls.get("empty_search") else [{
                "title": "Python list indexing and dictionary lookup", "url": self.controls.get("search_url", "https://www.bilibili.com/video/BV1AAAAAAAAA/"),
                "content": "Synthetic discovery text; not a real teaching observation"}]
            return self.httpx.Response(200, json={"results": rows, "unresponsive_engines": []})
        finally:
            self.active[kind] -= 1

    async def expand(self, *_):
        self.logical_model_calls += 1
        return []

    async def rerank(self, *_):
        self.logical_model_calls += 1
        return []


def create_fixture_app(source_root, output_dir, controls=None, settings_changes=None):
    """Real production app with synthetic Settings/DB and mocked providers.

    Return the app; fixture controls/counters are on app.state.fixture_world.
    Caller must use a non-loopback transport guard and disable proxy headers.
    No HTTP test backdoor is installed. Each source runtime needs a fresh process.
    """
    source_root, output_dir = Path(source_root).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(source_root))
    from backend.app.config import Settings
    assert Path(sys.modules[Settings.__module__].__file__).resolve().is_relative_to(source_root), "cached wrong source runtime"
    assert "app_mode" in Settings.__dataclass_fields__, "mobile implementation not installed"
    with patch.object(Settings, "from_env", classmethod(lambda cls: Settings())):
        from backend.app.main import create_app
    import httpx
    from backend.app.project_analysis import ProjectAnalyzer
    from backend.app.providers import SearXNGProvider
    from backend.app.extractor import MetadataExtractor
    from backend.app.models import now

    config = dict(app_mode="mobile", database_path=str(output_dir / "legacy-trap.sqlite3"),
        mobile_public_database_path=str(output_dir / "public.sqlite3"),
        mobile_per_ip_tasks_per_minute=60, mobile_per_ip_requests_per_minute=600,
        mobile_cleanup_interval_seconds=1,
        searxng_url="https://mock-search.invalid", llm_provider="openai_compatible",
        llm_base_url="https://mock-llm.invalid/v1", llm_api_key="synthetic-not-a-secret", llm_model="synthetic",
        parallel_platform_search=True, teaching_match_enabled=True,
        bilibili_search_rounds=1, mooc_search_rounds=1, max_search_requests=4,
        max_detail_pages=2, max_knowledge_points=2, max_pending_jobs=8,
        deadline_seconds=4, project_deadline_seconds=20, global_concurrency=2,
        search_timeout_seconds=2, search_max_retries=0, search_min_interval_seconds=0,
        api_write_limit_per_minute=200, submission_limit_per_minute=100,
        project_analysis_timeout_seconds=2, project_analysis_total_timeout_seconds=2,
        shared_course_library_enabled=False, mooc_refresh_enabled=False,
        official_sitemap_fallback=False, public_catalog_fallback=False,
        js_render_enabled=False, fetch_enabled=False)
    config.update(settings_changes or {})
    settings = Settings(**config).validate()
    trap = output_dir / "legacy-trap.sqlite3"
    trap.write_bytes(b"SYNTHETIC_LEGACY_DATABASE_MUST_NOT_OPEN")
    world = FixtureWorld(httpx, controls)
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(world.respond), trust_env=False)

    class FixtureFetcher:
        async def enrich(self, candidate, **_):
            world.metadata_calls += 1
            url = candidate.url if hasattr(candidate, "url") else candidate["url"]
            return MetadataExtractor().extract(fixture_page(url, "Python list indexing and dictionary lookup"), url, now())

    app = create_app(settings, provider=SearXNGProvider(settings, upstream), fetcher=FixtureFetcher(),
                     llm=world, analyzer=ProjectAnalyzer(settings, upstream))
    original = app.router.lifespan_context
    @asynccontextmanager
    async def lifecycle(target):
        try:
            async with original(target):
                yield
        finally:
            await upstream.aclose()
    app.router.lifespan_context = lifecycle
    app.state.fixture_world = world
    app.state.fixture_settings = settings
    app.state.fixture_legacy_trap = trap
    return app


def seed_public_fixture(app, public_store=None):
    """After startup, seed only extractor-validated synthetic public metadata."""
    from backend.app.extractor import MetadataExtractor
    from backend.app.models import now
    if public_store is None:
        manager = getattr(app.state, "mobile_tasks", None) or getattr(app.state, "mobile", None)
        public_store = getattr(app.state, "mobile_public", None) or getattr(manager, "public", None)
    assert public_store is not None, "supply startup's MobilePublicStore explicitly"
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    result = MetadataExtractor().extract(fixture_page(url), url, now())
    evidence = result.pop("evidence")
    resource = {**result, "url": url, "canonical_url": url, "resolved_url": url, "platform": "bilibili"}
    assert public_store.observe(resource, evidence), "synthetic own fixture rejected"
    return resource, evidence


@asynccontextmanager
async def serve_fixture(app):
    import httpx
    import uvicorn
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    assert port not in {8001, 8002}
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        proxy_headers=False, log_config=None, log_level="critical", access_log=False,
        lifespan="on", timeout_graceful_shutdown=1))
    pending = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if pending.done(): raise RuntimeError("fixture startup failed")
            if time.monotonic() > deadline: raise TimeoutError("fixture startup deadline")
            await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5,
            trust_env=False, limits=httpx.Limits(max_connections=20)) as client:
            yield client
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(pending, 5)
        except TimeoutError:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        sock.close()


async def run_local_validation(source_root, output_dir):
    source_root, output_dir = Path(source_root).resolve(), Path(output_dir).resolve()
    before = hash_public_source(source_root)
    checks = Checks()
    started = time.perf_counter()
    cap_values = []
    with LoopbackOnly() as guard:
        app = create_fixture_app(source_root, output_dir, {"hold_search": True})
        async with serve_fixture(app) as client:
            world = app.state.fixture_world
            first, second = await capability_protocol(client, checks)
            cap_values.extend([first.cap, second.cap])
            await ingress_and_legacy(client, checks, app.state.fixture_settings.max_request_body_bytes)
            seed_public_fixture(app)
            library = await checks.request(client, "GET", "/api/mobile/courses?query=Python&limit=10&offset=0", "public_browse")
            checks.check("public_browse_whitelist", library.status_code == 200 and library.json()["total"] == 1
                and set(library.json()["items"][0]) <= {"course_id", "url", "title", "platform", "thumbnail_url", "author", "resource_type", "observed_at", "expires_at", "access_notice"})
            world.search_gate.set()

            async def terminal(ticket):
                deadline = time.monotonic() + 8
                while True:
                    response = await checks.request(client, "GET", ticket.path, "task_poll", headers=ticket.headers)
                    if response.status_code != 200: raise AssertionError("owned task lost")
                    value = response.json()
                    if value["status"] not in {"running", "queued"}: return value
                    if time.monotonic() > deadline: raise TimeoutError("mobile terminal deadline")
                    await asyncio.sleep(.04)
            await terminal(second)
            inputs = [{"name": "Synthetic device project " + str(i),
                "requirements": "Read synthetic Python collections", "project_context": "PRIVATE_DEVICE_CONTEXT",
                "preferred_platforms": ["bilibili"]} for i in range(3)]
            analyses = [Ticket.fresh() for _ in inputs]
            cap_values.extend(t.cap for t in analyses)
            submitted = await asyncio.gather(*(checks.request(client, "POST", ticket.path, "analysis_submit",
                headers=ticket.headers, json={"kind": "analysis", "input": value}) for ticket, value in zip(analyses, inputs)))
            checks.check("three_analysis_submissions", all(r.status_code == 202 for r in submitted))
            results = await asyncio.gather(*(terminal(ticket) for ticket in analyses))
            checks.check("analysis_concurrency_bounded_two", world.maximum["analysis"] == 2,
                         observed=world.maximum["analysis"])
            searches = [Ticket.fresh() for _ in inputs]
            cap_values.extend(t.cap for t in searches)
            submitted = await asyncio.gather(*(checks.request(client, "POST", ticket.path, "search_submit",
                headers=ticket.headers, json={"kind": "search", "input": value,
                    "analysis": result["result"]["version"]["analysis"],
                    "reviewed_topic_technologies": {p["name"]: p["technology"] for p in result["result"]["version"]["analysis"]["knowledge_points"] if p.get("technology")}})
                for ticket, value, result in zip(searches, inputs, results)))
            checks.check("three_search_submissions", all(r.status_code == 202 for r in submitted))
            completed = await asyncio.gather(*(terminal(ticket) for ticket in searches))
            checks.check("project_searches_terminal", all(r["status"] in {"completed", "partial"} for r in completed))
            health = await asyncio.gather(*(checks.request(client, "GET", "/health", "concurrent_health") for _ in range(8)))
            checks.check("health_under_mobile_requests", all(r.status_code == 200 for r in health))
            checks.check("synthetic_private_data_not_persistent", public_rows_do_not_contain_private_markers(
                app.state.mobile.public.connection, cap_values + ["PRIVATE_DEVICE_CONTEXT", "SYNTHETIC_PRIVATE_MOBILE_A"]))
            checks.check("legacy_database_not_opened", app.state.fixture_legacy_trap.read_bytes() == b"SYNTHETIC_LEGACY_DATABASE_MUST_NOT_OPEN")
            model_observations = {"mock_http_analysis": world.calls.count("analysis"),
                "mock_http_search": world.calls.count("search"), "mock_logical_expand_and_rerank": world.logical_model_calls}
        checks.check("no_external_transport_attempt", guard.blocked == 0, blocked=guard.blocked)
    after = hash_public_source(source_root)
    checks.check("public_source_unchanged", before == after)
    elapsed = time.perf_counter() - started
    ordered = sorted(row["milliseconds"] for row in checks.requests)
    report = {**checks.receipt(), "source_before": before, "source_after": after,
        "source_root": str(source_root), "observed_seconds": elapsed,
        "observed_http_requests_per_second": len(checks.requests) / elapsed,
        "http_requests": len(checks.requests),
        "p50_ms": ordered[max(0, (len(ordered) + 1) // 2 - 1)],
        "p95_ms": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)],
        "mock_observations": model_observations,
        "limits": ["finite single-process synthetic local load; not supplier or multi-worker capacity",
                   "public fixture proves extractor/DTO plumbing, not a real course, playback or teaching coverage"]}
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    assert all(cap not in serialized for cap in cap_values), "capability leaked to receipt"
    (output_dir / "report.json").write_text(serialized, encoding="utf8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().drive.upper() != "C:": parser.error("use a fresh C-only synthetic directory")
    report = asyncio.run(run_local_validation(args.source_root, args.output))
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "http_requests": report["http_requests"], "supplier_http": 0,
                      "report": str(args.output / "report.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
