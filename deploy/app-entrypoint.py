"""Fail-closed Linux loopback deployment launcher; no provider requests."""
from __future__ import annotations

import io
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values

DATA_ROOT = Path("/var/lib/knowledge-sprite")
APP_ROOT = Path("/app")
KEYS_PATH = Path("/run/secrets/app_api_keys")
API_KEY_NAMES = frozenset({"LLM_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class DeploymentError(ValueError):
    """Only fixed codes, never paths, input values or credential text."""


def load_api_keys(path: Path, environ: dict) -> None:
    if not path.is_file() or path.stat().st_size > 32_768:
        raise DeploymentError("api_keys_file_missing_or_too_large")
    try:
        text = path.read_text(encoding="utf-8")
        values = dotenv_values(stream=io.StringIO(text), interpolate=False)
    except (OSError, UnicodeError, ValueError):
        raise DeploymentError("api_keys_file_invalid") from None
    if not set(values).issubset(API_KEY_NAMES):
        raise DeploymentError("api_keys_file_unknown_name")
    for name, value in values.items():
        if value is None or len(value) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise DeploymentError("api_keys_file_invalid_value")
        if value:
            if environ.get(name) and environ[name] != value:
                raise DeploymentError("api_keys_configuration_conflict")
            environ[name] = value


def validate_paths(database: str, *, data_root: Path, app_root: Path) -> Path:
    root = data_root.resolve(strict=True)
    path = Path(database)
    if not path.is_absolute() or path.suffix != ".sqlite3":
        raise DeploymentError("database_must_be_persistent_sqlite3")
    # Check lexical parents before resolve; resolving alone would hide symlinks.
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise DeploymentError("database_symlink_not_supported")
    path = path.resolve()
    if not path.is_relative_to(root) or path.parent != root:
        raise DeploymentError("database_outside_data_volume")
    if not (app_root / "frontend/dist/index.html").is_file() or not (app_root / "frontend/dist/assets").is_dir():
        raise DeploymentError("frontend_build_missing")
    if path.exists():
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
                if source.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise DeploymentError("database_integrity_failed")
        except sqlite3.Error:
            raise DeploymentError("database_integrity_failed") from None
    return path


def validate_boundary(environ: dict) -> None:
    if str(environ.get("LOCAL_ONLY", "true")).lower() != "true":
        raise DeploymentError("loopback_boundary_required")
    if str(environ.get("JS_RENDER_ENABLED", "false")).lower() != "false":
        raise DeploymentError("browser_runtime_not_in_image")
    hosts = {x.strip() for x in environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",")}
    if "127.0.0.1" not in hosts or not hosts.issubset(LOOPBACK_HOSTS):
        raise DeploymentError("loopback_hosts_required")
    for value in environ.get("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(","):
        try:
            parts = urlsplit(value.strip())
            valid = (parts.scheme in {"http", "https"} and parts.hostname in LOOPBACK_HOSTS and
                     parts.username is None and parts.password is None and not parts.path and
                     not parts.query and not parts.fragment and parts.port != 0)
        except ValueError:
            valid = False
        if not valid:
            raise DeploymentError("loopback_origins_required")


def uvicorn_argv() -> list[str]:
    return [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000",
            "--workers", "1", "--no-proxy-headers", "--no-access-log", "--no-server-header",
            "--timeout-graceful-shutdown", "30", "--log-level", "warning"]


def main() -> int:
    try:
        if sys.argv[1:]:
            raise DeploymentError("entrypoint_arguments_not_supported")
        os.umask(0o077)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        load_api_keys(KEYS_PATH, os.environ)
        validate_boundary(os.environ)
        validate_paths(os.environ.get("DATABASE_PATH", ""), data_root=DATA_ROOT, app_root=APP_ROOT)
        # Normal validation only: importing config does not contact providers.
        sys.path.insert(0, str(APP_ROOT))
        from backend.app.config import Settings
        Settings.from_env().validate()
    except (DeploymentError, ValueError, OSError):
        print(json.dumps({"status": "failed", "code": "deployment_preflight_failed"}), file=sys.stderr)
        return 1
    os.chdir(APP_ROOT)
    os.execv(sys.executable, uvicorn_argv())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
