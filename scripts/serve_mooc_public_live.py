"""Run the real public-course search chain with fresh, isolated live evidence.

This runner does not submit searches, seed candidates, load archived HTML, or
change permissions, provider settings, request budgets or extraction behavior.
Only SQLite storage is isolated. Submit the production UI on port 18019;
repair revisions use independent ports to preserve prior servers and evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.fetcher import NETWORK_OBSERVER, PLATFORM_POLICY_REVIEWS
import backend.app.main as main_module
from scripts import serve_platform_live_chain as audit

PHASE = ROOT / "reports/mooc-public-read-20261017"
REVISION = "outline-length-repair"
REVISION_PORTS = {REVISION: 18020, "outline-boundary-repair": 18021}


def evidence_folder(revision=None):
    if revision is not None and revision not in REVISION_PORTS:
        raise ValueError("Unknown live evidence revision")
    return PHASE / "revisions" / revision if revision else PHASE


def capture_public_mooc_response(result, kind):
    """Save only a fresh anonymous public course HTML response, as received.

The production PinnedHTTPClient makes anonymous GETs without a cookie jar or
Authorization header. This hook sees those bounded transport bytes, never a
browser session. Request/response headers and API payloads are not archived.
"""
    state = audit.CURRENT_JOB.get()
    if state is None or kind != "page" or result.status_code != 200:
        return
    parts = urlsplit(result.url)
    if (parts.scheme not in {"http", "https"}
            or parts.hostname not in {"icourse163.org", "www.icourse163.org"}
            or parts.username or parts.password or parts.port not in {None, 80, 443}
            or not re.fullmatch(r"/course/[A-Za-z0-9_-]+/?", parts.path)
            or result.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html"):
        return
    digest = audit.sha(result.body)
    folder = state["folder"] / "public-course-responses"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"response-{state['response_count']:04d}-{digest[:16]}.html"
    destination = folder / filename
    with destination.open("xb") as stream:
        stream.write(result.body)
    audit.append_event("public_course_response_saved", {
        "url": audit.public_url(result.url), "url_sha256": audit.sha(result.url.encode()),
        "response_index": state["response_count"], "http_status": result.status_code,
        "body_bytes": len(result.body), "body_sha256": digest,
        "file": destination.relative_to(state["folder"]).as_posix(),
        "body_representation": "exact anonymous production transport response bytes",
        "saved_headers": False, "saved_cookies": False, "saved_api_payload": False,
        "replayed_into_extractor": False,
    })


def service_class(output: Path, registry, *, resume=False):
    base = audit.service_class(output, registry, resume=resume)

    class PublicMoocAuditedService(base):
        async def run(self, job_id):
            parent = NETWORK_OBSERVER.get() or {}

            def response(result, kind):
                audit.audit_call("save_public_mooc_response", capture_public_mooc_response, result, kind)
                if parent.get("response"):
                    parent["response"](result, kind)

            token = NETWORK_OBSERVER.set({**parent, "response": response})
            try:
                return await super().run(job_id)
            finally:
                NETWORK_OBSERVER.reset(token)

    return PublicMoocAuditedService


def source_hashes():
    paths = [path for folder in (ROOT / "backend/app", ROOT / "frontend/dist")
             for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    paths.extend((Path(__file__).resolve(), Path(audit.__file__).resolve()))
    return {path.relative_to(ROOT).as_posix(): audit.sha(path.read_bytes()) for path in sorted(set(paths))}


def app_for(output: Path, *, offline_check=False, resume=False, revision=None):
    output = output.resolve()
    expected_output = evidence_folder(revision).resolve()
    if not offline_check and output != expected_output:
        raise ValueError("The live evidence folder is fixed")
    baseline = PHASE / "baseline.json"
    if not baseline.is_file():
        raise ValueError("Freeze this phase's preceding source/evidence baseline first")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise ValueError("Build the production frontend first")
    configured = Settings.from_env()
    settings = replace(configured, database_path=str(output / "live.sqlite3"))
    output.mkdir(parents=True, exist_ok=True)
    if resume:
        audit.check_resume_database(output / "live.sqlite3")
        if not (output / "startup.json").is_file():
            raise ValueError("--resume requires the preserved original startup.json")
    elif (output / "live.sqlite3").exists():
        raise ValueError("Refusing to reuse an existing live database; preserve this run and review explicitly")
    elif (output / "startup.json").exists():
        raise ValueError("Refusing to overwrite the original startup.json")
    public_settings = {key: value for key, value in asdict(settings).items()
                       if key not in {"tavily_api_key", "llm_api_key"}}
    startup = {
        "started_at": audit.now(), "settings": public_settings,
        "baseline_manifest_sha256": audit.sha(baseline.read_bytes()),
        "source_hashes": source_hashes(), "platform_policy_reviews": PLATFORM_POLICY_REVIEWS,
        "isolation": {"database_initially_absent": not (output / "live.sqlite3").exists(),
            "only_setting_overridden": "database_path", "no_seed_data": True,
            "no_prior_cache_import": True, "submissions": "real production UI/API only"},
        "raw_response_evidence": {"scope": "anonymous MOOC public /course HTML responses only",
            "saved_headers": False, "saved_cookies": False, "saved_api_payload": False,
            "replayed_into_extractor": False},
    }
    if revision:
        startup["revision"] = {"name": revision, "parent_phase": PHASE.name,
            "reason": "Diagnosed public outline truncation at 100 entries",
            "fresh_database_required_unless_explicit_resume": True,
            "parent_database_or_cache_imported": False}
    registry = {"output": str(output), "acceptance_valid": True, "audit_errors": [], "jobs": {},
                "scope": "current process instrumentation; prior runs require their own artifact validation"}
    if resume:
        startup["resume"] = {"explicitly_requested": True, "no_queued_or_running_jobs": True,
            "original_startup_sha256": audit.sha((output / "startup.json").read_bytes()),
            "prior_jobs_and_evidence_preserved": True}
    manifest_name = "resume-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json" if resume else "startup.json"
    registry_token = audit.CURRENT_AUDIT.set(registry)
    try:
        audit.write_json(output / manifest_name, startup, exclusive=True)
    finally:
        audit.CURRENT_AUDIT.reset(registry_token)
    original_service = main_module.JobService
    main_module.JobService = service_class(output, registry, resume=resume)
    try:
        app = main_module.create_app(settings)
        app.state.live_chain_audit = startup
        app.state.live_chain_audit_registry = registry

        @app.get("/api/live-audit", include_in_schema=False)
        async def audit_status():
            return {key: registry[key] for key in ("acceptance_valid", "audit_errors", "jobs", "scope")}
    except BaseException:
        main_module.JobService = original_service
        raise
    return app


def self_check(revision=None):
    """Exercise production startup/routes with no job or network submission."""
    from fastapi.testclient import TestClient
    original_service = main_module.JobService
    try:
        with tempfile.TemporaryDirectory(prefix="mooc-public-live-check-") as directory:
            app = app_for(Path(directory), offline_check=True, revision=revision)
            with TestClient(app) as client:
                health = client.get("/health")
                assert health.status_code == 200, health.text
                assert health.json()["job_counts"] == {}
                assert client.get("/").status_code == 200
                assert client.get("/api/capabilities").status_code == 200
                assert client.get("/api/live-audit").json()["acceptance_valid"] is True
                assert app.state.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
                assert not (Path(directory) / "jobs").exists()
                expected = replace(Settings.from_env(), database_path=str(Path(directory) / "live.sqlite3"))
                assert app.state.service.settings == expected
    finally:
        main_module.JobService = original_service
    print('{"offline_check":"passed","network_search_submitted":false,"live_database_created":false}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline startup checks with an empty temporary DB")
    parser.add_argument("--resume", action="store_true", help="Explicitly reuse this phase DB only when no jobs are active")
    parser.add_argument("--revision", choices=list(REVISION_PORTS), help="Use the named repair revision's independent empty database")
    args = parser.parse_args()
    if args.check:
        self_check(revision=args.revision)
    else:
        import uvicorn
        uvicorn.run(app_for(evidence_folder(args.revision), resume=args.resume, revision=args.revision),
                    host="127.0.0.1", port=REVISION_PORTS.get(args.revision, 18019), workers=1)
