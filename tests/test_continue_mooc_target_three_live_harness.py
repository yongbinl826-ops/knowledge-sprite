"""Offline synthetic continuation tests; these are not real recall evidence."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.providers import SearchBudgetReached, TavilyProvider
from scripts import continue_mooc_target_three_live as harness
from test_mooc_gaps_live_harness import configuration, install_sources


@pytest.fixture(autouse=True)
def no_environment_or_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline harness test read credentials or attempted network")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def prior(tmp_path):
    root = tmp_path / "parent"
    root.mkdir()
    source = root / "library.sqlite3"
    store = Store(str(source))
    store.connection.execute("CREATE TABLE original_private(value TEXT)")
    store.connection.execute("INSERT INTO original_private VALUES('leave unchanged')")
    states = {name: {"source_access_denied": False, "source_cooldown_seconds": 0, "engine_cooldowns": {}}
              for name in ("tavily", "serper")}
    controls = {"blocked_hosts": [], "paused_hosts": []}
    final = {"status": "finished_with_gaps", "all_tests_finished": True, "source_states": states,
        "fetch_host_controls": controls, "search_http_requests": 6, "stages": {}}
    running, stages, blocked = dict.fromkeys(harness.SOURCE_CAPS, 0), {}, {}
    for stage in harness.PRIOR_STAGES:
        folder = root / stage
        folder.mkdir()
        provider = harness.parent.STAGE_SOURCES[stage]
        counts = dict.fromkeys(harness.SOURCE_CAPS, 0)
        if stage.startswith("cache_"):
            blocked[stage] = 1
            attempts = [{"provider": provider, "status": "failed", "error_code": "query_budget_exhausted",
                         "network_attempted": False, "provider_requests": []}]
        else:
            counts[provider] = 3
            stages[stage] = counts
            attempts = [{"provider": provider, "status": "completed", "network_attempted": True,
                "provider_requests": [{"provider": provider, "http_status": 200, "status": "completed", "api_credits": 1}]} for _ in range(3)]
        running = {name: running[name] + counts[name] for name in running}
        job = {"job_id": stage, "status": "completed", "phase": "done"}
        summary = {"job_id": stage, "job_terminal": True, "error_type": None, "source_states": states,
            "fetch_host_controls": controls, "search_http_requests": sum(counts.values()), "detail_target_http_requests": 0,
            "sources": {name: {"http_requests": counts.get(name, 0)} for name in ("tavily", "serper", "searxng")}}
        ledger = {"caps": harness.SOURCE_CAPS, "actual_dispatch_reservations": running,
                  "stage_reservations": deepcopy(stages), "blocked_before_dispatch": deepcopy(blocked)}
        docs = {"summary": summary, "job": job, "search_attempts": attempts, "resources": {}, "evidence": {},
                "network": {"target_http_requests": 0, "responses": []}, "source-ledger": ledger}
        for name, value in docs.items():
            dump(folder / (name + ".json"), value)
        final["stages"][stage] = summary
        store.connection.execute("INSERT INTO jobs(id,status,data) VALUES(?,?,?)", (stage, "completed", json.dumps(job)))
        for attempt in attempts:
            store.connection.execute("INSERT INTO search_attempts(job_id,data) VALUES(?,?)", (stage, json.dumps(attempt)))
    store.connection.commit()
    store.close()
    final["source_ledger"] = ledger
    final["database_backup"] = {"status": "saved", "filename": "library.sqlite3", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    final["stages"]["warm"] = {"status": "not_demonstrated", "search_http_requests": 0, "detail_target_http_requests": 0}
    dump(root / "summary.json", final)
    dump(root / "plan.json", {"mode": "live", "knowledge_points": harness.POINTS, "mooc_rounds": 6,
        "stages": [*harness.PRIOR_STAGES, "warm"], "source_request_caps": harness.SOURCE_CAPS,
        "source_sha256": {name: hashlib.sha256((harness.ROOT / name).read_bytes()).hexdigest() for name in harness.PARENT_SOURCE_FILES}})
    return root, source


def change(root, path, update):
    path = root / path
    value = json.loads(path.read_text(encoding="utf-8"))
    update(value)
    dump(path, value)


def install(monkeypatch, **options):
    result = install_sources(monkeypatch, **options)
    for name in ("build_provider", "JobService", "make_fetcher", "fetch_tavily_usage"):
        monkeypatch.setattr(harness, name, getattr(harness.base, name))
    return result


@pytest.mark.asyncio
async def test_dry_run_is_read_only_and_records_inherited_remaining_allowance(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    before = source.read_bytes()
    monkeypatch.setattr(harness, "Store", lambda *_: pytest.fail("Writable Store in dry run"))
    monkeypatch.setattr(harness, "fetch_tavily_usage", lambda *_: pytest.fail("Quota in dry run"))
    output = tmp_path / "dry"
    result = await harness.run(output, source_database=source, prior_evidence=evidence)
    assert result["status"] == "dry_run" and result["search_http_requests"] == result["usage_http_requests"] == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    audit = json.loads((output / "prior-evidence-audit.json").read_text(encoding="utf-8"))
    assert audit["allowed"] and plan["remaining_new_requests"] == {"tavily": 15, "serper": 15, "bilibili": 0}
    assert plan["query_admission_per_stage"] == 30 and plan["mooc_rounds"] == 10
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        await harness.run(output, source_database=source, prior_evidence=evidence)
    with pytest.raises(ValueError):
        await harness.run(harness.ROOT / "never-create", source_database=source, prior_evidence=evidence)
    with pytest.raises(ValueError):
        await harness.run(tmp_path / "relative", source_database=Path("relative.sqlite3"), prior_evidence=evidence)


def test_settings_preserve_profile_renderer_bilibili_configuration_and_disable_warm_refresh(tmp_path):
    config = configuration(tmp_path, bilibili_search_provider="searxng", bilibili_search_rounds=4,
                           js_render_enabled=True, js_render_max_target_requests=13)
    for stage in (*harness.STAGES, "warm"):
        settings = harness.isolated_settings(config, tmp_path / "clone.sqlite3", stage)
        assert settings.mooc_search_rounds == 10 and settings.max_search_requests == 30
        assert settings.max_detail_pages == 36 and settings.deadline_seconds == 360
        assert settings.mooc_target_courses_per_point == 3 and settings.search_results_per_query == 10
        assert settings.bilibili_search_provider == config.bilibili_search_provider and settings.bilibili_search_rounds == 4
        assert settings.js_render_enabled and settings.js_render_max_target_requests == 13
        assert settings.mooc_refresh_enabled is (stage != "warm")
        assert settings.llm_provider == "none" and not settings.llm_api_key
        assert not settings.public_catalog_fallback and not settings.official_sitemap_fallback


def test_audit_accepts_only_documented_local_predispatch_failures_and_authorized_source_changes(tmp_path):
    evidence, source = prior(tmp_path)
    audit = harness.audit_prior_evidence(evidence, source)
    assert audit["allowed"] and audit["used"] == {"tavily": 3, "serper": 3, "bilibili": 0}
    assert sum(stage["intentional_predispatch_blocks"] for stage in audit["stages"]) == 2
    change(evidence, "plan.json", lambda d: d["source_sha256"].update({name: "0" * 64 for name in harness.AUTHORIZED_CHANGED_FILES}))
    audit = harness.audit_prior_evidence(evidence, source)
    assert audit["allowed"] and set(audit["source_changes"]) == harness.AUTHORIZED_CHANGED_FILES


@pytest.mark.parametrize("damage", ["missing", "incomplete", "source_stop", "host_stop", "hash", "db_sha", "ledger",
    "db_attempt", "provider429", "target403", "unproven_policy", "unfinished_response", "uncertain_attempt", "wrong_source"])
def test_audit_rejects_restrictions_unknown_evidence_and_budget_or_source_mismatches(tmp_path, damage):
    evidence, source = prior(tmp_path)
    if damage == "missing":
        (evidence / "tavily_mooc/network.json").unlink()
    elif damage == "incomplete":
        change(evidence, "summary.json", lambda d: d.update(all_tests_finished=False))
    elif damage == "source_stop":
        change(evidence, "summary.json", lambda d: d["source_states"]["tavily"].update(source_access_denied=True))
    elif damage == "host_stop":
        change(evidence, "summary.json", lambda d: d["fetch_host_controls"]["paused_hosts"].append("www.icourse163.org"))
    elif damage == "hash":
        change(evidence, "plan.json", lambda d: d["source_sha256"].update({"backend/app/providers.py": "0" * 64}))
    elif damage == "db_sha":
        change(evidence, "summary.json", lambda d: d["database_backup"].update(sha256="0" * 64))
    elif damage == "ledger":
        change(evidence, "summary.json", lambda d: d["source_ledger"]["actual_dispatch_reservations"].update(tavily=0))
    elif damage in {"db_attempt", "provider429", "uncertain_attempt"}:
        change(evidence, "tavily_mooc/search_attempts.json", lambda d: d[0].update(status="running") if damage == "uncertain_attempt"
               else d[0]["provider_requests"][0].update(http_status=429) if damage == "provider429" else d.pop())
    elif damage == "target403":
        change(evidence, "serper_mooc/network.json", lambda d: d["responses"].append({"url": "https://www.icourse163.org/course/X-123", "http_status": 403}))
    elif damage == "unproven_policy":
        change(evidence, "serper_mooc/resources.json", lambda d: d.update(r={"url": "https://www.icourse163.org/course/X-123", "fetch_status": "policy_unreviewed"}))
    elif damage == "unfinished_response":
        change(evidence, "cache_serper/network.json", lambda d: d.update(target_http_requests=1))
    elif damage == "wrong_source":
        wrong = evidence / "other.sqlite3"
        wrong.write_bytes(source.read_bytes())
        source = wrong
    result = harness.audit_prior_evidence(evidence, source)
    assert not result["allowed"] and result["reasons"]


@pytest.mark.asyncio
async def test_bad_evidence_blocks_before_even_read_only_quota_request(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    change(evidence, "summary.json", lambda d: d.update(all_tests_finished=False))
    monkeypatch.setattr(harness, "fetch_tavily_usage", lambda *_: pytest.fail("Quota request before evidence approval"))
    result = await harness.run(tmp_path / "blocked", source_database=source, prior_evidence=evidence,
        live=True, confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "preflight_blocked" and result["usage_http_requests"] == 0


@pytest.mark.parametrize("plan,key,paid,expected", [(15, 15, 0, True), (15, "no_key_limit", 0, True),
    (14, 1000, 0, False), (1000, 14, 0, False), (1000, 1000, 1, False), (True, 1000, 0, False)])
def test_quota_requires_remaining_fifteen_free_credits_not_fresh_eighteen(plan, key, paid, expected):
    assert harness.sufficient_free_usage({"allowed": True, "current_plan": "Researcher", "plan_remaining": plan,
        "key_remaining": key, "paygo_usage": paid, "paygo_limit": None}, 15) is expected


@pytest.mark.asyncio
async def test_ledger_carries_previous_three_and_prevents_sixteenth_new_dispatch():
    provider = TavilyProvider(Settings(tavily_api_key="offline-only", search_min_interval_seconds=0))
    ledger = harness.SourceLedger({"tavily": 3, "serper": 3, "bilibili": 0})
    ledger.install({"tavily": provider})
    for _ in range(15):
        with provider.query_scope(None):
            # Exercise the real provider's hook without an HTTP transport.
            await provider.request_hook()
    assert ledger.snapshot()["continuation_dispatch_reservations"]["tavily"] == 15
    with provider.query_scope(None):
        with pytest.raises(SearchBudgetReached):
            await provider.search("site:icourse163.org/course pandas", "zh", 10, ["icourse163.org"])
    assert not provider.last_requests and ledger.total["tavily"] == 18
    ledger.stage = "warm"
    ledger.total["tavily"] = 3
    with provider.query_scope(None):
        with pytest.raises(SearchBudgetReached):
            await provider.search("site:icourse163.org/course pandas", "zh", 10, ["icourse163.org"])


@pytest.mark.asyncio
async def test_warm_detail_guard_blocks_before_fetcher_or_renderer_is_called():
    async def forbidden(*args, **kwargs):
        pytest.fail("Warm detail reached fetcher")
    fetcher = SimpleNamespace(enrich=forbidden)
    ledger = harness.SourceLedger({"tavily": 3, "serper": 3, "bilibili": 0})
    ledger.stage = "warm"
    harness.install_warm_detail_guard(fetcher, ledger)
    with pytest.raises(RuntimeError):
        await fetcher.enrich({"url": "https://www.icourse163.org/course/X-123"})
    assert ledger.blocked_details == 1


@pytest.mark.asyncio
async def test_mocked_continuation_reuses_source_objects_preserves_parent_and_verifies_warm(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    before = source.read_bytes()
    calls, fetches, providers, services, fetcher = install(monkeypatch)
    output = tmp_path / "continued"
    result = await harness.run(output, source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_at_target" and result["all_tests_finished"] and result["warm_demonstrated"]
    assert source.read_bytes() == before and len(services) == 1 and services[0].fetcher is fetcher
    assert all(services[0]._providers[name] is provider for name, provider in providers.items())
    assert "searxng" not in calls and all("icourse163.org" in url for url in fetches)
    assert result["search_http_requests"] == len(calls) and result["parent_and_continuation_search_http_requests"] == len(calls) + 6
    assert result["source_ledger"]["actual_dispatch_reservations"] == {"tavily": 3 + calls.count("tavily"), "serper": 3 + calls.count("serper"), "bilibili": 0}
    assert all(row["qualified_count"] >= 3 for row in result["library_coverage"])
    assert result["stages"]["warm"]["search_http_requests"] == result["stages"]["warm"]["detail_target_http_requests"] == 0
    assert result["source_ledger"]["warm_detail_calls_blocked_before_dispatch"] == 0
    for stage in (*harness.STAGES, "warm"):
        for name in ("job", "search_attempts", "network", "source-ledger", "resources", "evidence", "stream-events", "summary"):
            assert (output / stage / (name + ".json")).is_file()
    assert result["database_backup"]["sha256"] == hashlib.sha256((output / "library.sqlite3").read_bytes()).hexdigest()
    serialized = json.dumps(result) + "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
    assert not any(key in serialized for key in ("offline-t-key", "offline-s-key", "offline-llm-key"))


@pytest.mark.asyncio
async def test_empty_recall_consumes_at_most_remaining_cap_and_never_claims_coverage(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    calls, *_ = install(monkeypatch, mode="empty")
    result = await harness.run(tmp_path / "empty", source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path))
    assert result["status"] == "finished_with_gaps" and result["all_tests_finished"]
    assert not result["all_points_at_target"] and not result["warm_demonstrated"]
    assert calls.count("tavily") == calls.count("serper") == 15
    assert result["source_ledger"]["actual_dispatch_reservations"] == {"tavily": 18, "serper": 18, "bilibili": 0}
    assert result["stages"]["warm"]["status"] == "not_demonstrated"


@pytest.mark.asyncio
async def test_interruption_keeps_evidence_and_backup_without_starting_next_source(tmp_path, monkeypatch):
    evidence, source = prior(tmp_path)
    started = asyncio.Event()
    calls, *_ = install(monkeypatch, interrupted=started)
    output = tmp_path / "cancelled"
    task = asyncio.create_task(harness.run(output, source_database=source, prior_evidence=evidence, live=True,
        confirm_serper_free_trial=True, configured=configuration(tmp_path)))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["status"] == "interrupted" and not result["all_tests_finished"]
    assert "serper" not in calls and result["database_backup"]["status"] == "saved"
    assert (output / "tavily_mooc/search_attempts.json").is_file()
    assert (output / "tavily_mooc/network.json").is_file()
