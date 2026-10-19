"""Prepare hash-identical student-edit versions for a bounded search retry.

Default is an offline plan, with no HTTP. --live permits at most two edit POSTs,
one per approved, currently partial source version. It never analyzes, confirms,
or searches. Every POST is checkpointed first. Existing run.json permits only
--observe-only; an uncertain POST is resolved by GET, never resent.

The exported source_run.json/manual_review.json fit phase2_search_acceptance.
Approval is inherited for identical content, not a new semantic review.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase2_search_acceptance import (
    EXPECTED_PROMPT, MAX_RESPONSE_BYTES, check_view, data_sha, dump, local_url,
    make_plan, now, output_path, runtime_binding, safe_error, sha, workspace_file,
)

DEFAULT_CASES = ["bicycle_csv_advanced", "pygame_maze_intermediate"]
PROJECT_ROUTE = re.compile(r"^/api/projects/[A-Za-z0-9][A-Za-z0-9_-]{0,100}$")


def prepare_plan(source_path, manual_path, selected, expected_prompt):
    approved = make_plan(source_path, manual_path, selected, expected_prompt)
    if len(approved["records"]) > 2:
        raise ValueError("This preparation allows at most two approved edit submissions.")
    records = []
    for record in approved["records"]:
        records.append({
            "case_id": record["case_id"], "project_id": record["project_id"],
            "version": record["version"], "source_version": record["version"],
            "expected_new_version": record["version"] + 1,
            "input": record["input"], "input_sha256": data_sha(record["input"]),
            "analysis_sha256": record["analysis_sha256"],
            "prompt_version": record["prompt_version"],
            "manual_review_sha256": record["manual_review_sha256"],
            "status": "not_submitted", "edit_attempted": False,
            "prepared": False,
        })
    return {
        "mode": "offline_plan", "created_at": now(),
        "source_run": approved["source_run"], "source_run_sha256": approved["source_run_sha256"],
        "manual_review": approved["manual_review"], "manual_review_sha256": approved["manual_review_sha256"],
        "expected_prompt": expected_prompt, "records": records,
        "required_source_status": "partial", "required_new_status": "analyzed",
        "max_edit_submissions": len(records), "analysis_submissions": 0,
        "confirm_submissions": 0, "search_submissions": 0,
        "direct_platform_requests": 0, "automatic_post_retries": 0,
        "approval_semantics": "Existing independent review is inherited only for exact input/analysis/prompt equality. Version binding changes; no new generation or semantic review is claimed.",
    }


def check_source(record, view):
    version = check_view(record, view)
    if version.get("status") != "partial":
        raise ValueError("Source must still be the approved current terminal partial version; no edit submitted.")
    if data_sha(version.get("input")) != record["input_sha256"]:
        raise ValueError("Approved source input hash changed.")
    return version


def check_prepared(record, view):
    rebound = {**record, "version": record["expected_new_version"]}
    version = check_view(rebound, view)
    if (version.get("status") != "analyzed" or version.get("origin") != "student_edit"
            or version.get("parent_version") != record["source_version"]
            or data_sha(version.get("input")) != record["input_sha256"]
            or version.get("confirmation") or version.get("search_started_at")):
        raise ValueError("New version is not an unchanged, unsearched analyzed student edit of the approved parent.")
    return version


class API:
    """Only project GET, capability GET, and bounded project-edit POST exist."""
    def __init__(self, client, run):
        self.client, self.run = client, run
        self.last_http_status = None

    async def request(self, method, path, **kwargs):
        allowed = (method == "GET" and (path == "/api/capabilities" or PROJECT_ROUTE.fullmatch(path)))
        allowed = allowed or (method == "POST" and path.endswith("/edit") and PROJECT_ROUTE.fullmatch(path[:-5]))
        if not allowed:
            raise ValueError("Only read-only local preflight and a project edit route are permitted.")
        counters = self.run.setdefault("local_api_requests", {})
        if method == "POST" and counters.get("POST", 0) >= self.run["max_edit_submissions"]:
            raise ValueError("Edit POST budget exhausted; no request sent.")
        counters[method] = counters.get(method, 0) + 1
        self.last_http_status = None
        async with asyncio.timeout(15):
            async with self.client.stream(method, path, **kwargs) as response:
                self.last_http_status = response.status_code
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("Local API response exceeded the evidence size bound.")
                    body.extend(chunk)
                response.raise_for_status()
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError("Local API returned a non-object.")
                return value


class Runner:
    def __init__(self, api, output, run):
        self.api, self.output, self.run = api, Path(output), run

    def checkpoint(self):
        self.run["last_checkpoint_at"] = now()
        dump(self.output / "run.json", self.run)

    async def view(self, record):
        return await self.api.request("GET", "/api/projects/" + record["project_id"])

    async def observe_attempt(self, record):
        """A single bounded GET; failure or an old version never triggers POST."""
        if not record.get("edit_attempted"):
            record.update(status="not_submitted", prepared=False)
            self.checkpoint()
            return False
        try:
            view = await self.view(record)
            record["last_observed_current_version"] = view.get("current_version")
            if view.get("current_version") == record["source_version"]:
                check_source(record, view)
                record.update(status="edit_not_observed_no_resubmit", prepared=False)
                self.checkpoint()
                return False
            check_prepared(record, view)
            record.update(status="prepared", prepared=True, persisted_view=view,
                          prepared_at=record.get("prepared_at") or now())
            self.checkpoint()
            return True
        except (httpx.HTTPError, ValueError, TimeoutError, OSError, TypeError, KeyError) as exc:
            record.update(status="uncertain_or_binding_failed_no_resubmit", prepared=False,
                          observation_error=safe_error(exc))
            self.checkpoint()
            return False

    async def edit_once(self, record):
        if record.get("edit_attempted"):
            raise ValueError("An attempted edit can only be observed, never resubmitted.")
        view = await self.view(record)
        version = check_source(record, view)
        payload = {"expected_version": record["source_version"], "analysis": deepcopy(version["analysis"])}
        record.update(edit_attempted=True, edit_submitted_at=now(),
                      edit_payload_sha256=data_sha(payload), status="edit_submission_checkpointed")
        # The durable attempted flag is written before the only allowed POST.
        self.checkpoint()
        try:
            response = await self.api.request("POST", "/api/projects/" + record["project_id"] + "/edit", json=payload)
            record["edit_http_status"] = self.api.last_http_status
            check_prepared(record, response)
            record.update(status="prepared", prepared=True, persisted_view=response, prepared_at=now())
            self.checkpoint()
            return True
        except (httpx.HTTPError, ValueError, TimeoutError, OSError, TypeError, KeyError) as exc:
            record.update(status="edit_response_uncertain_no_resubmit", prepared=False,
                          edit_http_status=self.api.last_http_status, edit_error=safe_error(exc))
            self.checkpoint()
            return await self.observe_attempt(record)


def inherited_outputs(run, output):
    """Export accepted-snapshot shape without claiming a new content review."""
    if not all(record.get("prepared") is True for record in run["records"]):
        return None
    source_path, manual_path = workspace_file(run["source_run"]), workspace_file(run["manual_review"])
    if sha(source_path) != run["source_run_sha256"] or sha(manual_path) != run["manual_review_sha256"]:
        raise ValueError("Approval source files changed; no inherited approval exported.")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    originals = {record["case_id"]: record for record in source["records"]}
    reviews = {review["case_id"]: review for review in manual["case_reviews"]}
    records, inherited = [], []
    for record in run["records"]:
        check_prepared(record, record["persisted_view"])
        original = originals[record["case_id"]]
        original_review = reviews[record["case_id"]]
        if data_sha(original_review) != record["manual_review_sha256"]:
            raise ValueError("The inherited case approval hash changed.")
        provenance = {
            "source_run": str(source_path), "source_run_sha256": sha(source_path),
            "source_record_sha256": data_sha(original),
            "manual_review": str(manual_path), "manual_review_sha256": sha(manual_path),
            "case_review_sha256": data_sha(original_review), "project_id": record["project_id"],
            "version": record["source_version"], "input_sha256": record["input_sha256"],
            "analysis_sha256": record["analysis_sha256"], "prompt_version": record["prompt_version"],
        }
        approval = {"type": "inherited_exact_content_approval", "inherited_at": now(),
            "inherited_from": provenance, "bound_version": record["expected_new_version"],
            "content_changes": False, "new_model_analysis": False, "new_independent_semantic_review": False}
        records.append({"case_id": record["case_id"], "project_id": record["project_id"],
            "version": record["expected_new_version"], "input": deepcopy(record["input"]),
            "status": "analyzed", "persisted_view": deepcopy(record["persisted_view"]),
            "approval": approval, "analysis_submission_attempted": False})
        review = deepcopy(original_review)
        review.update(version=record["expected_new_version"], api_status="analyzed",
                      review_type="inherited_exact_content_approval", approval=deepcopy(approval),
                      original_review_type=original_review.get("review_type"))
        inherited.append(review)
    source_export = {"mode": "search_retry_version_preparation", "created_at": now(),
        "source_run": str(source_path), "source_run_sha256": sha(source_path),
        "manual_review": str(manual_path), "manual_review_sha256": sha(manual_path),
        "expected_prompt": run["expected_prompt"], "records": records,
        "analysis_submissions": 0, "search_submissions": 0,
        "semantic_content_changed": False, "new_independent_semantic_review": False}
    requirement_count = sum(len(review["requirements"]) for review in inherited)
    manual_export = {"mode": "inherited_exact_content_approval", "inherited_at": now(),
        "original_reviewed_at": manual.get("reviewed_at"),
        "source_manual_review": str(manual_path), "source_manual_review_sha256": sha(manual_path),
        "new_independent_semantic_review": False, "new_model_analysis": False,
        "case_reviews": inherited, "assessed_requirements": requirement_count,
        "assessed_requirement_passes": requirement_count, "unassessed_requirements": 0,
        "accepted_output_semantic_pass": True,
        "limits": "Only version binding changed after exact input/analysis/prompt hash verification. Original independent judgments and low-priority notes are inherited; no new precision reading, project execution, search, video or production pass is claimed."}
    output = Path(output)
    source_export_path, manual_export_path = output / "source_run.json", output / "manual_review.json"
    # Verify in a local temporary pair before publishing either usable approval.
    pending_source, pending_manual = output / "source_run.pending.json", output / "manual_review.pending.json"
    dump(pending_source, source_export)
    dump(pending_manual, manual_export)
    compatibility = make_plan(pending_source, pending_manual, [r["case_id"] for r in records], run["expected_prompt"])
    pending_source.replace(source_export_path)
    pending_manual.replace(manual_export_path)
    checked = make_plan(source_export_path, manual_export_path, [r["case_id"] for r in records], run["expected_prompt"])
    dump(output / "search_plan.json", checked)
    return {"source_run": str(source_export_path), "source_run_sha256": sha(source_export_path),
            "manual_review": str(manual_export_path), "manual_review_sha256": sha(manual_export_path),
            "search_plan": str(output / "search_plan.json"),
            "make_plan_compatible_cases": len(compatibility["records"])}


def check_existing(run, plan, base):
    keys = ("case_id", "project_id", "version", "source_version", "expected_new_version", "input",
            "input_sha256", "analysis_sha256", "prompt_version", "manual_review_sha256")
    planned = {record["case_id"]: record for record in plan["records"]}
    if (run.get("base_url") != base or run.get("source_run_sha256") != plan["source_run_sha256"]
            or run.get("manual_review_sha256") != plan["manual_review_sha256"]
            or len(run.get("records", [])) != len(planned)
            or {r["case_id"] for r in run.get("records", [])} != set(planned)
            or any(any(row.get(key) != planned[row["case_id"]].get(key) for key in keys) for row in run["records"])):
        raise ValueError("Existing preparation/source selection changed; observation cannot replace its binding.")


async def execute(args, plan, output, binding, *, transport=None):
    path = output / "run.json"
    if args.observe_only:
        run = json.loads(path.read_text(encoding="utf-8"))
        check_existing(run, plan, args.base_url)
        run["observation_runtime_binding"] = binding
    else:
        if path.exists():
            raise ValueError("Existing run permits only observation; no POST submitted.")
        run = {**deepcopy(plan), "mode": "live_local_api_search_retry_preparation", "started_at": now(),
            "base_url": args.base_url, "runtime_binding": binding, "mock": transport is not None,
            "runner_sha256": sha(__file__)}
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10, follow_redirects=False,
                                 trust_env=False, transport=transport) as client:
        api = API(client, run)
        runner = Runner(api, output, run)
        runner.checkpoint()
        caps = await api.request("GET", "/api/capabilities")
        if (caps.get("mode") != "live" or caps.get("project_analysis", {}).get("prompt_version") != args.runtime_prompt):
            raise ValueError("Capabilities do not match the explicitly confirmed live runtime prompt; no POST submitted.")
        run["capabilities"] = caps
        runner.checkpoint()
        if args.observe_only:
            for record in run["records"]:
                if not await runner.observe_attempt(record):
                    break
        else:
            # Fail the entire preflight before any edit if either old snapshot changed.
            for record in run["records"]:
                record["preflight_view"] = await runner.view(record)
                check_source(record, record["preflight_view"])
            runner.checkpoint()
            for record in run["records"]:
                if not await runner.edit_once(record):
                    break
        run["exports"] = inherited_outputs(run, output)
        run["finished_at"] = now()
        run["summary"] = {"selected_cases": len(run["records"]),
            "prepared_cases": sum(r.get("prepared") is True for r in run["records"]),
            "edit_posts_attempted": sum(r.get("edit_attempted") is True for r in run["records"]),
            "analysis_submissions": 0, "confirm_submissions": 0, "search_submissions": 0,
            "automatic_post_retries": 0, "approval_is_inherited": True,
            "new_independent_semantic_review": False}
        runner.checkpoint()
    return run


async def self_test(output):
    """Real approved evidence + MockTransport only; zero live/network requests."""
    source = ROOT / "evidence/phase2-learning-v26/run.json"
    manual = ROOT / "evidence/phase2-learning-v26/manual-review.json"
    plan = prepare_plan(source, manual, DEFAULT_CASES, EXPECTED_PROMPT)
    source_rows = {row["case_id"]: row for row in json.loads(source.read_text(encoding="utf-8"))["records"]}
    results = []
    args = argparse.Namespace(observe_only=False, base_url="http://127.0.0.1:8000", runtime_prompt="mock-frozen-runtime")

    async def scenario(name, behavior=None, altered=False):
        folder = output / "self-test" / name
        if (folder / "run.json").exists():
            raise ValueError("Self-test evidence exists; select a new output directory instead of overwriting history.")
        views = {row["project_id"]: deepcopy(source_rows[row["case_id"]]["persisted_view"]) for row in plan["records"]}
        for view in views.values():
            view["version"]["status"] = "partial"
        if altered:
            views[plan["records"][1]["project_id"]]["version"]["analysis"]["project_summary"] = "changed"
        posts = []

        def handler(request):
            if request.url.path == "/api/capabilities":
                return httpx.Response(200, json={"mode": "live", "project_analysis": {"prompt_version": args.runtime_prompt}})
            identifier = request.url.path.split("/")[3]
            if request.method == "GET":
                return httpx.Response(200, json=views[identifier])
            checkpoint = json.loads((folder / "run.json").read_text(encoding="utf-8"))
            pending = next(row for row in checkpoint["records"] if row["project_id"] == identifier)
            assert pending["edit_attempted"] and pending["status"] == "edit_submission_checkpointed"
            payload = json.loads(request.content)
            assert set(payload) == {"expected_version", "analysis"}
            assert payload["analysis"] == views[identifier]["version"]["analysis"]
            assert payload["expected_version"] == 2
            posts.append(identifier)
            if behavior != "lost_not_persisted":
                view = deepcopy(views[identifier])
                view["current_version"] = 3
                view["version"].update(version=3, status="analyzed", origin="student_edit", parent_version=2,
                                       confirmation=None, search_started_at=None, batches=[], budgets={})
                views[identifier] = view
            if behavior in {"lost_persisted", "lost_not_persisted"}:
                raise httpx.ReadTimeout("Synthetic lost edit response", request=request)
            return httpx.Response(200, json=views[identifier])

        transport = httpx.MockTransport(handler)
        if altered:
            try:
                await execute(args, plan, folder, {"mock": True}, transport=transport)
            except ValueError:
                assert not posts
                results.append({"test": name, "passed": True, "post_count": 0})
                return
            raise AssertionError("Changed analysis was accepted")
        run = await execute(args, plan, folder, {"mock": True}, transport=transport)
        expected = 1 if behavior == "lost_not_persisted" else 2
        assert len(posts) == expected and len(set(posts)) == expected
        assert bool(run["exports"]) is (behavior != "lost_not_persisted")
        if run["exports"]:
            exported = json.loads(Path(run["exports"]["manual_review"]).read_text(encoding="utf-8"))
            assert all(not row["approval"]["new_independent_semantic_review"] for row in exported["case_reviews"])
            assert all(row["approval"]["inherited_from"]["version"] == 2 and row["version"] == 3 for row in exported["case_reviews"])
            assert make_plan(Path(run["exports"]["source_run"]), Path(run["exports"]["manual_review"]), DEFAULT_CASES, EXPECTED_PROMPT)
        args.observe_only = True
        observed = await execute(args, plan, folder, {"mock": True}, transport=transport)
        args.observe_only = False
        assert len(posts) == expected and observed["local_api_requests"]["POST"] == expected
        try:
            await execute(args, plan, folder, {"mock": True}, transport=transport)
        except ValueError:
            pass
        else:
            raise AssertionError("Existing run allowed live submission")
        results.append({"test": name, "passed": True, "post_count": expected,
                        "observe_only_additional_posts": 0, "exports_compatible": bool(run["exports"])})

    await scenario("successful_exact_edits")
    await scenario("lost_response_persisted", "lost_persisted")
    await scenario("lost_response_not_persisted", "lost_not_persisted")
    await scenario("cohort_content_mismatch_no_posts", altered=True)
    # Explicitly reject mismatched provenance even when content matches.
    old = deepcopy(source_rows[DEFAULT_CASES[0]]["persisted_view"])
    old["current_version"] = 3
    old["version"].update(version=3, status="analyzed", origin="model", parent_version=1)
    try:
        check_prepared(plan["records"][0], old)
    except ValueError:
        results.append({"test": "wrong_parent_or_origin_rejected", "passed": True})
    else:
        raise AssertionError("Wrong edit lineage accepted")
    fake_run = {"max_edit_submissions": 2}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
                                 base_url="http://127.0.0.1:8000") as client:
        api = API(client, fake_run)
        for route in ("/api/projects/id/analyze", "/api/projects/id/search", "/api/projects/id/confirm", "/api/projects"):
            try:
                await api.request("POST", route)
            except ValueError:
                continue
            raise AssertionError("Forbidden API route accepted")
    results.append({"test": "analysis_search_confirmation_create_routes_forbidden", "passed": True})
    report = {"mode": "zero_network_mocktransport_self_test", "created_at": now(),
              "real_api_requests": 0, "provider_requests": 0, "tests": results,
              "passed": all(row["passed"] for row in results), "runner_sha256": sha(__file__)}
    dump(output / "self-test.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--observe-only", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-run", type=Path, default=ROOT / "evidence/phase2-learning-v26/run.json")
    parser.add_argument("--manual-review", type=Path, default=ROOT / "evidence/phase2-learning-v26/manual-review.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/phase2-search-retry-preparation")
    parser.add_argument("--cases", help="Comma-separated approved source cases, at most two")
    parser.add_argument("--expected-prompt", default=EXPECTED_PROMPT)
    parser.add_argument("--base-url")
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--runtime-prompt")
    args = parser.parse_args()
    try:
        output = output_path(args.output)
        if args.self_test:
            report = asyncio.run(self_test(output))
            print(json.dumps({"mode": report["mode"], "passed": report["passed"], "tests": len(report["tests"]), "real_api_requests": 0}))
            return 0 if report["passed"] else 1
        selected = [part.strip() for part in args.cases.split(",") if part.strip()] if args.cases else DEFAULT_CASES
        if not selected or len(set(selected)) != len(selected) or len(selected) > 2:
            raise ValueError("Choose one or two distinct approved source cases.")
        plan = prepare_plan(args.source_run, args.manual_review, selected, args.expected_prompt)
        path = output / "run.json"
        if path.exists() and not args.observe_only:
            raise ValueError("run.json exists; only --observe-only is permitted. Never repeat an uncertain edit.")
        if args.observe_only and not path.is_file():
            raise ValueError("Observation requires the original run.json checkpoint.")
        if not args.live and not args.observe_only:
            dump(output / "plan.json", plan)
            print(json.dumps({"mode": "offline_plan", "network_requests": 0,
                              "cases": [r["case_id"] for r in plan["records"]], "max_edit_submissions": len(plan["records"])}))
            return 0
        if not all((args.base_url, args.runtime_manifest, args.runtime_pid, args.runtime_prompt)):
            raise ValueError("Live/observation requires confirmed loopback origin, runtime manifest, PID and runtime prompt.")
        args.base_url = local_url(args.base_url)
        binding = runtime_binding(args.runtime_manifest, args.base_url, args.runtime_pid)
        binding["preparation_runner_sha256"] = sha(__file__)
        run = asyncio.run(execute(args, plan, output, binding))
        print(json.dumps(run["summary"]))
        return 0 if run["exports"] else 1
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, httpx.HTTPError, TimeoutError) as exc:
        print(json.dumps({"status": "stopped", **safe_error(exc), "post_retry": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
