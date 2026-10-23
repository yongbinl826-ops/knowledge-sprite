"""No account, enumeration or legacy API: per-task temporary capabilities."""
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .mobile_tasks import MobileError, MobileTaskPayload, capability, task_id


def register_mobile_routes(app, settings):
    @app.exception_handler(MobileError)
    async def mobile_error(_request, exc):
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status,
                            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else {})

    def identity(identifier, request):
        # A token in a URL is never accepted as authentication.
        if request.query_params:
            raise MobileError()
        return task_id(identifier), capability(request.headers)

    @app.post("/api/mobile/tasks/{identifier}", status_code=202)
    async def create_mobile_task(identifier: str, request: Request):
        identifier, digest = identity(identifier, request)
        await app.state.mobile.cleanup_once()
        if identifier in app.state.mobile.tombstones:
            raise MobileError()
        existing = app.state.mobile.records.get(identifier)
        if existing:
            app.state.mobile._auth(identifier, digest)
        try:
            payload = MobileTaskPayload.model_validate(await request.json())
        except (ValidationError, ValueError):
            raise MobileError("invalid_request", 422) from None
        return await app.state.mobile.create(identifier, digest, payload, request.client.host if request.client else None)

    @app.get("/api/mobile/tasks/{identifier}")
    async def get_mobile_task(identifier: str, request: Request):
        identifier, digest = identity(identifier, request)
        app.state.mobile.rate(request.client.host if request.client else None)
        return await app.state.mobile.get(identifier, digest)

    @app.post("/api/mobile/tasks/{identifier}/cancel")
    async def cancel_mobile_task(identifier: str, request: Request):
        identifier, digest = identity(identifier, request)
        return await app.state.mobile.cancel(identifier, digest)

    @app.get("/api/mobile/courses")
    async def public_mobile_courses(request: Request):
        app.state.mobile.rate(request.client.host if request.client else None)
        allowed = {"query", "platform", "offset", "limit"}
        if set(request.query_params) - allowed or any(len(request.query_params.getlist(k)) > 1 for k in allowed):
            raise MobileError("invalid_request", 422)
        try:
            offset, limit = request.query_params.get("offset", "0"), request.query_params.get("limit", "20")
            if not offset.isascii() or not offset.isdigit() or not limit.isascii() or not limit.isdigit():
                raise ValueError()
            return app.state.mobile.public.browse(request.query_params.get("query", ""), request.query_params.get("platform"), int(offset), int(limit))
        except ValueError:
            raise MobileError("invalid_request", 422) from None
