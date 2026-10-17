from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .db import Store
from .models import SearchRequest
from .service import IdempotencyConflict, JobService


def create_app(settings: Settings | None = None, provider=None, fetcher=None, llm=None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=provider, fetcher=fetcher, llm=llm)
        app.state.service, app.state.store = service, store
        service.start()
        yield
        await service.stop()
        store.close()

    app = FastAPI(title="项目制知识引导小精灵", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "live", "single_worker": True}

    @app.get("/api/capabilities")
    async def capabilities():
        return app.state.service.capabilities()

    @app.post("/api/search-jobs", status_code=202)
    async def create_job(request: SearchRequest, idempotency_key: str | None = Header(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")):
        try:
            return app.state.service.create(request, idempotency_key)
        except IdempotencyConflict:
            raise HTTPException(409, detail="此幂等键已用于其他检索请求；新检索请使用新的幂等键") from None
        except ValueError:
            raise HTTPException(422, detail="知识点数量超过当前服务预算") from None

    @app.get("/api/search-jobs/{job_id}")
    async def get_job(job_id: str):
        job = app.state.store.get_job(job_id)
        if not job:
            raise HTTPException(404, detail="任务不存在")
        return job

    @app.post("/api/search-jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        result = await app.state.service.cancel(job_id)
        if result is None:
            raise HTTPException(404, detail="任务不存在")
        return result

    @app.get("/api/search-jobs/{job_id}/results")
    async def get_results(job_id: str):
        results = app.state.service.results(job_id)
        if results is None:
            raise HTTPException(404, detail="任务不存在")
        return results

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")
    if (frontend / "index.html").is_file():
        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(frontend / "index.html")
    return app


app = create_app()
