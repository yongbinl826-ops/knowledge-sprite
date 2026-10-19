"""One bounded continuation of a completed target-three run; dry run by default.

Only the explicitly supplied parent's isolated database is cloned. Its evidence
and actual dispatches must reconcile before any quota or discovery request. The
parent and this continuation together may spend at most 18 searches per source.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.providers import build_provider
from backend.app.service import JobService
from scripts import verify_mooc_target_three_live as parent
from scripts.compare_mooc_providers_live import fetch_controls, fetch_tavily_usage
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_course_library_live import backup_library
from scripts.verify_split_provider_live import make_fetcher, scrub

base = parent.base
POINTS = parent.POINTS
SOURCE_CAPS = parent.SOURCE_CAPS
PRIOR_STAGES = ("cache_tavily", "cache_serper", "tavily_mooc", "serper_mooc")
STAGES = ("tavily_mooc", "serper_mooc")
PARENT_SOURCE_FILES = (*base.SOURCE_FILES, "backend/app/source_adapters/icourse163.py",
                       "backend/app/mooc_urls.py", "scripts/verify_mooc_target_three_live.py")
# These are the reviewed changes for this single continuation: four additional
# bounded queries and two strictly equivalent SQL concepts (matcher rules v4).
AUTHORIZED_CHANGED_FILES = frozenset({"backend/app/config.py", "backend/app/platform_search.py",
    "backend/app/mooc_queries.py", "backend/app/mooc_relevance.py"})


def isolated_settings(configured, database, stage):
    if stage not in (*STAGES, "warm"):
        raise ValueError("Unknown continuation stage")
    return replace(parent.isolated_settings(configured, database, stage),
                   mooc_search_rounds=10, max_search_requests=30).validate()


def sufficient_free_usage(usage, required):
    def enough(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= required
    return (isinstance(usage, dict) and usage.get("allowed") is True
        and str(usage.get("current_plan", "")).lower() in {"researcher", "free"}
        and usage.get("paygo_usage") == 0 and enough(usage.get("plan_remaining"))
        and (usage.get("key_remaining") == "no_key_limit" or enough(usage.get("key_remaining"))))


def _load(path, files, label):
    raw = path.read_bytes()
    if len(raw) > 40_000_000:
        raise ValueError("Oversized evidence")
    files[label] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def _clean_source_states(states):
    return isinstance(states, dict) and all(isinstance(states.get(source), dict)
        and states[source].get("source_access_denied") is False
        and states[source].get("source_cooldown_seconds") == 0
        and not states[source].get("quota_exhausted") and not states[source].get("engine_cooldowns")
        for source in ("tavily", "serper"))


def _clean_hosts(controls):
    return (isinstance(controls, dict) and controls.get("blocked_hosts") == []
            and controls.get("paused_hosts") == [])


def audit_prior_evidence(prior, source):
    """Read only; no active source is rebuilt until a complete audit succeeds."""
    prior, source = Path(prior).resolve(), Path(source).resolve()
    report = {"allowed": False, "files": {}, "reasons": [], "stages": [], "source_changes": {},
              "used": dict.fromkeys(SOURCE_CAPS, 0), "remaining": dict(SOURCE_CAPS)}
    reasons, files = report["reasons"], report["files"]
    try:
        if source != prior / "library.sqlite3" or not source.is_file():
            raise ValueError("Source must be the exact parent backup")
        plan = _load(prior / "plan.json", files, "plan.json")
        final = _load(prior / "summary.json", files, "summary.json")
        if (plan.get("stages") != [*PRIOR_STAGES, "warm"] or plan.get("knowledge_points") != POINTS
                or plan.get("source_request_caps") != SOURCE_CAPS or plan.get("mooc_rounds") != 6
                or plan.get("mode") != "live" or final.get("all_tests_finished") is not True
                or final.get("status") not in {"finished_at_target", "finished_with_gaps"}):
            reasons.append("not_a_completed_original_target_three_run")
        if not _clean_source_states(final.get("source_states")) or not _clean_hosts(final.get("fetch_host_controls")):
            reasons.append("final_source_or_host_stop_unknown_or_active")
        hashes = plan.get("source_sha256", {})
        if set(hashes) != set(PARENT_SOURCE_FILES):
            reasons.append("source_manifest_incomplete")
        for name in PARENT_SOURCE_FILES:
            previous = hashes.get(name)
            current = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{64}", previous):
                reasons.append("invalid_source_hash:" + name)
            elif previous != current:
                report["source_changes"][name] = {"previous": previous, "current": current}
                if name not in AUTHORIZED_CHANGED_FILES:
                    reasons.append("unreviewed_source_change:" + name)
        backup = final.get("database_backup", {})
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        report["source_database_sha256"] = digest
        wal = Path(str(source) + "-wal")
        if (backup.get("status") != "saved" or backup.get("filename") != "library.sqlite3"
                or backup.get("sha256") != digest or (wal.exists() and wal.stat().st_size)):
            reasons.append("database_backup_hash_or_wal_mismatch")
        running_counts = dict.fromkeys(SOURCE_CAPS, 0)
        stage_counts, predispatch = {}, {}
        reader = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            reader.execute("PRAGMA query_only=ON")
            reader.execute("BEGIN")
            if reader.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
                reasons.append("database_has_unfinished_job")
            for stage in PRIOR_STAGES:
                documents = {name: _load(prior / stage / (name + ".json"), files, stage + "/" + name + ".json")
                    for name in ("summary", "job", "search_attempts", "resources", "evidence", "network", "source-ledger")}
                summary, job, attempts, resources, evidence, network, ledger = (documents[name] for name in
                    ("summary", "job", "search_attempts", "resources", "evidence", "network", "source-ledger"))
                if not (isinstance(summary, dict) and isinstance(job, dict) and isinstance(attempts, list)
                        and isinstance(resources, dict) and isinstance(evidence, dict) and isinstance(network, dict)
                        and isinstance(ledger, dict)):
                    raise ValueError("Invalid stage document shape")
                if (summary.get("job_terminal") is not True or summary.get("error_type") is not None
                        or job.get("status") in {None, "queued", "running"} or job.get("phase") != "done"
                        or summary.get("job_id") != job.get("job_id") or summary != final.get("stages", {}).get(stage)):
                    reasons.append(stage + ":incomplete_or_inconsistent_summary")
                stored_job = reader.execute("SELECT data FROM jobs WHERE id=?", (job.get("job_id"),)).fetchone()
                stored_attempts = [json.loads(row[0]) for row in reader.execute(
                    "SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (job.get("job_id"),))]
                if not stored_job or json.loads(stored_job[0]) != job or stored_attempts != attempts:
                    reasons.append(stage + ":database_evidence_mismatch")
                if not _clean_source_states(summary.get("source_states")) or not _clean_hosts(summary.get("fetch_host_controls")):
                    reasons.append(stage + ":source_or_host_stop_unknown_or_active")
                counts, blocked = dict.fromkeys(SOURCE_CAPS, 0), 0
                for attempt in attempts:
                    if not isinstance(attempt, dict) or attempt.get("provider") not in {"tavily", "serper"}:
                        reasons.append(stage + ":unselected_provider_or_invalid_attempt")
                        continue
                    traces = attempt.get("provider_requests")
                    if not isinstance(traces, list) or bool(attempt.get("network_attempted")) != bool(traces):
                        reasons.append(stage + ":missing_or_inconsistent_provider_trace")
                        continue
                    intentional = (stage.startswith("cache_") and attempt.get("error_code") == "query_budget_exhausted"
                                   and attempt.get("status") == "failed" and not traces and attempt.get("network_attempted") is False)
                    if intentional:
                        blocked += 1
                    elif attempt.get("status") not in {"completed", "skipped"} or attempt.get("error_code"):
                        reasons.append(stage + ":restricted_or_uncertain_attempt")
                    for trace in traces:
                        counts[attempt["provider"]] += 1
                        if (not isinstance(trace, dict) or trace.get("http_status") != 200
                                or trace.get("status") != "completed" or trace.get("error_code")
                                or attempt["provider"] != parent.STAGE_SOURCES[stage]):
                            reasons.append(stage + ":restricted_or_uncertain_provider_response")
                if stage.startswith("cache_") and sum(counts.values()):
                    reasons.append(stage + ":cache_stage_sent_search")
                if blocked:
                    predispatch[stage] = blocked
                if sum(counts.values()):
                    stage_counts[stage] = counts
                running_counts = {name: running_counts[name] + counts[name] for name in SOURCE_CAPS}
                if (ledger.get("caps") != SOURCE_CAPS or ledger.get("actual_dispatch_reservations") != running_counts
                        or ledger.get("stage_reservations") != stage_counts
                        or ledger.get("blocked_before_dispatch") != predispatch
                        or summary.get("search_http_requests") != sum(counts.values())
                        or any(summary.get("sources", {}).get(name, {}).get("http_requests") != counts[name]
                               for name in ("tavily", "serper"))
                        or summary.get("sources", {}).get("searxng", {}).get("http_requests") != 0):
                    reasons.append(stage + ":dispatch_ledger_mismatch")
                responses = network.get("responses")
                if not isinstance(responses, list):
                    raise ValueError("Missing network responses")
                if (network.get("target_http_requests") != len(responses)
                        or summary.get("detail_target_http_requests") != network.get("target_http_requests")):
                    reasons.append(stage + ":incomplete_target_network_evidence")
                for response in responses:
                    if not isinstance(response, dict) or (parent._mooc_url(response.get("url"))
                            and response.get("http_status") not in {200, 404, 410}):
                        reasons.append(stage + ":restricted_or_uncertain_target_response")
                for rid, resource in resources.items():
                    if not isinstance(resource, dict):
                        reasons.append(stage + ":invalid_resource")
                    elif parent._mooc_url(resource.get("url")):
                        state = resource.get("fetch_status")
                        if state not in parent.SAFE_PRIOR_MOOC_STATES:
                            reasons.append(stage + ":restricted_or_unknown_mooc_resource")
                        elif state == "policy_unreviewed" and not parent._policy_was_local(resource, evidence.get(rid, [])):
                            reasons.append(stage + ":policy_rejection_not_proven_local")
                report["stages"].append({"stage": stage, "actual_search_requests": counts,
                    "intentional_predispatch_blocks": blocked, "detail_target_http_requests": network.get("target_http_requests")})
        finally:
            reader.close()
        final_ledger = final.get("source_ledger", {})
        if (final_ledger.get("actual_dispatch_reservations") != running_counts or final_ledger.get("caps") != SOURCE_CAPS
                or final_ledger.get("stage_reservations") != stage_counts
                or final_ledger.get("blocked_before_dispatch") != predispatch
                or final.get("search_http_requests") != sum(running_counts.values())
                or any(running_counts[name] > cap for name, cap in SOURCE_CAPS.items())):
            reasons.append("final_dispatch_ledger_mismatch")
        warm = final.get("stages", {}).get("warm", {})
        if warm.get("status") != "not_demonstrated" or warm.get("search_http_requests") != 0 or warm.get("detail_target_http_requests") != 0:
            reasons.append("only_original_uncovered_run_supported")
        report["used"] = running_counts
        report["remaining"] = {name: max(0, cap - running_counts[name]) for name, cap in SOURCE_CAPS.items()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
        reasons.append("missing_invalid_or_inconsistent_parent_evidence")
    report["reasons"] = sorted(set(reasons))
    report["allowed"] = not reasons and len(report["stages"]) == len(PRIOR_STAGES)
    return report


class SourceLedger(parent.SourceLedger):
    def __init__(self, previous):
        super().__init__()
        if set(previous) != set(SOURCE_CAPS) or any(type(previous[k]) is not int or not 0 <= previous[k] <= v for k, v in SOURCE_CAPS.items()):
            raise ValueError("Invalid inherited dispatch ledger")
        self.previous = dict(previous)
        self.total = dict(previous)
        self.stage = "tavily_mooc"
        self.blocked_details = 0

    def snapshot(self):
        result = super().snapshot()
        result.update(inherited_dispatch_reservations=dict(self.previous),
            continuation_dispatch_reservations={name: self.total[name] - self.previous[name] for name in SOURCE_CAPS},
            remaining={name: cap - self.total[name] for name, cap in SOURCE_CAPS.items()},
            warm_detail_calls_blocked_before_dispatch=self.blocked_details, warm_actual_detail_cap=0)
        return result


def install_warm_detail_guard(fetcher, ledger):
    original = fetcher.enrich
    async def guarded(*args, **kwargs):
        if ledger.stage == "warm":
            ledger.blocked_details += 1
            ledger.on_change()
            raise RuntimeError("Warm verification permits no detail fetch")
        return await original(*args, **kwargs)
    fetcher.enrich = guarded


async def run(output, *, source_database, prior_evidence, live=False, confirm_serper_free_trial=False, configured=None):
    output, source, prior = parent._paths(output, source_database, prior_evidence)
    audit = audit_prior_evidence(prior, source)
    plan = {"schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run", "knowledge_points": POINTS,
        "prior_evidence": str(prior), "source_database": str(source), "source_request_caps": SOURCE_CAPS,
        "inherited_actual_requests": audit["used"], "remaining_new_requests": audit["remaining"],
        "stages": [*STAGES, "warm"], "mooc_rounds": 10, "query_admission_per_stage": 30, "results_per_query": 10,
        "max_detail_pages_per_stage": 36, "max_detail_pages_discovery_total": 72, "deadline_seconds_per_stage": 360,
        "target_courses_per_point": 3, "counting": "Distinct numeric course IDs with independently verified outlines",
        "bilibili_requests": 0, "llm_calls": 0, "billing_changes": False, "manual_url_seeds": False,
        "old_profile_relabelled": False, "source_objects_shared": True, "renderer": "Configured renderer/profile retained",
        "warm_search_cap": 0, "warm_detail_cap": 0, "warm_refresh_enabled": False,
        "stream_transport": "Production SSE generator in process; no browser latency claim",
        "authorized_source_changes": sorted(AUTHORIZED_CHANGED_FILES),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in (*PARENT_SOURCE_FILES, "scripts/continue_mooc_target_three_live.py")}}
    summary = {"status": "dry_run", "started_at": now(), "stages": {}, "usage_http_requests": 0,
        "search_http_requests": 0, "detail_target_http_requests": 0, "bilibili_search_requests": 0,
        "all_tests_finished": False, "all_points_at_target": False, "warm_demonstrated": False,
        "llm_calls": 0, "billing_changes": False, "precision": "unknown", "recall": "unknown"}
    secrets = ()
    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))
    if live:
        configured = configured or Settings.from_env()
        secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)
    for name, value in (("plan.json", plan), ("prior-evidence-audit.json", audit), ("summary.json", summary)):
        save(name, value)
    if not live:
        return summary
    if not audit["allowed"]:
        summary.update(status="preflight_blocked", reason="parent_evidence_restriction_or_inconsistency")
        save("summary.json", summary)
        return scrub(summary, secrets)
    if not configured.tavily_api_key.strip() or not configured.serper_api_key.strip() or not confirm_serper_free_trial:
        summary.update(status="preflight_blocked", reason="free_source_configuration_or_confirmation_missing")
        save("summary.json", summary)
        return scrub(summary, secrets)
    usage = await fetch_tavily_usage(configured.tavily_api_key)
    summary.update(usage_http_requests=1, tavily_free_usage=usage)
    if not sufficient_free_usage(usage, audit["remaining"]["tavily"]):
        summary.update(status="preflight_blocked", reason="remaining_free_tavily_allowance_not_verified")
        save("summary.json", summary)
        return scrub(summary, secrets)
    ledger, service, cancelled = SourceLedger(audit["used"]), None, None
    with TemporaryDirectory(prefix="mooc-target-three-continued-") as temporary:
        database = Path(temporary) / "library.sqlite3"
        summary["cloned_database_sha256"] = parent.clone_database(source, database)
        # The completed parent is immutable input. Detect mutation between audit
        # and clone before allowing any source request.
        if hashlib.sha256(source.read_bytes()).hexdigest() != audit["source_database_sha256"]:
            summary.update(status="preflight_blocked", reason="parent_database_changed_during_preflight")
            save("summary.json", summary)
            return scrub(summary, secrets)
        settings = isolated_settings(configured, database, "tavily_mooc")
        store = Store(str(database))
        try:
            fetcher = make_fetcher(settings)
            providers = {name: build_provider(settings, fetcher=fetcher, store=store, provider_name=name) for name in ("tavily", "serper")}
            ledger.install(providers)
            install_warm_detail_guard(fetcher, ledger)
            overrides = {settings.search_provider: parent.DisabledSource(), settings.search_provider_for("bilibili"): parent.DisabledSource(), **providers}
            service = JobService(settings, store, fetcher=fetcher, provider_overrides=overrides)
            service._providers.update(providers)
            service._provider_errors.update({name: None for name in providers})
            assert service.llm is None and fetcher.config.max_retries == 0
            summary.update(status="running", initial_coverage=parent.numeric_coverage(service))
            original_save = service._save
            def journal(job):
                original_save(job)
                if (output / ledger.stage).is_dir():
                    for name, value in (("job", job), ("search_attempts", store.attempts(job["job_id"])),
                            ("source-ledger", ledger.snapshot()), ("host-controls", fetch_controls(fetcher))):
                        save(ledger.stage + "/" + name + ".json", value)
            service._save = journal
            save("summary.json", summary)
            async def phase(stage):
                service.settings = isolated_settings(configured, database, stage)
                ledger.stage = stage
                result = await base.run_stage(service, store, output / stage, stage, secrets, ledger, summary["stages"])
                result.update(numeric_library_coverage=parent.numeric_coverage(service),
                    displayed_numeric_coverage=parent.displayed_numeric_coverage(service, result["job_id"]),
                    fetch_host_controls=fetch_controls(fetcher))
                save(stage + "/summary.json", result)
                save("summary.json", summary)
                if not result["job_terminal"] or result["error_type"]:
                    raise RuntimeError("Continuation stage incomplete")
                return result
            for stage in STAGES:
                await phase(stage)
            coverage = parent.numeric_coverage(service)
            if len(coverage) == len(POINTS) and all(row["qualified_count"] >= 3 for row in coverage):
                warm = await phase("warm")
                summary["warm_demonstrated"] = (warm["search_http_requests"] == warm["detail_target_http_requests"] == 0
                    and ledger.blocked_details == 0 and len(warm["per_point"]) == len(POINTS)
                    and all(row["library_cards"] >= 3 for row in warm["per_point"])
                    and len(warm["displayed_numeric_coverage"]) == len(POINTS)
                    and all(row["qualified_count"] >= 3 for row in warm["displayed_numeric_coverage"])
                    and warm["stream"]["first_library_card_ms"] is not None
                    and warm["stream"]["displayed_mooc_without_outline_count"] == 0)
            else:
                summary["stages"]["warm"] = {"status": "not_demonstrated", "reason": "fewer_than_three_distinct_qualified_courses",
                    "search_http_requests": 0, "detail_target_http_requests": 0}
            summary["all_tests_finished"] = True
        except asyncio.CancelledError as exc:
            cancelled = exc
            summary.update(status="interrupted", error_type="CancelledError")
        except Exception as exc:
            summary.update(status="harness_error", error_type=type(exc).__name__)
        finally:
            summary["source_ledger"] = ledger.snapshot()
            summary["search_http_requests"] = sum(ledger.total[name] - ledger.previous[name] for name in SOURCE_CAPS)
            summary["parent_and_continuation_search_http_requests"] = sum(ledger.total.values())
            summary["detail_target_http_requests"] = sum(row.get("detail_target_http_requests", 0) for row in summary["stages"].values())
            if service is not None:
                summary["library_coverage"] = parent.numeric_coverage(service)
                summary["all_points_at_target"] = len(summary["library_coverage"]) == len(POINTS) and all(row["qualified_count"] >= 3 for row in summary["library_coverage"])
                summary["fetch_host_controls"] = fetch_controls(service.fetcher)
                summary["source_states"] = service.health()["search_sources"]
            summary["database_backup"] = backup_library(store, output / "library.sqlite3", secrets)
            if summary["all_tests_finished"]:
                summary["status"] = "finished_at_target" if summary["all_points_at_target"] else "finished_with_gaps"
            summary["finished_at"] = now()
            save("summary.json", summary)
            store.close()
    if cancelled is not None:
        raise cancelled
    return scrub(summary, secrets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-serper-free-trial", action="store_true", help="Confirm remaining free credits cover the inherited remaining cap")
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--prior-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.output, source_database=args.source_database, prior_evidence=args.prior_evidence,
            live=args.live, confirm_serper_free_trial=args.confirm_serper_free_trial))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; evidence and isolated database were exported when possible.")
        return 130
    except Exception:
        print("Continuation could not start; check explicit paths and configuration. Secrets are not printed.")
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] in {"harness_error", "preflight_blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
