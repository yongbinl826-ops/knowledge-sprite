"""Read-only audit of the preserved held-out run; no HTTP or database writes."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.ranking import has_course_page
from scripts.live_acceptance_revision import audit_resource_evidence, same_resource_url

FOLDER = ROOT / "reports/completion-20261013"


def main():
    output = FOLDER / "held-out-audit.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite audit")
    report = json.loads((FOLDER / "held-out-live.json").read_text(encoding="utf-8"))
    resources, rows, groups = {}, [], []
    for job in report["jobs"]:
        for group in job.get("results", {}).get("groups", []):
            groups.append({"job_id": job["job_id"], "point": group["text"], "total_matches": group["total_matches"],
                           "default_displayed": len(group["items"]),
                           "platform_displayed": {key: len(items) for key, items in group["platform_items"].items()}})
            for item in [*group["items"], *(i for items in group["platform_items"].values() for i in items)]:
                resource, evidence = item["resource"], item["evidence"]
                audit = audit_resource_evidence(item)
                course_page = has_course_page(resource, evidence)
                discovered = any(e.get("kind") == "search" and same_resource_url(e.get("url"), resource["url"]) for e in evidence)
                match_ids = set(item["match"]["matched_evidence_ids"])
                own_ids = {e["evidence_id"] for e in evidence}
                row = {"job_id": job["job_id"], "knowledge_point": group["text"], "resource_id": resource["resource_id"],
                       "url": resource["url"], **audit, "page_course_without_video_claim": course_page,
                       "source_discovery_bound": discovered, "matched_evidence_ids_exist": bool(match_ids) and match_ids <= own_ids,
                       "all_catalog_rows_bound": audit["verified_chapter_count"] == len(resource.get("chapters", [])),
                       "learning_evidence_supported": bool(audit["search_discovered"] or audit["page_verified"] or audit["course_search_candidate"] or course_page)}
                rows.append(row)
                resources[resource["resource_id"]] = resource
    # De-duplicate repeats caused by platform views, not distinct point mappings.
    rows = list({(row["job_id"], row["knowledge_point"], row["resource_id"]): row for row in rows}.values())
    checks = {key: all(row[key] for row in rows) for key in (
        "source_discovery_bound", "matched_evidence_ids_exist", "all_catalog_rows_bound", "learning_evidence_supported", "has_type_provenance")}
    checks["no_unsupported_playback_claims"] = all(not row["playback_claimed"] or row["playback_verified"] for row in rows)
    checks["has_displayed_results"] = bool(rows)
    checks["source_unchanged_during_run"] = report["source_unchanged_during_run"]
    value = {"observed_at": datetime.now(timezone.utc).isoformat(), "mode": "read_only_preserved_evidence_audit",
             "checks": checks, "groups": groups, "resource_point_rows": rows,
             "unique_resource_fetch_status": dict(Counter(r["fetch_status"] for r in resources.values())),
             "catalog_rows": sum(len(r.get("chapters", [])) for r in resources.values()),
             "source_family_ids": sorted({r["course_identity"]["family_id"] for r in resources.values() if r["course_identity"]["family_id"]}),
             "boundary": "Stored evidence consistency only; no new page access, semantic completeness or playback validation"}
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": checks, "groups": groups}, ensure_ascii=False))


if __name__ == "__main__":
    main()
