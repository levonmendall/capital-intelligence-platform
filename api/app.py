"""FastAPI application factory for the Capital Intelligence Platform."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import ApiSettings
from api.dependencies import require_principal
from api.repositories import (
    ApiResources,
    RepositoryConflictError,
    RepositoryUnavailableError,
    build_resources,
)
from api.routes import (
    alerts_router,
    authentication_router,
    daily_router,
    decisions_router,
    environment_router,
    health_router,
    personal_router,
    portfolios_router,
    replays_router,
    users_router,
)
from delivery import SQLiteAlertStore
from security import AuthenticationService, SQLiteIdentityStore


def create_app(
    settings: ApiSettings | None = None,
    resources: ApiResources | None = None,
    authentication: AuthenticationService | None = None,
    alert_store: SQLiteAlertStore | None = None,
) -> FastAPI:
    """Create the API with explicit injectable data, identity, and alert stores."""

    resolved_settings = settings or ApiSettings.from_env()
    resolved_resources = resources or build_resources(resolved_settings)
    resolved_authentication = authentication or AuthenticationService(
        SQLiteIdentityStore(
            resolved_settings.identity_database,
            access_ttl=timedelta(minutes=resolved_settings.access_token_minutes),
            refresh_ttl=timedelta(days=resolved_settings.refresh_token_days),
            password_minimum_length=resolved_settings.password_minimum_length,
        ),
        required=resolved_settings.authentication_required,
    )
    resolved_authentication.store.bootstrap_administrator(
        email=resolved_settings.bootstrap_admin_email,
        password=resolved_settings.bootstrap_admin_password,
        display_name=resolved_settings.bootstrap_admin_name,
    )
    alert_path = (
        resolved_settings.alert_database
        or resolved_settings.snapshot_database.with_name("alerts.db")
    )
    resolved_alert_store = alert_store or SQLiteAlertStore(alert_path)
    app = FastAPI(
        title=resolved_settings.application_name,
        version=resolved_settings.application_version,
        description=(
            "Authenticated access to governed Capital Intelligence snapshots, "
            "decisions, replays, personal CIO memory, conviction trends, "
            "mandate-authorized portfolios, and selective alert delivery."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.resources = resolved_resources
    app.state.authentication = resolved_authentication
    app.state.alert_store = resolved_alert_store

    if resolved_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=[
                "Accept",
                "Authorization",
                "Content-Type",
                "X-Request-ID",
            ],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
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

    protected = [Depends(require_principal)]
    app.include_router(health_router)
    if resolved_authentication.required:
        app.include_router(authentication_router)
        app.include_router(users_router)
        app.include_router(alerts_router, dependencies=protected)
    app.include_router(daily_router, dependencies=protected)
    app.include_router(environment_router, dependencies=protected)
    app.include_router(decisions_router, dependencies=protected)
    app.include_router(replays_router, dependencies=protected)
    app.include_router(personal_router, dependencies=protected)
    app.include_router(portfolios_router, dependencies=protected)
    return app


__all__ = ["create_app"]
