"""One read-only localhost results GET after a conservative matching review.

Preserve the original run. Write separate post-review exports and prove that
the GET did not change the database, HTTP/model journals or original evidence.
This is not another search run and never invokes confirm/search/analyze APIs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.summarize_project_model_live import digest, read_json
from scripts.summarize_project_search_revision import referenced_evidence_ids, result_items


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def logical_snapshot(database: Path):
    tables, resources, evidence, owners = {}, {}, {}, {}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        schema = [(row[0], row[1]) for row in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name, sql in schema:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
                raise ValueError("Unexpected SQLite table name")
            cursor = conn.execute(f'SELECT * FROM "{name}"')
            rows = [list(row) for row in cursor]
            tables[name] = {"rows": len(rows), "sha256": digest({"schema": sql,
                "columns": [item[0] for item in cursor.description], "rows": sorted(rows, key=digest)})}
        for row in conn.execute("SELECT job_id,id,data FROM resources"):
            resources[row["job_id"], row["id"]] = json.loads(row["data"])
        for row in conn.execute("SELECT job_id,id,resource_id,knowledge_point_id,data FROM evidence"):
            key = row["job_id"], row["id"]
            evidence[key], owners[key] = json.loads(row["data"]), (row["resource_id"], row["knowledge_point_id"])
    return {"sha256": digest(tables), "tables": tables}, resources, evidence, owners


def evidence_file_hashes(directory: Path):
    # Exclude only this script's new outputs. Server stdout/access logs may grow
    # for a GET; they are not HTTP response or model journals.
    excluded = {"post-review-results.json", "post-review-checks.json"}
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".jsonl"} and path.name not in excluded}


def point_inventory(exported):
    output = {}
    for point in exported["points"]:
        group = point.get("result") or {}
        all_cards = {item["resource"]["resource_id"]: item for item in result_items(group)}
        defaults = {item["resource"]["resource_id"]: item for field in ("items", "partial_items", "review_items") for item in group.get(field, [])}
        output[point["project_knowledge_point_id"]] = {"name": point["name"], "job_id": point["job_id"],
            "knowledge_point_id": point["knowledge_point_id"],
            "supported_matches": group.get("total_matches", 0), "partial_matches": group.get("total_partial_matches", 0),
            "review_matches": group.get("total_review_matches", 0), "default_card_count": len(defaults),
            "displayed_supported_cards": len(group.get("items", [])), "displayed_partial_cards": len(group.get("partial_items", [])),
            "displayed_review_cards": len(group.get("review_items", [])), "all_cards": all_cards,
            "default_resource_ids": sorted(defaults)}
    return output


def visible_card_ledger(exported):
    """Describe each default card itself, never borrow point-level fetch counts."""
    rows = []
    for point in exported["points"]:
        group = point.get("result") or {}
        for field, placement in (("items", "supported"), ("partial_items", "partial"), ("review_items", "needs_review")):
            for item in group.get(field, []):
                resource = item["resource"]
                rows.append({"project_knowledge_point_id": point["project_knowledge_point_id"],
                    "point_name": point["name"], "job_id": point["job_id"],
                    "resource_id": resource["resource_id"], "title": resource["title"], "url": resource["url"],
                    "placement": placement, "topic_evidence_status": item["match"].get("topic_evidence_status"),
                    "fetch_status": resource["fetch_status"], "metadata_evidence_level": resource.get("metadata_evidence_level"),
                    "video_evidence_status": resource.get("video_evidence_status"),
                    "resource_type": resource.get("resource_type"), "fetched_at": resource.get("fetched_at"),
                    "cache": resource.get("cache"), "chapter_count": len(resource.get("chapters", [])),
                    "supporting_evidence_ids": item["match"].get("supporting_evidence_ids", []),
                    "evidence_kinds": sorted({entry.get("kind") for entry in item["evidence"] if entry.get("kind")}),
                    "playback_verified": resource.get("playback_verified", False),
                    "interpretation": "This displayed resource has freshly or previously fetched metadata; playback and complete teaching coverage are unverified."
                        if resource["fetch_status"] == "fetched" else "This displayed card has no successful fetched metadata in this run; other resources fetched for the same point do not verify this card."})
    return rows


def verify_review(original, reviewed, resources, evidence, owners):
    checks = {"project_id_unchanged": original["project_id"] == reviewed["project_id"],
        "current_version_unchanged": original["current_version"] == reviewed["current_version"],
        "original_input_unchanged": original["original_input"] == reviewed["original_input"],
        "input_unchanged": original["input"] == reviewed["input"]}
    for field in ("version", "input", "analysis", "confirmation", "batches", "budgets", "model", "prompt_version", "origin", "retained_analysis", "search_started_at", "cancel_requested"):
        checks[f"version_{field}_unchanged"] = original["version"].get(field) == reviewed["version"].get(field)
    before, after = point_inventory(original), point_inventory(reviewed)
    checks["same_project_point_ids"] = before.keys() == after.keys()
    differences, points, failures = [], [], []
    for point_id, new in after.items():
        old = before.get(point_id, {})
        checks[f"{point_id}/job_mapping_unchanged"] = (old.get("job_id"), old.get("knowledge_point_id")) == (new["job_id"], new["knowledge_point_id"])
        job_id, point_checks = new["job_id"], []
        for resource_id, item in new["all_cards"].items():
            resource_ids = {identifier for (owner_job, identifier), owner in owners.items() if owner_job == job_id and owner[0] == resource_id}
            point_ids = {identifier for (owner_job, identifier), owner in owners.items() if owner_job == job_id
                and owner[0] == resource_id and owner[1] in {None, new["knowledge_point_id"]}}
            linked = any(owner_job == job_id and owner == (resource_id, new["knowledge_point_id"])
                and evidence[owner_job, identifier].get("kind") == "search" for (owner_job, identifier), owner in owners.items())
            refs = referenced_evidence_ids(item["match"])
            row_checks = {
                "original_resource_fields_and_chapters": item["resource"] == resources.get((job_id, resource_id)),
                "same_point_source_observation_exists": linked,
                "match_identity": item["match"].get("resource_id") == resource_id and item["match"].get("knowledge_point_id") == new["knowledge_point_id"],
                "matched_refs_exist": refs.issubset(resource_ids),
                "support_refs_belong_to_point": set(item["match"].get("supporting_evidence_ids", [])).issubset(point_ids),
                "exported_evidence_unchanged": all(entry["evidence_id"] in resource_ids and evidence.get((job_id, entry["evidence_id"])) == entry for entry in item["evidence"]),
                "matched_refs_on_card": refs.issubset({entry["evidence_id"] for entry in item["evidence"]}),
            }
            point_checks.append(all(row_checks.values()))
            if not all(row_checks.values()):
                failures.append({"point_id": point_id, "resource_id": resource_id, "checks": row_checks})
        checks[f"{point_id}/only_original_source_resources_and_evidence"] = all(point_checks)
        old_cards, new_cards = old.get("all_cards", {}), new["all_cards"]
        changed = [{"resource_id": key, "title": new_cards[key]["resource"]["title"],
            "changed_match_fields": [field for field in set(old_cards[key]["match"]) | set(new_cards[key]["match"])
                if old_cards[key]["match"].get(field) != new_cards[key]["match"].get(field)],
            "before_match": old_cards[key]["match"], "after_match": new_cards[key]["match"]}
            for key in sorted(old_cards.keys() & new_cards.keys()) if old_cards[key]["match"] != new_cards[key]["match"]]
        changes = {"project_knowledge_point_id": point_id, "name": new["name"],
            "removed": [{"resource_id": key, "title": old_cards[key]["resource"]["title"], "match": old_cards[key]["match"]} for key in sorted(old_cards.keys() - new_cards.keys())],
            "added": [{"resource_id": key, "title": new_cards[key]["resource"]["title"], "match": new_cards[key]["match"]} for key in sorted(new_cards.keys() - old_cards.keys())],
            "changed": changed,
            "removed_default_cards": sorted(set(old.get("default_resource_ids", [])) - set(new["default_resource_ids"])),
            "added_default_cards": sorted(set(new["default_resource_ids"]) - set(old.get("default_resource_ids", [])))}
        differences.append(changes)
        points.append({"project_knowledge_point_id": point_id,
            "before": {key: value for key, value in old.items() if key != "all_cards"},
            "after": {key: value for key, value in new.items() if key != "all_cards"}})
    return checks, points, differences, failures


def review(directory: Path, base: str):
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Use an explicit http://127.0.0.1:<port> acceptance server only")
    original = read_json(directory / "project-results.json")
    project_id = str(UUID(original["project_id"]))
    version = original["version"]["version"]
    if type(version) is not int or version < 1:
        raise ValueError("Invalid original project version")
    result_path, check_path = directory / "post-review-results.json", directory / "post-review-checks.json"
    if result_path.exists() or check_path.exists():
        raise FileExistsError("Post-review evidence already exists; refusing to overwrite")
    files_before = evidence_file_hashes(directory)
    database = directory / "live/live.sqlite3"
    snapshot_before, resources, evidence, owners = logical_snapshot(database)
    endpoint = base.rstrip("/") + f"/api/projects/{project_id}/results?version={version}"
    started = datetime.now(timezone.utc).isoformat()
    # Exactly one GET. No retries, other endpoints, automatic confirmation or search.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(endpoint, method="GET", headers={"Accept": "application/json"}), timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Results GET did not return HTTP 200")
        reviewed = json.load(response)
    finished = datetime.now(timezone.utc).isoformat()
    snapshot_after, _, _, _ = logical_snapshot(database)
    files_after = evidence_file_hashes(directory)
    checks, points, differences, failures = verify_review(original, reviewed, resources, evidence, owners)
    checks.update(database_logical_snapshot_unchanged=snapshot_before == snapshot_after,
        original_exports_and_http_model_journals_unchanged=files_before == files_after)
    payload = {"kind": "post_review_matching_on_same_real_search_evidence", "started_at": started, "finished_at": finished,
        "request": {"method": "GET", "url": endpoint, "count": 1}, "new_search_performed": False, "new_model_call_performed": False,
        "checks_passed": all(checks.values()), "checks": checks, "failed_checks": [key for key, value in checks.items() if not value],
        "database_before": snapshot_before, "database_after": snapshot_after,
        "files_before_sha256": files_before, "files_after_sha256": files_after,
        "post_review_results_sha256": digest(reviewed), "points": points, "match_changes": differences,
        "source_reference_failures": failures,
        "limitations": ["This is one read-only recomputation of matches over the same search evidence, not another search or model analysis run.",
            "Original HTTP/model journals and the original result export are preserved. Matching changes are separately listed.",
            "Source consistency does not by itself establish pedagogical completeness or video playback."]}
    with result_path.open("x", encoding="utf-8") as stream:
        json.dump(reviewed, stream, ensure_ascii=False, indent=2)
    with check_path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/project-search-diagnosis-20261018/final-live")
    parser.add_argument("--base", default="http://127.0.0.1:18122")
    args = parser.parse_args()
    payload = review(args.output.resolve(), args.base)
    print(json.dumps({"checks_passed": payload["checks_passed"], "failed_checks": payload["failed_checks"],
        "points": [{"id": point["project_knowledge_point_id"], "supported": point["after"]["supported_matches"],
                    "partial": point["after"]["partial_matches"], "cards": point["after"]["default_card_count"]} for point in payload["points"]]}))
    return 0 if payload["checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
