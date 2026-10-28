"""Production entry points no longer schedule or publish chapter matching."""
from copy import deepcopy

import httpx
import pytest

from backend.app import fast_video_search as fast
from backend.app.project_service import ProjectService
from test_background_covers import CoverEnricher, IMAGE, state_with_cards
from test_fast_video_search import settings


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Removed chapter flow tests must stay offline")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(fast, "build_provider", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_flag", [False, True])
async def test_legacy_catalog_resume_only_fills_missing_images_and_preserves_history(legacy_flag):
    state = state_with_cards(2)
    state["recommendations"]["loop"][1]["resource"].update(thumbnail_url=IMAGE, cover_status="ready")
    original = deepcopy(state)
    model_calls = []

    async def model(*args, **kwargs):
        model_calls.append(True)
        raise AssertionError("No chapter model exists in the resume path")

    result = await fast.resume_video_catalogs(settings(), [{"id": "loop", "name": "循环结构", "technology": "Python"}],
        state, publish=lambda _: None, complete=model, cover_only=legacy_flag,
        chapter_enricher_factory=CoverEnricher)
    assert not model_calls
    assert state == original, "Caller-owned historical state must remain unchanged"
    assert result["catalog_enrichment"]["mode"] == "covers_only"
    assert result["progress"]["catalog_model_calls"] == original["progress"]["catalog_model_calls"]
    assert result["progress"]["model_calls"] == original["progress"]["model_calls"]
    assert len(CoverEnricher.instances[-1].resources) == 1
    for before, after in zip(original["recommendations"]["loop"], result["recommendations"]["loop"]):
        assert before["matched_chapters"] == after["matched_chapters"]
        assert after["resource"]["thumbnail_url"] == IMAGE
    assert result["diagnostics"]["chapters"] == original["diagnostics"]["chapters"]


def test_project_legacy_catalog_endpoint_delegates_only_to_cover_resume(monkeypatch):
    calls = []
    service = ProjectService.__new__(ProjectService)
    monkeypatch.setattr(service, "_resume_metadata", lambda project_id, version, **kwargs:
        calls.append((project_id, version, kwargs)) or "handled")
    assert service.resume_catalogs("existing", 4) == "handled"
    assert calls == [("existing", 4, {"cover_only": True})]
    assert fast.MAX_CATALOG_MODEL_CALLS == 0
    assert fast.catalog_background_limits(settings())["model_calls"] == 0
