"""Process health and deployment readiness routes."""

from fastapi import APIRouter, Depends, Response, status

from api.config import ApiSettings
from api.dependencies import (
    get_alert_store,
    get_authentication,
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
    ready_state = all(item.ready for item in components.values() if item.required)
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(ready=ready_state, components=components)
