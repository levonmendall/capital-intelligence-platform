"""System health and distinct readiness-status routes."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status

from api.canonical_environment import CanonicalEnvironmentRepository
from api.config import ApiSettings
from api.dependencies import (
    get_alert_store,
    get_authentication,
    get_operational_settings,
    get_resources,
    get_settings,
)
from api.readiness_status import ReadinessStatusRepository
from api.repositories import (
    ApiResources,
    ReadinessComponent,
    RepositoryUnavailableError,
    _read_only_connection,
)
from api.schemas import (
    HealthResponse,
    ReadinessComponentResponse,
    ReadinessResponse,
)
from delivery import SQLiteAlertStore
from operations import OperationalSettings
from security import AuthenticationService

router = APIRouter(tags=["operations"])


def _database_component(
    *,
    name: str,
    path: Path,
    required: bool,
    detail: str,
) -> ReadinessComponent:
    if not path.exists() and not required:
        return ReadinessComponent(
            name=name,
            required=False,
            ready=True,
            detail=f"{detail} is optional and has not been created",
        )
    try:
        with _read_only_connection(path) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except (sqlite3.Error, RepositoryUnavailableError) as error:
        return ReadinessComponent(
            name=name,
            required=required,
            ready=False,
            detail=str(error),
        )
    ready = row is not None and str(row[0]).lower() == "ok"
    return ReadinessComponent(
        name=name,
        required=required,
        ready=ready,
        detail=(
            f"{detail} is readable and passed SQLite quick_check"
            if ready
            else f"{detail} failed SQLite quick_check"
        ),
    )


def _dependency_components(
    *,
    request: Request,
    resources: ApiResources,
    authentication: AuthenticationService,
    alert_store: SQLiteAlertStore,
    settings: ApiSettings,
    operations: OperationalSettings,
) -> dict[str, ReadinessComponentResponse]:
    legacy_read_only_compatibility = (
        not settings.require_canonical_environment
        and not settings.full_universe_screening_database.exists()
    )
    active_checks = [
        resources.portfolios.check(),
        resources.journal.check(),
        ReadinessComponent(
            name="live_provider",
            required=resources.require_live_provider,
            ready=(
                resources.live_provider_configured
                or not resources.require_live_provider
            ),
            detail=(
                "live provider credentials are configured"
                if resources.live_provider_configured
                else "live provider credentials are not required"
                if not resources.require_live_provider
                else "required live provider credentials are missing"
            ),
        ),
        _database_component(
            name="full_universe_screening",
            path=settings.full_universe_screening_database,
            required=not legacy_read_only_compatibility,
            detail="complete-universe screening authority",
        ),
        CanonicalEnvironmentRepository(
            settings.environment_database,
            required=settings.require_canonical_environment,
        ).check(),
    ]
    if legacy_read_only_compatibility:
        active_checks.append(resources.snapshots.check())
        slo_snapshot = request.app.state.operational_slo_service.assess()
        slo_states = ", ".join(
            f"{item.name.value}={item.status.value}"
            for item in slo_snapshot.components
        )
        active_checks.append(
            ReadinessComponent(
                name="operational_slos",
                required=operations.require_operational_slos,
                ready=slo_snapshot.ready,
                detail=(
                    f"legacy read-only compatibility; policy="
                    f"{slo_snapshot.policy_version}; evaluated_at="
                    f"{slo_snapshot.evaluated_at.isoformat()}; {slo_states}"
                ),
            )
        )
    identity = authentication.readiness()
    active_checks.append(
        ReadinessComponent(
            name=identity.name,
            required=identity.required,
            ready=identity.ready,
            detail=identity.detail,
        )
    )
    alert_ready, alert_detail = alert_store.readiness()
    email_detail = (
        " SMTP email delivery is configured."
        if settings.smtp_host and settings.smtp_from_address
        else " Email delivery is disabled; in-app delivery remains available."
    )
    active_checks.append(
        ReadinessComponent(
            name="scheduled_alerts",
            required=True,
            ready=alert_ready,
            detail=alert_detail + email_detail,
        )
    )
    backup_ready = operations.backup_directory.exists() and os.access(
        operations.backup_directory,
        os.W_OK,
    )
    active_checks.append(
        ReadinessComponent(
            name="backup_target",
            required=True,
            ready=backup_ready,
            detail=(
                f"backup target is writable: {operations.backup_directory}"
                if backup_ready
                else f"backup target is unavailable: {operations.backup_directory}"
            ),
        )
    )
    active_checks.append(
        ReadinessComponent(
            name="operational_policy",
            required=True,
            ready=True,
            detail=(
                f"environment={operations.environment}; https_enforced="
                f"{str(operations.enforce_https).lower()}; "
                "encrypted_backups_required="
                f"{str(operations.require_encrypted_backups).lower()}"
            ),
        )
    )
    return {
        item.name: ReadinessComponentResponse(
            required=item.required,
            ready=item.ready,
            detail=item.detail,
        )
        for item in active_checks
    }


@router.get("/health", response_model=HealthResponse)
def health(settings: ApiSettings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.application_name,
        version=settings.application_version,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(
    request: Request,
    response: Response,
    resources: ApiResources = Depends(get_resources),
    authentication: AuthenticationService = Depends(get_authentication),
    alert_store: SQLiteAlertStore = Depends(get_alert_store),
    settings: ApiSettings = Depends(get_settings),
    operations: OperationalSettings = Depends(get_operational_settings),
) -> ReadinessResponse:
    components = _dependency_components(
        request=request,
        resources=resources,
        authentication=authentication,
        alert_store=alert_store,
        settings=settings,
        operations=operations,
    )
    ready_state = all(
        item.ready for item in components.values() if item.required
    )
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(ready=ready_state, components=components)


@router.get("/v1/readiness/status")
def readiness_status(
    request: Request,
    resources: ApiResources = Depends(get_resources),
    authentication: AuthenticationService = Depends(get_authentication),
    alert_store: SQLiteAlertStore = Depends(get_alert_store),
    settings: ApiSettings = Depends(get_settings),
    operations: OperationalSettings = Depends(get_operational_settings),
) -> dict[str, object]:
    components = _dependency_components(
        request=request,
        resources=resources,
        authentication=authentication,
        alert_store=alert_store,
        settings=settings,
        operations=operations,
    )
    dependency_ready = all(
        item.ready for item in components.values() if item.required
    )
    persisted = ReadinessStatusRepository(
        readiness_evidence_path=settings.readiness_evidence_database,
        product_test_readiness_path=settings.product_test_readiness_database,
    )
    operational = persisted.latest_operational()
    paper_test = persisted.latest_paper_test()
    return {
        "system_health": {
            "state": "healthy",
            "ready": True,
            "detail": "API process is alive and serving requests",
        },
        "dependency_readiness": {
            "state": "ready" if dependency_ready else "blocked",
            "ready": dependency_ready,
            "detail": (
                "all required active API dependencies are ready"
                if dependency_ready
                else "one or more required active API dependencies are unavailable"
            ),
            "components": {
                name: component.model_dump()
                for name, component in components.items()
            },
        },
        "operational_readiness": operational,
        "paper_test_readiness": paper_test,
        "statuses_are_independent": True,
        "api_health_implies_paper_test_readiness": False,
        "real_money_authorized": False,
        "performance_claims_permitted": False,
        "schema_version": "capital-intelligence-readiness-status.v1",
    }


__all__ = ["router"]
