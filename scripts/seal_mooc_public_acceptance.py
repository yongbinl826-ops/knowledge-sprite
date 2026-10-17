"""Seal completed live evidence; only loopback API and local files are read."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT / "reports/mooc-public-read-20261017"
FINAL = PHASE / "revisions/outline-boundary-repair"
JOB = "f2930cbf-37cd-424e-8036-fb73631573f1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    destination = PHASE / "final-validation.json"
    if destination.exists():
        raise SystemExit("Refusing to replace sealed acceptance")
    for suffix, name in (("", "api-job-exact.json"), ("/results", "api-results-exact.json")):
        with urllib.request.urlopen(f"http://127.0.0.1:18021/api/search-jobs/{JOB}{suffix}", timeout=10) as response:
            raw = response.read()
        value = json.loads(raw)
        assert value["job_id"] == JOB
        assert value["status"] in {"completed", "partial", "failed", "cancelled"}
        with (FINAL / name).open("xb") as stream:
            stream.write(raw)
    baseline = json.loads((PHASE / "baseline.json").read_text("utf-8"))
    previous = ROOT / "reports/platform-live-chain-20261017"
    old_changes = [name for name, digest in baseline["previous_artifacts"].items()
                   if sha(previous / name) != digest]
    assert not old_changes, old_changes
    assert sha(previous / "final-validation.json") == baseline["previous_final_sha256"]
    assert sha(ROOT / ".env") == baseline["env_sha256"]
    startup = json.loads((FINAL / "startup.json").read_text("utf-8"))
    drift = [name for name, digest in startup["source_hashes"].items() if sha(ROOT / name) != digest]
    assert not drift, drift
    verification = json.loads((FINAL / "verification.json").read_text("utf-8"))
    assert verification["job_id"] == JOB
    assert verification["checks"]["all_course_response_hashes_match_fresh_saved_bytes"]
    assert verification["checks"]["all_chapter_evidence_bound"]
    assert verification["checks"]["all_stored_chapters_match_entire_raw_outline"]
    assert verification["checks"]["no_detail_cache_hits"]
    assert verification["checks"]["no_search_cache_hits"]
    ui = json.loads((FINAL / "ui-verification.json").read_text("utf-8"))
    assert ui["job_id"] == JOB and ui["all_checks_passed"]
    for folder in (PHASE, FINAL):
        output = folder / "completed-live.sqlite3"
        if output.exists():
            raise RuntimeError(f"Refusing to overwrite {output}")
        with closing(sqlite3.connect(f"file:{folder / 'live.sqlite3'}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(output)) as target:
                source.backup(target)
                assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    tests = {}
    all_cases = {}
    for filename in ("backend-tests-final.xml", "final-changed-tests.xml"):
        cases = list(ET.parse(PHASE / filename).getroot().iter("testcase"))
        failures = [case.attrib for case in cases if case.find("failure") is not None or case.find("error") is not None]
        assert not failures, failures
        tests[filename] = {"cases": len(cases), "failures": len(failures), "sha256": sha(PHASE / filename)}
        all_cases.update({(case.get("classname"), case.get("name")): True for case in cases})
    sources = set(startup["source_hashes"])
    sources.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "frontend/src").rglob("*") if path.is_file())
    sources.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_mooc*.py"))
    sources.update({"README.md", "scripts/seal_mooc_public_acceptance.py"})
    with zipfile.ZipFile(PHASE / "final-source.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(sources):
            archive.write(ROOT / name, name)
    excluded = {"live.sqlite3", "live.sqlite3-wal", "live.sqlite3-shm", "server.stdout.log", "server.stderr.log"}
    artifacts = {path.relative_to(PHASE).as_posix(): sha(path) for path in sorted(PHASE.rglob("*"))
                 if path.is_file() and path.name not in excluded and not path.name.endswith(("-wal", "-shm"))}
    write_new(destination, {
        "sealed_at": datetime.now(timezone.utc).isoformat(), "job_id": JOB,
        "live_url": f"http://127.0.0.1:18021/?job={JOB}",
        "acceptance": verification["acceptance"],
        "tests": tests, "distinct_test_cases_passed": len(all_cases),
        "source_hashes_match_final_startup": True,
        "final_source_hashes": {name: sha(ROOT / name) for name in sorted(sources)},
        "env_unchanged": True, "env_sha256": baseline["env_sha256"],
        "previous_phase_artifacts_unchanged": len(baseline["previous_artifacts"]),
        "previous_final_sha256": baseline["previous_final_sha256"],
        "artifacts": artifacts,
        "not_sealed": sorted(excluded),
        "evidence_boundary": "Final live job uses final startup source. First job retains its own startup hashes and known 100/122 failure. Saved HTML is evidence, not input to either live job."
    })
    print(json.dumps({"sealed": str(destination), "artifacts": len(artifacts), "distinct_tests": len(all_cases)}))


if __name__ == "__main__":
    main()
