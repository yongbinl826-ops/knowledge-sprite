from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from .config import Settings
from .db import Store
from .models import SearchRequest
from .service import AdmissionRejected, IdempotencyConflict, JobService
from .project_models import AnalysisDocument, ProjectInput
from .project_service import ProjectError, ProjectService
from .security import RequestSecurityMiddleware
from .result_stream import job_snapshot, project_snapshot, result_events


class AnalyzeProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int | None = Field(default=None, ge=0)
    input: ProjectInput | None = None


class EditProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    input: ProjectInput | None = None
    analysis: AnalysisDocument


class ProjectVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)


class ConfirmProjectRequest(ProjectVersionRequest):
    acknowledged_skipped_prerequisites: list[str] = Field(default_factory=list, max_length=24)


def create_app(settings: Settings | None = None, provider=None, fetcher=None, llm=None, analyzer=None) -> FastAPI:
    settings = (settings or Settings.from_env()).validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.database_path)
        service = projects = None
        try:
            service = JobService(settings, store, provider=provider, fetcher=fetcher, llm=llm)
            app.state.service, app.state.store = service, store
            service.start()
            projects = ProjectService(settings, store, service, analyzer=analyzer)
            app.state.projects = projects
            projects.start()
            yield
        finally:
            # Startup failures must release a worker already started, and one
            # cleanup failure must not leave the SQLite connection open.
            try:
                if projects is not None:
                    await projects.stop()
            finally:
                try:
                    if service is not None:
                        await service.stop()
                finally:
                    store.close()

    app = FastAPI(title="项目制知识引导小精灵", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])
    app.add_middleware(RequestSecurityMiddleware, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError):
        # Default FastAPI validation responses echo rejected user input.
        details = [{key: error[key] for key in ("loc", "msg", "type") if key in error}
                   for error in exc.errors()][:30]
        return JSONResponse({"detail": details}, status_code=422)

    @app.exception_handler(ProjectError)
    async def project_error(_request, exc: ProjectError):
        return JSONResponse({"detail": exc.message, "code": exc.code, **exc.details}, status_code=exc.status)

    @app.get("/health")
    async def health():
        state = app.state.service.health()
        state["project_analysis_pending"] = len(app.state.projects.analysis_tasks)
        state["project_search_pending"] = len(app.state.projects.tasks)
        return JSONResponse(state, status_code=200 if state["status"] == "ok" else 503)

    @app.get("/health/live")
    async def liveness():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness():
        infrastructure = app.state.service.health()["status"] == "ok"
        search = app.state.service.capabilities()["search"]["status"] in {"configured", "available"}
        analysis = bool(getattr(app.state.projects.analyzer, "available", False))
        ready = infrastructure and search and analysis
        return JSONResponse({"status": "ready" if ready else "not_ready", "infrastructure_ready": infrastructure,
            "search_configured": search, "analysis_configured": analysis,
            "upstream_check": "configuration_and_last_observation_only"}, status_code=200 if ready else 503)

    @app.get("/api/capabilities")
    async def capabilities():
        return {**app.state.service.capabilities(), **app.state.projects.capabilities(),
            "deployment": {"local_only": settings.local_only, "authentication": False,
                "single_process": True, "external_access_requires_authenticated_proxy": True},
            "http_limits": {"max_request_body_bytes": settings.max_request_body_bytes,
                "write_limit_per_minute": settings.api_write_limit_per_minute,
                "max_pending_analyses": settings.max_pending_analyses,
                "max_pending_project_searches": settings.max_pending_project_searches}}

    @app.post("/api/projects", status_code=201)
    async def create_project(request: ProjectInput):
        return app.state.projects.create(request)

    @app.get("/api/projects")
    async def list_projects():
        return {"projects": app.state.projects.db.list()}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str, version: int | None = None):
        return app.state.projects.view(project_id, version)

    @app.post("/api/projects/{project_id}/analyze", status_code=202)
    async def analyze_project(project_id: str, request: AnalyzeProjectRequest):
        projects = app.state.projects
        pending = [key for key, task in projects.analysis_tasks.items() if not task.done()]
        same_project = any(key[0] == project_id for key in pending)
        if same_project:
            current = projects.view(project_id)
            version = current.get("version") or {}
            source = request.input.model_dump() if request.input is not None else current["input"]
            if (version.get("status") == "analyzing" and version.get("input") == source and
                request.expected_version in (None, current["current_version"])):
                return current
            return JSONResponse({"detail": "该项目已有分析正在进行，请等待完成后再调整。",
                                 "code": "analysis_in_progress"}, status_code=409)
        if len(pending) >= settings.max_pending_analyses:
            return JSONResponse({"detail": "分析等待队列已满，请稍后重试。", "code": "analysis_queue_full"},
                                status_code=429, headers={"Retry-After": "5"})
        return app.state.projects.analyze(project_id, request.expected_version, request.input)

    @app.post("/api/projects/{project_id}/edit")
    async def edit_project(project_id: str, request: EditProjectRequest):
        return app.state.projects.edit(project_id, request.expected_version, request.analysis, request.input)

    @app.post("/api/projects/{project_id}/confirm")
    async def confirm_project(project_id: str, request: ConfirmProjectRequest):
        return app.state.projects.confirm(project_id, request.version, request.acknowledged_skipped_prerequisites)

    @app.post("/api/projects/{project_id}/search", status_code=202)
    async def search_project(project_id: str, request: ProjectVersionRequest):
        pending = [key for key, task in app.state.projects.tasks.items() if not task.done()]
        if (project_id, request.version) not in pending and len(pending) >= settings.max_pending_project_searches:
            return JSONResponse({"detail": "项目检索等待队列已满，请稍后重试。", "code": "project_search_queue_full"},
                                status_code=429, headers={"Retry-After": "5"})
        return app.state.projects.search(project_id, request.version)

    @app.post("/api/projects/{project_id}/cancel")
    async def cancel_project(project_id: str, request: ProjectVersionRequest):
        return await app.state.projects.cancel(project_id, request.version)

    @app.get("/api/projects/{project_id}/results")
    async def project_results(project_id: str, version: int | None = None):
        return project_snapshot(app.state.projects, app.state.store, project_id, version)

    @app.get("/api/projects/{project_id}/events")
    async def project_events(request: Request, project_id: str, version: int | None = None):
        initial = project_snapshot(app.state.projects, app.state.store, project_id, version)
        initial_revision = app.state.store.connection.total_changes
        # Pin an omitted version to the version visible when the stream opens.
        pinned = (initial.get("version") or {}).get("version", version)
        return StreamingResponse(result_events(request,
            lambda: project_snapshot(app.state.projects, app.state.store, project_id, pinned),
            lambda: app.state.store.connection.total_changes, initial, initial_revision=initial_revision), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.post("/api/search-jobs", status_code=202)
    async def create_job(request: SearchRequest, idempotency_key: str | None = Header(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")):
        try:
            return app.state.service.create(request, idempotency_key)
        except IdempotencyConflict:
            raise HTTPException(409, detail="此幂等键已用于其他检索请求；新检索请使用新的幂等键") from None
        except AdmissionRejected as exc:
            return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status,
                                headers={"Retry-After": str(exc.retry_after)})
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
        results = job_snapshot(app.state.service, app.state.store, job_id)
        if results is None:
            raise HTTPException(404, detail="任务不存在")
        return results

    @app.get("/api/search-jobs/{job_id}/events")
    async def job_events(request: Request, job_id: str):
        initial = job_snapshot(app.state.service, app.state.store, job_id)
        initial_revision = app.state.store.connection.total_changes
        if initial is None:
            raise HTTPException(404, detail="任务不存在")
        return StreamingResponse(result_events(request,
            lambda: job_snapshot(app.state.service, app.state.store, job_id),
            lambda: app.state.store.connection.total_changes, initial, initial_revision=initial_revision), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")
    if (frontend / "index.html").is_file():
        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(frontend / "index.html")
    return app


app = create_app()
