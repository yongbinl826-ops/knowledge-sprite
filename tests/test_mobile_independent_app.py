"""Real application + ASGI synthetic boundary controls, no real upstream."""
import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("MOBILE_AUDIT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))
SPEC = importlib.util.spec_from_file_location("mobile_boundary_app_probe", ROOT / "scripts/validate_mobile_boundary.py")
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def run(coro):
    with probe.LoopbackOnly() as guard:
        result = asyncio.run(coro)
        assert guard.blocked == 0
        return result


async def client_for(app, peer="127.0.0.1"):
    import httpx
    return httpx.AsyncClient(base_url="http://127.0.0.1", trust_env=False,
        transport=httpx.ASGITransport(app=app, client=(peer, 12345)))


def test_actual_app_capability_isolation_legacy_and_bounded_body(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "protocol", {"hold_search": True})
        checks = probe.Checks()
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                first, second = await probe.capability_protocol(client, checks)
                records = app.state.mobile.records
                checks.check("different_tasks_do_not_share_private_job",
                             records[first.task_id]["job_id"] != records[second.task_id]["job_id"])
                await probe.ingress_and_legacy(client, checks, app.state.fixture_settings.max_request_body_bytes)
                assert app.state.store.connection.execute("PRAGMA database_list").fetchall()[0][2] == ""
                assert app.state.fixture_legacy_trap.read_bytes() == b"SYNTHETIC_LEGACY_DATABASE_MUST_NOT_OPEN"
                for response in [await client.get("/api/mobile/tasks/" + second.task_id, headers=second.headers),
                                 await client.get("/api/mobile/courses")]:
                    assert response.headers.get("cache-control") == "no-store"
                assert all(row["pass"] for row in checks.rows), [row for row in checks.rows if not row["pass"]]
                receipt = checks.receipt()
                (tmp_path / "protocol-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
    run(execute())


def test_idle_cleanup_physically_erases_private_RAM_without_a_request(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "ttl", {"hold_search": True})
        async with app.router.lifespan_context(app):
            manager = app.state.mobile
            async with await client_for(app) as client:
                ticket = probe.Ticket.fresh()
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"],
                    "project_context": "TTL_PRIVATE_SENTINEL", "preferred_platforms": ["bilibili"]}}
                response = await client.post(ticket.path, headers=ticket.headers, json=payload)
                assert response.status_code == 202
                await asyncio.wait_for(app.state.fixture_world.search_entered.wait(), 2)
                expired_now = manager.records[ticket.task_id]["expires_at"] + 1
                manager.clock = lambda: expired_now
                # No HTTP request or manual cleanup call during this wait.
                deadline = asyncio.get_running_loop().time() + 2
                while ticket.task_id in manager.records:
                    assert asyncio.get_running_loop().time() < deadline, "idle cleaner did not erase expired data"
                    await asyncio.sleep(.025)
                for table in ["jobs", "knowledge_points", "resources", "matches", "evidence", "search_attempts", "cache", "idempotency_keys", "job_consumers",
                              "projects", "project_versions", "project_functions", "project_knowledge_points", "project_prerequisites", "project_batches", "project_point_job_mappings"]:
                    assert app.state.store.connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0, table
                assert not app.state.service.active_tasks
                assert app.state.service.queue.qsize() == 0
                assert ticket.task_id in manager.tombstones
                manager.clock = lambda: 0  # clock rollback cannot revive a tombstone
                assert (await client.get(ticket.path, headers=ticket.headers)).status_code == 404
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 404
                assert not (tmp_path / "ttl/legacy-trap.sqlite3-wal").exists()
    run(execute())


def test_daily_budget_survives_cancel_and_restart_without_private_rows(tmp_path):
    async def execute():
        output = tmp_path / "restart"
        app = probe.create_fixture_app(SOURCE, output, {"hold_search": True}, {"mobile_daily_tasks": 1})
        ticket = probe.Ticket.fresh()
        payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"],
                   "project_context": "RESTART_PRIVATE_SENTINEL", "preferred_platforms": ["bilibili"]}}
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                budget_before = [tuple(row) for row in app.state.mobile.public.connection.execute("SELECT * FROM mobile_daily_budget")]
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                assert (await client.post(ticket.path + "/cancel", headers=ticket.headers)).status_code == 200
                assert [tuple(row) for row in app.state.mobile.public.connection.execute("SELECT * FROM mobile_daily_budget")] == budget_before
                assert probe.public_rows_do_not_contain_private_markers(app.state.mobile.public.connection, [ticket.cap, ticket.task_id, "RESTART_PRIVATE_SENTINEL"])
        # Reuse only the synthetic public DB, not the old in-memory Store.
        app2 = probe.create_fixture_app(SOURCE, tmp_path / "restart-app2", {"hold_search": True}, {
            "mobile_public_database_path": str(output / "public.sqlite3"), "mobile_daily_tasks": 1})
        async with app2.router.lifespan_context(app2):
            async with await client_for(app2) as client:
                assert (await client.get(ticket.path, headers=ticket.headers)).status_code == 404
                new = probe.Ticket.fresh()
                denied = await client.post(new.path, headers=new.headers, json=payload)
                assert denied.status_code == 429 and denied.json()["code"] == "daily_budget_exhausted"
                assert denied.headers.get("Retry-After")
                assert [tuple(row) for row in app2.state.mobile.public.connection.execute("SELECT * FROM mobile_daily_budget")] == budget_before
                assert app2.state.fixture_world.calls == []
    run(execute())


def test_same_peer_xff_cannot_bypass_creation_cap_and_cancel_remains_available(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "peer", {"hold_search": True}, {"mobile_per_ip_tasks_per_minute": 2})
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"], "preferred_platforms": ["bilibili"]}}
                tickets = [probe.Ticket.fresh() for _ in range(3)]
                responses = [await client.post(ticket.path, headers={**ticket.headers, "X-Forwarded-For": f"198.51.100.{index + 1}"}, json=payload)
                             for index, ticket in enumerate(tickets)]
                assert [r.status_code for r in responses] == [202, 202, 429]
                assert responses[-1].headers.get("Retry-After")
                assert (await client.post(tickets[0].path + "/cancel", headers=tickets[0].headers)).status_code == 200
                assert len(app.state.mobile.ip_buckets) == 1
    run(execute())


def test_stable_task_reads_do_not_rewrite_public_course_rows(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "memo", {"empty_search": True})
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                resource, evidence = probe.seed_public_fixture(app)
                ticket = probe.Ticket.fresh()
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"], "preferred_platforms": ["bilibili"]}}
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                # Attach the own metadata observation to the task's real RAM job.
                jid = app.state.mobile.records[ticket.task_id]["job_id"]
                resource["resource_id"] = "synthetic-own-source"
                app.state.store.save_resource(jid, resource)
                for row in evidence:
                    app.state.store.add_evidence(jid, resource["resource_id"], None, row)
                await app.state.mobile.cleanup_once(observe=True)
                before = app.state.mobile.public.connection.total_changes
                statements = []
                app.state.mobile.public.connection.set_trace_callback(statements.append)
                for _ in range(5):
                    assert (await client.get(ticket.path, headers=ticket.headers)).status_code == 200
                assert app.state.mobile.public.connection.total_changes == before, "stable reads amplified public DB writes"
                writes = [sql for sql in statements if sql.split()[0].upper() in {"BEGIN", "INSERT", "UPDATE", "DELETE", "COMMIT"}]
                assert writes == [], "stable reads acquired public write transactions"
                app.state.mobile.public.connection.set_trace_callback(None)
                # A genuine later own observation remains publishable. No
                # search/client field is used to manufacture this title.
                from backend.app.extractor import MetadataExtractor
                from datetime import datetime, timezone
                observed = datetime.now(timezone.utc).timestamp() + 1
                app.state.mobile.public.clock = lambda: observed + 1
                newer = MetadataExtractor().extract(probe.fixture_page(resource["url"], "Synthetic later own Python course"),
                                                    resource["url"], datetime.fromtimestamp(observed, timezone.utc).isoformat())
                new_evidence = newer.pop("evidence")
                updated = {**newer, "url": resource["url"], "canonical_url": resource["url"],
                           "platform": "bilibili", "resource_id": resource["resource_id"]}
                app.state.store.save_resource(jid, updated)
                for row in new_evidence:
                    app.state.store.add_evidence(jid, resource["resource_id"], None, row)
                await app.state.mobile.cleanup_once(observe=True)
                assert app.state.mobile.public.browse()["items"][0]["title"] == "Synthetic later own Python course"
    run(execute())


def test_private_network_candidate_is_not_sent_to_fetcher(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "ssrf", {"search_url": "http://127.0.0.1/private"})
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                ticket = probe.Ticket.fresh()
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"], "preferred_platforms": ["bilibili"]}}
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                deadline = asyncio.get_running_loop().time() + 3
                while True:
                    response = await client.get(ticket.path, headers=ticket.headers)
                    assert response.status_code == 200
                    if response.json()["status"] not in {"running", "queued"}: break
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(.025)
                assert app.state.fixture_world.metadata_calls == 0
                assert app.state.store.connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0
                assert app.state.mobile.public.browse()["total"] == 0
    run(execute())


def test_task_capacity_and_ip_bucket_capacity_stay_bounded(tmp_path):
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "capacity", {"hold_search": True}, {
            "mobile_max_tasks": 2, "mobile_max_active_tasks": 2, "mobile_max_ip_buckets": 16, "local_only": False})
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"], "preferred_platforms": ["bilibili"]}}
                tickets = [probe.Ticket.fresh() for _ in range(3)]
                responses = [await client.post(ticket.path, headers=ticket.headers, json=payload) for ticket in tickets]
                assert [r.status_code for r in responses] == [202, 202, 429]
                assert responses[-1].json()["code"] == "task_capacity"
                assert responses[-1].headers.get("Retry-After")
                assert len(app.state.mobile.records) == 2
                assert app.state.mobile.public.connection.execute("SELECT tasks FROM mobile_daily_budget").fetchone()[0] == 2
            # Exercise real ASGI peer addresses, not XFF values. An unfamiliar
            # peer after the bounded map fills must fail without map growth.
            for index in range(16):
                async with await client_for(app, f"198.51.100.{index+1}") as client:
                    response = await client.get("/api/mobile/courses")
                    assert response.status_code in {200, 429}
            assert len(app.state.mobile.ip_buckets) <= 16
            async with await client_for(app, "203.0.113.1") as client:
                response = await client.get("/api/mobile/courses")
                assert response.status_code == 429 and response.headers.get("Retry-After")
            assert len(app.state.mobile.ip_buckets) == 16
    run(execute())


def test_server_access_logs_do_not_record_capability_or_private_payload(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="knowledge_sprite.http")
    async def execute():
        app = probe.create_fixture_app(SOURCE, tmp_path / "logging", {"hold_search": True})
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                ticket = probe.Ticket.fresh()
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"],
                    "project_context": "PRIVATE_LOG_SENTINEL", "preferred_platforms": ["bilibili"]}}
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                assert (await client.get(ticket.path, headers=ticket.headers)).status_code == 200
                assert (await client.get(ticket.path + "?token=" + ticket.cap)).status_code == 404
                records = [record.getMessage() for record in caplog.records if record.name == "knowledge_sprite.http"]
                assert records
                text = "\n".join(records)
                assert ticket.cap not in text and "PRIVATE_LOG_SENTINEL" not in text
                assert ticket.task_id not in text
                assert "/api/mobile/tasks/{identifier}" in text
    run(execute())
