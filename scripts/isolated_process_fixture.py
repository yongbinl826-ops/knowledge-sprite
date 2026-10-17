"""Loopback-only fixture processes for process-lifecycle acceptance, never production."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone
from starlette.requests import Request


def stamp():
    return datetime.now(timezone.utc).isoformat()


def append_durable(path, value):
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def install_loopback_guard(path, allowed_ports):
    """Python socket boundary, explicitly not an OS firewall/external exactly-once proof."""
    def guard(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            return
        address = args[1] if event != "socket.getaddrinfo" else args[:2]
        host, port = address[:2] if isinstance(address, tuple) and len(address) >= 2 else (None, None)
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        permitted = host == "127.0.0.1" and port in allowed_ports
        append_durable(path, {"at": stamp(), "pid": os.getpid(), "event": event,
                              "host": host, "port": port, "allowed": permitted})
        if not permitted:
            raise RuntimeError("Fixture network guard rejected non-owned loopback destination")
    sys.addaudithook(guard)


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, job_id TEXT, attempt_key TEXT, data TEXT)")
        self.db.commit()

    def add(self, kind, job_id, key, **data):
        with self.db:
            self.db.execute("INSERT INTO events(at,kind,job_id,attempt_key,data) VALUES(?,?,?,?,?)",
                            (stamp(), kind, job_id, key, json.dumps(data)))


def build_fixture(args):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    app = FastAPI()
    ledger = Ledger(args.ledger)
    active = set()

    @app.get("/__fixture/identity")
    async def identity():
        return {"pid": os.getpid(), "token": args.token, "db": args.db, "port": args.port,
                "mode": args.mode, "active": len(active), "ledger": args.ledger}

    @app.get("/__fixture/events")
    async def events():
        rows = ledger.db.execute("SELECT id,at,kind,job_id,attempt_key,data FROM events ORDER BY id").fetchall()
        return [{"id": r[0], "at": r[1], "kind": r[2], "job_id": r[3], "attempt_key": r[4], "data": json.loads(r[5])} for r in rows]

    @app.post("/work")
    async def work(request: Request):
        body = await request.json()
        if body.get("token") != args.token:
            return JSONResponse({"error": "wrong fixture token"}, status_code=403)
        job_id, phase = body["job_id"], body["phase"]
        key = hashlib.sha256(json.dumps([job_id, phase, body.get("query", "")]).encode()).hexdigest()
        ledger.add("entered", job_id, key, phase=phase, query=body.get("query"), caller_pid=body["pid"])
        active.add(key)
        outcome = "abandoned"
        try:
            if body.get("block"):
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if await request.is_disconnected():
                        outcome = "disconnected"
                        return JSONResponse({"disconnected": True}, status_code=499)
                    await asyncio.sleep(.02)
                outcome = "fixture_timeout"
                return JSONResponse({"timeout": True}, status_code=504)
            await asyncio.sleep(.03)
            outcome = "returned"
            title = body["topic"] + " course"
            html = '<html><title>' + title + '</title><script type="application/ld+json">' + json.dumps(
                {"@context": "https://schema.org", "@type": "Course", "name": title,
                 "description": "Local fixture teaching " + body["topic"]}) + '</script></html>'
            return {"html": html}
        finally:
            active.discard(key)
            ledger.add(outcome, job_id, key, phase=phase)

    return app


def build_application(args):
    import httpx
    from backend.app.config import Settings
    from backend.app.extractor import MetadataExtractor
    from backend.app.main import create_app
    from backend.app.models import Candidate

    class LoopbackTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            allowed = (request.url.scheme == "http" and request.url.host == "127.0.0.1"
                       and request.url.port == args.target_port)
            append_durable(args.audit, {"at": stamp(), "pid": os.getpid(), "event": "fixture_http_dispatch",
                "host": request.url.host, "port": request.url.port, "allowed": allowed})
            if not allowed:
                raise RuntimeError("Fixture HTTP dispatcher rejected non-owned destination")
            return await super().handle_async_request(request)

    def running_job():
        db = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT data FROM jobs WHERE status='running'").fetchall()
        finally:
            db.close()
        if len(rows) != 1:
            raise RuntimeError("Fixture expected exactly one durable running job")
        return json.loads(rows[0][0])

    async def work(phase, query=""):
        job = running_job()
        topic = job["request"]["knowledge_points"][0]
        # Windows IOCP ConnectEx does not emit socket.connect in all paths;
        # enforce and log this HTTP boundary independently of socket auditing.
        async with httpx.AsyncClient(trust_env=False, timeout=50, transport=LoopbackTransport(trust_env=False)) as client:
            response = await client.post(f"http://127.0.0.1:{args.target_port}/work", json={
                "token": args.token, "job_id": job["job_id"], "pid": os.getpid(),
                "phase": phase, "query": query, "topic": topic, "block": topic.startswith("hold_")})
            response.raise_for_status()
            return job, response.json()

    class Provider:
        name = "isolated_process_fixture"
        async def search(self, query, *_args):
            job, _ = await work("provider", query)
            topic = job["request"]["knowledge_points"][0]
            return [Candidate(id="fixture-" + job["job_id"], title=topic + " course tutorial",
                              url="https://fixture.example.com/course/" + job["job_id"],
                              snippet="Local fixture teaching " + topic, source=self.name, query=query)]

    class Fetcher:
        async def enrich(self, candidate):
            _, result = await work("target", candidate["url"])
            return MetadataExtractor().extract(result["html"], candidate["url"], stamp())

    settings = Settings(database_path=args.db, search_provider="isolated_process_fixture",
                        fetch_enabled=True, max_search_requests=2, max_detail_pages=1,
                        global_concurrency=1, max_pending_jobs=2, submission_limit_per_minute=30,
                        deadline_seconds=60, max_queue_wait_seconds=60, search_max_retries=0,
                        official_sitemap_fallback=False, js_render_enabled=False, llm_provider="none")
    app = create_app(settings, provider=Provider(), fetcher=Fetcher())

    @app.get("/__fixture/identity")
    async def identity():
        return {"pid": os.getpid(), "token": args.token, "db": args.db, "port": args.port,
                "mode": args.mode, "target_port": args.target_port}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["app", "target"], required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--audit", required=True)
    args = parser.parse_args()
    if 8000 in (args.port, args.target_port) or not all(1024 <= x <= 65535 for x in (args.port, args.target_port)):
        raise SystemExit("Unsafe fixture port")
    # CPython on Windows builds its event-loop self-pipe with a localhost
    # ephemeral socketpair. Construct that runtime primitive before enforcing
    # the two fixture ports; no application client exists at this point.
    loop = asyncio.new_event_loop()
    append_durable(args.audit, {"at": stamp(), "pid": os.getpid(),
        "event": "asyncio_loopback_self_pipe_created_before_guard", "host": "127.0.0.1", "port": None, "allowed": True})
    install_loopback_guard(args.audit, {args.port, args.target_port})
    import uvicorn
    app = build_application(args) if args.mode == "app" else build_fixture(args)
    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, workers=1,
                            access_log=False, log_level="warning", loop="none")
    try:
        loop.run_until_complete(uvicorn.Server(config).serve())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
