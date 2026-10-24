"""Mobile GET keeps access to catalog-only updates without another POST."""
import asyncio

import httpx
import pytest

from backend.app.models import now
from test_mobile_backend import document, setup, ticket


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["complete", "cancel"])
async def test_mobile_keeps_completed_task_readable_until_late_chapter_update(tmp_path, monkeypatch, finish):
    app, _, provider, _ = setup(tmp_path, fast_video_recommendations_enabled=True)
    ready, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def engine(settings, points, input_data, *, publish, **kwargs):
        calls.append(1)
        snapshot = {"status": "completed", "finished_at": now(), "progress": {},
            "recommendations": {points[0]["id"]: [{"resource": {"resource_id": "r1", "title": "Python list",
                "url": "https://www.bilibili.com/video/BV1q741157jG", "platform": "bilibili"},
                "added_at": now(), "matched_chapters": []}]},
            "catalog_enrichment": {"status": "running", "started_at": now()}}
        publish(snapshot)
        ready.set()
        await release.wait()
        snapshot["recommendations"][points[0]["id"]][0]["matched_chapters"] = [{"chapter_id": "c2", "title": "List indexing"}]
        snapshot["catalog_enrichment"].update(status="completed", finished_at=now())
        publish(snapshot)

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", engine)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            path, headers = ticket()
            payload = {"kind": "search", "input": {"name": "Local report", "requirements": "Read list values",
                "preferred_platforms": ["bilibili"]}, "analysis": document().model_dump()}
            assert (await client.post(path, headers=headers, json=payload)).status_code == 202
            await asyncio.wait_for(ready.wait(), 1)
            first = (await client.get(path, headers=headers)).json()
            assert first["status"] == "completed" and first["result"]["pipeline"]["catalog_pending"]
            assert first["result"]["pipeline"]["terminal"]
            if finish == "complete":
                release.set()
                await asyncio.gather(*app.state.projects.tasks.values())
            else:
                cancelled = (await client.post(path + "/cancel", headers=headers)).json()
                assert cancelled["status"] == "completed"
                assert cancelled["result"]["pipeline"]["catalog_status"] == "cancelled"
            response = await client.get(path, headers=headers)
            final = response.json()
            assert response.status_code == 200 and final["status"] == "completed"
            assert not final["result"]["pipeline"]["catalog_pending"]
            chapters = final["result"]["points"][0]["result"]["video_recommendations"][0]["matched_chapters"]
            assert chapters == ([{"chapter_id": "c2", "title": "List indexing"}] if finish == "complete" else [])
            assert calls == [1] and provider.calls == []
