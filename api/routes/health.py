"""Process health and deployment readiness routes."""

from fastapi import APIRouter, Depends, Response, status

from api.config import ApiSettings
from api.dependencies import get_resources, get_settings
from api.repositories import ApiResources
from api.schemas import (
    HealthResponse,
    ReadinessComponentResponse,
    ReadinessResponse,
)

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
) -> ReadinessResponse:
    checks = resources.readiness()
    ready_state = all(item.ready for item in checks if item.required)
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        ready=ready_state,
        components={
            item.name: ReadinessComponentResponse(
                required=item.required,
                ready=item.ready,
                detail=item.detail,
            )
            for item in checks
        },
    )
