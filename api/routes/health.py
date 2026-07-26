"""Process health and deployment readiness routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Response, status

from api.config import ApiSettings
from api.dependencies import (
    get_alert_store,
    get_authentication,
    get_operational_settings,
    get_resources,
    get_settings,
)
from api.repositories import ApiResources
from api.schemas import (
    HealthResponse,
    ReadinessComponentResponse,
    ReadinessResponse,
)
from delivery import SQLiteAlertStore
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.risk import risk_source_readiness
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.technical_momentum import (
    technical_momentum_source_readiness,
)
from intelligence.valuation import valuation_source_readiness
from operations import OperationalSettings
from security import AuthenticationService

router = APIRouter(tags=["operations"])


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
    response: Response,
    resources: ApiResources = Depends(get_resources),
    authentication: AuthenticationService = Depends(get_authentication),
    alert_store: SQLiteAlertStore = Depends(get_alert_store),
    settings: ApiSettings = Depends(get_settings),
    operations: OperationalSettings = Depends(get_operational_settings),
) -> ReadinessResponse:
    checks = list(resources.readiness())
    identity = authentication.readiness()
    components = {
        item.name: ReadinessComponentResponse(
            required=item.required,
            ready=item.ready,
            detail=item.detail,
        )
        for item in checks
    }
    components[identity.name] = ReadinessComponentResponse(
        required=identity.required,
        ready=identity.ready,
        detail=identity.detail,
    )
    alert_ready, alert_detail = alert_store.readiness()
    email_detail = (
        " SMTP email delivery is configured."
        if settings.smtp_host and settings.smtp_from_address
        else " Email delivery is disabled; in-app delivery remains available."
    )
    components["scheduled_alerts"] = ReadinessComponentResponse(
        required=True,
        ready=alert_ready,
        detail=alert_detail + email_detail,
    )
    engine_path = settings.snapshot_database.with_name("analytical_engines.db")
    if engine_path.exists():
        engine_ready, engine_detail = SQLiteAnalyticalEngineStore(
            engine_path,
            read_only=True,
        ).readiness()
        normalization_ready, normalization_detail = SQLiteNormalizationStore(
            engine_path,
            read_only=True,
        ).readiness()
        synthesis_ready, synthesis_detail = SQLiteSynthesisStore(
            engine_path,
            read_only=True,
        ).readiness()
        governance_ready, governance_detail = SQLiteGovernanceStore(
            engine_path,
            read_only=True,
        ).readiness()
    else:
        engine_ready = True
        engine_detail = (
            "analytical engine history has not been created; the core daily "
            "intelligence path remains available"
        )
        normalization_ready = True
        normalization_detail = (
            "normalization history has not been created; raw analytical engine "
            "results remain available"
        )
        synthesis_ready = True
        synthesis_detail = (
            "weighted synthesis history has not been created; normalization "
            "remains available"
        )
        governance_ready = True
        governance_detail = (
            "governance history has not been created; weighted synthesis remains "
            "available"
        )
    components["analytical_engines"] = ReadinessComponentResponse(
        required=False,
        ready=engine_ready,
        detail=engine_detail,
    )
    components["multi_engine_normalization"] = ReadinessComponentResponse(
        required=False,
        ready=normalization_ready,
        detail=normalization_detail,
    )
    components["multi_engine_synthesis"] = ReadinessComponentResponse(
        required=False,
        ready=synthesis_ready,
        detail=synthesis_detail,
    )
    components["multi_engine_governance"] = ReadinessComponentResponse(
        required=False,
        ready=governance_ready,
        detail=governance_detail,
    )
    breadth_source = os.environ.get(
        "CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE"
    )
    if breadth_source and breadth_source.strip():
        breadth_path = Path(breadth_source).expanduser()
        breadth_ready = breadth_path.is_file() and os.access(breadth_path, os.R_OK)
        breadth_detail = (
            f"market breadth source is readable: {breadth_path}"
            if breadth_ready
            else f"configured market breadth source is unavailable: {breadth_path}"
        )
    else:
        breadth_ready = True
        breadth_detail = (
            "market breadth source is not configured; the engine will publish "
            "unavailable without blocking the core daily intelligence path"
        )
    components["market_breadth_source"] = ReadinessComponentResponse(
        required=False,
        ready=breadth_ready,
        detail=breadth_detail,
    )
    valuation_ready, valuation_detail = valuation_source_readiness()
    components["valuation_source"] = ReadinessComponentResponse(
        required=False,
        ready=valuation_ready,
        detail=valuation_detail,
    )
    technical_ready, technical_detail = technical_momentum_source_readiness()
    components["technical_momentum_source"] = ReadinessComponentResponse(
        required=False,
        ready=technical_ready,
        detail=technical_detail,
    )
    risk_ready, risk_detail = risk_source_readiness()
    components["risk_source"] = ReadinessComponentResponse(
        required=False,
        ready=risk_ready,
        detail=risk_detail,
    )
    backup_ready = operations.backup_directory.exists() and os.access(
        operations.backup_directory,
        os.W_OK,
    )
    components["backup_target"] = ReadinessComponentResponse(
        required=True,
        ready=backup_ready,
        detail=(
            f"backup target is writable: {operations.backup_directory}"
            if backup_ready
            else f"backup target is unavailable: {operations.backup_directory}"
        ),
    )
    components["operational_policy"] = ReadinessComponentResponse(
        required=True,
        ready=True,
        detail=(
            f"environment={operations.environment}; https_enforced="
            f"{str(operations.enforce_https).lower()}; "
            "encrypted_backups_required="
            f"{str(operations.require_encrypted_backups).lower()}"
        ),
    )
    ready_state = all(
        item.ready for item in components.values() if item.required
    )
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(ready=ready_state, components=components)