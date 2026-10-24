"""Catalog-only HTTP admission uses the existing local project guard."""
import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method,queue_code", [
    ("catalogs", "resume_catalogs", "catalog_queue_full"),
    ("covers", "resume_covers", "cover_queue_full"),
])
async def test_catalog_endpoint_admits_same_owner_and_limits_new_work(tmp_path, monkeypatch, endpoint, method, queue_code):
    app = create_app(Settings(database_path=str(tmp_path / "catalog.sqlite"),
        fetch_enabled=False, llm_provider="none", teaching_match_enabled=False,
        max_pending_project_searches=1))
    async with app.router.lifespan_context(app):
        calls = []
        def resume(project_id, version):
            calls.append((project_id, version))
            return {"project_id": project_id, "version": {"version": version}}
        monkeypatch.setattr(app.state.projects, method, resume)
        owner = asyncio.create_task(asyncio.Event().wait())
        app.state.projects.tasks[("saved", 17)] = owner
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,
                    client=("127.0.0.1", 1)), base_url="http://127.0.0.1") as client:
                same = await client.post(f"/api/projects/saved/{endpoint}", json={"version": 17})
                assert same.status_code == 202
                assert same.json()["version"]["version"] == 17
                full = await client.post(f"/api/projects/other/{endpoint}", json={"version": 1})
                assert full.status_code == 429
                assert full.json()["code"] == queue_code
                assert full.headers["Retry-After"] == "5"
                assert calls == [("saved", 17)]
        finally:
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
            app.state.projects.tasks.clear()
