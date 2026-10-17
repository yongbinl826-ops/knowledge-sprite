"""Serve the production search UI with isolated, append-only live evidence.

This runner never submits a search, seeds a candidate, reads saved HTML, or
changes provider/permission/budget configuration. Submit through the real UI.
Only database/cache storage is isolated. Existing production methods are wrapped
to observe their outcomes; all requests and policy decisions remain unchanged.
"""
from __future__ import annotations

import argparse
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.fetcher import FetchStopped, NETWORK_OBSERVER, PLATFORM_POLICY_REVIEWS
from backend.app.service import JobService
import backend.app.main as main_module

PHASE = ROOT / "reports/platform-live-chain-20261017"
CURRENT_JOB: ContextVar[dict | None] = ContextVar("live_chain_audit_job", default=None)
CURRENT_AUDIT: ContextVar[dict | None] = ContextVar("live_chain_audit_registry", default=None)
SECRET_KEYS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "headers",
               "api_key", "tavily_api_key", "llm_api_key", "password", "secret", "token"}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def public_url(value: str):
    """Exclude query values, fragments and embedded credentials from journals."""
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"}:
            return "[non-http URL]"
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, host + port, parts.path, "", ""))
    except (ValueError, TypeError):
        return "[invalid URL]"


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()
                if str(key).lower() not in SECRET_KEYS and not str(key).lower().endswith("_api_key")}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, str):
        text = re.sub(r"https?://[^\s<>\"']+", lambda match: public_url(match.group()), value)
        text = re.sub(r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*",
                      "[credential redacted]", text)
        return re.sub(r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",
                      "[credential redacted]", text)
    return value


def audit_error(operation: str, error: Exception):
    """Never let a failed evidence sink replace a production outcome.

    Error text is intentionally excluded: I/O/provider exceptions can contain
    credentials. Memory remains authoritative even when every disk write fails.
    """
    state, registry = CURRENT_JOB.get(), CURRENT_AUDIT.get()
    record = {"at": now(), "operation": operation, "error_type": type(error).__name__,
              "acceptance_valid": False}
    if state is not None:
        record["job_id"] = state.get("job_id")
        state["acceptance_valid"] = False
        state["audit_errors"].append(record)
    if registry is not None:
        registry["acceptance_valid"] = False
        registry["audit_errors"].append(record)
    output = (state or {}).get("output") or (registry or {}).get("output")
    if output:
        try:
            with (Path(output) / "audit-errors.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # A second storage failure cannot recurse or change the job result.
            pass


def audit_call(operation, callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except Exception as exc:
        audit_error(operation, exc)
        return None


def write_json(path: Path, data, *, exclusive=False):
    def write():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
            stream.write(json.dumps(clean(data), ensure_ascii=False, indent=2))
        return True
    return audit_call("write_json:" + path.name, write)


def append_event(kind: str, data):
    state = CURRENT_JOB.get()
    if state is None:
        return
    def write():
        state["sequence"] += 1
        event = {"sequence": state["sequence"], "recorded_at": now(), "event_type": kind, **clean(data)}
        with (state["folder"] / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    audit_call("append_event:" + kind, write)


def observe_response(result, kind):
    state = CURRENT_JOB.get()
    if state is None:
        return
    state["response_count"] += 1
    # Hash the bytes returned by the real bounded transport, before decoding or
    # extraction. Bodies are not journaled, so public pages cannot leak embedded
    # session tokens or cookies into this audit log.
    append_event("http_response_body", {"response_index": state["response_count"],
        "request_kind": kind, "url": public_url(result.url), "url_sha256": sha(result.url.encode()),
        "http_status": result.status_code, "body_bytes": len(result.body), "body_sha256": sha(result.body),
        "body_representation": "exact bytes returned by production bounded transport; not saved HTML replay"})


def instrument_fetcher(fetcher):
    policy_original, request_original, trace_original = fetcher._site_policy, fetcher._request, fetcher._trace

    def policy(url):
        try:
            answer = policy_original(url)
        except FetchStopped as exc:
            audit_call("policy_blocked", append_event, "policy_decision", {
                "url": public_url(url), "url_sha256": sha(url.encode()), "decision": "blocked_before_network",
                "status": exc.status, "reason": str(exc), "policy": exc.policy})
            raise
        audit_call("policy_allowed", append_event, "policy_decision", {"url": public_url(url),
            "url_sha256": sha(url.encode()), "decision": "passed_site_policy_only",
            "note": "robots and subsequent HTTP checks still apply"})
        return answer

    def trace(event, url, **fields):
        answer = trace_original(event, url, **fields)
        audit_call("fetcher_trace", lambda: append_event("fetcher_trace", dict(fetcher.request_trace[-1])))
        return answer

    async def request(url, max_bytes, *, kind="page"):
        parent = NETWORK_OBSERVER.get() or {}
        dns_records = []

        def response(result, response_kind):
            audit_call("observe_response", observe_response, result, response_kind)
            if parent.get("response"):
                parent["response"](result, response_kind)

        def dns_trace(record):
            # The resolver publishes the same dict before it finishes mutating
            # status/duration. Keep that reference and copy it in finally below.
            dns_records.append(record)
            audit_call("dns_start", lambda: append_event("dns_http_trace_started", {
                "trace_index": len(dns_records), "snapshot_stage": "started_not_terminal",
                "trace": deepcopy(record)}))
            if parent.get("dns_trace"):
                parent["dns_trace"](record)

        # Wrap at the request boundary so a nested official provider cannot
        # replace and discard the audit observer. Existing hooks/budgets survive.
        token = NETWORK_OBSERVER.set({**parent, "response": response, "dns_trace": dns_trace})
        try:
            return await request_original(url, max_bytes, kind=kind)
        finally:
            try:
                for index, record in enumerate(dns_records, 1):
                    audit_call("dns_final", lambda index=index, record=record: append_event(
                        "dns_http_trace_final", {"trace_index": index, "snapshot_stage": "request_finally",
                            "terminal_status_observed": record.get("status") not in {None, "running", "started"},
                            "trace": deepcopy(record)}))
            finally:
                NETWORK_OBSERVER.reset(token)

    fetcher._site_policy, fetcher._request, fetcher._trace = policy, request, trace


def source_hashes():
    paths = [path for folder in (ROOT / "backend/app", ROOT / "frontend/dist")
             for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    paths.append(Path(__file__).resolve())
    return {path.relative_to(ROOT).as_posix(): sha(path.read_bytes()) for path in sorted(paths)}


def service_class(output: Path, registry=None, *, resume=False):
    registry = registry if registry is not None else {
        "output": str(output), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    class AuditedJobService(JobService):
        def __init__(self, *args, **kwargs):
            if resume:
                check_resume_database(output / "live.sqlite3")
            super().__init__(*args, **kwargs)
            self.audit_registry = registry
            instrument_fetcher(self.fetcher)

        async def _discover(self, query, request, original_point):
            audit_call("provider_query_started", append_event, "provider_query_started", {"provider": self.settings.search_provider,
                "knowledge_point": original_point, "query": query.query, "domain_filters": query.domain_filters})
            outcome, count = "exception", None
            try:
                items = await super()._discover(query, request, original_point)
                outcome, count = "returned", len(items)
                return items
            finally:
                audit_call("provider_query_finished", append_event, "provider_query_finished", {"provider": self.settings.search_provider,
                    "query": query.query, "outcome": outcome, "candidate_count": count,
                    "requests": getattr(self.provider, "last_requests", []),
                    "dns_requests": getattr(self.provider, "last_dns_requests", []),
                    "upstream_warnings": getattr(self.provider, "last_warnings", [])})

        async def run(self, job_id):
            if not re.fullmatch(r"[0-9a-f-]{36}", job_id):
                raise ValueError("Unexpected job ID")
            folder = output / "jobs" / job_id
            state = {"folder": folder, "output": output, "job_id": job_id, "sequence": 0,
                     "response_count": 0, "acceptance_valid": True, "audit_errors": []}
            token = CURRENT_JOB.set(state)
            registry_token = CURRENT_AUDIT.set(registry)
            try:
                audit_call("create_job_audit_folder", folder.mkdir, parents=True, exist_ok=False)
                audit_call("write_input", lambda: write_json(folder / "input.json", self.store.get_job(job_id)))
                audit_call("job_started", append_event, "job_started", {"job_id": job_id, "mode": "production_live_search",
                    "candidate_injection": False, "saved_page_replay": False})
                return await super().run(job_id)
            finally:
                def export_job():
                    job = self.store.get_job(job_id)
                    resources = self.store.resources(job_id)
                    write_json(folder / "job.json", job)
                    write_json(folder / "results.json", self.results(job_id))
                    write_json(folder / "resources-and-evidence.json", [
                        {"resource": resource, "evidence": self.store.evidence(job_id, rid)}
                        for rid, resource in resources.items()])
                    append_event("job_finished", {"job_id": job_id, "status": job["status"] if job else "unknown",
                        "observed_http_responses": state["response_count"], "resource_count": len(resources),
                        "catalog_entry_count": sum(len(row.get("chapters", [])) for row in resources.values())})
                try:
                    audit_call("export_job", export_job)
                    audit_call("write_audit_status", lambda: write_json(folder / "audit-status.json", {
                        "acceptance_valid": state["acceptance_valid"], "audit_errors": state["audit_errors"]}))
                    registry["jobs"][job_id] = {"acceptance_valid": state["acceptance_valid"],
                                                "audit_errors": list(state["audit_errors"])}
                finally:
                    CURRENT_AUDIT.reset(registry_token)
                    CURRENT_JOB.reset(token)
    return AuditedJobService


def check_resume_database(database: Path):
    """Read-only admission; never mark an active job interrupted to permit reuse."""
    if not database.is_file():
        raise ValueError("--resume requires this phase's existing live database")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        pending = connection.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    if pending:
        raise ValueError("Cannot resume while the database contains queued or running jobs")


def app_for(output: Path, *, offline_check=False, resume=False):
    output = output.resolve()
    if not offline_check and output != PHASE.resolve():
        raise ValueError("The live evidence folder is fixed")
    if not (PHASE / "baseline/manifest.json").is_file():
        raise ValueError("Freeze the preceding source/evidence baseline first")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise ValueError("Build the production frontend first")
    settings = replace(Settings.from_env(), database_path=str(output / "live.sqlite3"))
    # The configured provider remains the only primary provider. Never enable a
    # paid provider or model merely because a key happens to exist in the env.
    if settings.search_provider != "searxng":
        raise ValueError("This run expects the already configured SearXNG provider")
    output.mkdir(parents=True, exist_ok=True)
    if resume:
        check_resume_database(output / "live.sqlite3")
        if not (output / "startup.json").is_file():
            raise ValueError("--resume requires the preserved original startup.json")
    elif (output / "live.sqlite3").exists():
        raise ValueError("Refusing to reuse an existing live database; preserve this run and review explicitly")
    elif (output / "startup.json").exists():
        raise ValueError("Refusing to overwrite the original startup.json")
    public_settings = {key: value for key, value in asdict(settings).items()
                       if key not in {"tavily_api_key", "llm_api_key"}}
    startup = {"started_at": now(), "settings": public_settings,
        "baseline_manifest_sha256": sha((PHASE / "baseline/manifest.json").read_bytes()),
        "source_hashes": source_hashes(), "platform_policy_reviews": PLATFORM_POLICY_REVIEWS,
        "isolation": {"database_initially_absent": not (output / "live.sqlite3").exists(),
                      "only_setting_overridden": "database_path", "no_seed_data": True,
                      "no_prior_cache_import": True, "submissions": "real production UI/API only"}}
    registry = {"output": str(output), "acceptance_valid": True, "audit_errors": [], "jobs": {},
                "scope": "current process instrumentation; prior runs require their own artifact validation"}
    if resume:
        startup["resume"] = {"explicitly_requested": True, "no_queued_or_running_jobs": True,
            "original_startup_sha256": sha((output / "startup.json").read_bytes()),
            "prior_jobs_and_evidence_preserved": True}
    manifest_name = "resume-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json" if resume else "startup.json"
    registry_token = CURRENT_AUDIT.set(registry)
    try:
        write_json(output / manifest_name, startup, exclusive=True)
    finally:
        CURRENT_AUDIT.reset(registry_token)
    original_service = main_module.JobService
    main_module.JobService = service_class(output, registry, resume=resume)
    try:
        app = main_module.create_app(settings)
        # create_app looks up its module's JobService when lifespan starts.
        # Retain the audited class for this dedicated single-app process.
        app.state.live_chain_audit = startup
        app.state.live_chain_audit_registry = registry
        @app.get("/api/live-audit", include_in_schema=False)
        async def audit_status():
            return {key: registry[key] for key in ("acceptance_valid", "audit_errors", "jobs", "scope")}
    except BaseException:
        main_module.JobService = original_service
        raise
    return app


def self_check():
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory(prefix="platform-live-harness-check-") as directory:
        app = app_for(Path(directory), offline_check=True)
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200, health.text
            assert health.json()["job_counts"] == {}
            assert client.get("/").status_code == 200
            assert client.get("/api/capabilities").status_code == 200
            store = app.state.store
            assert store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
            assert not (Path(directory) / "jobs").exists()
            assert app.state.service.settings.database_path == str(Path(directory) / "live.sqlite3")
            # Policy instrumentation must preserve the production deny decisions.
            for url in ("https://www.bilibili.com/video/BV1VZ4y1G7YB/",
                        "https://www.icourse163.org/learn/PKU-1003479006"):
                try:
                    app.state.service.fetcher._site_policy(url)
                except FetchStopped:
                    pass
                else:
                    raise AssertionError("Expected existing platform gate to remain active")
    print(json.dumps({"offline_check": "passed", "network_search_submitted": False,
                      "production_core_modified": False, "live_database_created": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline startup/route checks in a temporary empty DB")
    parser.add_argument("--resume", action="store_true", help="Explicitly reuse this phase DB only when no jobs are active")
    args = parser.parse_args()
    if args.check:
        self_check()
    else:
        import uvicorn
        uvicorn.run(app_for(PHASE, resume=args.resume), host="127.0.0.1", port=18018, workers=1)
