"""Scoped complete-entity budgets; all requests are offline fixtures."""
import gzip
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped
from backend.app.service import JobService
from backend.app.source_adapters.bilibili import _initial_state
from test_bilibili_embedded_parts import extract, markup, payload
from test_bilibili_public_scope import VIDEO, ROBOTS, isolated_fetcher, response
from test_compressed_metadata_transport import Chunks, REAL_ASYNC_CLIENT


@pytest.mark.asyncio
@pytest.mark.parametrize("override,expected", [(None, 500), (8_000_000, 8_000_000)])
async def test_public_video_cap_requires_explicit_override_and_robots_stays_small(override, expected):
    fetcher, http, _ = isolated_fetcher({ROBOTS: response(ROBOTS, status=404, body=b""), VIDEO: response(VIDEO)},
        max_bytes=500, bilibili_public_metadata_max_bytes=override)
    limits = []
    original = http.request
    async def recording(url, addresses, max_bytes):
        limits.append((url, max_bytes))
        return await original(url, addresses, max_bytes)
    http.request = recording
    await fetcher.fetch(VIDEO)
    assert limits == [(ROBOTS, 500), (VIDEO, expected)]


@pytest.mark.asyncio
async def test_general_page_and_direct_robots_do_not_receive_video_budget():
    other = "https://courses.example.org/course"
    robots = "https://courses.example.org/robots.txt"
    fetcher, http, _ = isolated_fetcher({ROBOTS: response(ROBOTS, status=404, body=b""),
        robots: response(robots, status=404, body=b""), other: response(other)},
        bilibili_public_metadata_max_bytes=8_000_000)
    calls = []
    original = http.request
    async def recording(url, addresses, max_bytes):
        calls.append((url, max_bytes))
        return await original(url, addresses, max_bytes)
    http.request = recording
    await fetcher.fetch(other)
    await fetcher.fetch(ROBOTS)
    assert calls == [(robots, 256_000), (other, 1_000_000), (ROBOTS, 256_000), (ROBOTS, 1_000_000)]


@pytest.mark.asyncio
async def test_redirect_rechecks_scope_before_using_larger_budget():
    target = "https://courses.example.org/large"
    fetcher, http, dns = isolated_fetcher({ROBOTS: response(ROBOTS, status=404, body=b""),
        VIDEO: response(VIDEO, status=302, body=b"", location=target)},
        bilibili_public_metadata_max_bytes=8_000_000)
    with pytest.raises(FetchStopped) as error:
        await fetcher.fetch(VIDEO)
    assert error.value.status == "policy_unreviewed"
    assert target not in http.calls + dns


def wire_fetcher(monkeypatch, body, *, content_type="text/html", cap=8_000_000, damage=False):
    from backend.app import fetcher as module
    packed = gzip.compress(body)
    if damage:
        packed = packed[:-1]
    streams = []
    async def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        stream = Chunks([(0, packed)])
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": content_type, "content-encoding": "gzip"}, stream=stream)
    def client(**kwargs):
        return REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    async def dns(url, timeout):
        return ["9.9.9.9"]
    return Fetcher(FetcherConfig(bilibili_public_metadata=True,
        bilibili_public_metadata_max_bytes=cap, min_interval_seconds=0, max_retries=0), resolver=dns), streams


@pytest.mark.asyncio
async def test_complete_gzip_html_above_generic_cap_can_provide_actual_catalog(monkeypatch):
    body = markup(extra="<!--" + "x" * 1_100_000 + "-->").encode()
    fetcher, streams = wire_fetcher(monkeypatch, body)
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == "fetched" and result["video_evidence_status"] == "page_verified"
    assert len(result["chapters"]) == 2 and streams[0].closed
    trace = [r["transport"] for r in fetcher.request_trace if r["event"] == "http_transport"][-1]
    assert trace["body_complete"] and trace["decoded_bytes_read"] == len(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["over-cap", "incomplete", "media"])
async def test_larger_metadata_budget_does_not_admit_overflow_truncation_or_media(monkeypatch, failure):
    body = markup(extra="<!--" + "x" * 1_100_000 + "-->").encode()
    fetcher, streams = wire_fetcher(monkeypatch, body,
        cap=1_050_000 if failure == "over-cap" else 8_000_000,
        damage=failure == "incomplete", content_type="video/mp4" if failure == "media" else "text/html")
    result = await fetcher.enrich({"url": VIDEO})
    assert result["fetch_status"] == ("invalid_encoding" if failure == "incomplete" else "too_large")
    assert not result["chapters"] and streams[0].closed
    trace = [r["transport"] for r in fetcher.request_trace if r["event"] == "http_transport"][-1]
    assert not trace["body_complete"]
    if failure == "media":
        assert trace["max_bytes"] == 1_000_000 and trace["decoded_bytes_read"] == 1_000_001


def test_larger_complete_own_state_still_requires_identity_and_exact_json():
    data = payload()
    data["unrelated_state"] = "x" * 2_100_000
    assert len(extract(markup(data))["chapters"]) == 2
    data["videoData"]["bvid"] = "BV1OTHER0000"
    assert extract(markup(data))["chapters"] == []
    original = "window.__INITIAL_STATE__=" + json.dumps(payload()) + ";"
    assert _initial_state(original + " " * (4_000_000 - len(original))) is not None
    assert _initial_state(original + " " * (4_000_001 - len(original))) is None
    assert _initial_state(original[:-2]) is None
    assert _initial_state(original + "window.__INITIAL_STATE__={};") is None


@pytest.mark.parametrize("value", [0, -1, 16_000_001, True, 2.5])
def test_fetcher_rejects_invalid_scoped_limit(value):
    with pytest.raises(ValueError, match="bilibili_public_metadata_max_bytes"):
        Fetcher(FetcherConfig(bilibili_public_metadata_max_bytes=value))


@pytest.mark.parametrize("value", ["0", "16000001", "many", "1.5"])
def test_environment_scoped_limit_fails_closed(monkeypatch, value):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BILIBILI_PUBLIC_METADATA_MAX_BYTES", value)
    with pytest.raises(ValueError, match="BILIBILI_PUBLIC_METADATA_MAX_BYTES"):
        Settings.from_env()


def test_service_runtime_and_only_bilibili_cache_keys_follow_scoped_cap():
    store = Store(":memory:")
    try:
        old = JobService(Settings(bilibili_public_metadata=True, bilibili_public_metadata_max_bytes=1_000_000), store)
        new = JobService(Settings(bilibili_public_metadata=True), store)
        assert new.fetcher.config.max_bytes == 1_000_000
        assert new.fetcher.config.bilibili_public_metadata_max_bytes == 8_000_000
        platform = next(r for r in new.capabilities()["platforms"] if r["id"] == "bilibili")
        assert platform["metadata_max_bytes"] == 8_000_000 and platform["metadata_max_state_chars"] == 4_000_000
        old_key, _ = old._page_cache({"canonical_url": VIDEO})
        store.cache_set(old_key, "page", {"fetch_status": "too_large"}, 300)
        new_key, cached = new._page_cache({"canonical_url": VIDEO})
        assert old_key != new_key and cached is None
        assert store.cache_get(old_key)["data"]["fetch_status"] == "too_large"
        for url in ["https://www.freecodecamp.org/news/course", "https://www.icourse163.org/course/PKU-1003479006"]:
            assert old._page_cache({"canonical_url": url})[0] == new._page_cache({"canonical_url": url})[0]
    finally:
        store.close()
