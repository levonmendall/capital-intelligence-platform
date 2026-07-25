"""Latest market-environment route."""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_resources
from api.repositories import ApiResources
from api.schemas import EnvironmentResponse, ErrorResponse

router = APIRouter(prefix="/v1/environment", tags=["environment"])


@router.get(
    "/latest",
    response_model=EnvironmentResponse,
    responses={404: {"model": ErrorResponse}},
)
def latest_environment(
    resources: ApiResources = Depends(get_resources),
) -> EnvironmentResponse:
    payload = resources.snapshots.latest_payload()
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no canonical environment snapshot is available",
        )
    environment = payload.get("environment")
    sources = payload.get("sources")
    if not isinstance(environment, dict) or not isinstance(sources, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="latest snapshot does not contain the canonical environment contract",
        )
    return EnvironmentResponse(
        snapshot_identifier=str(payload["identifier"]),
        as_of=str(payload["as_of"]),
        environment=environment,
        sources={str(key): str(value) for key, value in sources.items()},
    )
