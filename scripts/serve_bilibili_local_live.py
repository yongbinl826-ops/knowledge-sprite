"""Fresh local-only acceptance server; normal provider, extraction and budgets.

Adds the existing read-only HTTP audit side channel. It never seeds candidates,
replays saved HTML, sends credentials, or alters source responses.
"""
from dataclasses import replace
import argparse
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.fetcher import utcnow
import backend.app.main as main_module
from scripts import serve_platform_live_chain as audit


def app_for(output: Path, port: int = 18101):
    output.mkdir(parents=True, exist_ok=True)
    database = output / "live.sqlite3"
    if database.exists():
        raise RuntimeError("This acceptance run requires a fresh database directory")
    settings = replace(Settings.from_env(), database_path=str(database))
    if not settings.bilibili_public_metadata:
        raise RuntimeError("Enable BILIBILI_PUBLIC_METADATA for this local acceptance run")
    registry = {"output": str(output), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    main_module.JobService = audit.service_class(output, registry)
    app = main_module.create_app(settings)
    sources = [path for folder in (ROOT / "backend/app", ROOT / "frontend/dist")
               for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    sources.append(Path(__file__).resolve())
    (output / "run.json").write_text(json.dumps({
        "started_at": utcnow(), "url": f"http://127.0.0.1:{port}",
        "fresh_database": True, "saved_page_replay": False, "candidate_injection": False,
        "bilibili_public_metadata": settings.bilibili_public_metadata,
        "source_hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    @app.get("/api/live-audit", include_in_schema=False)
    async def live_audit():
        return registry

    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=["initial", "final"], default="initial")
    args = parser.parse_args()
    port = 18102 if args.revision == "final" else 18101
    name = "final-live-run" if args.revision == "final" else "live-run"
    uvicorn.run(app_for(ROOT / "reports/bilibili-local-use-20261017" / name, port),
                host="127.0.0.1", port=port, workers=1)
