import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.providers import HTTPProvider
from scripts import verify_split_provider_live as harness


@pytest.mark.asyncio
async def test_dry_run_never_loads_environment_or_constructs_service(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("dry run touched runtime")
    monkeypatch.setattr(harness.Settings, "from_env", forbidden)
    monkeypatch.setattr(harness, "JobService", forbidden)
    result = await harness.run(tmp_path / "dry")
    assert result["status"] == "dry_run" and result["search_http_requests"] == 0
    with pytest.raises(FileExistsError):
        await harness.run(tmp_path / "dry")


@pytest.mark.asyncio
async def test_real_jobservice_split_routing_empty_mock_transport_and_isolated_database(tmp_path, monkeypatch):
    requests = []
    async def no_sleep(_):
        pass
    async def response(client, method, url, trace, **kwargs):
        requests.append((url, kwargs))
        if "tavily" in url:
            assert "Authorization" not in kwargs["headers"]
            assert kwargs["headers"]["X-Tavily-Access-Mode"] == "keyless"
        return httpx.Response(200, json={"results": []})
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    original = tmp_path / "must-not-open.sqlite3"
    original.write_bytes(b"original user database")
    output = tmp_path / "integration"
    result = await harness.run(output, live=True, configured=Settings(database_path=str(original),
        searxng_url="http://127.0.0.1:18888", tavily_api_key="forbidden-account-key", llm_api_key="forbidden-llm-key",
        teaching_match_enabled=True, js_render_enabled=True, official_sitemap_fallback=True, public_catalog_fallback=True))
    assert original.read_bytes() == b"original user database"
    assert 0 < len(requests) <= 8
    assert result["search_http_requests"] == len(requests)
    assert result["detail_target_http_requests"] == result["llm_calls"] == 0
    assert all(row["discovery_count"] == 0 for row in result["platforms"].values())
    attempts = json.loads((output / "search_attempts.json").read_text(encoding="utf-8"))
    assert {row["provider"] for row in attempts if row["platform"] == "bilibili"} == {"searxng"}
    assert {row["provider"] for row in attempts if row["platform"] == "icourse163"} == {"tavily"}
    all_text = "".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    assert "forbidden-account-key" not in all_text and "forbidden-llm-key" not in all_text
    assert all(not row.get("cache_hit") for row in attempts)


@pytest.mark.asyncio
async def test_production_source_access_stop_does_not_disable_other_platform(tmp_path, monkeypatch):
    seen = {"tavily": 0, "searxng": 0}
    async def no_sleep(_):
        pass
    async def response(client, method, url, trace, **kwargs):
        name = "tavily" if "tavily" in url else "searxng"
        seen[name] += 1
        return httpx.Response(403 if name == "tavily" else 200, json={"results": []})
    monkeypatch.setattr(HTTPProvider, "_bounded_response", staticmethod(response))
    monkeypatch.setattr("backend.app.providers.asyncio.sleep", no_sleep)
    result = await harness.run(tmp_path / "stops", live=True, configured=Settings(searxng_url="http://127.0.0.1:18888"))
    assert seen["tavily"] == 1 and seen["searxng"] >= 2
    assert result["source_states"]["tavily"]["source_access_denied"] is True
    assert result["source_states"]["searxng"]["source_access_denied"] is False
