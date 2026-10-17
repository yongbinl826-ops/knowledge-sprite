"""Server configuration, cache isolation and diagnostic persistence; no network/Edge."""
from dataclasses import replace

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, HTTPResult
from backend.app.models import Candidate, Resource, SearchRequest
from backend.app.service import JobService


class SearchFixture:
    name = "fixture"

    async def search(self, query, language, limit, domains):
        return [Candidate(id="one", title="SQL joins video", url="https://www.bilibili.com/video/BV1234567890/",
            snippet="SQL joins teaching", query=query, source="fixture", type_source="search_template", resource_type_hint="video")]


def test_env_defaults_and_explicit_host_bounded_configuration(monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for key in tuple(config.os.environ):
        if key.startswith(("JS_RENDER_", "FETCH_BODY_")) or key == "FETCH_PHASED_TIMEOUTS":
            monkeypatch.delenv(key)
    defaults = Settings.from_env()
    assert not defaults.js_render_enabled and not defaults.fetch_phased_timeouts
    assert defaults.js_render_allowed_hosts == defaults.js_render_asset_hosts == ()
    assert (defaults.js_render_timeout_seconds, defaults.js_render_max_resources,
        defaults.js_render_max_target_requests, defaults.js_render_max_doh_requests,
        defaults.js_render_max_total_bytes) == (20, 6, 12, 24, 2_000_000)
    monkeypatch.setenv("JS_RENDER_ENABLED", "true")
    monkeypatch.setenv("FETCH_PHASED_TIMEOUTS", "true")
    monkeypatch.setenv("JS_RENDER_ALLOWED_HOSTS", "Courses.Example.org,https://evil.example/a,*.example.org,127.0.0.1,courses.example.org")
    monkeypatch.setenv("JS_RENDER_ASSET_HOSTS", "cdn.example.org,cdn.example.org:443,@evil.example")
    monkeypatch.setenv("JS_RENDER_TIMEOUT_SECONDS", "9999")
    monkeypatch.setenv("JS_RENDER_MAX_TOTAL_BYTES", "999999999")
    monkeypatch.setenv("JS_RENDER_MAX_OBSERVED_DATA_RESOURCES", "99")
    monkeypatch.setenv("FETCH_BODY_MIN_BYTES_PER_SECOND", "0")
    monkeypatch.setenv("FETCH_BODY_TIMEOUT_CAP_SECONDS", "invalid")
    actual = Settings.from_env()
    assert actual.js_render_enabled and actual.fetch_phased_timeouts
    assert actual.js_render_allowed_hosts == ("courses.example.org",)
    assert actual.js_render_asset_hosts == ("cdn.example.org",)
    assert actual.js_render_timeout_seconds == 120 and actual.js_render_max_total_bytes == 8_000_000
    assert actual.js_render_max_observed_data_resources == 2
    assert actual.fetch_body_min_bytes_per_second == 1024 and actual.fetch_body_timeout_cap_seconds == 20


@pytest.mark.parametrize("value", [",", "http://microsoft.github.io/AI-For-Beginners/", "https://127.0.0.1/", "https://microsoft.github.io/?term=1", "https://microsoft.github.io/#lesson"])
def test_invalid_exact_entry_restriction_never_silently_broadens(value):
    from backend.app.config import render_entries
    with pytest.raises(ValueError): render_entries(value)


def test_exact_entry_configuration_wires_and_isolates_cache(monkeypatch):
    from backend.app.config import render_entries
    entry = "https://microsoft.github.io/AI-For-Beginners/"
    settings = Settings(js_render_enabled=True,js_render_allowed_hosts=("microsoft.github.io",),
        js_render_allowed_entries=render_entries(entry))
    store=Store(":memory:")
    try:
        service=JobService(settings,store,provider=SearchFixture())
        assert service.fetcher.renderer.config.allowed_entries == (entry,)
        assert service.capabilities()["js_render"]["allowed_entries"] == (entry,)
        first,_=service._page_cache({"canonical_url":entry})
        service.settings=replace(settings,js_render_allowed_entries=())
        assert service._page_cache({"canonical_url":entry})[0] != first
    finally: store.close()


@pytest.mark.asyncio
async def test_default_disabled_renderer_has_no_network_or_browser(monkeypatch):
    import backend.app.rendering as rendering
    async def unexpected(*args, **kwargs):
        raise AssertionError("Disabled configuration must not prepare resources or start Edge")
    monkeypatch.setattr(rendering.SafeRenderer, "_prepare_and_run", unexpected)
    store = Store(":memory:")
    try:
        service = JobService(Settings(), store, provider=SearchFixture())
        assert isinstance(service.fetcher, Fetcher)
        result = await service.fetcher.renderer.render(service.fetcher, HTTPResult(200, {}, b"", "https://courses.example.org/"))
        assert result.status == "disabled" and result.html is None
        capabilities = service.capabilities()
        assert capabilities["js_render"]["status"] == "disabled"
        assert capabilities["js_render"]["online_browser_fallback"] is False
        assert capabilities["fetch"]["transport"]["phased_timeouts"] is False
    finally:
        store.close()


def test_service_wires_phased_transport_and_renderer_without_claiming_success():
    settings = Settings(fetch_phased_timeouts=True, fetch_body_idle_timeout_seconds=7,
        fetch_body_min_bytes_per_second=65536, fetch_body_timeout_cap_seconds=25,
        js_render_enabled=True, js_render_allowed_hosts=("courses.example.org",),
        js_render_asset_hosts=("cdn.example.org",), js_render_timeout_seconds=120,
        js_render_max_observed_data_resources=1)
    store = Store(":memory:")
    try:
        service = JobService(settings, store, provider=SearchFixture())
        transport, renderer = service.fetcher.config, service.fetcher.renderer.config
        assert transport.phased_timeouts and transport.body_idle_timeout_seconds == 7
        assert transport.body_min_bytes_per_second == 65536 and transport.body_timeout_cap_seconds == 25
        assert renderer.enabled and renderer.allowed_hosts == settings.js_render_allowed_hosts
        assert renderer.asset_hosts == settings.js_render_asset_hosts and renderer.timeout_seconds == 120
        assert renderer.max_observed_data_resources == 1
        capability = service.capabilities()["js_render"]
        assert capability["status"] == "configured" and capability["playback_verified"] is False
        assert capability["process_network_egress"] == "unknown"
    finally:
        store.close()


@pytest.mark.parametrize("change", [
    {"js_render_enabled": True}, {"js_render_allowed_hosts": ("courses.example.org",)},
    {"js_render_asset_hosts": ("cdn.example.org",)}, {"js_render_timeout_seconds": 25},
    {"js_render_max_total_bytes": 500_000}, {"js_render_max_observed_data_resources": 0},
    {"fetch_phased_timeouts": True}, {"fetch_body_idle_timeout_seconds": 10},
    {"fetch_body_min_bytes_per_second": 65536}, {"fetch_body_timeout_cap_seconds": 30},
])
def test_page_cache_cannot_replay_another_render_or_transport_profile(change):
    # Cache contents remain present for the original profile, but must not leak
    # into an explicitly different rendering policy or timeout configuration.
    store = Store(":memory:")
    try:
        original = Settings()
        service = JobService(original, store, provider=SearchFixture())
        resource = {"canonical_url": "https://courses.example.org/public"}
        key, cached = service._page_cache(resource)
        assert cached is None
        store.cache_set(key, "page", {"fetch_status": "fetched", "render_diagnostics": {"status": "disabled"}}, 60)
        service.settings = replace(original, **change)
        new_key, cached = service._page_cache(resource)
        assert new_key != key and cached is None
        service.settings = original
        assert service._page_cache(resource)[1]["data"]["render_diagnostics"]["status"] == "disabled"
    finally:
        store.close()


def test_old_policy_failure_cache_is_preserved_but_not_replayed(monkeypatch):
    store = Store(":memory:")
    try:
        service = JobService(Settings(), store, provider=SearchFixture())
        resource = {"canonical_url": "https://microsoft.github.io/AI-For-Beginners/"}
        current_renderer, current_transport = service._renderer_profile, service._transport_profile
        old_renderer = {**current_renderer(), "version": 1}
        old_transport = {k:v for k,v in current_transport().items() if k != "version"}
        with monkeypatch.context() as patch:
            patch.setattr(service, "_renderer_profile", lambda: old_renderer)
            patch.setattr(service, "_transport_profile", lambda: old_transport)
            old_key, _ = service._page_cache(resource)
            store.cache_set(old_key, "page", {"fetch_status":"fetched", "render_diagnostics":{"status":"robots_unavailable"}},60)
        new_key, cached = service._page_cache(resource)
        assert old_key != new_key and cached is None
        assert store.cache_get(old_key)["data"]["render_diagnostics"]["status"] == "robots_unavailable"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_render_diagnostics_survive_job_model_and_database_roundtrip():
    diagnostics = {"status": "render_timeout", "acquisition": "offline_rendered_dom",
        "manifest_sha256": "a" * 64, "cleanup": {"node_exited": True}, "html_present": False}
    class FetchFixture:
        __slots__ = ()  # Configuration must not add a renderer to injected stubs.
        async def enrich(self, candidate):
            return {"fetch_status": "fetched", "render_diagnostics": diagnostics, "evidence": []}
    store = Store(":memory:")
    try:
        service = JobService(Settings(max_search_requests=1, max_detail_pages=1), store,
            provider=SearchFixture(), fetcher=FetchFixture())
        job_id = service.create(SearchRequest(knowledge_points=["SQL joins"], language="en", preferred_platforms=[]))["job_id"]
        await service.run(job_id)
        resource = next(iter(store.resources(job_id).values()))
        assert Resource.model_validate(resource).render_diagnostics == diagnostics
        assert resource["render_diagnostics"] == diagnostics
        assert not hasattr(service.fetcher, "renderer")
        resource.pop("render_diagnostics")
        assert Resource.model_validate(resource).render_diagnostics is None
    finally:
        store.close()
