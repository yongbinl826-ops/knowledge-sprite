"""Replay actual browser DOM through old/new extractors; no network or main DB writes."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import rank_resource
from backend.app.resource_identity import derive_course_identity

OUT = ROOT / "reports/platform-catalog-20261017"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    observations = json.loads((OUT / "browser/observations.json").read_text(encoding="utf-8"))
    independent = json.loads((OUT / "catalog-independent-check.json").read_text(encoding="utf-8"))
    baseline = OUT / "baseline-v7/code"
    archive = OUT / "baseline-v7/source.zip"
    manifest = json.loads((OUT / "baseline-v7/manifest.json").read_text(encoding="utf-8"))
    assert sha(archive) == manifest["archive_sha256"]
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not entry.filename.startswith("backend/") or entry.is_dir():
                continue
            target = (baseline / entry.filename).resolve()
            assert target.is_relative_to(baseline.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            content = z.read(entry)
            assert hashlib.sha256(content).hexdigest() == manifest["source_hashes"][entry.filename]
            target.write_bytes(content)

    records, ui_items = [], []
    point = {"knowledge_point_id": "actual-catalog-audit", "text": "列表与字典"}
    request = SearchRequest(knowledge_points=[point["text"]])
    for source in observations["records"]:
        platform = source["platform"]
        capture = OUT / source["dom_file"]
        content = capture.read_text(encoding="utf-8")
        inputs = [{"path": source["dom_file"], "sha256": sha(capture)}]
        if platform == "icourse163":
            term = OUT / "browser/mooc-term-dom.html"
            # Two separately captured visible fragments from the SAME course URL.
            content = content.replace("</body>", term.read_text(encoding="utf-8") + "</body>")
            inputs.append({"path": "browser/mooc-term-dom.html", "sha256": sha(term)})
        payload = {"html": content, "url": source["url"], "fetched_at": observations["captured_at"]}
        code = "import sys,json;sys.path.insert(0,sys.argv[1]);from backend.app.extractor import MetadataExtractor;p=json.load(sys.stdin);print(json.dumps(MetadataExtractor().extract(**p),ensure_ascii=False))"
        old = subprocess.run([sys.executable, "-c", code, str(baseline)],
                             input=json.dumps(payload, ensure_ascii=False), text=True, encoding="utf-8",
                             capture_output=True, check=True, cwd=baseline)
        previous = json.loads(old.stdout)
        extracted = MetadataExtractor().extract(**payload)
        expected = independent["platforms"][platform]["items"]
        assert len(previous["chapters"]) == 0
        assert len(extracted["chapters"]) == len(expected)
        for current, checked in zip(extracted["chapters"], expected):
            assert current["title"] == " ".join(checked["raw_text"].split()), (current, checked)
            assert current.get("duration_seconds") == checked["duration_seconds"]
            assert current["url"] is None and current["start_seconds"] is None and current["end_seconds"] is None
        dom_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        for evidence in extracted["evidence"]:
            evidence.update(acquisition="browser_observed_dom", source_sha256=dom_sha)
        for provenance in extracted["field_provenance"].values():
            provenance.update(acquisition="browser_observed_dom", source_sha256=dom_sha)
        resource = Resource(resource_id="observed-" + platform, url=source["url"], canonical_url=source["url"],
                            platform=platform, discovered_at=observations["captured_at"], **{
                                k: v for k, v in extracted.items() if k != "evidence"
                            }).model_dump()
        resource["course_identity"] = derive_course_identity(resource, extracted["evidence"])
        match = rank_resource(point, resource, extracted["evidence"], request)
        assert match is not None, platform
        contextual_point = {**point, "text": "Python 列表与字典"}
        contextual_match = rank_resource(contextual_point, resource, extracted["evidence"],
                                         SearchRequest(knowledge_points=[contextual_point["text"]]))
        if platform == "icourse163":
            assert resource["access_notice"] == "老师已关闭该学期，无法查看"
            assert resource["video_evidence_status"] == "none"
        assert resource["playback_verified"] is False
        ui_items.append({"resource": resource, "evidence": extracted["evidence"], "match": match})
        records.append({"platform": platform, "url": source["url"], "inputs": inputs,
                        "acquisition": "browser_observed_dom", "combined_dom_sha256": dom_sha,
                        "http_status": "unknown", "automatic_backend_fetch_verified": False,
                        "automatic_backend_fetch_status": "site_policy_blocked" if platform == "bilibili" else "policy_unreviewed",
                        "before_catalog_count": len(previous["chapters"]),
                        "after_catalog_count": len(extracted["chapters"]),
                        "contextual_match_check": {"point": contextual_point["text"], "matched": contextual_match is not None,
                            "note": "Existing topic rules do not borrow Python context across separately observed catalog rows. No threshold or ranking rule was changed for this audit."},
                        "matches_independent_audit": True, "metadata": extracted})
    output = {"scope": "Actual ordinary-browser page captures replayed through production MetadataExtractor. No network during replay; not a full automated discovery/fetch acceptance.",
              "point": point["text"], "records": records, "ui_items": ui_items}
    (OUT / "extraction-comparison.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": [{k: v for k, v in r.items() if k != "metadata"} for r in records]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
