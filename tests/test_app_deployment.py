"""Offline deployment checks. Synthetic files only; no Docker daemon/API calls."""
from contextlib import closing
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location("deployment_" + name, ROOT / "deploy" / ("app-" + name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


entry, health, backup = module("entrypoint"), module("healthcheck"), module("backup")


def make_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE preserved_input(id INTEGER PRIMARY KEY, text TEXT)")
    connection.execute("INSERT INTO preserved_input VALUES(1,'synthetic student text, not a credential')")
    connection.commit()
    return connection


def app_paths(tmp_path):
    data, app = tmp_path / "persistent", tmp_path / "image"
    data.mkdir()
    (app / "frontend/dist/assets").mkdir(parents=True)
    (app / "frontend/dist/index.html").write_text("<div id='root'></div>", encoding="utf-8")
    return data, app


def test_compose_is_loopback_host_single_instance_with_persistent_and_bounded_resources():
    config = yaml.safe_load((ROOT / "compose.app.yaml").read_text(encoding="utf-8"))
    app = config["services"]["app"]
    assert app["network_mode"] == "host" and "ports" not in app
    assert app["environment"]["LOCAL_ONLY"] == "true"
    assert app["environment"]["ALLOWED_HOSTS"] == "localhost,127.0.0.1,::1"
    assert app["environment"]["JS_RENDER_ENABLED"] == "false"
    assert app["read_only"] is True and app["user"] == "10001:10001"
    assert app["init"] is True and app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["volumes"] == ["app-data:/var/lib/knowledge-sprite", "app-backups:/var/backups/knowledge-sprite"]
    assert set(config["volumes"]) == {"app-data", "app-backups"}
    assert app["pids_limit"] == 128 and app["mem_limit"] == "1g" and app["cpus"] == 1.0
    assert app["stop_grace_period"] == "45s" and app["restart"] == "on-failure:3"
    assert "noexec,nosuid,size=64m" in app["tmpfs"][0]
    assert app["logging"]["options"] == {"max-size": "10m", "max-file": "3"}
    assert app["healthcheck"]["test"] == ["CMD", "python", "/app/deploy/app-healthcheck.py"]
    assert all("API_KEY" not in name for name in app["environment"])
    assert app["secrets"] == ["app_api_keys"]
    assert config["secrets"]["app_api_keys"]["file"] == "${APP_API_KEYS_FILE:-./deploy/app-api-keys.env.example}"


def test_optional_search_overlay_uses_existing_loopback_service_without_private_config_generation():
    data = yaml.safe_load((ROOT / "compose.app.searxng.yaml").read_text(encoding="utf-8"))
    assert set(data["services"]) == {"app"}
    app = data["services"]["app"]
    assert app["environment"] == {"SEARXNG_URL": "http://127.0.0.1:18780"}
    assert app["depends_on"] == {"searxng": {"condition": "service_started"}}
    assert "volumes" not in app and "ports" not in app


def test_public_examples_keep_costs_unconfigured_teaching_enabled_and_bounded_streams():
    from dotenv import dotenv_values
    config = dotenv_values(ROOT / "deploy/app.env.example", interpolate=False)
    assert config["LLM_PROVIDER"] == "none" and config["SEARXNG_URL"] == ""
    assert config["TEACHING_MATCH_ENABLED"] == config["PARALLEL_PLATFORM_SEARCH"] == "true"
    assert config["TAVILY_ALLOW_KEYLESS"] == "false" and config["SEARXNG_FAILOVER_PROVIDER"] == ""
    assert config["MAX_SEARCH_REQUESTS"] == "30" and config["MAX_DETAIL_PAGES"] == "40"
    assert config["MAX_EVENT_STREAMS"] == "16" and config["GLOBAL_CONCURRENCY"] == "2"
    assert config["SEARCH_MAX_RETRIES"] == "0"
    assert not set(config) & entry.API_KEY_NAMES
    assert dotenv_values(ROOT / "deploy/app-api-keys.env.example", interpolate=False) == {
        "LLM_API_KEY": "", "TAVILY_API_KEY": "", "SERPER_API_KEY": ""}


def test_image_uses_locks_nonroot_runtime_and_does_not_copy_operator_material():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM ${PYTHON_IMAGE} AS app", 1)[1]
    assert "COPY frontend/package.json frontend/package-lock.json" in dockerfile
    assert "npm ci --no-audit --no-fund" in dockerfile and "npm run build" in dockerfile
    assert "--require-hashes --only-binary=:all: -r requirements.lock.txt" in runtime
    assert "COPY --from=frontend-build /build/frontend/dist/" in runtime
    assert "USER 10001:10001" in runtime and "STOPSIGNAL SIGTERM" in runtime
    assert "PYTHON_DOTENV_DISABLED=1" in runtime
    assert "COPY . " not in dockerfile and "ADD " not in dockerfile
    assert all(token not in runtime for token in ["node_modules", "COPY .env", "settings.yml", "evidence/", "data/"])
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**" in ignore and "!backend/**/*.py" in ignore
    for value in ["**/.env", "**/.env.*", "**/*.sqlite*", "**/.git", "**/evidence", "**/node_modules", "deploy/searxng/settings.yml"]:
        assert value in ignore


def test_argv_enforces_one_loopback_worker_and_prevents_proxy_and_access_logs(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    argv = entry.uvicorn_argv()
    assert argv[argv.index("--workers") + 1] == "1"
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "8000"
    assert "--no-proxy-headers" in argv and "--no-access-log" in argv and "--no-server-header" in argv
    assert "--reload" not in argv and argv[argv.index("--timeout-graceful-shutdown") + 1] == "30"


@pytest.mark.parametrize("change", [
    {"LOCAL_ONLY": "false"}, {"LOCAL_ONLY": "0"}, {"JS_RENDER_ENABLED": "true"},
    {"ALLOWED_HOSTS": "localhost,127.0.0.1,app.example"}, {"ALLOWED_HOSTS": "*"},
    {"CORS_ORIGINS": "http://example.org"}, {"CORS_ORIGINS": "http://user@localhost:8000"},
    {"CORS_ORIGINS": "http://localhost:8000/path"}, {"CORS_ORIGINS": "http://localhost:0"},
])
def test_entrypoint_refuses_disabled_boundary_foreign_hosts_and_origin_overrides(change):
    with pytest.raises(entry.DeploymentError):
        entry.validate_boundary(change)


def test_entrypoint_accepts_loopback_private_configuration():
    entry.validate_boundary({})
    entry.validate_boundary({"LOCAL_ONLY": "true", "CORS_ORIGINS": "http://127.0.0.1:8000,http://localhost:5173"})


def test_database_stays_on_volume_and_existing_integrity_is_read_only(tmp_path):
    data, app = app_paths(tmp_path)
    database = data / "existing.sqlite3"
    with closing(make_database(database)):
        before = database.read_bytes()
        assert entry.validate_paths(str(database.resolve()), data_root=data, app_root=app) == database.resolve()
        assert database.read_bytes() == before
    assert entry.validate_paths(str((data / "new.sqlite3").resolve()), data_root=data, app_root=app).name == "new.sqlite3"
    assert not (data / "new.sqlite3").exists()


@pytest.mark.parametrize("name", ["../outside.sqlite3", "sub/directory.sqlite3", "file.db", ":memory:"])
def test_entrypoint_database_path_rejects_escape_and_ephemeral_target(tmp_path, name):
    data, app = app_paths(tmp_path)
    with pytest.raises(entry.DeploymentError):
        entry.validate_paths(str(data / name), data_root=data, app_root=app)


def test_corrupt_database_or_unbuilt_frontend_cannot_start(tmp_path):
    data, app = app_paths(tmp_path)
    database = data / "corrupt.sqlite3"
    database.write_bytes(b"not a database")
    with pytest.raises(entry.DeploymentError, match="integrity"):
        entry.validate_paths(str(database.resolve()), data_root=data, app_root=app)
    (app / "frontend/dist/index.html").unlink()
    with pytest.raises(entry.DeploymentError, match="frontend"):
        entry.validate_paths(str((data / "new.sqlite3").resolve()), data_root=data, app_root=app)


def test_api_key_secret_file_is_allowlisted_unexpanded_and_never_printed(tmp_path, capsys):
    keyfile = tmp_path / "synthetic-api-keys"
    keyfile.write_text('LLM_API_KEY="synthetic-${OTHER_KEY}"\nTAVILY_API_KEY=\nSERPER_API_KEY=synthetic-value\n', encoding="utf-8")
    environ = {}
    entry.load_api_keys(keyfile, environ)
    assert environ == {"LLM_API_KEY": "synthetic-${OTHER_KEY}", "SERPER_API_KEY": "synthetic-value"}
    assert capsys.readouterr() == ("", "")
    assert "synthetic-value" not in " ".join(entry.uvicorn_argv())


@pytest.mark.parametrize("content", ["LD_PRELOAD=unsafe\n", "LLM_API_KEY\n", 'LLM_API_KEY="first\nsecond"\n', "LLM_API_KEY=" + "a" * 8193])
def test_key_file_cannot_inject_process_options_or_oversize_multiline_value(tmp_path, content):
    path = tmp_path / "keys"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(entry.DeploymentError) as caught:
        entry.load_api_keys(path, {})
    assert content not in str(caught.value)


def test_conflicting_key_sources_fail_without_echo(tmp_path):
    path = tmp_path / "keys"
    path.write_text("LLM_API_KEY=synthetic-one\n", encoding="utf-8")
    with pytest.raises(entry.DeploymentError, match="conflict") as caught:
        entry.load_api_keys(path, {"LLM_API_KEY": "synthetic-two"})
    assert "synthetic" not in str(caught.value)


def test_preflight_failure_does_not_exec_or_print_configuration(tmp_path, monkeypatch, capsys):
    data, app = app_paths(tmp_path)
    keys = tmp_path / "keys"
    keys.write_text("LLM_API_KEY=synthetic-private-value\n", encoding="utf-8")
    monkeypatch.setattr(entry, "KEYS_PATH", keys)
    monkeypatch.setattr(entry, "DATA_ROOT", data)
    monkeypatch.setattr(entry, "APP_ROOT", app)
    monkeypatch.setattr(sys, "argv", ["app-entrypoint.py"])
    monkeypatch.setenv("LOCAL_ONLY", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    called = Mock()
    monkeypatch.setattr(entry.os, "execv", called)
    previous_mask = entry.os.umask(0o077)
    try:
        assert entry.main() == 1
    finally:
        entry.os.umask(previous_mask)
    assert not called.called
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "failed", "code": "deployment_preflight_failed"}
    assert "synthetic" not in captured.err and str(tmp_path) not in captured.err


class HealthResponse(io.BytesIO):
    def __init__(self, data, *, status=200, url="http://127.0.0.1:8000/health"):
        super().__init__(data)
        self.status, self.url = status, url

    def geturl(self):
        return self.url


def test_health_calls_fixed_loopback_not_upstreams_and_distinguishes_ready():
    opener = Mock()
    opener.open.return_value = HealthResponse(b'{"status":"ok","sqlite":"ok"}')
    assert health.check(opener=opener)
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8000/health"
    assert opener.open.call_args.kwargs == {"timeout": 3}
    opener.open.return_value = HealthResponse(b'{"status":"ready"}', url="http://127.0.0.1:8000/health/ready")
    assert health.check(ready=True, opener=opener)
    assert opener.open.call_args.args[0].full_url.endswith("/health/ready")


@pytest.mark.parametrize("payload,status,url", [
    (b'{"status":"not_ready"}', 503, "http://127.0.0.1:8000/health"),
    (b'{"status":"ok"}', 200, "https://foreign.example/health"),
    (b'not json', 200, "http://127.0.0.1:8000/health"),
    (b'[]', 200, "http://127.0.0.1:8000/health"),
    (b' ' * 32769, 200, "http://127.0.0.1:8000/health"),
], ids=["not-ready", "foreign-redirect", "malformed", "non-object", "oversize"])
def test_health_failure_redirect_malformed_and_size_limits_are_closed(payload, status, url):
    opener = Mock()
    opener.open.return_value = HealthResponse(payload, status=status, url=url)
    assert not health.check(opener=opener)


def test_health_redirect_handler_never_constructs_followup_request():
    assert health.NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://foreign.example") is None


def test_health_timeout_does_not_print_exception_data(capsys):
    opener = Mock()
    opener.open.side_effect = TimeoutError("synthetic-private-value")
    assert not health.check(opener=opener)
    assert capsys.readouterr() == ("", "")


def test_health_default_opener_disables_environment_proxy_and_redirects(monkeypatch):
    captured = []
    opener = Mock()
    opener.open.return_value = HealthResponse(b'{"status":"ok"}')
    monkeypatch.setenv("HTTP_PROXY", "http://foreign.example")
    monkeypatch.setattr(health, "build_opener", lambda *handlers: captured.extend(handlers) or opener)
    assert health.check()
    assert captured[0].proxies == {} and isinstance(captured[1], health.NoRedirect)


def test_active_wal_snapshot_includes_committed_and_excludes_uncommitted_without_source_write(tmp_path):
    source, target, restored = tmp_path / "source.sqlite3", tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3"
    with closing(make_database(source)) as writer:
        writer.execute("INSERT INTO preserved_input VALUES(2,'committed WAL row')")
        writer.commit()
        writer.execute("INSERT INTO preserved_input VALUES(3,'uncommitted row')")
        before = {f.name: f.read_bytes() for f in [source, Path(str(source) + "-wal")]}
        report = backup.snapshot(source, target)
        assert report["status"] == "ok" and report["file"] == "backup.sqlite3"
        assert {f.name: f.read_bytes() for f in [source, Path(str(source) + "-wal")]} == before
        with closing(sqlite3.connect(target)) as copy:
            assert copy.execute("SELECT id FROM preserved_input ORDER BY id").fetchall() == [(1,), (2,)]
        backup.snapshot(target, restored)
        with closing(sqlite3.connect(restored)) as copy:
            assert copy.execute("SELECT id FROM preserved_input ORDER BY id").fetchall() == [(1,), (2,)]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == report["sha256"]
        writer.rollback()


@pytest.mark.parametrize("name", ["../outside.sqlite3", "/absolute.sqlite3", "..sqlite3", "file.db", "sub/file.sqlite3", None])
def test_backup_name_cannot_escape_or_change_format(tmp_path, name):
    with pytest.raises(ValueError):
        backup.safe_file(tmp_path, name)


def test_existing_backup_and_live_database_never_overwritten(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "backup.sqlite3"
    with closing(make_database(source)):
        backup.snapshot(source, target)
        before = source.read_bytes(), target.read_bytes()
        with pytest.raises(FileExistsError):
            backup.snapshot(source, target)
        with pytest.raises(ValueError):
            backup.snapshot(source, source)
        assert before == (source.read_bytes(), target.read_bytes())


def test_failed_backup_removes_only_new_target(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "new.sqlite3"
    with closing(make_database(source)):
        before = source.read_bytes()
        with pytest.raises(TimeoutError):
            backup.snapshot(source, target, timeout_seconds=0)
        assert not target.exists() and source.read_bytes() == before


def test_migration_rehearsal_changes_only_the_new_snapshot_and_preserves_old_rows(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "migration.sqlite3"
    with closing(make_database(source)):
        before = source.read_bytes()
        result = backup.migrate_copy(source, target)
        assert source.read_bytes() == before
    assert result["status"] == "ok" and result["tables"] > 1
    with closing(sqlite3.connect(target)) as migrated:
        assert migrated.execute("SELECT text FROM preserved_input WHERE id=1").fetchone() == ("synthetic student text, not a credential",)
        tables = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"jobs", "projects", "project_versions"}.issubset(tables)


@pytest.mark.asyncio
@pytest.mark.parametrize("client,expected", [("127.0.0.1", 200), ("172.20.0.1", 403)])
async def test_existing_asgi_loopback_gate_requires_real_loopback_not_docker_bridge(client, expected):
    from backend.app.config import Settings
    from backend.app.security import RequestSecurityMiddleware
    messages = []
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "method": "GET", "scheme": "http", "path": "/health", "raw_path": b"/health",
             "query_string": b"", "headers": [(b"host", b"127.0.0.1:8000")], "client": (client, 1234)}
    await RequestSecurityMiddleware(app, Settings())(scope, receive, send)
    assert messages[0]["status"] == expected
    if expected == 403:
        assert json.loads(messages[1]["body"])["code"] == "local_access_only"
