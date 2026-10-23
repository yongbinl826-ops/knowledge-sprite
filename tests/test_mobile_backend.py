"""Synthetic mobile ASGI integration. No supplier transport or real credentials."""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.main import create_app
from backend.app.mobile_public import MobilePublicStore, public_course
from backend.app.mobile_tasks import MobileTaskPayload
from backend.app.models import now
from backend.app.project_models import AnalysisDocument


def document():
    return AnalysisDocument.model_validate({"analysis_format": "concept_list_v1",
        "scope": "Offline local list report", "technical_plan": "Python", "assumptions": [],
        "knowledge_points": [{"id": "k1", "name": "Python list indexing", "description": "List positions",
            "technology": "Python", "selection": "learn"}]})


class Analyzer:
    available = True
    calls = 0
    async def analyze(self, _):
        self.calls += 1
        return document()


class NoLLM:
    available = False
    async def expand(self, *_, **__):
        raise AssertionError("Unconfigured model must never be called")
    async def rerank(self, *_, **__):
        raise AssertionError("Unconfigured model must never be called")


class Search:
    def __init__(self):
        self.calls = []
    async def search(self, query, *args, **kwargs):
        self.calls.append((query, kwargs))
        return []


class NoFetch:
    async def enrich(self, *_):
        raise AssertionError("There are no discovered resources to fetch")


def setup(tmp_path, **changes):
    values = dict(app_mode="mobile", database_path=str(tmp_path / "never-open.sqlite3"),
        mobile_public_database_path=str(tmp_path / "public.sqlite3"),
        llm_provider="none", llm_api_key="", searxng_url="https://mock.invalid",
        parallel_platform_search=True, teaching_match_enabled=True, global_concurrency=2,
        bilibili_search_rounds=1, mooc_search_rounds=1, max_search_requests=4,
        max_detail_pages=1, max_knowledge_points=2, fetch_enabled=False,
        search_max_retries=0, search_min_interval_seconds=0, deadline_seconds=3,
        project_deadline_seconds=10, mobile_cleanup_interval_seconds=1,
        api_write_limit_per_minute=200, submission_limit_per_minute=100,
        mobile_per_ip_tasks_per_minute=60, mobile_per_ip_requests_per_minute=600,
        public_catalog_fallback=False, official_sitemap_fallback=False)
    values.update(changes)
    settings = Settings(**values).validate()
    provider, analyzer = Search(), Analyzer()
    app = create_app(settings, provider, NoFetch(), NoLLM(), analyzer)
    return app, settings, provider, analyzer


def ticket():
    cap = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    return "/api/mobile/tasks/" + str(uuid4()), {"Authorization": "Bearer " + cap}


async def settle(client, path, headers):
    for _ in range(100):
        row = (await client.get(path, headers=headers)).json()
        if row["status"] not in {"queued", "running"}:
            return row
        await asyncio.sleep(.01)
    raise AssertionError("Offline task failed to settle")


def public_fixture():
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    page = '<html><head><meta property="og:type" content="video"><title>Python list indexing lesson</title></head>'
    page += '<body><script type="application/ld+json">' + json.dumps({"@type": "VideoObject", "name": "Python list indexing lesson",
        "description": "A public list indexing lesson.", "embedUrl": url}) + '</script></body></html>'
    resource = MetadataExtractor().extract(page, url, now())
    evidence = resource.pop("evidence")
    resource.update(url=url, canonical_url=url, resolved_url=url, platform="bilibili")
    return resource, evidence


@pytest.mark.asyncio
async def test_analysis_then_device_search_uses_existing_shapes_and_one_RAM_queue(tmp_path):
    app, settings, provider, analyzer = setup(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            assert not provider.calls and analyzer.calls == 0
            p, h = ticket()
            payload = {"kind": "analysis", "input": {"name": "Local report", "requirements": "Read list values",
                "preferred_platforms": ["bilibili", "icourse163"]}}
            assert (await client.post(p, headers=h, json=payload)).status_code == 202
            view = await settle(client, p, h)
            assert view["status"] == "completed" and analyzer.calls == 1
            assert view["result"]["version"]["analysis"] == document().model_dump()
            q, hh = ticket()
            search = {"kind": "search", "input": payload["input"], "analysis": view["result"]["version"]["analysis"]}
            assert (await client.post(q, headers=hh, json=search)).status_code == 202
            result = await settle(client, q, hh)
            assert result["status"] == "completed" and result["result"]["points"]
            assert analyzer.calls == 1  # Imported reviewed device analysis never reanalyzes.
            row = app.state.projects.db.version(app.state.mobile.records[q.rsplit('/', 1)[1]]["project_id"], 1)
            assert "acknowledged_skipped_prerequisites" not in row["confirmation"]
            assert row["confirmation"]["analysis"]["analysis_format"] == "concept_list_v1"
            assert row["confirmation"]["search_mode"] == "professional_terms_v1"
            assert len(provider.calls) == 3  # Both platforms and unrestricted web, one slot each.
            assert sum("site:" not in query for query, _ in provider.calls) == 1
            assert app.state.store.connection.execute("PRAGMA database_list").fetchone()[2] == ""
            assert not __import__("pathlib").Path(settings.database_path).exists()


@pytest.mark.asyncio
async def test_cleaner_failure_and_public_schema_fail_closed_admission(tmp_path):
    app, _, provider, _ = setup(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            manager = app.state.mobile
            assert (await client.get("/health")).status_code == 200
            manager.cleaner.cancel()
            await asyncio.gather(manager.cleaner, return_exceptions=True)
            assert (await client.get("/health")).status_code == 503
            assert (await client.get("/health/ready")).status_code == 503
            path, headers = ticket()
            response = await client.post(path, headers=headers, json={"kind": "direct_search", "request": {"knowledge_points": ["Python list"]}})
            assert response.status_code == 503 and response.json()["code"] == "mobile_not_ready"
            assert not provider.calls and manager.public.connection.execute("SELECT count(*) FROM mobile_daily_budget").fetchone()[0] == 0
            manager.start()
            manager.public.connection.execute("UPDATE mobile_metadata SET schema_version=2")
            manager.public.connection.commit()
            assert not manager.healthy()


@pytest.mark.asyncio
async def test_background_observation_memo_tracks_new_evidence_and_poll_is_read_only(tmp_path):
    app, _, _, _ = setup(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            path, headers = ticket()
            await client.post(path, headers=headers, json={"kind": "direct_search", "request": {"knowledge_points": ["Python list"]}})
            await settle(client, path, headers)
            manager = app.state.mobile
            jid = manager.records[path.rsplit('/', 1)[1]]["job_id"]
            resource, evidence = public_fixture()
            resource["resource_id"] = "observed"
            app.state.store.save_resource(jid, resource)
            for row in evidence:
                app.state.store.add_evidence(jid, "observed", None, row)
            calls = []
            original = manager.public.observe
            def observed(r, e):
                calls.append(len(e))
                return original(r, e)
            manager.public.observe = observed
            await manager.cleanup_once(observe=True)
            assert calls == [len(evidence)]
            writes = []
            manager.public.connection.set_trace_callback(writes.append)
            for _ in range(5):
                assert (await client.get(path, headers=headers)).status_code == 200
            await manager.cleanup_once(observe=True)
            assert calls == [len(evidence)]
            # Prune is a background write; five HTTP polls themselves did not observe/upsert.
            assert not any("INSERT" in x.upper() or "UPSERT" in x.upper() for x in writes)
            app.state.store.add_evidence(jid, "observed", None, {"evidence_id": "new", "kind": "page", "text": "new own fact"})
            await manager.cleanup_once(observe=True)
            assert calls == [len(evidence), len(evidence) + 1]
            before = manager.public.connection.total_changes
            writes.clear()
            assert original(resource, evidence) is False
            assert manager.public.connection.total_changes == before
            assert not any(x.split()[0].upper() in {"BEGIN", "INSERT", "UPDATE", "DELETE", "COMMIT"} for x in writes)
            manager.clock = lambda: manager.records[path.rsplit('/', 1)[1]]["expires_at"] + 1
            await manager.cleanup_once()
            assert not manager.observation_memo


@pytest.mark.parametrize("change", [
    {"app_mode": []}, {"mobile_task_ttl_seconds": True}, {"mobile_task_ttl_seconds": 7201},
    {"mobile_max_tasks": "64"}, {"mobile_origins": (["https://localhost"],)},
    {"mobile_origins": ("https://evil.invalid",)}, {"mobile_daily_model_calls": -1},
    {"mobile_max_active_tasks": 9, "mobile_max_tasks": 8},
    {"app_mode": "mobile", "teaching_match_enabled": False},
    {"app_mode": "mobile", "parallel_platform_search": False},
    {"app_mode": "mobile", "database_path": "same.sqlite3", "mobile_public_database_path": "same.sqlite3"},
])
def test_mobile_configuration_is_strict(change):
    with pytest.raises(ValueError):
        replace(Settings(), **change).validate()


@pytest.mark.parametrize("mutation", ["search_title", "client_title", "wrong_id", "wrong_url", "stale"])
def test_public_observation_requires_own_extractor_bound_facts(mutation):
    resource, evidence = public_fixture()
    current = __import__("time").time()
    assert public_course(resource, evidence, 3600, current)
    if mutation == "stale":
        resource["cache"] = {"stale": True}
    else:
        title = next(e for e in evidence if e.get("field") == "title")
        if mutation in {"search_title", "client_title"}:
            source = "search" if mutation == "search_title" else "client"
            title["source"] = resource["field_provenance"]["title"]["source"] = source
            title["id"] = "ev_" + hashlib.sha256(f"{title['url']}|title|{source}|{resource['title']}".encode()).hexdigest()[:20]
        elif mutation == "wrong_id":
            title["id"] = "ev_wrong"
        else:
            title["url"] = "https://www.bilibili.com/video/BV1BBBBBBBBB/"
    assert public_course(resource, evidence, 3600, current) is None


def test_unknown_legacy_file_not_even_opened_and_unknown_public_version_refused(tmp_path, monkeypatch):
    import backend.app.mobile_public as module
    settings = replace(Settings(), mobile_public_database_path=str(tmp_path / "unknown.sqlite3"))
    path = tmp_path / "unknown.sqlite3"
    path.write_bytes(b"legacy student bytes")
    opened = []
    original = module.sqlite3.connect
    def trap(*args, **kwargs):
        opened.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", trap)
    with pytest.raises(ValueError):
        MobilePublicStore(settings)
    assert not opened and path.read_bytes() == b"legacy student bytes"
    settings = replace(settings, mobile_public_database_path=str(tmp_path / "known.sqlite3"))
    public = MobilePublicStore(settings)
    public.connection.execute("UPDATE mobile_metadata SET schema_version=2")
    public.connection.commit()
    public.close()
    with pytest.raises(ValueError):
        MobilePublicStore(settings)


def test_reservation_counts_model_calls_and_detail_HTTP_worst_case(tmp_path):
    app, settings, _, _ = setup(tmp_path, max_search_requests=6)
    # Use the actual manager method with a tiny read-only context, not a replica.
    from types import SimpleNamespace
    from backend.app.mobile_tasks import MobileTasks
    holder = SimpleNamespace(settings=settings)
    payload = MobileTaskPayload.model_validate({"kind": "direct_search", "request": {
        "knowledge_points": ["Python lists", "Python dict"], "preferred_platforms": ["bilibili", "icourse163"]}})
    costs = MobileTasks._costs(holder, payload)
    assert costs["model_calls"] == 4 and costs["search_requests"] == 6
    assert costs["detail_http"] == settings.max_detail_pages * 40
    payload.request.learning_skills = {"Python lists": ["Python list indexing"]}
    assert MobileTasks._costs(holder, payload)["model_calls"] == settings.teaching_match_max_calls_per_job + 1 + 4
    payload.request.preferred_platforms = []
    assert len(payload.request.learning_skills) == 1  # Mixed skill/non-skill points.
    assert MobileTasks._costs(holder, payload)["model_calls"] >= 1 + 2 + settings.teaching_match_max_calls_per_job + 1
