"""Real ASGI mobile tasks reuse public facts; no supplier or model transport."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import time

import httpx
import pytest

from backend.app.mobile_public import MobilePublicStore, public_source_snapshot
from backend.app.models import SearchRequest
from backend.app.mooc_refresh import MoocRefresh
from test_course_library import observed
from test_mobile_backend import public_fixture, setup, ticket, settle
from scripts.validate_mobile_boundary import LoopbackOnly


@pytest.fixture(autouse=True)
def no_external_transport():
    with LoopbackOnly() as guard:
        yield
        assert guard.blocked == 0


def source(platform):
    if platform == "icourse163":
        return observed(chapters=("列表", "字典"), title="Python 列表课程", timestamp=time.time()-10)
    return public_fixture()


def test_public_snapshot_removes_personal_ids_and_browse_never_exposes_internal_proofs(tmp_path):
    _, config, _, _ = setup(tmp_path)
    public = MobilePublicStore(config)
    try:
        resource, evidence = source("icourse163")
        resource.update(project_context="PRIVATE_CONTEXT", job_id="PRIVATE_JOB", learning_support={"secret": True})
        for row in evidence:
            row.update(job_id="PRIVATE_JOB", knowledge_point_id="PRIVATE_POINT", query="PRIVATE_QUERY")
        assert public.observe(resource, evidence)
        raw = public.connection.execute("SELECT data FROM mobile_public_courses").fetchone()[0]
        assert "PRIVATE_" not in raw and '"kind":"search"' not in raw
        assert resource["resource_id"] not in raw
        cards = public.browse()["items"]
        assert len(cards) == 1 and "_source_snapshot" not in cards[0]
        point = {"knowledge_point_id": "current", "text": "列表", "technology": "Python"}
        req = SearchRequest(knowledge_points=["列表"], topic_technologies={"列表": "Python"}, preferred_platforms=["icourse163"])
        before = public.connection.total_changes
        assert len(public.lookup(point, req)) == 1
        wrong = {**point, "technology": "JavaScript"}
        wrong_req = req.model_copy(update={"topic_technologies": {"列表": "JavaScript"}})
        assert public.lookup(wrong, wrong_req) == []
        assert public.connection.total_changes == before
    finally:
        public.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["bilibili", "icourse163"])
async def test_default_mobile_new_task_reads_public_library_then_keeps_bounded_gap_search(tmp_path, platform):
    app, config, provider, _ = setup(tmp_path, max_search_requests=10, bilibili_search_rounds=1,
        mooc_search_rounds=3, mooc_target_courses_per_point=1)
    assert config.open_web_search_enabled and config.shared_course_library_enabled
    assert config.mooc_gap_search_enabled and config.mooc_refresh_enabled and config.teaching_match_enabled
    async with app.router.lifespan_context(app):
        manager = app.state.mobile
        assert not provider.calls
        resource, evidence = source(platform)
        assert manager.public.observe(resource, evidence)
        private_trap = tmp_path / "never-open.sqlite3"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1", trust_env=False) as client:
            path, headers = ticket()
            name = "Python list indexing" if platform == "bilibili" else "Python 列表"
            created = await client.post(path, headers=headers, json={"kind": "direct_search", "request": {
                "knowledge_points": [name], "preferred_platforms": ["bilibili", "icourse163"]}})
            assert created.status_code == 202, created.text
            row = await settle(client, path, headers)
            assert row["status"] in {"completed", "partial"}
            result = row["result"]
            group = result["groups"][0]
            assert group["related_recommendations"]
            assert all(ref["reference"]["exact_teaching_verified"] is False for ref in group["related_recommendations"])
            jid = manager.records[path.rsplit("/", 1)[1]]["job_id"]
            job = app.state.store.get_job(jid)
            attempts = app.state.store.attempts(jid)
            assert job["public_library_reuse"]["point_pairs"] == 1
            assert any(a["platform"] == "open_web" and a["domain_filters"] == [] for a in attempts)
            assert all(a["priority_request_limit"] == 1 for a in attempts)
            assert job["progress"]["search_requests"] <= job["budgets"]["max_search_requests"] == 5
            daily = dict(manager.public.connection.execute("SELECT * FROM mobile_daily_budget").fetchone())
            assert daily["search_requests"] == 5
            if platform == "icourse163":
                assert group["outline_evidence_summary"]["qualified_course_count"] == 1
                assert job["progress"]["gap_queries_skipped"] == 2
                assert job["progress"]["search_requests"] == 3
            else:
                assert group["outline_evidence_summary"]["qualified_course_count"] == 0
                assert job["progress"]["search_requests"] == 5
            assert not private_trap.exists()
            # Polling cannot re-observe/public-write the same facts or call sources.
            calls = len(provider.calls)
            before = manager.public.connection.total_changes
            for _ in range(3):
                assert (await client.get(path, headers=headers)).status_code == 200
            assert manager.public.connection.total_changes == before and len(provider.calls) == calls
            assert (await client.post("/api/mobile/courses", json={})).status_code in {404, 405}
            assert (await client.get("/api/search-jobs/"+jid)).status_code == 404
            # Expiring private processing does not delete public facts or refund
            # the aggregate reservation, and clears private refresh-topic hashes.
            await manager.cleanup_once(force=True)
            assert manager.public.browse()["total"] == 1
            assert dict(manager.public.connection.execute("SELECT * FROM mobile_daily_budget").fetchone()) == daily
            assert app.state.store.connection.execute("SELECT COUNT(*) FROM mooc_refresh_state").fetchone()[0] == 0
            next_path, next_headers = ticket()
            assert (await client.post(next_path, headers=next_headers, json={"kind": "direct_search", "request": {
                "knowledge_points": [name], "preferred_platforms": ["bilibili", "icourse163"]}})).status_code == 202
            again = await settle(client, next_path, next_headers)
            assert again["result"]["groups"][0]["related_recommendations"]
            assert manager.public.connection.execute("SELECT tasks FROM mobile_daily_budget").fetchone()[0] == 2


def test_public_card_only_history_cannot_fabricate_source_or_matching(tmp_path):
    _, config, _, _ = setup(tmp_path)
    public = MobilePublicStore(config)
    try:
        resource, evidence = source("bilibili")
        assert public.observe(resource, evidence)
        row = public.connection.execute("SELECT course_id,data FROM mobile_public_courses").fetchone()
        old = json.loads(row["data"])
        old.pop("_source_snapshot")
        with public.connection:
            public.connection.execute("UPDATE mobile_public_courses SET data=? WHERE course_id=?", (json.dumps(old), row["course_id"]))
        point = {"knowledge_point_id": "p", "text": "Python list indexing"}
        req = SearchRequest(knowledge_points=[point["text"]], preferred_platforms=["bilibili"])
        assert public.browse()["total"] == 1 and public.lookup(point, req) == []
        # A subsequently observed exact own page may backfill missing proofs,
        # retaining its original observation and expiry.
        assert public.observe(resource, evidence)
        assert public.browse()["items"][0]["expires_at"] == old["expires_at"]
    finally:
        public.close()


def test_refresh_identity_keeps_independent_declared_technologies():
    point = {"knowledge_point_id": "p", "text": "事件"}
    python = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "Python"})
    js = python.model_copy(update={"topic_technologies": {"事件": "JavaScript"}})
    assert MoocRefresh.topic_key(point, python, {}) != MoocRefresh.topic_key(point, js, {})


@pytest.mark.asyncio
async def test_related_partial_public_outline_does_not_stop_teaching_enabled_gap_search(tmp_path):
    app, _, provider, _ = setup(tmp_path, max_search_requests=10, mooc_search_rounds=3, max_detail_pages=0)
    async with app.router.lifespan_context(app):
        # The own title declares both topics, but the actual bound outline
        # only lists one. Related title evidence cannot fill outline gaps.
        resource, evidence = observed(chapters=("列表",), title="Python 列表与字典课程", timestamp=time.time()-10)
        assert app.state.mobile.public.observe(resource, evidence)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1", trust_env=False) as client:
            path, headers = ticket()
            assert (await client.post(path, headers=headers, json={"kind": "direct_search", "request": {
                "knowledge_points": ["Python 列表与字典"], "preferred_platforms": ["bilibili", "icourse163"]}})).status_code == 202
            row = await settle(client, path, headers)
            group = row["result"]["groups"][0]
            assert group["related_recommendations"]
            assert group["outline_evidence_summary"]["qualified_course_count"] == 0
            job = app.state.store.get_job(app.state.mobile.records[path.rsplit("/", 1)[1]]["job_id"])
            assert job["progress"]["gap_queries_skipped"] == 0
            assert len(provider.calls) == job["progress"]["search_requests"] == 5
            # An expired public snapshot cannot stay visible via a private copy.
            public = app.state.mobile.public
            public.clock = lambda: time.time() + 4000000
            before = public.connection.total_changes
            assert (await client.get(path, headers=headers)).json()["result"]["groups"][0]["related_recommendations"] == []
            assert public.connection.total_changes == before
