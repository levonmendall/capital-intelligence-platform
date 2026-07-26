"""Read-only governed decision routes."""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_resources
from api.repositories import ApiResources
from api.schemas import DecisionResponse, ErrorResponse

router = APIRouter(
    prefix="/v1/decisions",
    tags=["legacy snapshot decisions"],
    deprecated=True,
)


@router.get(
    "/{decision_identifier}",
    response_model=DecisionResponse,
    responses={404: {"model": ErrorResponse}},
)
def decision(
    decision_identifier: str,
    resources: ApiResources = Depends(get_resources),
) -> DecisionResponse:
    payload = resources.snapshots.find_decision(decision_identifier)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="decision was not found in canonical snapshot history",
        )
    return DecisionResponse.model_validate(payload)
