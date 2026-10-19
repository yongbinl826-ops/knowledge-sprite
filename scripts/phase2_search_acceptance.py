"""Bounded real search acceptance for independently approved existing projects.

Default: offline plan, zero HTTP. --live confirms/searches each selected project
at most once; checkpoints precede POSTs. Existing run.json requires
--observe-only, which never POSTs. No analysis, direct platform/media request,
seeded candidate, mock source, budget override or playback claim exists in live.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.url_utils import UnsafeURL, normalize_url

EXPECTED_PROMPT = "project-analysis-v2.6-bounded-semantic-review"
TERMINAL = {"completed", "partial", "no_results", "failed", "cancelled", "interrupted", "analysis_failed"}
MAX_RESPONSE_BYTES = 24_000_000
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def local_url(value):
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username is not None or parts.password is not None or parts.path not in {"", "/"}
            or parts.query or parts.fragment or parts.port == 0):
        raise ValueError("Only an explicitly selected loopback API origin is allowed.")
    return value.rstrip("/")


def safe_identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid evidence/project/job identifier.")
    return value


def output_path(value):
    path = Path(value).resolve()
    if path.parent != ROOT / "evidence" or not path.name.startswith("phase2-search-"):
        raise ValueError("Output must be one workspace evidence/phase2-search-* directory.")
    return path


def workspace_file(value):
    path = Path(value).resolve()
    if (not (path.is_relative_to(ROOT / "evidence") or path.is_relative_to(ROOT / "tmp"))
            or path.suffix != ".json" or not path.is_file()):
        raise ValueError("Required evidence file is absent or outside the workspace: " + str(path))
    return path


def safe_error(exc):
    return {"error_type": type(exc).__name__,
            "reason": str(exc)[:400] if type(exc) is ValueError else "Local evidence or API read failed; no automatic POST retry."}


def make_plan(source_path, manual_path, selected, expected_prompt):
    source_path, manual_path = workspace_file(source_path), workspace_file(manual_path)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    records = source.get("records", [])
    reviews = {row["case_id"]: row for row in manual.get("case_reviews", [])}
    if len(reviews) != len(manual.get("case_reviews", [])):
        raise ValueError("Duplicate manual case IDs.")
    known = {row["case_id"]: row for row in records}
    if len(known) != len(records) or len(records) > 4 or (selected and not set(selected) <= known.keys()):
        raise ValueError("Select at most four distinct cases that exist in the source run.")
    chosen, excluded = [], []
    for case_id, row in known.items():
        if selected and case_id not in selected:
            continue
        review = reviews.get(case_id, {})
        view = row.get("persisted_view") or {}
        version = view.get("version") or {}
        analysis = version.get("analysis") or {}
        units, functions = analysis.get("knowledge_points", []), analysis.get("functions", [])
        unit_ids, function_ids = {u["id"] for u in units}, {f["id"] for f in functions}
        requirements, unit_reviews = review.get("requirements", []), review.get("unit_reviews", [])
        approved = bool(row.get("status") == "analyzed" and analysis and requirements
            and review.get("project_id") == row.get("project_id") and review.get("version") == version.get("version")
            and row.get("version") == version.get("version") == view.get("current_version")
            and version.get("input") == row.get("input") == view.get("original_input") == view.get("input")
            and version.get("prompt_version") == review.get("prompt_version") == expected_prompt
            and review.get("analysis_sha256") == data_sha(analysis)
            and all(r.get("passed") is True and r.get("unit_ids") and set(r["unit_ids"]) <= unit_ids
                    and set(r.get("function_ids", [])) <= function_ids for r in requirements)
            and len(unit_reviews) == len(units) and {u.get("id") for u in unit_reviews} == unit_ids
            and all(u.get("project_relevant") is True and u.get("appropriate_granularity") is True for u in unit_reviews)
            and all(review.get(key, {}).get("passed") is True for key in ("background", "prerequisites", "technical_correctness"))
            and not review.get("known_high_or_medium_issues"))
        if not approved:
            excluded.append(case_id)
            continue
        safe_identifier(case_id)
        safe_identifier(row["project_id"])
        chosen.append({"case_id": case_id, "project_id": row["project_id"], "version": version["version"],
            "input": row["input"], "prompt_version": expected_prompt, "analysis_sha256": data_sha(analysis),
            "manual_review_sha256": data_sha(review), "status": "not_submitted", "confirm_attempted": False,
            "search_attempted": False, "first_useful_seconds_upper_bound": None,
            "first_page_verified_useful_seconds_upper_bound": None, "first_full_collection_seconds_upper_bound": None})
    if excluded or not chosen or len({r["project_id"] for r in chosen}) != len(chosen):
        raise ValueError("Selected cases lack a complete, hash/version-bound independent manual pass: " + ",".join(excluded))
    return {"mode": "offline_plan", "created_at": now(), "source_run": str(source_path), "source_run_sha256": sha(source_path),
        "manual_review": str(manual_path), "manual_review_sha256": sha(manual_path), "expected_prompt": expected_prompt,
        "records": chosen, "excluded_unapproved_cases": excluded, "max_search_submissions": len(chosen),
        "limits": {"max_search_requests_per_batch": 30, "max_detail_pages_per_batch": 40, "global_concurrency": 1,
                   "per_batch_deadline_seconds": 240, "max_observation_seconds_per_project": 1100},
        "analysis_submissions": 0, "direct_platform_requests": 0, "playback_verified_by_runner": False}


def runtime_binding(path, base, expected_pid):
    path = workspace_file(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("pid") != expected_pid or Path(manifest.get("root", "")).resolve() != ROOT
            or manifest.get("port") != (urlsplit(base).port or (443 if base.startswith("https:") else 80))):
        raise ValueError("The runtime manifest does not match the explicitly confirmed PID, workspace and port.")
    files, frontend_snapshot = {}, {}
    for name, expected in manifest.get("files", {}).items():
        relative = name.replace("\\", "/")
        candidate = (ROOT / relative).resolve()
        source_file = candidate.is_relative_to(ROOT / "backend/app") and candidate.suffix == ".py"
        build_file = candidate.is_relative_to(ROOT / "frontend/dist") and not candidate.name.startswith(".")
        if build_file:
            frontend_snapshot[relative] = {"loaded_snapshot_sha256": expected,
                "current_sha256": sha(candidate) if candidate.is_file() else None,
                "browser_acceptance_required_separately": True}
            continue
        if not source_file or not candidate.is_file() or sha(candidate) != expected:
            raise ValueError("Runtime snapshot differs from current file: " + relative)
        files[relative] = expected
    required = {"backend/app/service.py", "backend/app/providers.py", "backend/app/public_catalog.py", "backend/app/queries.py",
                "backend/app/ranking.py", "backend/app/project_service.py", "backend/app/project_analysis.py", "backend/app/analysis_review.py"}
    if not required <= files.keys():
        raise ValueError("Runtime manifest lacks required analysis/search components.")
    return {"manifest": str(path), "manifest_sha256": sha(path), "pid_parent_confirmed": expected_pid,
            "root": str(ROOT), "port": manifest["port"], "started_at": manifest.get("started_at"), "files": files,
            "frontend_snapshot": frontend_snapshot,
            "runner_sha256": sha(__file__)}


def check_view(record, view):
    version = view.get("version") or {}
    if (view.get("project_id") != record["project_id"] or view.get("current_version") != record["version"]
            or version.get("version") != record["version"] or version.get("prompt_version") != record["prompt_version"]
            or view.get("original_input") != record["input"] or view.get("input") != record["input"]
            or version.get("input") != record["input"] or data_sha(version.get("analysis")) != record["analysis_sha256"]):
        raise ValueError("Project input, current version, prompt or manually approved analysis changed; no mutation is allowed.")
    confirmation = version.get("confirmation")
    if confirmation and (confirmation.get("confirmation_version") != record["version"]
                         or confirmation.get("input") != record["input"]
                         or data_sha(confirmation.get("analysis")) != record["analysis_sha256"]):
        raise ValueError("Confirmation snapshot differs from the independently approved analysis.")
    return version


def safe_resource_url(resource):
    try:
        return normalize_url(resource.get("url") or resource.get("canonical_url"))
    except (UnsafeURL, TypeError, ValueError):
        return None


def summarize_item(item):
    resource, match = item.get("resource", {}), item.get("match", {})
    available = {e.get("evidence_id") or e.get("id") for e in item.get("evidence", [])}
    supporting = set(match.get("supporting_evidence_ids", [])) & available
    supported = [p for p in match.get("subtopic_coverage", []) if p.get("status") == "supported"
                 and set(p.get("evidence_ids", [])) & supporting]
    url = safe_resource_url(resource)
    useful = bool(url and supported and match.get("topic_evidence_status") in {"supported", "partial"}
                  and resource.get("resource_type") in {"video", "course", "playlist"}
                  and resource.get("video_evidence_status") in {"page_verified", "search_discovered"})
    return {"resource_id": resource.get("resource_id"), "title": resource.get("title"), "safe_url": url, "url_safe": bool(url),
        "resource_type": resource.get("resource_type"), "video_evidence_status": resource.get("video_evidence_status"),
        "topic_evidence_status": match.get("topic_evidence_status"), "subtopic_coverage": match.get("subtopic_coverage", []),
        "supporting_evidence_ids": sorted(supporting), "useful_metadata_evidence": useful,
        "useful_page_verified_evidence": useful and resource.get("video_evidence_status") == "page_verified",
        "language": resource.get("language"), "fetch_status": resource.get("fetch_status"),
        "requires_login": resource.get("requires_login"), "requires_payment": resource.get("requires_payment"),
        "requires_enrollment": resource.get("requires_enrollment"), "access_notice": resource.get("access_notice"),
        "cache": resource.get("cache"), "playback_verified_by_runner": False}


def summarize_project(result):
    units = []
    for point in result.get("points", []):
        group = point.get("result") or {}
        coverage = group.get("collection_coverage") or {}
        parts = coverage.get("subtopics", [])
        sections = {name: [summarize_item(item) for item in group.get(name, [])] for name in ("items", "partial_items", "review_items")}
        def part_supported(part):
            if part.get("status") != "supported":
                return False
            for item in [*sections["items"], *sections["partial_items"]]:
                if not item["useful_metadata_evidence"] or item["resource_id"] not in part.get("resource_ids", []):
                    continue
                for detail in item["subtopic_coverage"]:
                    if (detail.get("id") == part.get("id") and detail.get("text") == part.get("text")
                            and detail.get("status") == "supported"
                            and set(detail.get("evidence_ids", [])) & set(part.get("evidence_ids", [])) & set(item["supporting_evidence_ids"])):
                        return True
            return False
        supported = sum(part_supported(p) for p in parts)
        label = "full" if parts and supported == len(parts) else "some" if supported else "none"
        units.append({key: point.get(key) for key in ("project_knowledge_point_id", "name", "selection", "status", "batch_id", "job_id", "knowledge_point_id")} |
            {"counts": {name: len(rows) for name, rows in sections.items()}, "collection_coverage": coverage,
             "subtopic_coverage_label": label, "subtopics_supported": supported, "subtopics_total": len(parts), **sections})
    selected = [u for u in units if u.get("selection") == "learn"]
    displayed = [item for u in units for section in ("items", "partial_items", "review_items") for item in u[section]]
    evidence_sections = [item for u in selected for section in ("items", "partial_items") for item in u[section]]
    status = (result.get("version") or {}).get("status")
    complete = bool(selected and all(u["subtopic_coverage_label"] == "full" for u in selected)
                    and all(item["url_safe"] for item in displayed))
    return {"status": status, "units": units, "selected_unit_count": len(selected),
        "units_full": sum(u["subtopic_coverage_label"] == "full" for u in selected),
        "units_some": sum(u["subtopic_coverage_label"] == "some" for u in selected),
        "units_none": sum(u["subtopic_coverage_label"] == "none" for u in selected),
        "safe_displayed_urls": all(item["url_safe"] for item in displayed),
        "any_useful_metadata_evidence": any(i["useful_metadata_evidence"] for i in evidence_sections),
        "any_useful_page_verified_evidence": any(i["useful_page_verified_evidence"] for i in evidence_sections),
        "all_selected_subtopics_covered": complete, "automated_evidence_gate_pass": status == "completed" and complete,
        "production_acceptance_pass": False if status in TERMINAL and (status != "completed" or not complete) else None,
        "remaining_review": "Real link metadata and server topic judgments still require independent relevance/learner-stage review; playback was not tested."}


def summarize_job(job, results):
    attempts = results.get("search_attempts", [])
    providers, engines, dns, skipped = Counter(), Counter(), Counter(), Counter()
    for attempt in attempts:
        provider = attempt.get("provider", "unknown")
        for request in attempt.get("provider_requests", []):
            providers[request.get("provider", provider)] += 1
            engines[request.get("engines_requested", "not_recorded")] += 1
        dns[provider] += len(attempt.get("provider_dns_requests", []))
        for warning in attempt.get("upstream_warnings", []):
            if warning.get("reason_code") in {"timeout_cooldown", "suspended"}:
                skipped[warning.get("engine", "unknown")] += 1
    return {"job_id": job.get("job_id"), "status": job.get("status"), "phase": job.get("phase"),
        "created_at": job.get("created_at"), "updated_at": job.get("updated_at"), "progress": job.get("progress", {}),
        "budget_limited": job.get("budget_limited"), "warnings": job.get("warnings", []), "errors": job.get("errors", []),
        "search_attempt_count": len(attempts), "current_provider_http_counts": dict(providers), "engine_group_http_counts": dict(engines),
        "discovery_dns_http_counts": dict(dns), "engine_skipped_warning_counts": dict(skipped),
        "cache_hit_attempts": sum(a.get("cache_hit") is True for a in attempts),
        "cached_origin_http_not_counted": sum(len(a.get("cache_origin_requests", [])) for a in attempts)}


class API:
    def __init__(self, client, run):
        self.client, self.run = client, run
        self.last_http_status = None

    async def request(self, method, path, **kwargs):
        if not path.startswith(("/api/projects/", "/api/search-jobs/", "/api/capabilities", "/health")):
            raise ValueError("Unapproved local API route.")
        counter = self.run.setdefault("local_api_requests", {})
        counter[method] = counter.get(method, 0) + 1
        self.last_http_status = None
        async with asyncio.timeout(15):
            async with self.client.stream(method, path, **kwargs) as response:
                self.last_http_status = response.status_code
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("Local API response exceeded evidence size bound.")
                    body.extend(chunk)
                response.raise_for_status()
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError("Local API returned a non-object.")
                return value


class Runner:
    def __init__(self, api, output, run, *, observe_only, deadline, poll_interval):
        self.api, self.output, self.run = api, output, run
        self.observe_only, self.deadline, self.poll_interval = observe_only, deadline, poll_interval

    def checkpoint(self):
        self.run["last_observed_at"] = now()
        dump(self.output / "run.json", self.run)

    async def view(self, record):
        view = await self.api.request("GET", f"/api/projects/{record['project_id']}")
        check_view(record, view)
        return view

    async def mutation_once(self, record, operation, payload):
        key = operation + "_attempted"
        if self.observe_only or record.get(key):
            raise ValueError("No POST is allowed in observation or after a checkpointed attempt.")
        # A fresh exact GET immediately precedes each write checkpoint.
        before = await self.view(record)
        record["pre_" + operation + "_view"] = before
        record.update({key: True, operation + "_attempted_at": now(), "status": operation + "_submission_pending"})
        self.checkpoint()
        try:
            view = await self.api.request("POST", f"/api/projects/{record['project_id']}/{operation}", json=payload)
            record[operation + "_http_status"] = self.api.last_http_status
            record[operation + "_response"] = view
            check_view(record, view)
            self.checkpoint()
            return view
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            record[operation + "_outcome_uncertain"] = True
            record[operation + "_error_type"] = type(exc).__name__
            record[operation + "_http_status"] = self.api.last_http_status
            self.checkpoint()
            # Never retry an uncertain POST, including a lost success response.
            view = await self.view(record)
            record[operation + "_reconciliation_view"] = view
            version = view["version"]
            applied = bool(version.get("confirmation")) if operation == "confirm" else bool(version.get("search_started_at"))
            record[operation + "_reconciled_as_applied"] = applied
            self.checkpoint()
            if not applied:
                raise ValueError("POST outcome not observed as applied; stop and use observation only.") from None
            return view

    async def collect_jobs(self, record, result):
        summaries = []
        for batch in (result.get("version") or {}).get("batches", []):
            job_id = batch.get("job_id")
            if not job_id:
                continue
            safe_identifier(job_id)
            job = await self.api.request("GET", f"/api/search-jobs/{job_id}")
            job_results = await self.api.request("GET", f"/api/search-jobs/{job_id}/results")
            dump(self.output / record["case_id"] / f"{job_id}-job.json", job)
            dump(self.output / record["case_id"] / f"{job_id}-results.json", job_results)
            summaries.append(summarize_job(job, job_results))
        record["jobs"] = summaries

    async def observe(self, record):
        started, last_jobs = time.monotonic(), -float("inf")
        while time.monotonic() - started < self.deadline:
            try:
                result = await self.api.request("GET", f"/api/projects/{record['project_id']}/results", params={"version": record["version"]})
                version = check_view(record, result)
                projection = summarize_project(result)
                elapsed = None
                if version.get("search_started_at"):
                    elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(version["search_started_at"])).total_seconds())
                first = False
                for field, observed in (("first_useful_seconds_upper_bound", projection["any_useful_metadata_evidence"]),
                    ("first_page_verified_useful_seconds_upper_bound", projection["any_useful_page_verified_evidence"]),
                    ("first_full_collection_seconds_upper_bound", projection["all_selected_subtopics_covered"])):
                    if observed and record.get(field) is None:
                        record[field], first = round(elapsed, 3) if elapsed is not None else None, True
                        record[field + "_observed_at"] = now()
                        dump(self.output / record["case_id"] / (field + "-results.json"), result)
                terminal = version.get("status") in TERMINAL
                record.update(status=version.get("status"), last_result_at=now(), wall_seconds_since_server_search=elapsed,
                    observation_wall_seconds=round(time.monotonic() - started, 3), metrics=projection,
                    terminal=terminal, budgets=version.get("budgets"), warnings=version.get("warnings", []), error=version.get("error"))
                if terminal:
                    record["terminal_observed_at"] = now()
                dump(self.output / record["case_id"] / "project-results.json", result)
                if first or terminal or time.monotonic() - last_jobs >= 15:
                    await self.collect_jobs(record, result)
                    last_jobs = time.monotonic()
                self.checkpoint()
                if terminal:
                    print(json.dumps({"case_id": record["case_id"], "status": record["status"], "wall_seconds": elapsed,
                        "full": projection["units_full"], "some": projection["units_some"], "none": projection["units_none"]}), flush=True)
                    return True
            except (httpx.HTTPError, ValueError, TimeoutError) as exc:
                record["last_observation_error_type"] = type(exc).__name__
                record["observation_error_count"] = record.get("observation_error_count", 0) + 1
                self.checkpoint()
                if isinstance(exc, ValueError):
                    return False
            await asyncio.sleep(self.poll_interval)
        record.update(observation_deadline_reached=True, terminal=False)
        self.checkpoint()
        return False

    async def run_case(self, record):
        record.setdefault("acceptance_started_at", now())
        current = await self.view(record)
        record["initial_view"] = current
        version = current["version"]
        if self.observe_only:
            if not version.get("search_started_at"):
                record.update(status="search_not_observed", terminal=False)
                self.checkpoint()
                return False
        else:
            if not version.get("confirmation"):
                if version.get("status") != "analyzed":
                    raise ValueError("Only a manually approved analyzed version can be confirmed.")
                current = await self.mutation_once(record, "confirm", {"version": record["version"], "acknowledged_skipped_prerequisites": []})
                version = current["version"]
            else:
                record["existing_confirmation_reused"] = True
            budget = version.get("budgets") or {}
            if any(budget.get(key) != expected for key, expected in (("per_batch_search_requests", 30),
                    ("per_batch_detail_pages", 40), ("per_batch_deadline_seconds", 240))):
                raise ValueError("Confirmed search budget differs from preview 30/40/240; no search submitted.")
            if not version.get("search_started_at"):
                await self.mutation_once(record, "search", {"version": record["version"]})
            else:
                record["existing_search_observed_without_post"] = True
        self.checkpoint()
        return await self.observe(record)


async def execute(args, plan, output, binding):
    path = output / "run.json"
    if args.observe_only:
        run = json.loads(path.read_text(encoding="utf-8"))
        if (run.get("base_url") != args.base_url or run.get("source_run_sha256") != plan["source_run_sha256"]
                or run.get("manual_review_sha256") != plan["manual_review_sha256"]
                or {r["case_id"] for r in run["records"]} != {r["case_id"] for r in plan["records"]}
                or any(any(record.get(key) != next(r for r in plan["records"] if r["case_id"] == record["case_id"])[key]
                           for key in ("project_id", "version", "input", "analysis_sha256", "prompt_version")) for record in run["records"])):
            raise ValueError("Existing run/source selection changed; observation cannot replace its binding.")
        run["observation_runtime_binding"] = binding
    else:
        run = {**plan, "mode": "live_local_api_search_acceptance", "started_at": now(), "base_url": args.base_url,
               "runtime_binding": binding, "mock": False, "seeded_candidates": False, "poll_interval_seconds": args.poll_interval,
               "first_useful_semantics": "Earliest observed real video/course metadata with safe URL and supporting subtopic evidence; polling is an upper bound, not playback or teaching quality proof."}
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10, follow_redirects=False, trust_env=False) as client:
        api = API(client, run)
        caps = await api.request("GET", "/api/capabilities")
        limits = caps.get("limits", {})
        if (caps.get("project_analysis", {}).get("prompt_version") != (args.runtime_prompt or plan["expected_prompt"]) or caps.get("mode") != "live"
                or any(limits.get(k) != v for k, v in (("max_search_requests", 30), ("max_detail_pages", 40), ("global_concurrency", 1)))):
            raise ValueError("Runtime prompt/search budget does not match the confirmed preview; no POST submitted.")
        run["capabilities"] = caps
        run["runtime_prompt"] = args.runtime_prompt or plan["expected_prompt"]
        runner = Runner(api, output, run, observe_only=args.observe_only, deadline=args.deadline, poll_interval=args.poll_interval)
        # Verify the whole selected cohort before any confirmation/search write.
        for record in run["records"]:
            record["preflight_view"] = await runner.view(record)
        runner.checkpoint()
        for record in run["records"]:
            try:
                complete = await runner.run_case(record)
            except (httpx.HTTPError, ValueError, TimeoutError) as exc:
                record.update(status="stopped_without_resubmit", terminal=False, stop_error=safe_error(exc))
                runner.checkpoint()
                complete = False
            if not complete:
                break  # Never start another case while this one is uncertain.
    run["finished_observation_at"] = now()
    run["summary"] = {"observed_cases": len(run["records"]), "search_posts_attempted": sum(bool(r.get("search_attempted")) for r in run["records"]),
        "confirm_posts_attempted": sum(bool(r.get("confirm_attempted")) for r in run["records"]),
        "terminal_cases": sum(r.get("terminal") is True for r in run["records"]),
        "partial_cases": sum(r.get("status") == "partial" for r in run["records"]),
        "units_full": sum(r.get("metrics", {}).get("units_full", 0) for r in run["records"]),
        "units_some": sum(r.get("metrics", {}).get("units_some", 0) for r in run["records"]),
        "units_none": sum(r.get("metrics", {}).get("units_none", 0) for r in run["records"]),
        "production_acceptance_pass": False if any(r.get("metrics", {}).get("production_acceptance_pass") is False for r in run["records"]) else None}
    runner.checkpoint()
    print(json.dumps(run["summary"]), flush=True)
    return 0 if all(r.get("terminal") for r in run["records"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--observe-only", action="store_true")
    parser.add_argument("--source-run", type=Path, default=ROOT / "evidence/phase2-learning-v26/run.json")
    parser.add_argument("--manual-review", type=Path, default=ROOT / "evidence/phase2-learning-v26/manual-review.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/phase2-search-v26")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--cases", help="Comma-separated manually approved case IDs")
    parser.add_argument("--base-url")
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--expected-prompt", default=EXPECTED_PROMPT)
    parser.add_argument("--runtime-prompt", help="Explicit current service prompt; previously accepted analyses retain their own hash-bound prompt/version.")
    parser.add_argument("--deadline", type=float, default=1100)
    parser.add_argument("--poll-interval", type=float, default=2.5)
    args = parser.parse_args()
    try:
        output = output_path(args.output)
        if not 1 <= args.deadline <= 1100 or not 2 <= args.poll_interval <= 3:
            raise ValueError("Observation deadline must be 1-1100 seconds and polling 2-3 seconds.")
        if args.case and args.cases:
            raise ValueError("Use --case or --cases, not both.")
        selected = args.case or ([s.strip() for s in args.cases.split(",") if s.strip()] if args.cases else [])
        plan = make_plan(args.source_run, args.manual_review, selected, args.expected_prompt)
        path = output / "run.json"
        if path.exists() and not args.observe_only:
            raise ValueError("run.json exists; only --observe-only is permitted. Never resubmit an uncertain run.")
        if args.observe_only and not path.is_file():
            raise ValueError("Observation requires the original run.json checkpoint.")
        if not args.live and not args.observe_only:
            dump(output / "plan.json", plan)
            print(json.dumps({"mode": "offline_plan", "network_requests": 0, "cases": [r["case_id"] for r in plan["records"]]}))
            return 0
        if not args.base_url or not args.runtime_manifest or not args.runtime_pid:
            raise ValueError("Live/observation requires explicitly confirmed loopback origin, runtime manifest and PID.")
        args.base_url = local_url(args.base_url)
        binding = runtime_binding(args.runtime_manifest, args.base_url, args.runtime_pid)
        return asyncio.run(execute(args, plan, output, binding))
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, httpx.HTTPError, TimeoutError) as exc:
        # Never reflect HTTP response bodies, headers or credential-bearing URLs.
        print(json.dumps({"status": "stopped", **safe_error(exc), "post_retry": False}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
