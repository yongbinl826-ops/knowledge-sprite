"""One idle, identity-checked 8001 restart, preserving its in-memory environment."""
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import restart_ai_video_runtime_20261021 as runtime

OUT = Path(__file__).resolve().parent / "runtime-final"
OUT.mkdir(exist_ok=True)
record = OUT / "restart.json"
if record.exists():
    raise RuntimeError("Restart already recorded; inspect the receipt before any further action")
prior = json.loads((ROOT / "evidence/ai-video-fallback-repair-20261021/runtime/restart-4.json").read_text(encoding="utf-8"))
old = next(row for row in prior["started"] if row["port"] == 8001)
runtime.KNOWN = {8001: (old["listeners"][0][1], old["launcher_pid"], "legacy")}
runtime.REQUIRE_IDLE = True
runtime.KNOWN_STUCK = set()
health = runtime.request(8001, "/health")
keys = ("active_jobs", "queue_depth", "project_analysis_pending", "project_search_pending")
if any(health.get(key) != 0 for key in keys):
    print(json.dumps({"status": "waiting_for_existing_work", **{key: health.get(key) for key in keys}}))
    sys.exit(0)
public, environment = runtime.identity(8001)
unrelated = {port: runtime.listeners(port) for port in (8000, 8002, 8017, 8928)}
sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
           for path in (ROOT / "backend/app").rglob("*.py")}
with (OUT / "import-check.log").open("wb") as output:
    check = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", "-B", "-c",
        "import backend.app.main; print('application_import_ok')"], cwd=ROOT, env=environment,
        stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW)
if check.returncode:
    raise RuntimeError("Import failed; service was not stopped")
source_path = Path(public["database"]["path"])
backup_path = OUT / "discovery-before-restart.sqlite3"
with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
        assert backup.execute("pragma quick_check").fetchone()[0] == "ok"
receipt = {"status": "prepared", "before": public, "started_at": runtime.stamp(),
           "configuration_changed": False, "credentials_written": False,
           "source_hashes": sources, "backup": str(backup_path),
           "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest()}
def save():
    record.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
again, _ = runtime.identity(8001)
assert (again["created"], again["parent_created"]) == (public["created"], public["parent_created"])
save()
for key, created in (("pid", "created"), ("parent_pid", "parent_created")):
    try:
        process = runtime.psutil.Process(public[key])
        assert process.create_time() == public[created]
        process.terminate()
        process.wait(timeout=10)
    except runtime.psutil.NoSuchProcess:
        pass
assert not runtime.listeners(8001)
receipt["status"] = "stopped"
save()
with (OUT / "stdout.log").open("wb") as stdout, (OUT / "stderr.log").open("wb") as stderr:
    child = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), *public["command"][1:]],
        cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        creationflags=subprocess.CREATE_NO_WINDOW)
receipt["launcher_pid"] = child.pid
save()
for _ in range(40):
    try:
        if runtime.request(8001, "/health/ready").get("status") == "ready":
            break
    except Exception:
        pass
    time.sleep(.3)
else:
    raise RuntimeError("Backend did not become ready; inspect logs")
receipt["health"] = runtime.request(8001, "/health")
receipt["project_analysis"] = runtime.request(8001, "/api/capabilities")["project_analysis"]
receipt["listeners"] = runtime.listeners(8001)
after_db = runtime.db_summary(source_path)
assert receipt["project_analysis"]["prompt_version"] == "project-analysis-v5.5-auditable-concept-validation"
assert unrelated == {port: runtime.listeners(port) for port in unrelated}
assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in sources.items())
for key in ("job_ids", "resources_count", "evidence_count", "projects_count", "project_versions_count"):
    assert public["database"].get(key) == after_db.get(key), key
receipt.update(status="passed", finished_at=runtime.stamp(), unrelated_ports_unchanged=True,
               database_after=after_db, previous_rows_preserved=True)
save()
print(json.dumps({"status": "passed", "port": 8001, "receipt": str(record)}, ensure_ascii=False))
