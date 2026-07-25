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
    business_cycle_router,
    daily_router,
    decisions_router,
    environment_router,
    health_router,
    liquidity_router,
    objectives_router,
    operations_router,
    personal_router,
    personal_cio_history_router,
    portfolios_router,
    replays_router,
    users_router,
)
from delivery import SQLiteAlertStore
from operations import (
    MetricRegistry,
    OperationalSettings,
    configure_logging,
    install_operational_middleware,
)
from security import AuthenticationService, SQLiteIdentityStore


def create_app(
    settings: ApiSettings | None = None,
    resources: ApiResources | None = None,
    authentication: AuthenticationService | None = None,
    alert_store: SQLiteAlertStore | None = None,
    operational_settings: OperationalSettings | None = None,
    metrics: MetricRegistry | None = None,
) -> FastAPI:
    """Create the API with explicit injectable runtime dependencies."""

    resolved_settings = settings or ApiSettings.from_env()
    resolved_operations = operational_settings or OperationalSettings.from_env()
    configure_logging(resolved_operations)
    resolved_operations.backup_directory.mkdir(parents=True, exist_ok=True)
    resolved_operations.worker_heartbeat_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
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
    resolved_metrics = metrics or MetricRegistry()
    app = FastAPI(
        title=resolved_settings.application_name,
        version=resolved_settings.application_version,
        description=(
            "Authenticated access to governed Capital Intelligence snapshots, "
            "global liquidity and business-cycle intelligence, investor "
            "objectives, Personal CIO briefs, decisions, replays, personal "
            "memory, conviction trends, mandate-authorized portfolios, and "
            "selective alert delivery."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.operational_settings = resolved_operations
    app.state.resources = resolved_resources
    app.state.authentication = resolved_authentication
    app.state.alert_store = resolved_alert_store
    app.state.metrics = resolved_metrics

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
    install_operational_middleware(app, resolved_operations, resolved_metrics)

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
    app.include_router(operations_router)
    if resolved_authentication.required:
        app.include_router(authentication_router)
        app.include_router(users_router)
        app.include_router(alerts_router, dependencies=protected)
        app.include_router(objectives_router, dependencies=protected)
        app.include_router(personal_cio_history_router, dependencies=protected)
    app.include_router(daily_router, dependencies=protected)
    app.include_router(environment_router, dependencies=protected)
    app.include_router(business_cycle_router, dependencies=protected)
    app.include_router(liquidity_router, dependencies=protected)
    app.include_router(decisions_router, dependencies=protected)
    app.include_router(replays_router, dependencies=protected)
    app.include_router(personal_router, dependencies=protected)
    app.include_router(portfolios_router, dependencies=protected)
    return app


__all__ = ["create_app"]
