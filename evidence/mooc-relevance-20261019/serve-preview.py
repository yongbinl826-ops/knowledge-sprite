"""Run the existing local preview database and retain the observed source pause."""
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app
import uvicorn

database = ROOT / "data/discovery-tavily-preview-20261019.sqlite3"
assert database.is_file(), "The existing preview database must already exist"
app = create_app(replace(Settings.from_env(), database_path=str(database)).validate())
original_lifespan = app.router.lifespan_context
evidence_dir = Path(__file__).resolve().parent


@asynccontextmanager
async def retain_source_pause(application):
    async with original_lifespan(application):
        remaining = 0.0
        source = application.state.service._source_objects().get("tavily")
        if source and source.auth_mode == "keyless":
            attempts = json.loads((evidence_dir / "live/search_attempts.json").read_text(encoding="utf-8"))
            for attempt in attempts:
                for trace in attempt.get("provider_requests", []):
                    if trace.get("provider") == "tavily" and trace.get("http_status") == 429:
                        until = (datetime.fromisoformat(trace["started_at"]).timestamp()
                                 + trace.get("elapsed_seconds", 0) + trace.get("retry_after_seconds", 0))
                        remaining = max(remaining, until - time.time())
            if remaining > 0:
                source.paused_until = time.monotonic() + remaining
                source.last_status = "fault"
        (evidence_dir / "preview-startup.json").write_text(json.dumps({
            "started_at_unix": time.time(), "port": 8002, "database": str(database),
            "restored_keyless_pause_seconds": max(0, remaining),
            "startup_search_requests": 0,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        yield


app.router.lifespan_context = retain_source_pause
uvicorn.run(app, host="127.0.0.1", port=8002, workers=1, access_log=False)
