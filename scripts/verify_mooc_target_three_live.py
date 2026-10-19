"""Opt-in MOOC-only continuation of an audited isolated live-test database.

Dry run is the default. The prior database is cloned with SQLite backup, never
modified. Cached real searches are revisited first with zero search dispatches,
then Tavily and Serper each have at most 18 new requests. Three distinct numeric
course IDs per point, each with its own qualifying outline, are required.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.mooc_urls import course_identity_parts, public_course_url
from backend.app.providers import build_provider, SearchBudgetReached, SearchError
from backend.app.service import JobService
from scripts import verify_mooc_gaps_live as base
from scripts.compare_mooc_providers_live import fetch_controls, fetch_tavily_usage
from scripts.test_tavily_mooc_recall import atomic_json, now
from scripts.verify_course_library_live import backup_library
from scripts.verify_split_provider_live import make_fetcher, scrub

POINTS = list(base.POINTS)
SOURCE_CAPS = {"tavily": 18, "serper": 18, "bilibili": 0}
STAGE_SOURCES = {"cache_tavily": "tavily", "cache_serper": "serper", "tavily_mooc": "tavily",
                 "serper_mooc": "serper", "warm": "tavily"}
PRIOR_STAGES = ("live/tavily", "live/serper", "route-recheck/sql")
RESTRICTED = {"captcha", "access_denied", "rate_limited", "robots_blocked", "robots_disallowed", "login_required",
              "quota_exhausted", "blocked", "site_policy_restricted", "site_policy_blocked"}
SAFE_PRIOR_MOOC_STATES = {"fetched", "not_fetched", "policy_unreviewed", "not_found", "error_page"}


def isolated_settings(configured, database, stage):
    if stage not in STAGE_SOURCES:
        raise ValueError("Unknown continuation stage")
    values = {name: value for name, value in base.OVERRIDES.items()
              if name not in {"search_provider", "bilibili_search_provider", "bilibili_search_rounds"}}
    values.update(mooc_search_provider=STAGE_SOURCES[stage], max_search_requests=18,
                  max_detail_pages=36, deadline_seconds=360, mooc_target_courses_per_point=3)
    # This last stage measures library reuse only; it must not lease a due
    # refresh or turn an intentionally disabled search into a source failure.
    if stage == "warm":
        values["mooc_refresh_enabled"] = False
    return replace(configured, database_path=str(database), **values).validate()


def _mooc_url(value):
    try:
        return urlsplit(value or "").hostname in {"icourse163.org", "www.icourse163.org"}
    except ValueError:
        return False


def _policy_was_local(resource, evidence):
    fields = resource.get("field_provenance")
    if not isinstance(fields, dict) or not isinstance(evidence, list):
        return False
    provenance = fields.get("fetch_status", {})
    if not isinstance(provenance, dict):
        return False
    for row in evidence:
        if not isinstance(row, dict):
            continue
        sent = row.get("restricted_target_request_sent", row.get("blocked_target_request_sent"))
        if (row.get("evidence_id") == provenance.get("evidence_id") and row.get("kind") == "site_policy"
                and row.get("source") == "official_policy_review" and provenance.get("source") == "official_policy_review"
                and row.get("blocked_target_url") == resource.get("url") and sent is False
                and row.get("restricted_target_http_status") is None and public_course_url(resource.get("url"))):
            return True
    return False


def audit_prior_evidence(prior):
    """Fail closed on missing/incomplete evidence or unresolved source stops."""
    prior = Path(prior).resolve()
    report = {"allowed": False, "files": {}, "stages": [], "reasons": [], "local_route_rejections": 0}
    for stage in PRIOR_STAGES:
        documents = {}
        for name in ("summary", "job", "search_attempts", "resources", "evidence", "network"):
            path = prior / stage / (name + ".json")
            try:
                raw = path.read_bytes()
                if len(raw) > 40_000_000:
                    raise ValueError("Oversized prior evidence")
                documents[name] = json.loads(raw)
                report["files"][stage + "/" + path.name] = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError, TypeError):
                report["reasons"].append(stage + ":missing_or_invalid_" + name)
        if len(documents) != 6:
            continue
        summary, job, attempts, resources, evidence, network = (documents[name] for name in
            ("summary", "job", "search_attempts", "resources", "evidence", "network"))
        if not (isinstance(summary, dict) and isinstance(job, dict) and isinstance(attempts, list)
                and isinstance(resources, dict) and isinstance(evidence, dict) and isinstance(network, dict)):
            report["reasons"].append(stage + ":invalid_document_shape")
            continue
        if (summary.get("job_terminal") is not True or summary.get("error_type") is not None
                or job.get("status") in {None, "queued", "running"} or job.get("phase") != "done"):
            report["reasons"].append(stage + ":incomplete_job")
        sources = summary.get("source_states")
        if not isinstance(sources, dict):
            report["reasons"].append(stage + ":missing_source_states")
            sources = {}
        for source in ("tavily", "serper"):
            state = sources.get(source)
            if state is None and source == "serper" and stage == "route-recheck/sql":
                continue
            if (not isinstance(state, dict) or state.get("source_access_denied") is not False
                    or state.get("source_cooldown_seconds") != 0 or state.get("quota_exhausted") is True):
                report["reasons"].append(stage + ":restricted_or_unknown_" + source)
        requests = 0
        for attempt in attempts:
            if not isinstance(attempt, dict):
                report["reasons"].append(stage + ":invalid_attempt")
                continue
            if attempt.get("provider") not in {"tavily", "serper"}:
                continue
            if attempt.get("error_code") in RESTRICTED or attempt.get("status") in {"running", "cancelled"}:
                report["reasons"].append(stage + ":restricted_or_incomplete_attempt")
            traces = attempt.get("provider_requests")
            if not isinstance(traces, list) or (attempt.get("network_attempted") and not traces):
                report["reasons"].append(stage + ":missing_provider_trace")
                continue
            for trace in traces:
                requests += 1
                if (not isinstance(trace, dict) or trace.get("http_status") != 200
                        or trace.get("status") != "completed" or trace.get("error_code")):
                    report["reasons"].append(stage + ":restricted_or_uncertain_provider_response")
        responses = network.get("responses")
        if not isinstance(responses, list):
            report["reasons"].append(stage + ":missing_network_responses")
            responses = []
        for response in responses:
            if not isinstance(response, dict):
                report["reasons"].append(stage + ":invalid_network_response")
                continue
            if _mooc_url(response.get("url")) and response.get("http_status") not in {200, 404, 410}:
                report["reasons"].append(stage + ":restricted_or_uncertain_target_response")
        mooc_resources = 0
        for rid, resource in resources.items():
            if not isinstance(resource, dict):
                report["reasons"].append(stage + ":invalid_resource")
                continue
            if not _mooc_url(resource.get("url")):
                continue
            mooc_resources += 1
            status = resource.get("fetch_status")
            if status not in SAFE_PRIOR_MOOC_STATES:
                report["reasons"].append(stage + ":restricted_or_unknown_mooc_resource")
            elif status == "policy_unreviewed":
                if _policy_was_local(resource, evidence.get(rid, [])):
                    report["local_route_rejections"] += 1
                else:
                    report["reasons"].append(stage + ":policy_rejection_not_proven_local")
        controls = summary.get("fetch_host_controls", network.get("host_controls", {}))
        if not isinstance(controls, dict) or (controls and (controls.get("blocked_hosts") or controls.get("paused_hosts"))):
            report["reasons"].append(stage + ":retained_host_restriction")
        report["stages"].append({"stage": stage, "mooc_provider_http": requests, "mooc_resources": mooc_resources,
            "source_states": sources, "network_response_count": len(responses),
            "target_requests_all_platforms": network.get("target_http_requests")})
    report["reasons"] = sorted(set(report["reasons"]))
    report["allowed"] = not report["reasons"] and len(report["stages"]) == len(PRIOR_STAGES)
    report["scope"] = "Prior MOOC search/fetch controls audited; Bilibili is never requested by this continuation."
    return report


class SourceLedger:
    def __init__(self):
        self.stage = "cache_tavily"
        self.total = {"tavily": 0, "serper": 0, "bilibili": 0}
        self.stages = {}
        self.blocked_dispatches = {}
        self.on_change = lambda: None

    def install(self, providers):
        for name, provider in providers.items():
            original = provider.query_scope
            def scope(hook, *, source=name, original_scope=original):
                async def reserve():
                    allowed = self.stage in {"tavily_mooc", "serper_mooc"} and STAGE_SOURCES[self.stage] == source
                    if not allowed or self.total[source] >= SOURCE_CAPS[source]:
                        self.blocked_dispatches[self.stage] = self.blocked_dispatches.get(self.stage, 0) + 1
                        self.on_change()
                        raise SearchBudgetReached()
                    if hook:
                        await hook()
                    self.total[source] += 1
                    per_stage = self.stages.setdefault(self.stage, {"tavily": 0, "serper": 0, "bilibili": 0})
                    per_stage[source] += 1
                    self.on_change()
                return original_scope(reserve)
            provider.query_scope = scope

    def snapshot(self):
        return {"current_stage": self.stage, "actual_dispatch_reservations": dict(self.total),
                "stage_reservations": {name: dict(value) for name, value in self.stages.items()},
                "blocked_before_dispatch": dict(self.blocked_dispatches), "caps": SOURCE_CAPS,
                "cache_only_actual_search_cap": 0, "warm_actual_search_cap": 0}


class DisabledSource:
    """No external client for an unselected platform/provider."""
    name = "disabled_unselected_source"
    async def search(self, *args, **kwargs):
        raise SearchError("unselected_source_disabled", "This verification only permits MOOC discovery")


def numeric_coverage(service):
    result = []
    for index, text in enumerate(POINTS):
        hits = service.course_library.lookup({"knowledge_point_id": "numeric-" + str(index), "text": text},
            service._course_library_profile(), limit=service.settings.shared_course_library_max_candidates)
        courses = {}
        for hit in hits:
            identity = course_identity_parts(hit["resource"].get("url"))
            if identity:
                key = str(int(identity["course_id"]))
                courses.setdefault(key, {"course_id": key, "title": hit["resource"].get("title"),
                    "url": hit["resource"]["url"], "entry_key": hit["entry_key"]})
        result.append({"text": text, "qualified_count": len(courses), "target": 3,
                       "remaining": max(0, 3 - len(courses)), "courses": list(courses.values())})
    return result


def displayed_numeric_coverage(service, job_id):
    result = []
    names = {row["knowledge_point_id"]: row["text"] for row in service.store.get_job(job_id)["knowledge_points"]}
    for group in (service.results(job_id) or {}).get("groups", []):
        identifiers = set()
        for item in group.get("discovery_platform_items", {}).get("icourse163", []):
            identity = course_identity_parts(item.get("resource", {}).get("url"))
            if identity:
                identifiers.add(str(int(identity["course_id"])))
        result.append({"text": names[group["knowledge_point_id"]], "qualified_count": len(identifiers),
                       "course_ids": sorted(identifiers)})
    return result


def _paths(output, source_database, prior_evidence):
    output = Path(output).resolve()
    source, prior = Path(source_database), Path(prior_evidence)
    if not source.is_absolute() or not source.is_file() or not prior.is_absolute() or not prior.is_dir():
        raise ValueError("Source database and prior evidence must be explicit existing absolute paths")
    if output.is_relative_to(ROOT):
        raise ValueError("Output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    return output, source.resolve(), prior.resolve()


def clone_database(source, destination):
    reader = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    writer = sqlite3.connect(destination)
    try:
        reader.execute("PRAGMA query_only=ON")
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()
    return hashlib.sha256(destination.read_bytes()).hexdigest()


async def run(output, *, source_database, prior_evidence, live=False, confirm_serper_free_trial=False, configured=None):
    output, source, prior = _paths(output, source_database, prior_evidence)
    plan = {"schema_version": 1, "created_at": now(), "mode": "live" if live else "dry_run", "knowledge_points": POINTS,
        "source_database": str(source), "prior_evidence": str(prior), "source_request_caps": SOURCE_CAPS,
        "stages": list(STAGE_SOURCES), "prior_database_cloned": True, "cache_seeded": True,
        "manually_seeded_urls": False, "new_search_free_allowance_required": {"tavily": 18, "serper": 18},
        "max_detail_pages_per_stage": 36, "max_detail_pages_discovery_total": 144,
        "deadline_seconds_per_stage": 360, "mooc_rounds": 6, "results_per_query": 10,
        "target": "Three distinct numeric course IDs per point, each independently outline supported",
        "source_objects_shared": True, "renderer": "Configured profile retained across every stage",
        "warm_refresh": "Disabled only for zero-search library verification; no refresh timestamp is synthesized",
        "stream_transport": "Production SSE generator in process; no browser latency claim",
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in (*base.SOURCE_FILES, "backend/app/source_adapters/icourse163.py",
                                       "backend/app/mooc_urls.py", "scripts/verify_mooc_target_three_live.py")}}
    atomic_json(output / "plan.json", plan)
    summary = {"status": "dry_run", "started_at": now(), "stages": {}, "usage_http_requests": 0,
        "search_http_requests": 0, "detail_target_http_requests": 0, "bilibili_search_requests": 0,
        "all_tests_finished": False, "all_points_at_target": False, "warm_demonstrated": False,
        "llm_calls": 0, "billing_changes": False, "precision": "unknown", "recall": "unknown"}
    secrets = ()
    def save(name, value):
        atomic_json(output / name, scrub(value, secrets))
    if not live:
        save("summary.json", summary)
        return summary
    configured = configured or Settings.from_env()
    secrets = tuple(value for value in (configured.tavily_api_key, configured.serper_api_key, configured.llm_api_key) if value)
    save("plan.json", plan)
    if not configured.tavily_api_key.strip() or not configured.serper_api_key.strip() or not confirm_serper_free_trial:
        summary.update(status="preflight_blocked", reason="free_source_configuration_or_confirmation_missing")
        save("summary.json", summary)
        return scrub(summary, secrets)
    audit = audit_prior_evidence(prior)
    save("prior-evidence-audit.json", audit)
    expected_source = prior / "route-recheck" / "library.sqlite3"
    if not audit["allowed"] or not expected_source.is_file() or not source.samefile(expected_source):
        summary.update(status="preflight_blocked", reason="prior_restriction_or_incomplete_evidence" if not audit["allowed"] else "source_evidence_mismatch")
        save("summary.json", summary)
        return scrub(summary, secrets)
    usage = await fetch_tavily_usage(configured.tavily_api_key)
    summary.update(usage_http_requests=1, tavily_free_usage=usage)
    if not base.sufficient_free_usage(usage):
        summary.update(status="preflight_blocked", reason="eighteen_free_tavily_credits_not_verified")
        save("summary.json", summary)
        return scrub(summary, secrets)
    ledger, service = SourceLedger(), None
    cancelled = None
    with TemporaryDirectory(prefix="mooc-target-three-") as temporary:
        database = Path(temporary) / "library.sqlite3"
        summary["cloned_database_sha256"] = clone_database(source, database)
        settings = isolated_settings(configured, database, "cache_tavily")
        store = Store(str(database))
        try:
            if store.connection.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued') LIMIT 1").fetchone():
                raise ValueError("Prior database has an unfinished job")
            fetcher = make_fetcher(settings)
            providers = {name: build_provider(settings, fetcher=fetcher, store=store, provider_name=name)
                         for name in ("tavily", "serper")}
            ledger.install(providers)
            overrides = {settings.search_provider: DisabledSource(), settings.search_provider_for("bilibili"): DisabledSource(), **providers}
            service = JobService(settings, store, fetcher=fetcher, provider_overrides=overrides)
            service._providers.update(providers)
            service._provider_errors.update({name: None for name in providers})
            assert service.llm is None and fetcher.config.max_retries == 0 and POINTS == base.POINTS
            renderer = getattr(fetcher, "renderer", None)
            summary.update(status="running", initial_coverage=numeric_coverage(service),
                           previous_restrictions="No unresolved MOOC provider/host stop found in required prior evidence.")
            original_save = service._save
            def journal(job):
                original_save(job)
                folder = output / ledger.stage
                if folder.is_dir():
                    for name, value in (("job", job), ("search_attempts", store.attempts(job["job_id"])),
                                        ("source-ledger", ledger.snapshot()), ("host-controls", fetch_controls(fetcher))):
                        atomic_json(folder / (name + ".json"), scrub(value, secrets))
            service._save = journal
            save("summary.json", summary)
            for stage in ("cache_tavily", "cache_serper", "tavily_mooc", "serper_mooc"):
                service.settings = isolated_settings(configured, database, stage)
                ledger.stage = stage
                assert service.fetcher is fetcher and getattr(fetcher, "renderer", None) is renderer
                phase = await base.run_stage(service, store, output / stage, stage, secrets, ledger, summary["stages"])
                phase["numeric_library_coverage"] = numeric_coverage(service)
                phase["displayed_numeric_coverage"] = displayed_numeric_coverage(service, phase["job_id"])
                phase["fetch_host_controls"] = fetch_controls(fetcher)
                phase["cache_only"] = stage.startswith("cache_")
                save(stage + "/summary.json", phase)
                save("summary.json", summary)
                if not phase["job_terminal"]:
                    raise RuntimeError("Continuation stage did not terminate")
            coverage = numeric_coverage(service)
            if len(coverage) == len(POINTS) and all(row["qualified_count"] >= 3 for row in coverage):
                service.settings = isolated_settings(configured, database, "warm")
                ledger.stage = "warm"
                warm = await base.run_stage(service, store, output / "warm", "warm", secrets, ledger, summary["stages"])
                warm["numeric_library_coverage"] = numeric_coverage(service)
                warm["displayed_numeric_coverage"] = displayed_numeric_coverage(service, warm["job_id"])
                summary["warm_demonstrated"] = (warm["job_terminal"] and warm["search_http_requests"] == 0
                    and warm["detail_target_http_requests"] == 0
                    and len(warm["per_point"]) == len(POINTS) and all(row["library_cards"] >= 3 for row in warm["per_point"])
                    and len(warm["displayed_numeric_coverage"]) == len(POINTS)
                    and all(row["qualified_count"] >= 3 for row in warm["displayed_numeric_coverage"])
                    and warm["stream"]["first_library_card_ms"] is not None
                    and warm["stream"]["displayed_mooc_without_outline_count"] == 0)
                save("warm/summary.json", warm)
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
            summary["search_http_requests"] = sum(ledger.total.values())
            summary["detail_target_http_requests"] = sum(row.get("detail_target_http_requests", 0) for row in summary["stages"].values())
            if service is not None:
                summary["library_coverage"] = numeric_coverage(service)
                summary["all_points_at_target"] = len(summary["library_coverage"]) == len(POINTS) and all(
                    row["qualified_count"] >= 3 for row in summary["library_coverage"])
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
    parser.add_argument("--confirm-serper-free-trial", action="store_true", help="Confirm at least 18 remaining free trial credits")
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
        print("Verification could not start; inspect explicit paths and configuration. Secrets are not printed.")
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] in {"harness_error", "preflight_blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
