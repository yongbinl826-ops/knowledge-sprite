"""Synthetic data only: process ownership and bounded result subscriptions."""
import asyncio
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.runtime_guard import database_owner
from backend.app.security import RequestSecurityMiddleware


class EmptySearch:
    async def search(self, *_args, **_kwargs):
        return []


@pytest.mark.asyncio
async def test_second_application_cannot_recover_live_database(tmp_path):
    settings = Settings(database_path=str(tmp_path / "owner.sqlite"), llm_provider="none", fetch_enabled=False)
    first = create_app(settings, provider=EmptySearch())
    async with first.router.lifespan_context(first):
        first.state.store.save_job({"job_id": "synthetic", "status": "running", "warnings": []})
        second = create_app(settings, provider=EmptySearch())
        with pytest.raises(RuntimeError, match="already owned"):
            async with second.router.lifespan_context(second):
                pytest.fail("A second application must not start")
        assert first.state.store.get_job("synthetic")["status"] == "running"
    # Clean stop has recovered it; startup may reopen and read existing data.
    third = create_app(settings, provider=EmptySearch())
    async with third.router.lifespan_context(third):
        assert third.state.store.get_job("synthetic")["status"] == "interrupted"


def test_file_owner_released_after_abrupt_process_exit(tmp_path):
    database = tmp_path / "synthetic.sqlite"
    code = ("import os,sys;from backend.app.runtime_guard import database_owner;"
            "lock=database_owner(sys.argv[1]);lock.__enter__();print('locked',flush=True);"
            "sys.stdin.readline();os._exit(0)")
    child = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-c", code, str(database)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(RuntimeError, match="already owned"):
            with database_owner(str(database)):
                pytest.fail("Cross-process owner bypass")
        child.communicate("exit\n", timeout=10)
        assert child.returncode == 0
        with database_owner(str(database)):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


def test_owner_released_on_startup_error_and_independent_paths(tmp_path):
    path = str(tmp_path / "first.sqlite")
    with pytest.raises(ValueError):
        with database_owner(path):
            with database_owner(str(tmp_path / "second.sqlite")):
                raise ValueError("synthetic startup failure")
    with database_owner(path):
        pass
    with database_owner(":memory:"):
        with database_owner(":memory:"):
            pass


@pytest.mark.parametrize("value", [0, -1, 129, True, "16"])
def test_event_limit_configuration_is_strict(value):
    with pytest.raises(ValueError, match="MAX_EVENT_STREAMS"):
        replace(Settings(), max_event_streams=value).validate()


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["disconnect", "error"])
async def test_event_stream_limit_rejects_before_projection_and_releases(end):
    settings = replace(Settings(), max_event_streams=1)
    entered, release = asyncio.Event(), asyncio.Event()
    downstream = []

    async def application(scope, receive, send):
        downstream.append(scope["path"])
        entered.set()
        await release.wait()
        if end == "error":
            raise ValueError("synthetic private content must not leak")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"complete"})

    middleware = RequestSecurityMiddleware(application, settings)

    async def call():
        response = []
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Future()

        async def send(message):
            response.append(message)

        scope = {"type": "http", "method": "GET", "path": "/api/projects/synthetic/events",
                 "raw_path": b"/api/projects/synthetic/events", "query_string": b"",
                 "headers": [(b"host", b"127.0.0.1")], "scheme": "http", "client": ("127.0.0.1", 7)}
        await middleware(scope, receive, send)
        return response

    first = asyncio.create_task(call())
    await asyncio.wait_for(entered.wait(), 1)
    try:
        rejected = await asyncio.wait_for(call(), 1)
        assert rejected[0]["status"] == 429
        assert dict(rejected[0]["headers"])[b"retry-after"] == b"2"
        assert b"event_streams_full" in rejected[1]["body"]
        assert len(downstream) == 1
        if end == "disconnect":
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            release.set()
            assert (await first)[0]["status"] == 500
        assert middleware.event_streams == 0
        release.set()
        response = await call()
        assert response[0]["status"] == (500 if end == "error" else 200)
        assert middleware.event_streams == 0
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
