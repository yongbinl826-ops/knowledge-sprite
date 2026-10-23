"""Explicit live acceptance against a restarted local service; no mocked sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def coverage(result):
    output = []
    groups = result.get("groups")
    if groups is None:
        groups = [row.get("result") or {"text": row.get("name"), "knowledge_point_id": row.get("project_knowledge_point_id")}
                  for row in result.get("points", []) if row.get("selection") == "learn"]
    for group in groups:
        rows = [*group.get("items", []), *group.get("partial_items", []),
                *group.get("related_recommendations", [])]
        resources = {}
        for row in rows:
            reference = row.get("reference")
            if reference:
                if group.get("technology") and reference.get("technical_context") not in {"observed", "parent_course"}:
                    continue
                supporting = set(reference.get("evidence_ids", []))
                if (not set(reference.get("basis", [])) & {"page", "catalog"}
                        or not any(item.get("evidence_id") in supporting
                                   and item.get("kind") in {"page", "catalog"}
                                   and not item.get("cache", {}).get("stale")
                                   for item in row.get("evidence", []))):
                    continue
            resource = row.get("resource", {})
            if (resource.get("fetch_status") in {"fetched", "success"}
                    and resource.get("video_evidence_status") == "page_verified"
                    and resource.get("requires_payment") is not True
                    and not resource.get("cache", {}).get("stale")):
                resources[resource["resource_id"]] = {key: resource.get(key) for key in
                    ("url", "title", "thumbnail_url", "fetch_status", "video_evidence_status",
                     "playback_verified", "resource_id")}
        output.append({"point": group.get("text") or group.get("name"),
                       "knowledge_point_id": group.get("knowledge_point_id"),
                       "verified_videos": list(resources.values())})
    return output


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    with httpx.Client(base_url=args.base, timeout=45, trust_env=False) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()
        def post(path, body, **kwargs):
            response = client.post(path, json=body, **kwargs)
            response.raise_for_status()
            return response.json()

        capabilities = get("/api/capabilities")
        assert capabilities["ai_video_fallback"]["policy_version"] == "grounded-video-v2"
        save(args.output / "capabilities.json", capabilities)
        if args.project:
            original = get(f"/api/projects/{args.project}")
            save(args.output / "project-before.json", original)
            prior = original["version"]
            if args.source_version is not None:
                source = get(f"/api/projects/{args.project}?version={args.source_version}")
                save(args.output / "project-source.json", source)
                prior = source["version"]
                if prior["input"] != original["version"]["input"]:
                    raise ValueError("Historical analysis does not match the current project input")
            if not prior.get("analysis"):
                raise ValueError("Choose an existing reviewed analysis with --source-version")
            if args.clone_project:
                # Keep concurrent edits/failed analyses on the source project intact.
                cloned_input = dict(prior["input"], name=prior["input"]["name"] + "（视频补链验收）")
                clone = post("/api/projects", cloned_input)
                args.project = clone["project_id"]
                original = post(f"/api/projects/{args.project}/analyze", {"expected_version": clone["current_version"]})
                analysis_started = time.monotonic()
                while original["version"]["status"] == "analyzing":
                    if time.monotonic() - analysis_started > 180:
                        raise TimeoutError("Clone analysis exceeded 180 seconds; task retained")
                    time.sleep(5)
                    original = get(f"/api/projects/{args.project}")
                save(args.output / "clone-analysis.json", original)
                if not original["version"].get("analysis"):
                    raise ValueError("Clone analysis did not complete successfully")
            current = post(f"/api/projects/{args.project}/edit", {
                "expected_version": original["current_version"], "input": prior["input"],
                "analysis": prior["analysis"]})
            version = current["current_version"]
            assert current["version"]["analysis"] == prior["analysis"]
            points = prior["analysis"]["knowledge_points"]
            selected = [p for p in points if p["selection"] == "learn"]
            prior_confirmation = prior.get("confirmation") or {}
            confirm = {"version": version, "acknowledged_skipped_prerequisites":
                       prior_confirmation.get("acknowledged_skipped_prerequisites", [])}
            technologies = prior_confirmation.get("topic_technologies")
            if technologies:
                confirm["reviewed_topic_technologies"] = technologies
            post(f"/api/projects/{args.project}/confirm", confirm)
            created = post(f"/api/projects/{args.project}/search", {"version": version})
            result_path = f"/api/projects/{args.project}/results?version={version}"
            job_path = None
            expected_count = len(selected)
        else:
            request = {"knowledge_points": ["Python 列表", "pandas 分组聚合", "pygame 矩形碰撞检测"],
                       "preferred_platforms": ["bilibili"], "student_level": "beginner"}
            created = post("/api/search-jobs", request,
                           headers={"Idempotency-Key": "grounded-live-" + uuid4().hex})
            job_path = f"/api/search-jobs/{created['job_id']}"
            result_path = job_path + "/results"
            expected_count = 3
        save(args.output / "created.json", created)
        print(json.dumps({"started": result_path, "expected_points": expected_count}, ensure_ascii=False), flush=True)
        start = time.monotonic()
        observations = []
        while True:
            result = get(result_path)
            status = (result.get("version") or {}).get("status") if args.project else result.get("status")
            job = get(job_path) if job_path else None
            if job:
                status = job["status"]
            groups = coverage(result)
            observation = {"seconds": round(time.monotonic() - start), "status": status,
                           "verified_points": sum(bool(g["verified_videos"]) for g in groups),
                           "total_points": len(groups),
                           "fallback": job.get("ai_video_fallback") if job else None}
            observations.append(observation)
            print(json.dumps(observation, ensure_ascii=False), flush=True)
            save(args.output / "results.json", result)
            save(args.output / "observations.json", observations)
            if job:
                save(args.output / "job.json", job)
            if status in {"completed", "partial", "failed", "interrupted", "cancelled", "no_results", "budget_exceeded"}:
                if not job or not job.get("platform_search", {}).get("followup_pending"):
                    break
            if time.monotonic() - start > 900:
                raise TimeoutError("Live acceptance exceeded 900 seconds; live task retained")
            time.sleep(15)
        if args.project:
            for batch in (result.get("version") or {}).get("batches", []):
                if batch.get("job_id"):
                    save(args.output / f"job-{batch['job_id']}.json", get(f"/api/search-jobs/{batch['job_id']}"))
        report = {"base_url": args.base, "result_path": result_path,
                  "scope": "live API, configured search/model, real source-page fetches; no fixtures or URL injection",
                  "expected_points": expected_count, "covered_points": sum(bool(g["verified_videos"]) for g in groups),
                  "status": status, "groups": groups, "playback_verified_by_this_script": False}
        save(args.output / "report.json", report)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project")
    parser.add_argument("--source-version", type=int)
    parser.add_argument("--clone-project", action="store_true")
    main(parser.parse_args())
