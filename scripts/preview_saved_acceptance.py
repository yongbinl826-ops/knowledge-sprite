"""Temporary loopback preview of a finished live run; write routes are disabled."""
import asyncio
import json
from pathlib import Path
import sys
import uvicorn
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app


def main():
    report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    assert report['final_job']['status'] not in {'queued', 'running'}
    values = report['effective_settings']
    app = create_app(Settings(**values))
    @app.middleware('http')
    async def read_only(request, call_next):
        if request.method not in {'GET', 'HEAD'}:
            return JSONResponse({'detail':'Finished acceptance preview; no new jobs'}, status_code=405)
        return await call_next(request)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001, log_level='warning'))
    async def serve():
        async def expire():
            await asyncio.sleep(600)
            server.should_exit = True
        timer = asyncio.create_task(expire())
        try: await server.serve()
        finally: timer.cancel()
    asyncio.run(serve())


if __name__ == '__main__': main()
