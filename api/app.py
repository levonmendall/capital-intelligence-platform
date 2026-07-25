"""FastAPI application factory for the Capital Intelligence Platform."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import ApiSettings
from api.repositories import (
    ApiResources,
    RepositoryConflictError,
    RepositoryUnavailableError,
    build_resources,
)
from api.routes import (
    daily_router,
    decisions_router,
    environment_router,
    health_router,
    personal_router,
    portfolios_router,
    replays_router,
)


def create_app(
    settings: ApiSettings | None = None,
    resources: ApiResources | None = None,
) -> FastAPI:
    """Create a read-only API with explicit injectable dependencies."""

    resolved_settings = settings or ApiSettings.from_env()
    resolved_resources = resources or build_resources(resolved_settings)
    app = FastAPI(
        title=resolved_settings.application_name,
        version=resolved_settings.application_version,
        description=(
            "Read-only access to governed Capital Intelligence snapshots, "
            "decisions, replays, personal CIO memory, conviction trends, "
            "and virtual portfolios."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.resources = resolved_resources

    if resolved_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RepositoryUnavailableError)
    async def unavailable_handler(
        request: Request,
        error: RepositoryUnavailableError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(RepositoryConflictError)
    async def conflict_handler(
        request: Request,
        error: RepositoryConflictError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=409, content={"detail": str(error)})

    app.include_router(health_router)
    app.include_router(daily_router)
    app.include_router(environment_router)
    app.include_router(decisions_router)
    app.include_router(replays_router)
    app.include_router(personal_router)
    app.include_router(portfolios_router)
    return app


__all__ = ["create_app"]
