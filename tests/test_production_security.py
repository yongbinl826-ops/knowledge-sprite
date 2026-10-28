"""Offline HTTP production-boundary tests; no external service success implied."""
import asyncio
import gzip
import json
import logging
import time
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.security import RequestSecurityMiddleware
from backend.app.url_utils import UnsafeURL, normalize_url


class EmptySearch:
    async def search(self, *_args, **_kwargs):
        return []


class NoFetch:
    async def enrich(self, _candidate):
        raise AssertionError("Security tests must not fetch external pages")


def application(tmp_path, **changes):
    settings = Settings(database_path=str(tmp_path / "security.sqlite3"),
                        max_search_requests=1, max_detail_pages=0, **changes)
    return create_app(settings, provider=EmptySearch(), fetcher=NoFetch())


@pytest.mark.asyncio
async def test_local_origin_boundary_and_security_headers(tmp_path):
    app = application(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            response = await client.get("/api/projects")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert len(response.headers["x-request-id"]) == 32
            for origin in ("http://127.0.0.1:8000", "http://127.0.0.1:5173"):
                assert (await client.post("/api/projects", headers={"Origin": origin}, json={
                    "name": "本地项目", "requirements": "读取 Excel 并绘制成绩图表"})).status_code == 201
            for origin in ("https://evil.example", "null", "http://127.0.0.1:8000.evil.example"):
                response = await client.post("/api/projects", headers={"Origin": origin}, json={
                    "name": "恶意网页", "requirements": "不应持久化"})
                assert response.status_code == 403 and response.json()["code"] == "untrusted_origin"
                assert response.headers["x-content-type-options"] == "nosniff"
            response = await client.get("/api/projects", headers={"Sec-Fetch-Site": "cross-site"})
            assert response.status_code == 403
            assert len((await client.get("/api/projects")).json()["projects"]) == 2
            preflight = await client.options("/api/projects", headers={"Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.asyncio
async def test_rebinding_remote_client_and_forged_proxy_headers_rejected(tmp_path):
    app = application(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as local:
            response = await local.get("/api/projects", headers={"Host": "rebind.evil.example"})
            assert response.status_code == 400 and response.json()["code"] == "untrusted_host"
            assert (await local.get("/health/live", headers={"Host": "[::1]:8000"})).status_code == 200
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.10", 1234)),
                                    base_url="http://127.0.0.1") as remote:
            response = await remote.get("/api/projects", headers={"X-Forwarded-For": "127.0.0.1"})
            assert response.status_code == 403 and response.json()["code"] == "local_access_only"


@pytest.mark.asyncio
async def test_bounded_content_length_chunked_body_and_json_only(tmp_path):
    app = application(tmp_path, max_request_body_bytes=1024)

    async def chunks():
        yield b"x" * 600
        yield b"y" * 600

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            for response in (
                await client.post("/api/projects", content=b"x" * 1025, headers={"Content-Type": "application/json"}),
                await client.post("/api/projects", content=chunks(), headers={"Content-Type": "application/json"}),
            ):
                assert response.status_code == 413 and response.json()["code"] == "request_too_large"
            for length in ("-1", "not-a-number", "9" * 5000, "10"):
                response = await client.post("/api/projects", content=b"{}", headers={
                    "Content-Length": length, "Content-Type": "application/json"})
                assert response.status_code == 400
            response = await client.post("/api/projects", content="name=forged&requirements=csrf",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            assert response.status_code == 415 and response.json()["code"] == "json_required"
            response = await client.post("/api/projects", content=b"{}", headers={"Content-Encoding": "gzip"})
            assert response.status_code == 415
            assert (await client.get("/api/projects")).json()["projects"] == []


@pytest.mark.asyncio
async def test_stalled_body_is_timed_out_before_application_dispatch():
    called = False
    messages = []

    async def app(_scope, _receive, _send):
        nonlocal called
        called = True

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    middleware = RequestSecurityMiddleware(app, Settings(request_body_timeout_seconds=1))
    await middleware({"type": "http", "method": "POST", "path": "/api/projects", "raw_path": b"/api/projects",
        "query_string": b"", "scheme": "http", "client": ("127.0.0.1", 1234),
        "headers": [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")]}, receive, send)
    assert not called
    assert messages[0]["status"] == 408
    assert b"request_body_timeout" in messages[1]["body"]


@pytest.mark.asyncio
async def test_api_rate_limit_covers_project_writes_but_not_cancellation_or_reads(tmp_path):
    app = application(tmp_path, api_write_limit_per_minute=2)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            for _ in range(2):
                assert (await client.post("/api/projects", json={"name": "测试", "requirements": "读取数据"})).status_code == 201
            response = await client.post("/api/projects", json={"name": "第三个", "requirements": "读取数据"})
            assert response.status_code == 429 and response.json()["code"] == "api_write_rate_limited"
            assert 1 <= int(response.headers["retry-after"]) <= 60
            assert (await client.post("/api/search-jobs/missing/cancel")).status_code == 404
            assert (await client.get("/api/projects")).status_code == 200


@pytest.mark.asyncio
async def test_analysis_queue_cap_and_same_project_inflight_version_protection(tmp_path):
    class PendingAnalyzer:
        available = True

        async def analyze(self, _project):
            await asyncio.Event().wait()

    settings = Settings(database_path=str(tmp_path / "analysis.sqlite3"), max_pending_analyses=1)
    app = create_app(settings, provider=EmptySearch(), fetcher=NoFetch(), analyzer=PendingAnalyzer())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            projects = [(await client.post("/api/projects", json={"name": str(i), "requirements": "读取数据"})).json()["project_id"]
                        for i in range(2)]
            first = await client.post(f"/api/projects/{projects[0]}/analyze", json={"expected_version": 0})
            assert first.status_code == 202
            duplicate = await client.post(f"/api/projects/{projects[0]}/analyze", json={"expected_version": 1})
            assert duplicate.status_code == 202 and duplicate.json()["current_version"] == 1
            changed = await client.post(f"/api/projects/{projects[0]}/analyze", json={"expected_version": 1,
                "input": {"name": "更改", "requirements": "读取其他数据"}})
            assert changed.status_code == 409 and changed.json()["code"] == "analysis_in_progress"
            second = await client.post(f"/api/projects/{projects[1]}/analyze", json={"expected_version": 0})
            assert second.status_code == 429 and second.json()["code"] == "analysis_queue_full"
            assert (await client.get(f"/api/projects/{projects[1]}")).json()["current_version"] == 0
            assert len(app.state.projects.analysis_tasks) == 1


@pytest.mark.asyncio
async def test_project_scheduler_admission_does_not_create_work(tmp_path):
    app = application(tmp_path, max_pending_project_searches=1)
    async with app.router.lifespan_context(app):
        pending = asyncio.create_task(asyncio.Event().wait())
        app.state.projects.tasks[("other", 1)] = pending
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.post("/api/projects/not-created/search", json={"version": 1})
            assert response.status_code == 429 and response.json()["code"] == "project_search_queue_full"
            assert app.state.store.job_counts() == {}


@pytest.mark.asyncio
async def test_validation_errors_and_http_logs_do_not_echo_user_text_or_exception_values(tmp_path, caplog):
    app = application(tmp_path)

    @app.get("/api/raise-test")
    async def crash():
        raise RuntimeError("SECRET_TOKEN https://internal.example/private")

    with caplog.at_level(logging.INFO, logger="knowledge_sprite.http"):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                response = await client.post("/api/projects?private=SECRET_TOKEN", json={"name": "SECRET_TOKEN", "requirements": ""})
                assert response.status_code == 422
                assert "SECRET_TOKEN" not in response.text and '"input"' not in response.text
                response = await client.get("/api/raise-test")
                assert response.status_code == 500 and response.json()["code"] == "internal_error"
                assert "SECRET_TOKEN" not in response.text and "internal.example" not in response.text
                assert response.headers["x-request-id"] == response.json()["request_id"]
    assert "SECRET_TOKEN" not in caplog.text and "internal.example" not in caplog.text
    assert "request_id=" in caplog.text and "error_type=RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_health_distinguishes_liveness_infrastructure_and_missing_product_dependencies(tmp_path):
    app = application(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health")).status_code == 200
            ready = await client.get("/health/ready")
            assert ready.status_code == 503 and ready.json()["status"] == "not_ready"
            assert ready.json()["analysis_configured"] is False
            assert ready.json()["search_configured"] is False
            assert ready.json()["upstream_check"] == "configuration_and_last_observation_only"
            caps = (await client.get("/api/capabilities")).json()
            assert caps["deployment"]["local_only"] is True and not caps["deployment"]["authentication"]


@pytest.mark.asyncio
async def test_failed_project_startup_stops_worker_and_closes_database(tmp_path, monkeypatch):
    from backend.app import main
    from backend.app.db import Store

    stores = []

    class RecordingStore(Store):
        closed = False

        def __init__(self, path):
            super().__init__(path)
            stores.append(self)

        def close(self):
            super().close()
            self.closed = True

    def fail_projects(*_args, **_kwargs):
        raise RuntimeError("Synthetic startup failure")

    monkeypatch.setattr(main, "Store", RecordingStore)
    monkeypatch.setattr(main, "ProjectService", fail_projects)
    app = application(tmp_path)
    with pytest.raises(RuntimeError, match="Synthetic startup failure"):
        async with app.router.lifespan_context(app):
            raise AssertionError("Failed startup cannot yield a running app")
    assert stores[0].closed and app.state.service.worker is None


@pytest.mark.parametrize("changes", [
    {"cors_origins": ("*",)}, {"cors_origins": ("https://example.org/path",)},
    {"allowed_hosts": ("*",)}, {"allowed_hosts": ()}, {"allowed_hosts": ("localhost:8000",)},
    {"database_path": ""}, {"search_provider": "unknown"}, {"llm_provider": "unknown"},
    {"searxng_url": "file:///etc/passwd"}, {"llm_base_url": "https://secret@example.org/v1"},
    {"max_request_body_bytes": 0}, {"max_pending_analyses": 0}, {"api_write_limit_per_minute": True},
    {"local_only": "false"},
])
def test_invalid_security_or_provider_configuration_fails_before_startup(changes):
    with pytest.raises(ValueError):
        replace(Settings(), **changes).validate()


@pytest.mark.parametrize("name,value", [("LOCAL_ONLY", "typo"), ("MAX_PENDING_ANALYSES", "bad"),
                                        ("MAX_REQUEST_BODY_BYTES", "0")])
def test_env_security_configuration_never_silently_weakens(monkeypatch, name, value):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("host", ["127.1", "127.0.1", "2130706433", "0x7f000001", "0177.0.0.1",
                                  "0x7f.0.0.1", "0x7f.1", "127.000.000.001", "0X7F000001", "０１７７.0.0.1"])
def test_browser_numeric_ipv4_forms_never_become_navigation_or_fetch_urls(host):
    with pytest.raises(UnsafeURL):
        normalize_url(f"https://{host}/video")


def test_regular_public_course_and_public_ipv4_urls_preserved():
    assert normalize_url("https://www.bilibili.com/video/BV1234567890/?p=2") == "https://www.bilibili.com/video/BV1234567890/?p=2"
    assert normalize_url("https://93.184.216.34/course") == "https://93.184.216.34/course"


@pytest.mark.parametrize("changes", [
    {"project_analysis_timeout_seconds": 0}, {"project_analysis_timeout_seconds": 181},
    {"project_analysis_total_timeout_seconds": 601}, {"project_analysis_total_timeout_seconds": 59},
    {"llm_max_output_tokens": 255}, {"llm_max_output_tokens": 16001}, {"llm_max_output_tokens": True},
])
def test_model_cost_and_timeout_configuration_fail_closed(changes):
    with pytest.raises(ValueError):
        replace(Settings(), **changes).validate()


@pytest.mark.parametrize("per_call,total", [(60, 100), (180, 600)])
def test_model_budget_defaults_and_exact_environment_overrides(monkeypatch, per_call, total):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    for name in ("PROJECT_ANALYSIS_TIMEOUT_SECONDS", "PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS", "LLM_MAX_OUTPUT_TOKENS",
                 "PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings.from_env()
    assert (defaults.project_analysis_timeout_seconds, defaults.project_analysis_total_timeout_seconds,
            defaults.llm_max_output_tokens, defaults.project_analysis_normalization_max_output_tokens) == (60, 60, 6000, 16000)
    monkeypatch.setenv("PROJECT_ANALYSIS_TIMEOUT_SECONDS", str(per_call))
    monkeypatch.setenv("PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS", str(total))
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS", "4096")
    actual = Settings.from_env()
    assert (actual.project_analysis_timeout_seconds, actual.project_analysis_total_timeout_seconds,
            actual.llm_max_output_tokens, actual.project_analysis_normalization_max_output_tokens) == (per_call, total, 2048, 4096)
    actual.validate()


@pytest.mark.parametrize("value", [255, 16001, True, False, None, "12000", 12000.0])
def test_normalization_token_budget_rejects_invalid_values_before_startup(value):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS"):
        replace(Settings(), project_analysis_normalization_max_output_tokens=value).validate()


@pytest.mark.parametrize("value", [256, 4096, 12000, 16000])
def test_normalization_token_budget_accepts_boundaries_and_environment_overrides(monkeypatch, value):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS", str(value))
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2048")
    direct = replace(Settings(), project_analysis_normalization_max_output_tokens=value).validate()
    assert direct.project_analysis_normalization_max_output_tokens == value
    loaded = Settings.from_env()
    assert loaded.project_analysis_normalization_max_output_tokens == value
    assert loaded.llm_max_output_tokens == 2048


@pytest.mark.parametrize("value", ["", "255", "16001", "-1", "12000.0", "true", "typo"])
def test_normalization_token_budget_environment_typos_fail_closed(monkeypatch, value):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS", value)
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS"):
        Settings.from_env()


def model_settings(**changes):
    changes.setdefault("project_semantic_review_enabled", False)  # transport-only fixtures
    return Settings(llm_provider="openai_compatible", llm_base_url="https://model.example/v1",
                    llm_api_key="offline-security-fixture-key", llm_model="offline-fixture", **changes)


@pytest.mark.asyncio
async def test_model_output_token_budget_is_sent_to_upstream():
    from backend.app.llm import complete_json
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await complete_json(model_settings(llm_max_output_tokens=384), "fixture", {}, client) == {"ok": True}
    assert json.loads(requests[0].content)["max_tokens"] == 384


@pytest.mark.asyncio
async def test_project_analysis_schema_failure_never_retries(monkeypatch):
    import backend.app.project_analysis as module
    calls = []

    async def respond(*_args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        assert len(calls) == 1
        await asyncio.sleep(0.05)
        return {}

    monkeypatch.setattr(module, "complete_json", respond)
    settings = model_settings(project_analysis_timeout_seconds=1, project_analysis_total_timeout_seconds=1)
    started = time.monotonic()
    with pytest.raises(module.AnalysisError) as error:
        await module.ProjectAnalyzer(settings).analyze(module.ProjectInput(name="CSV count", requirements="Read a CSV and print its row count"))
    assert error.value.code == "schema" and len(calls) == 1
    assert 0 < calls[0] <= 1
    assert time.monotonic() - started < 1


class CountingModelStream(httpx.AsyncByteStream):
    def __init__(self, *, delay=0, compressed=False):
        self.delay, self.compressed = delay, compressed
        self.chunks_read, self.closed = 0, False

    async def __aiter__(self):
        if self.compressed:
            self.chunks_read += 1
            yield gzip.compress(b"x" * 1_000_000)
            return
        for _ in range(1000):
            self.chunks_read += 1
            if self.delay:
                await asyncio.sleep(self.delay)
            yield b"x" * 16_384

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("compressed", [False, True])
async def test_model_oversized_stream_is_cut_off_and_closed_even_when_compressed(compressed):
    from backend.app.llm import complete_json, LLMResponseTooLarge
    stream = CountingModelStream(compressed=compressed)
    response_headers = {"Content-Encoding": "gzip"} if compressed else {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, headers=response_headers, stream=stream))) as client:
        with pytest.raises(LLMResponseTooLarge):
            await complete_json(model_settings(), "fixture", {}, client)
        assert stream.closed and stream.chunks_read < 20
        assert not client.is_closed


@pytest.mark.asyncio
async def test_borrowed_model_slow_stream_has_wall_clock_deadline_without_reconfiguration():
    from backend.app.llm import complete_json
    stream = CountingModelStream(delay=0.02)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    timeout = httpx.Timeout(0.75, connect=0.2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=timeout) as client:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await complete_json(model_settings(), "fixture", {}, client, timeout_seconds=0.06)
        assert time.monotonic() - started < 0.8
        assert stream.closed and stream.chunks_read < 10 and not client.is_closed
        assert requests[0].extensions["timeout"]["read"] == 0.75
        assert requests[0].extensions["timeout"]["connect"] == 0.2


@pytest.mark.asyncio
async def test_owned_model_client_and_stream_close_on_deadline(monkeypatch):
    import backend.app.llm as module
    stream, created = CountingModelStream(delay=0.02), []
    original_client = httpx.AsyncClient

    def factory(**kwargs):
        client = original_client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    with pytest.raises(TimeoutError):
        await module.complete_json(model_settings(), "fixture", {}, timeout_seconds=0.06)
    assert stream.closed and created[0].is_closed


@pytest.mark.parametrize("value", ["", "none", "turbo", "LOW", None, True, []])
def test_invalid_reasoning_effort_configuration_fails_closed(value):
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT"):
        replace(Settings(), llm_reasoning_effort=value).validate()


def test_reasoning_effort_default_and_explicit_environment_values(monkeypatch):
    monkeypatch.setenv("PROJECT_ANALYSIS_REASONING_EFFORT", "inherit")
    monkeypatch.setenv("PROJECT_ANALYSIS_MODEL", "")
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("LLM_THINKING_MODE", "provider_default")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    assert Settings.from_env().llm_reasoning_effort == "auto"
    for value in ("provider_default", "low", "medium", "high", "max"):
        monkeypatch.setenv("LLM_REASONING_EFFORT", f" {value.upper()} ")
        assert Settings.from_env().llm_reasoning_effort == value
    monkeypatch.setenv("LLM_REASONING_EFFORT", "turbo")
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT"):
        Settings.from_env()


@pytest.mark.asyncio
@pytest.mark.parametrize("base,model,effort,expected", [
    ("https://api.deepseek.com", "deepseek-flash", "auto", "low"),
    ("https://api.deepseek.com/v1", "deepseek-v4-pro", "auto", "low"),
    ("https://api.deepseek.com:443/v1", "deepseek-flash", "auto", "low"),
    ("https://API.DEEPSEEK.COM/v1", "deepseek-flash", "auto", "low"),
    ("https://api.deepseek.com/v1", "deepseek-chat", "auto", None),
    ("https://api.deepseek.com/v1", "future-model", "auto", None),
    ("https://api.openai.com/v1", "deepseek-flash", "auto", None),
    ("https://model.example/v1", "deepseek-v4-pro", "auto", None),
    ("https://api.deepseek.com.attacker.example/v1", "deepseek-flash", "auto", None),
    ("https://attacker-api.deepseek.com/v1", "deepseek-flash", "auto", None),
    ("https://attacker.example/api.deepseek.com", "deepseek-flash", "auto", None),
    ("http://api.deepseek.com/v1", "deepseek-flash", "auto", None),
    ("https://api.deepseek.com:8443/v1", "deepseek-flash", "auto", None),
    ("https://api.deepseek.com/v1", "deepseek-flash", "provider_default", None),
    ("https://model.example/v1", "offline-fixture", "low", "low"),
    ("https://model.example/v1", "offline-fixture", "medium", "medium"),
    ("https://api.deepseek.com/v1", "deepseek-flash", "high", "high"),
    ("https://api.deepseek.com/v1", "deepseek-v4-pro", "max", "max"),
])
async def test_reasoning_effort_payload_is_endpoint_scoped_and_operator_overridable(base, model, effort, expected):
    from backend.app.llm import complete_json
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})

    settings = replace(model_settings(), llm_base_url=base, llm_model=model, llm_reasoning_effort=effort,
                       llm_thinking_mode="provider_default")
    settings.validate()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await complete_json(settings, "fixture", {}, client) == {"ok": True}
    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 6000
    if expected is None:
        assert "reasoning_effort" not in payload
    else:
        assert payload["reasoning_effort"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected_code", [("length", "output_truncated"), ("bytes", "response_too_large")])
async def test_small_project_preserves_input_and_reports_provider_limits_without_scope_blame(tmp_path, failure, expected_code):
    from backend.app.project_analysis import ProjectAnalyzer
    requests = []

    def respond(request):
        requests.append(request)
        if failure == "bytes":
            return httpx.Response(200, content=b"x" * 720_001)
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"scope":'}}]})

    settings = replace(model_settings(), database_path=str(tmp_path / "small-project.sqlite3"))
    original = {"name": "Python 小游戏", "requirements": "用 Python 做一个贪吃蛇小游戏，方向键控制移动，吃到食物增加分数，撞墙或碰到自己时结束，支持重新开始。"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as upstream:
        app = create_app(settings, provider=EmptySearch(), fetcher=NoFetch(), analyzer=ProjectAnalyzer(settings, upstream))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                created = await client.post("/api/projects", json=original)
                pid = created.json()["project_id"]
                assert (await client.post(f"/api/projects/{pid}/analyze", json={"expected_version": 0})).status_code == 202
                await asyncio.gather(*app.state.projects.analysis_tasks.values())
                result = (await client.get(f"/api/projects/{pid}/results")).json()
    error = result["version"]["error"]
    assert error["code"] == expected_code
    assert "缩小" not in error["message"] and "分阶段" not in error["message"]
    assert result["original_input"]["requirements"] == original["requirements"]
    assert result["version"]["status"] == "analysis_failed" and result["version"]["analysis"] is None
    assert len(requests) == 1


@pytest.mark.parametrize("value", ["", "none", "turbo", "ENABLED", None, True, []])
def test_invalid_thinking_mode_configuration_fails_closed(value):
    with pytest.raises(ValueError, match="LLM_THINKING_MODE"):
        replace(Settings(), llm_thinking_mode=value).validate()


def test_thinking_mode_environment_default_and_explicit_values(monkeypatch):
    monkeypatch.setenv("PROJECT_ANALYSIS_REASONING_EFFORT", "inherit")
    monkeypatch.setenv("PROJECT_ANALYSIS_MODEL", "")
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "provider_default")
    monkeypatch.delenv("LLM_THINKING_MODE", raising=False)
    assert Settings.from_env().llm_thinking_mode == "auto"
    for value in ("provider_default", "enabled", "disabled"):
        monkeypatch.setenv("LLM_THINKING_MODE", f" {value.upper()} ")
        assert Settings.from_env().llm_thinking_mode == value
    monkeypatch.setenv("LLM_THINKING_MODE", "unknown")
    with pytest.raises(ValueError, match="LLM_THINKING_MODE"):
        Settings.from_env()


@pytest.mark.parametrize("thinking", ["auto", "disabled"])
@pytest.mark.parametrize("effort", ["low", "medium", "high", "max"])
def test_disabled_thinking_and_explicit_reasoning_conflict_before_any_request(thinking, effort):
    settings = replace(model_settings(), llm_base_url="https://api.deepseek.com/v1", llm_model="deepseek-flash",
                       llm_thinking_mode=thinking, llm_reasoning_effort=effort)
    with pytest.raises(ValueError, match="LLM_THINKING_MODE disables thinking"):
        settings.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize("base,model,thinking,effort,expected_thinking,expected_effort", [
    ("https://api.deepseek.com/v1", "deepseek-flash", "auto", "auto", "disabled", None),
    ("https://api.deepseek.com", "deepseek-v4-pro", "auto", "auto", "disabled", None),
    ("https://api.deepseek.com:443/v1", "deepseek-flash", "auto", "auto", "disabled", None),
    ("https://API.DEEPSEEK.COM/v1", "deepseek-flash", "auto", "auto", "disabled", None),
    ("https://api.deepseek.com/v1", "deepseek-flash", "auto", "provider_default", "disabled", None),
    ("https://api.deepseek.com/v1", "future-model", "auto", "auto", None, None),
    ("https://model.example/v1", "deepseek-flash", "auto", "auto", None, None),
    ("https://api.openai.com/v1", "deepseek-v4-pro", "auto", "auto", None, None),
    ("https://api.deepseek.com.evil.example/v1", "deepseek-flash", "auto", "auto", None, None),
    ("https://attacker-api.deepseek.com/v1", "deepseek-flash", "auto", "auto", None, None),
    ("https://evil.example/api.deepseek.com", "deepseek-flash", "auto", "auto", None, None),
    ("http://api.deepseek.com/v1", "deepseek-flash", "auto", "auto", None, None),
    ("https://api.deepseek.com:8443/v1", "deepseek-flash", "auto", "auto", None, None),
    ("https://api.deepseek.com/v1", "deepseek-flash", "provider_default", "provider_default", None, None),
    ("https://api.deepseek.com/v1", "deepseek-flash", "provider_default", "auto", None, "low"),
    ("https://api.deepseek.com/v1", "deepseek-flash", "enabled", "auto", "enabled", "low"),
    ("https://api.deepseek.com/v1", "deepseek-flash", "enabled", "high", "enabled", "high"),
    ("https://api.deepseek.com/v1", "deepseek-flash", "disabled", "auto", "disabled", None),
    ("https://model.example/v1", "custom-model", "enabled", "max", "enabled", "max"),
    ("https://model.example/v1", "custom-model", "disabled", "provider_default", "disabled", None),
    ("https://model.example/v1", "custom-model", "auto", "medium", None, "medium"),
])
async def test_finite_json_thinking_payload_default_scope_and_administrator_override(
        base, model, thinking, effort, expected_thinking, expected_effort):
    from backend.app.llm import complete_json
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})

    settings = replace(model_settings(), llm_base_url=base, llm_model=model,
                       llm_thinking_mode=thinking, llm_reasoning_effort=effort)
    settings.validate()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await complete_json(settings, "bounded JSON fixture", {}, client) == {"ok": True}
    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 6000 and payload["response_format"] == {"type": "json_object"}
    assert payload.get("thinking") == ({"type": expected_thinking} if expected_thinking else None)
    assert payload.get("reasoning_effort") == expected_effort
    if expected_thinking is None:
        assert "thinking" not in payload
    if expected_effort is None:
        assert "reasoning_effort" not in payload
