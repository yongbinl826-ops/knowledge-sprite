"""Audit of the documented shared local instance, not imaginary user accounts.

All settings, database records, headers and client labels are synthetic. These
tests intentionally prove shared-instance behavior, not a tenant-isolation claim.
No environment/configuration file is loaded and no external transport is used.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from backend.app import config
from backend.app.config import Settings
from backend.app.models import now
from backend.app.project_models import AnalysisDocument


AUDIT_RECORDS = []
PROJECT_MARKER = "synthetic-private-project-A"
EVIDENCE_MARKER = "synthetic-private-evidence-A"


class ForbiddenAuditCall(BaseException):
    pass


class MockSearch:
    def __init__(self): self.calls = 0
    async def search(self, *_args, **_kwargs):
        self.calls += 1
        return []


class NoFetch:
    async def enrich(self, *_args, **_kwargs):
        raise ForbiddenAuditCall("No external fetch in access audit")


class NoLLM:
    available = False
    async def generate_json(self, *_args, **_kwargs):
        raise ForbiddenAuditCall("No model in access audit")


def document():
    return AnalysisDocument.model_validate({
        "scope": "Synthetic keyboard demonstration", "technical_plan": "pygame local window",
        "assumptions": [], "functions": [{"id": "f1", "name": "Keyboard input",
            "original_requirement": "Read keyboard input", "acceptance_criteria": "Observe a key event"}],
        "knowledge_points": [{"id": "k1", "name": "pygame 事件处理", "description": "Synthetic topic",
            "function_ids": ["f1"], "why_needed": "Handle input", "learning_goal": "Understand input events",
            "necessity": "required", "prerequisite_ids": [], "learning_order": 1, "selection": "learn"}]})


class MockAnalyzer:
    available = True
    def __init__(self): self.calls = 0
    async def analyze(self, _request):
        self.calls += 1
        return document()


@pytest.fixture
def audit(tmp_path, monkeypatch):
    # Windows asyncio may initialise its local self-wakeup socket here. All
    # outbound/socket entrypoints are denied after the loop exists, before app use.
    loop = asyncio.new_event_loop()
    def denied(*_args, **_kwargs):
        raise ForbiddenAuditCall("External transport or real configuration access denied")
    for method in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, method, denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(config, "load_dotenv", denied)
    # main.py has a module-level create_app(). Intercept its settings factory
    # before import; its real from_env implementation is never executed.
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: cls(database_path=":memory:", llm_provider="none")))
    connect = sqlite3.connect
    db_connections = []
    def synthetic_connect(path, *args, **kwargs):
        if path != ":memory:":
            resolved = Path(path).resolve()
            if not resolved.is_relative_to(tmp_path.resolve()):
                raise ForbiddenAuditCall("Only this test's fresh synthetic SQLite path is allowed")
        db_connections.append(str(path))
        return connect(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", synthetic_connect)
    main = importlib.import_module("backend.app.main")
    counter = 0
    def application(**changes):
        nonlocal counter
        counter += 1
        settings = Settings(database_path=str(tmp_path / f"synthetic-{counter}.sqlite3"),
            llm_provider="none", search_provider="tavily", max_search_requests=1, max_detail_pages=0,
            deadline_seconds=5, search_min_interval_seconds=0, official_sitemap_fallback=False,
            public_catalog_fallback=False, shared_course_library_enabled=False,
            mooc_refresh_enabled=False, api_write_limit_per_minute=120, **changes)
        return main.create_app(settings, provider=MockSearch(), fetcher=NoFetch(), llm=NoLLM(), analyzer=MockAnalyzer())
    value = SimpleNamespace(run=loop.run_until_complete, app=application, connections=db_connections,
                            record=lambda name, result: AUDIT_RECORDS.append({"test": name, **result}))
    try:
        yield value
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@asynccontextmanager
async def client(app, peer="127.0.0.2", label="A"):
    # These labels are unverified request metadata, not server identities.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 12000)),
        base_url="http://127.0.0.1:8000", headers={"Cookie": f"audit_label={label}", "X-User": label}) as session:
        yield session


async def analyzed(app, session):
    created = await session.post("/api/projects", json={"name": "Synthetic A project",
        "requirements": PROJECT_MARKER, "preferred_platforms": ["bilibili"]})
    assert created.status_code == 201
    pid = created.json()["project_id"]
    response = await session.post(f"/api/projects/{pid}/analyze", json={"expected_version": 0})
    assert response.status_code == 202
    await asyncio.gather(*list(app.state.projects.analysis_tasks.values()))
    assert app.state.projects.view(pid)["version"]["status"] == "analyzed"
    return pid


def seed_job(app):
    # Explicit synthetic persistence precondition; no provider work is queued.
    store = app.state.store
    jid, point_id, rid = "audit-job-A", "audit-point-A", "audit-resource-A"
    text = "pygame 键盘控制角色左右移动"
    job = {"job_id": jid, "status": "queued", "phase": "queued", "created_at": now(), "updated_at": now(),
        "request": {"knowledge_points": [text], "project_context": PROJECT_MARKER,
            "preferred_platforms": ["bilibili"], "student_level": "beginner", "language": "zh"},
        "knowledge_points": [{"knowledge_point_id": point_id, "text": text}],
        "warnings": [], "errors": [], "progress": {}, "budgets": {"max_search_requests": 1}}
    store.create_job(job)
    url = "https://www.bilibili.com/video/BV1ab411c7De"
    title = "pygame键盘事件——控制小船左右移动"
    resource = {"resource_id": rid, "platform": "bilibili", "url": url, "canonical_url": url,
        "title": title, "resource_type": "video", "video_evidence_status": "search_discovered",
        "metadata_evidence_level": "search", "fetch_status": "search_only_policy",
        "field_provenance": {"title": {"source": "search", "evidence_id": "audit-evidence-A"},
            "resource_type": {"source": "url_pattern", "evidence_id": "audit-evidence-A"},
            "video_evidence_status": {"source": "url_pattern", "evidence_id": "audit-evidence-A"}}}
    store.save_resource(jid, resource)
    store.add_evidence(jid, rid, point_id, {"evidence_id": "audit-evidence-A", "kind": "search",
        "source": "synthetic-audit-not-live-proof", "url": url, "title": title,
        "snippet": EVIDENCE_MARKER, "knowledge_point_id": point_id})
    return jid


def test_two_unidentified_local_clients_share_project_read_edit_confirm_cancel_and_SSE(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app, label="A") as a, client(app, "127.0.0.3", "B") as b:
                pid = await analyzed(app, a)
                listed = (await b.get("/api/projects")).json()["projects"]
                assert pid in {p["project_id"] for p in listed}
                route = f"/api/projects/{pid}"
                view = await b.get(route)
                assert view.status_code == 200 and PROJECT_MARKER in view.text
                results = await b.get(route + "/results")
                stream = await b.get(route + "/events")
                assert results.status_code == stream.status_code == 200
                assert PROJECT_MARKER in stream.text and "event: complete" in stream.text
                assert stream.headers["cache-control"] == "no-store"
                plan = document().model_dump(); plan["knowledge_points"][0]["name"] = "pygame 键盘输入"
                edit = await b.post(route + "/edit", json={"expected_version": 1, "analysis": plan})
                assert edit.status_code == 200 and edit.json()["current_version"] == 2
                assert (await a.get(route)).json()["version"]["analysis"] == plan
                assert (await b.post(route + "/confirm", json={"version": 2})).status_code == 200
                cancelled = await a.post(route + "/cancel", json={"version": 2})
                assert cancelled.status_code == 200 and cancelled.json()["version"]["status"] == "cancelled"
                audit.record("shared_project", {"list": 200, "read": 200, "results": 200, "SSE": 200,
                    "edit_by_other_client": 200, "confirm_by_other_client": 200, "cancel": 200,
                    "mock_analyzer_calls": app.state.projects.analyzer.calls, "real_model_calls": 0})
    audit.run(scenario())


def test_job_request_evidence_results_cancel_and_SSE_are_shared_by_job_ID(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            jid = seed_job(app)
            async with client(app, "127.0.0.3", "B") as b:
                route = f"/api/search-jobs/{jid}"
                assert PROJECT_MARKER in (await b.get(route)).text
                cancel = await b.post(route + "/cancel")
                assert cancel.status_code == 200 and cancel.json()["cancelled"] is True
                result, stream = await b.get(route + "/results"), await b.get(route + "/events")
                assert result.status_code == stream.status_code == 200
                assert EVIDENCE_MARKER in result.text and EVIDENCE_MARKER in stream.text
                assert PROJECT_MARKER in stream.text and "event: complete" in stream.text
                assert (await b.get("/api/search-jobs/missing-audit-id")).status_code == 404
                audit.record("shared_job_and_evidence", {"read": 200, "cancel_by_other_client": 200,
                    "results_contains_synthetic_evidence": True, "SSE_contains_synthetic_request_and_evidence": True})
    audit.run(scenario())


@pytest.mark.parametrize("proxy_headers", [
    {"X-Forwarded-For": "127.0.0.1"}, {"X-Real-IP": "127.0.0.1"},
    {"Forwarded": "for=127.0.0.1;proto=https;host=localhost"},
    {"X-Forwarded-User": "A", "X-Auth-Request-User": "A", "Authorization": "Bearer synthetic-unverified"},
])
def test_remote_peer_cannot_forge_loopback_or_identity_in_app_scope(audit, proxy_headers):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app, "203.0.113.8", "unverified") as remote:
                for path in ("/api/projects", "/health", "/api/capabilities", "/api/projects/unknown/events"):
                    response = await remote.get(path, headers=proxy_headers)
                    assert response.status_code == 403 and response.json()["code"] == "local_access_only"
                audit.record("remote_forged_headers", {"header_names": sorted(proxy_headers), "status": 403,
                    "note": "ASGI peer guard only; upstream proxy scope rewriting is a separate deployment responsibility"})
    audit.run(scenario())


def test_unverified_identity_headers_do_not_create_authorization_for_local_clients(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app) as a, client(app, "127.0.0.3", "B") as b:
                pid = await analyzed(app, a); route = f"/api/projects/{pid}"
                ordinary = await b.get(route)
                forged = await b.get(route, headers={"X-Forwarded-User": "administrator",
                    "X-Auth-Request-User": "different", "Authorization": "Bearer synthetic-unverified"})
                assert ordinary.status_code == forged.status_code == 200
                assert ordinary.json() == forged.json()
                assert (await b.get("/api/capabilities")).json()["deployment"]["authentication"] is False
    audit.run(scenario())


@pytest.mark.parametrize("headers,code", [
    ({"Origin": "https://audit-cross-site.invalid"}, "untrusted_origin"),
    ({"Origin": "null"}, "untrusted_origin"),
    ({"Sec-Fetch-Site": "cross-site"}, "cross_site_request"),
    ({"Sec-Fetch-Site": "same-site"}, "cross_site_request"),
])
def test_cross_site_project_read_write_and_SSE_are_rejected(audit, headers, code):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app) as session:
                pid = await analyzed(app, session)
                for method, path, body in [("GET", "/api/projects", None),
                    ("GET", f"/api/projects/{pid}/events", None),
                    ("POST", "/api/projects", {"name": "Blocked", "requirements": "Synthetic"})]:
                    response = await session.request(method, path, json=body, headers=headers)
                    assert response.status_code == 403 and response.json()["code"] == code
                    assert PROJECT_MARKER not in response.text
                assert len(app.state.projects.db.list()) == 1
                audit.record("cross_site", {"header_names": sorted(headers), "code": code, "status": 403})
    audit.run(scenario())


def test_host_DNS_rebinding_guard_and_known_development_origin_are_not_login(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app) as session:
                response = await session.get("/api/projects", headers={"Host": "audit-rebind.invalid"})
                assert response.status_code == 400 and response.json()["code"] == "untrusted_host"
                response = await session.get("/api/projects", headers={"Origin": "http://127.0.0.1:5173"})
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
                assert (await session.get("/api/projects")).status_code == 200  # no browser credentials required
                assert "set-cookie" not in response.headers
    audit.run(scenario())


def test_health_openapi_and_global_SQL_schema_do_not_claim_user_isolation(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app) as session:
                seed_job(app)
                health = await session.get("/health")
                assert health.status_code == 200 and health.json()["job_counts"].get("queued") == 1
                assert PROJECT_MARKER not in health.text and EVIDENCE_MARKER not in health.text
                live = await session.get("/health/live", headers={"Sec-Fetch-Site": "cross-site"})
                assert live.status_code == 200 and live.json() == {"status": "ok"}
                ready = await session.get("/health/ready")
                assert ready.status_code in {200, 503}
                assert ready.json()["upstream_check"] == "configuration_and_last_observation_only"
                schema = (await session.get("/openapi.json")).json()
                assert not schema.get("components", {}).get("securitySchemes")
                columns = {table: [row[1] for row in app.state.store.connection.execute(f"PRAGMA table_info({table})")]
                    for table in ("projects", "project_versions", "jobs", "resources", "evidence", "idempotency_keys", "job_consumers")}
                assert not any(set(names) & {"user_id", "owner_id", "tenant_id"} for names in columns.values())
                audit.record("shared_schema_and_health", {"schema_columns": columns,
                    "health_exposes_aggregate_counts": True, "health_contains_student_or_evidence_payload": False,
                    "health_ready_is_live_upstream_probe": False, "openapi_has_security_schemes": False})
    audit.run(scenario())


def test_opted_out_local_only_accepts_remote_clients_without_new_identity_boundary(audit):
    async def scenario():
        app = audit.app(local_only=False)
        async with app.router.lifespan_context(app):
            async with client(app, "203.0.113.8", "A") as remote_a, client(app, "198.51.100.8", "B") as remote_b:
                made = await remote_a.post("/api/projects", json={"name": "Synthetic remote A", "requirements": PROJECT_MARKER})
                assert made.status_code == 201
                pid = made.json()["project_id"]
                assert PROJECT_MARKER in (await remote_b.get(f"/api/projects/{pid}")).text
                cap = (await remote_b.get("/api/capabilities")).json()["deployment"]
                assert cap["local_only"] is False and cap["authentication"] is False
                audit.record("explicit_nonlocal_configuration", {"created": 201, "other_remote_read": 200,
                    "note": "Synthetic local_only=False settings; not a claim about actual D configuration/bind/proxy"})
    audit.run(scenario())


def test_idempotency_key_namespace_is_instance_global_not_client_scoped(audit):
    async def scenario():
        app = audit.app()
        async with app.router.lifespan_context(app):
            async with client(app, label="A") as a, client(app, "127.0.0.3", "B") as b:
                body = {"knowledge_points": ["pygame 键盘输入"], "preferred_platforms": ["bilibili"]}
                headers = {"Idempotency-Key": "synthetic-audit-shared-key"}
                first, second = await a.post("/api/search-jobs", json=body, headers=headers), await b.post("/api/search-jobs", json=body, headers=headers)
                assert first.status_code == second.status_code == 202
                assert first.json()["job_id"] == second.json()["job_id"]
                audit.record("instance_global_idempotency", {"same_job_for_two_client_labels": True,
                    "real_network_calls": 0, "identity_partition": False})
    audit.run(scenario())
