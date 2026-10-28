"""Offline proofs for opt-in same-host overlap and shared access controls."""
import asyncio
from types import SimpleNamespace

import pytest

import backend.app.fetcher as module
from backend.app.fetcher import FETCH_DEADLINE_AT, NETWORK_OBSERVER, Fetcher, FetcherConfig, FetchStopped, HTTPResult, RobotsRules


BASE = "https://learning.example.org"
PUBLIC = ["93.184.216.34"]


async def resolve(url, timeout):
    return PUBLIC


def reply(url, status=200, headers=None):
    return HTTPResult(status, headers or {}, b"public page", url)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_configured_inflight_bound_is_real_and_other_hosts_continue(concurrency):
    first_wave = asyncio.Event()
    release = asyncio.Event()
    calls, active, peak = [], [0], [0]

    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if url.startswith(BASE):
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                if active[0] == concurrency:
                    first_wave.set()
                try:
                    await release.wait()
                finally:
                    active[0] -= 1
            return reply(url)

    f = Fetcher(FetcherConfig(per_host_concurrency=concurrency, min_interval_seconds=0),
                resolver=resolve, http_client=HTTP())
    tasks = [asyncio.create_task(f._request(BASE + f"/{i}", 1000)) for i in range(4)]
    try:
        await asyncio.wait_for(first_wave.wait(), .5)
        await asyncio.sleep(0)
        assert len(calls) == concurrency
        assert (await f._request("https://other.example.org/ok", 1000)).status_code == 200
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert peak[0] == concurrency
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_overlapping_reads_still_space_starts_by_robots_delay(monkeypatch):
    clock = [1000.0]
    real_sleep = asyncio.sleep
    async def sleep(seconds):
        clock[0] += seconds
        await real_sleep(0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    calls, entered, release = [], asyncio.Event(), asyncio.Event()
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append((url, clock[0]))
            if len(calls) == 2:
                entered.set()
            await release.wait()
            return reply(url)
    f = Fetcher(FetcherConfig(per_host_concurrency=2, min_interval_seconds=.5),
                resolver=resolve, http_client=HTTP())
    f._robots[BASE] = (2000.0, RobotsRules("User-agent: *\nCrawl-delay: 5", "ProjectLearningDiscovery/0.1"))
    tasks = [asyncio.create_task(f._request(BASE + f"/{i}", 1000)) for i in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), .5)
        assert [stamp for _, stamp in calls] == [1000.0, 1005.0]
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 503])
async def test_denial_during_pacing_blocks_waiter_before_http(monkeypatch, status):
    clock = [1000.0]
    pacing, resume_pacing, entered, release = [asyncio.Event() for _ in range(4)]
    calls = []
    async def sleep(seconds):
        pacing.set()
        await resume_pacing.wait()
        clock[0] += seconds
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            entered.set()
            await release.wait()
            return reply(url, status, {"retry-after": "120"})
    f = Fetcher(FetcherConfig(per_host_concurrency=2, min_interval_seconds=5), resolver=resolve, http_client=HTTP())
    first = asyncio.create_task(f._request(BASE + "/first", 1000))
    await asyncio.wait_for(entered.wait(), .5)
    second = asyncio.create_task(f._request(BASE + "/second", 1000))
    await asyncio.wait_for(pacing.wait(), .5)
    release.set()
    with pytest.raises(FetchStopped) as failed:
        await first
    resume_pacing.set()
    with pytest.raises(FetchStopped) as blocked:
        await second
    assert blocked.value.status == failed.value.status
    assert calls == [BASE + "/first"]
    with pytest.raises(FetchStopped):
        await f._request(BASE + "/third", 1000)
    assert calls == [BASE + "/first"]


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_at", ["dns", "budget"])
async def test_denial_is_rechecked_after_awaited_dns_or_budget_hook(wait_at):
    entered, release, waiting, continue_waiter = [asyncio.Event() for _ in range(4)]
    calls = []
    async def resolver(url, timeout):
        if url.endswith("/second") and wait_at == "dns":
            waiting.set()
            await continue_waiter.wait()
        return PUBLIC
    async def reserve():
        waiting.set()
        await continue_waiter.wait()
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            entered.set()
            await release.wait()
            return reply(url, 403)
    f = Fetcher(FetcherConfig(per_host_concurrency=2, min_interval_seconds=0), resolver=resolver, http_client=HTTP())
    first = asyncio.create_task(f._request(BASE + "/first", 1000))
    await asyncio.wait_for(entered.wait(), .5)
    token = NETWORK_OBSERVER.set({"before_target_http": reserve} if wait_at == "budget" else None)
    try:
        second = asyncio.create_task(f._request(BASE + "/second", 1000))
    finally:
        NETWORK_OBSERVER.reset(token)
    await asyncio.wait_for(waiting.wait(), .5)
    release.set()
    with pytest.raises(FetchStopped):
        await first
    continue_waiter.set()
    with pytest.raises(FetchStopped) as blocked:
        await second
    assert blocked.value.status == "access_denied"
    assert calls == [BASE + "/first"]


@pytest.mark.asyncio
async def test_queued_request_after_inflight_denial_never_resolves_or_sends():
    entered, release = asyncio.Event(), asyncio.Event()
    dns, calls = [], []
    async def resolver(url, timeout):
        dns.append(url)
        return PUBLIC
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            entered.set()
            await release.wait()
            return reply(url, 429, {"retry-after": "120"})
    f = Fetcher(FetcherConfig(min_interval_seconds=0), resolver=resolver, http_client=HTTP())
    first = asyncio.create_task(f._request(BASE + "/first", 1000))
    await asyncio.wait_for(entered.wait(), .5)
    second = asyncio.create_task(f._request(BASE + "/second", 1000))
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert all(isinstance(x, FetchStopped) and x.status == "rate_limited" for x in results)
    assert calls == dns == [BASE + "/first"]


@pytest.mark.asyncio
async def test_cancelled_inflight_request_releases_one_slot_without_cancelling_peer():
    first_two, release = asyncio.Event(), asyncio.Event()
    calls = []
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if len(calls) == 2:
                first_two.set()
            if not url.endswith("/replacement"):
                await release.wait()
            return reply(url)
    f = Fetcher(FetcherConfig(per_host_concurrency=2, min_interval_seconds=0), resolver=resolve, http_client=HTTP())
    first = asyncio.create_task(f._request(BASE + "/one", 1000))
    second = asyncio.create_task(f._request(BASE + "/two", 1000))
    try:
        await asyncio.wait_for(first_two.wait(), .5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        assert (await asyncio.wait_for(f._request(BASE + "/replacement", 1000), .5)).status_code == 200
    finally:
        release.set()
        await second


@pytest.mark.asyncio
async def test_job_deadline_in_host_queue_does_not_leak_slots():
    entered, release = asyncio.Event(), asyncio.Event()
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            if url.endswith("/slow"):
                entered.set()
                await release.wait()
            return reply(url)
    f = Fetcher(FetcherConfig(min_interval_seconds=0), resolver=resolve, http_client=HTTP())
    first = asyncio.create_task(f._request(BASE + "/slow", 1000))
    await asyncio.wait_for(entered.wait(), .5)
    token = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + .01)
    try:
        with pytest.raises(TimeoutError):
            await f._request(BASE + "/expires", 1000)
    finally:
        FETCH_DEADLINE_AT.reset(token)
        release.set()
        await first
    assert (await f._request(BASE + "/next", 1000)).status_code == 200


@pytest.mark.asyncio
async def test_global_fetch_bound_and_shared_robots_probe_survive_overlap():
    two_pages, release = asyncio.Event(), asyncio.Event()
    calls, active, peak = [], [0], [0]
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {}, b"User-agent: *\nAllow: /", url)
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            if active[0] == 2:
                two_pages.set()
            try:
                await release.wait()
            finally:
                active[0] -= 1
            return reply(url)
    f = Fetcher(FetcherConfig(global_concurrency=2, per_host_concurrency=2, min_interval_seconds=0),
                resolver=resolve, http_client=HTTP())
    tasks = [asyncio.create_task(f.fetch(BASE + f"/{i}")) for i in range(3)]
    try:
        await asyncio.wait_for(two_pages.wait(), .5)
        assert calls.count(BASE + "/robots.txt") == 1
        assert len(calls) == 3
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert peak[0] == 2
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_second_inflight_retry_after_cannot_shorten_host_pause():
    both, long_release, short_release = [asyncio.Event() for _ in range(3)]
    calls = []
    class HTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            if len(calls) == 2:
                both.set()
            await (long_release if url.endswith("/long") else short_release).wait()
            return reply(url, 429, {"retry-after": "120" if url.endswith("/long") else "1"})
    f = Fetcher(FetcherConfig(per_host_concurrency=2, min_interval_seconds=0), resolver=resolve, http_client=HTTP())
    long_task = asyncio.create_task(f._request(BASE + "/long", 1000))
    short_task = asyncio.create_task(f._request(BASE + "/short", 1000))
    await asyncio.wait_for(both.wait(), .5)
    long_release.set()
    with pytest.raises(FetchStopped):
        await long_task
    original_pause = f._paused_until["learning.example.org"]
    short_release.set()
    with pytest.raises(FetchStopped):
        await short_task
    assert f._paused_until["learning.example.org"] == original_pause


@pytest.mark.parametrize("value", [0, 6, -1, True, 1.5])
def test_invalid_per_host_concurrency_rejected(value):
    with pytest.raises(ValueError, match="per_host_concurrency"):
        Fetcher(FetcherConfig(per_host_concurrency=value))
