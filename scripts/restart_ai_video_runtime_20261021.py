"""Inspect or restart only the two verified project APIs without changing config.

Run with the installed Nature runtime (psutil is already available there).
Default is read-only process/DB inspection. --restart requires explicit caller
coordination after code and build verification. Credentials stay in memory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "ai-video-fallback-repair-20261021" / "runtime"
KNOWN = {8001: (50304, 63440, "legacy"), 8017: (51368, 70832, "mobile")}
KNOWN_STUCK = {"e9b5ba93-e122-4815-8978-2a76a8e70bcb", "392391ee-bd5c-4903-89e3-1a35c2a88b19"}
REQUIRE_IDLE = False
RECEIPT_NAME = "restart"
BASELINE_IDENTITIES = {}
SAFE_KEYS = (
    "DATABASE_PATH", "APP_MODE", "CORS_ORIGINS", "LOCAL_ONLY",
    "MOBILE_PUBLIC_DATABASE_PATH", "MOBILE_ORIGINS", "OPEN_WEB_SEARCH_ENABLED",
    "PARALLEL_PLATFORM_SEARCH", "TEACHING_MATCH_ENABLED", "SHARED_COURSE_LIBRARY_ENABLED",
    "MOOC_GAP_SEARCH_ENABLED", "MOOC_REFRESH_ENABLED", "AI_VIDEO_FALLBACK_ENABLED",
    "MAX_SEARCH_REQUESTS", "MAX_DETAIL_PAGES", "BILIBILI_PUBLIC_METADATA",
    "BILIBILI_PUBLIC_METADATA_MAX_BYTES",
)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def request(port, path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.load(response)


def listeners(port):
    return [(item.laddr.ip, item.pid) for item in psutil.net_connections(kind="tcp")
            if item.status == psutil.CONN_LISTEN and item.laddr.port == port]


def database_path(env, mobile=False):
    path = Path(env.get("MOBILE_PUBLIC_DATABASE_PATH" if mobile else "DATABASE_PATH")
                or ("data/mobile-public.sqlite3" if mobile else "data/discovery.sqlite3"))
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(ROOT / "data") or not path.is_file():
        raise RuntimeError("Database is missing or outside the known project data directory")
    return path


def db_summary(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        result = {"path": str(path), "integrity": connection.execute("pragma quick_check").fetchone()[0]}
        for table in ("jobs", "resources", "evidence", "projects", "project_versions"):
            if table in tables:
                result[table + "_count"] = connection.execute(f"select count(*) from {table}").fetchone()[0]
        if "jobs" in tables:
            result["job_ids"] = [row[0] for row in connection.execute("select id from jobs order by id")]
            result["pending"] = [{"job_id": row[0], "status": row[1]} for row in connection.execute(
                "select id,status from jobs where status in ('queued','running') order by id")]
        return result


def identity(port):
    pid, parent_pid, mode = KNOWN[port]
    if listeners(port) != [("127.0.0.1", pid)]:
        raise RuntimeError(f"Unexpected listener identity on {port}")
    process, parent = psutil.Process(pid), psutil.Process(parent_pid)
    command = process.cmdline()
    expected = ["-m", "uvicorn", "backend.app.main:app", "--app-dir", str(ROOT),
                "--host", "127.0.0.1", "--port", str(port), "--workers", "1"]
    if not all(token in command for token in expected) or process.ppid() != parent_pid:
        raise RuntimeError(f"Unexpected command or parent on {port}")
    if Path(parent.exe()).resolve() != (ROOT / ".venv/Scripts/python.exe").resolve():
        raise RuntimeError(f"Unexpected executable on {port}")
    if Path(process.cwd()).resolve() != ROOT:
        raise RuntimeError(f"Unexpected working directory on {port}")
    environment = process.environ()
    if environment.get("APP_MODE") != mode:
        raise RuntimeError(f"Unexpected application mode on {port}")
    baseline = BASELINE_IDENTITIES.get(port)
    if baseline and (process.create_time() != baseline["created"]
            or parent.create_time() != baseline["parent_created"]
            or command != baseline["command"]
            or {key: environment.get(key) for key in SAFE_KEYS} != baseline["settings"]):
        raise RuntimeError(f"Fresh baseline identity or configuration changed on {port}")
    summary = db_summary(database_path(environment, mode == "mobile"))
    if baseline and summary["path"] != baseline["database"]["path"]:
        raise RuntimeError(f"Fresh baseline database path changed on {port}")
    pending = {row["job_id"] for row in summary.get("pending", [])}
    if not pending.issubset(KNOWN_STUCK):
        raise RuntimeError("A new job arrived; coordinate before restarting")
    health = request(port, "/health")
    if (port == 8017 or REQUIRE_IDLE) and any(health.get(key) != 0 for key in (
            "active_jobs", "queue_depth", "project_analysis_pending", "project_search_pending")):
        raise RuntimeError(f"Service {port} has active work")
    if health.get("project_analysis_pending") != 0:
        raise RuntimeError("Project analysis has started; coordinate before restarting")
    if port == 8001 and (health.get("project_search_pending") is None or health["project_search_pending"] > 2):
        raise RuntimeError("A new project search arrived; coordinate before restarting")
    public = {"port": port, "pid": pid, "parent_pid": parent_pid,
              "created": process.create_time(), "parent_created": parent.create_time(),
              "command": command, "cwd": str(ROOT), "parent_cwd": parent.cwd(),
              "settings": {key: environment.get(key) for key in SAFE_KEYS},
              "database": summary, "health": {key: health.get(key) for key in (
                  "status", "database_ok", "active_jobs", "queue_depth", "project_analysis_pending", "project_search_pending")}}
    return public, environment


def write_receipt(receipt):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (f"{RECEIPT_NAME}.json" if receipt.get("restart_requested") else f"{RECEIPT_NAME}-preflight.json")
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")


def source_hashes():
    result = {}
    for area in (ROOT / "backend/app", ROOT / "frontend/dist", ROOT / "frontend/dist-mobile-preview"):
        for path in sorted(area.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    global KNOWN, REQUIRE_IDLE, RECEIPT_NAME, BASELINE_IDENTITIES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--require-idle", action="store_true")
    parser.add_argument("--prior-receipt", type=Path)
    parser.add_argument("--baseline-inventory", type=Path,
                        help="Explicit fresh verified idle identity baseline after an external restart")
    parser.add_argument("--receipt-name", choices=("restart", "restart-2", "restart-3", "restart-4", "restart-5", "restart-6", "restart-7", "restart-8", "restart-9"), default="restart")
    args = parser.parse_args()
    REQUIRE_IDLE, RECEIPT_NAME = args.require_idle, args.receipt_name
    if args.prior_receipt and args.baseline_inventory:
        raise RuntimeError("Choose prior receipt or fresh baseline, never both")
    if args.prior_receipt:
        previous = json.loads(args.prior_receipt.read_text(encoding="utf-8"))
        if previous.get("status") != "passed" or {row["port"] for row in previous["started"]} != {8001, 8017}:
            raise RuntimeError("Prior successful restart receipt required")
        new_known = {}
        for row in previous["started"]:
            if len(row["listeners"]) != 1 or row["listeners"][0][0] != "127.0.0.1":
                raise RuntimeError("Prior receipt listener identity is invalid")
            port = row["port"]
            new_known[port] = (row["listeners"][0][1], row["launcher_pid"], "legacy" if port == 8001 else "mobile")
        KNOWN = new_known
    if args.baseline_inventory:
        baseline = json.loads(args.baseline_inventory.read_text(encoding="utf-8"))
        if (not REQUIRE_IDLE or baseline.get("status") != "verified_idle_baseline"
                or Path(baseline.get("workspace", "")).resolve() != ROOT
                or baseline.get("previous_service_identity_gone") is not True
                or baseline.get("same_configuration_and_datastores") is not True
                or {row["port"] for row in baseline.get("services", [])} != {8001, 8017}):
            raise RuntimeError("Explicit verified idle baseline required")
        BASELINE_IDENTITIES = {row["port"]: row for row in baseline["services"]}
        KNOWN = {port: (row["pid"], row["parent_pid"], "legacy" if port == 8001 else "mobile")
                 for port, row in BASELINE_IDENTITIES.items()}
    receipt = {"started_at": stamp(), "restart_requested": args.restart, "status": "preflight",
               "credentials_written": False, "configuration_changed": False,
               "stopped": [], "started": [], "before": []}
    if args.baseline_inventory:
        receipt["identity_baseline"] = {"path": str(args.baseline_inventory.resolve()),
            "kind": "fresh_inventory_after_external_restart", "provenance": baseline.get("provenance"),
            "not_continuity_of_prior_restart_receipt": True}
    environments = {}
    untouched = {port: listeners(port) for port in (8000, 8002, 8928)}
    try:
        for port in KNOWN:
            public, environments[port] = identity(port)
            receipt["before"].append(public)
        write_receipt(receipt)
        if not args.restart:
            print(json.dumps({"status": "ready_for_coordinated_restart", "receipt": str(OUT / f'{RECEIPT_NAME}-preflight.json'),
                              "ports": list(KNOWN), "pending_jobs_retained": [pending["job_id"]
                                  for row in receipt["before"] for pending in row["database"].get("pending", [])]}, ensure_ascii=False))
            return
        receipt["source_hashes_at_restart"] = source_hashes()
        receipt["video_repair_source_hashes"] = {name: hashlib.sha256((ROOT / "backend/app" / name).read_bytes()).hexdigest()
            for name in ("related_concepts.py", "related_recommendations.py", "ai_video_service.py", "ai_video_fallback.py",
                         "fetcher.py", "config.py", "service.py", "read_related_cache.py", "queries.py",
                         "video_availability.py", "source_adapters/bilibili.py")}
        # Fail before any stop if the existing virtual environment cannot import
        # the new application with the preserved per-service configuration.
        for port, environment in environments.items():
            with (OUT / f"{port}.import-check.log").open("wb") as output:
                check = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", "-B", "-c",
                    "import backend.app.main; print('application_import_ok')"], cwd=ROOT, env=environment,
                    stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            if check.returncode:
                raise RuntimeError(f"Application import failed for {port}; no service stopped")
        # All environments are already in memory. Recheck identities and jobs
        # immediately before a stop; no raw env or credentials are serialized.
        for port in KNOWN:
            identity(port)
        backup_root = Path(tempfile.mkdtemp(prefix="knowledge-sprite-ai-video-restart-20261021-"))
        receipt["backup_root"] = str(backup_root)
        for row in receipt["before"]:
            port = row["port"]
            source_path = Path(row["database"]["path"])
            backup_path = backup_root / source_path.name
            with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
                    if backup.execute("pragma quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("Database backup integrity check failed")
            row["backup"] = {"path": str(backup_path), "sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest()}
        receipt["status"] = "restarting"
        write_receipt(receipt)
        for row in receipt["before"]:
            port = row["port"]
            check, _ = identity(port)
            if check["created"] != row["created"] or check["parent_created"] != row["parent_created"]:
                raise RuntimeError("Verified process identity changed")
            for key, time_key in (("pid", "created"), ("parent_pid", "parent_created")):
                try:
                    process = psutil.Process(row[key])
                    if process.create_time() != row[time_key]:
                        raise RuntimeError("Process id was reused; no stop")
                    process.terminate()
                    process.wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass
            if listeners(port):
                raise RuntimeError("Port remained occupied; no duplicate start")
            # The old task may have saved more evidence between preflight and
            # shutdown. Compare recovery against the last committed DB state.
            row["database_at_stop"] = db_summary(Path(row["database"]["path"]))
            receipt["stopped"].append({"port": port, "pid": row["pid"], "at": stamp()})
            write_receipt(receipt)
            command = [str(ROOT / ".venv/Scripts/python.exe"), *row["command"][1:]]
            with (OUT / f"{port}.stdout.log").open("ab") as stdout, (OUT / f"{port}.stderr.log").open("ab") as stderr:
                child = subprocess.Popen(command, cwd=ROOT, env=environments[port], stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            receipt["started"].append({"port": port, "launcher_pid": child.pid, "at": stamp()})
            write_receipt(receipt)
            ready = False
            for _ in range(30):
                try:
                    if request(port, "/health/ready").get("status") == "ready":
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(0.3)
            if not ready:
                raise RuntimeError(f"Service {port} did not become ready; inspect its logs")
            health, capabilities = request(port, "/health"), request(port, "/api/capabilities")
            fallback = capabilities.get("ai_video_fallback")
            if (not fallback or fallback.get("enabled") is not True or fallback.get("model_configured") is not True
                    or fallback.get("policy_version") != "grounded-video-v2"
                    or fallback.get("retained_candidate_probes_per_point") != 3
                    or fallback.get("max_recovery_attempts_per_query") != 2
                    or fallback.get("max_recovery_queries_per_point") != 3
                    or fallback.get("max_page_link_hops") != 1
                    or fallback.get("max_page_link_probes_per_point") != 3
                    or fallback.get("exclude_known_paid_videos") is not True):
                raise RuntimeError(f"AI video feature missing on {port}")
            bilibili = next((item for item in capabilities.get("platforms", []) if item.get("id") == "bilibili"), {})
            if (bilibili.get("metadata") != "public_video_metadata_only"
                    or bilibili.get("metadata_max_bytes") != 8_000_000
                    or bilibili.get("metadata_max_state_chars") != 4_000_000):
                raise RuntimeError(f"Bilibili public metadata size policy missing on {port}")
            preserved_features = {
                "open_web": capabilities["platform_search"]["open_web_enabled"],
                "parallel": capabilities["platform_search"]["parallel"],
                "teaching": capabilities["teaching_match_enabled"],
                "library": capabilities["shared_course_library"]["enabled"],
                "gap": capabilities["mooc_gap_search"]["enabled"],
                "refresh": capabilities["mooc_gap_search"]["query_refresh_enabled"],
            }
            if not all(preserved_features.values()):
                raise RuntimeError(f"An existing feature changed on {port}")
            after_db = db_summary(Path(row["database"]["path"]))
            for key in ("job_ids", "resources_count", "evidence_count", "projects_count", "project_versions_count"):
                if key in row["database_at_stop"] and row["database_at_stop"][key] != after_db.get(key):
                    raise RuntimeError(f"Preserved database rows differ on {port}: {key}")
            receipt["started"][-1].update({"listeners": listeners(port), "health": health,
                "ai_video_fallback": fallback, "preserved_features": preserved_features, "database_after": after_db,
                "bilibili_metadata_policy": {key: bilibili[key] for key in (
                    "metadata", "metadata_max_bytes", "metadata_max_state_chars")},
                "preexisting_rows_preserved": True})
            write_receipt(receipt)
        if untouched != {port: listeners(port) for port in untouched}:
            raise RuntimeError("An unrelated listener changed independently")
        if receipt["source_hashes_at_restart"] != source_hashes():
            raise RuntimeError("Source or built assets changed during restart; verify final runtime snapshot")
        receipt.update(status="passed", finished_at=stamp(), untouched_ports=list(untouched))
        write_receipt(receipt)
        print(json.dumps({"status": "passed", "ports": list(KNOWN), "receipt": str(OUT / f'{RECEIPT_NAME}.json'),
                          "backup_root": str(backup_root)}, ensure_ascii=False))
    except Exception as error:
        receipt.update(status="failed", finished_at=stamp(), failure_type=type(error).__name__, failure=str(error))
        write_receipt(receipt)
        raise


if __name__ == "__main__":
    main()
