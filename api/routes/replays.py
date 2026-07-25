"""Read-only Decision Replay routes."""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_resources
from api.repositories import ApiResources
from api.schemas import ErrorResponse, ReplayListResponse, ReplayReference

router = APIRouter(prefix="/v1/replays", tags=["decision replay"])


@router.get("", response_model=ReplayListResponse)
def list_replays(
    resources: ApiResources = Depends(get_resources),
) -> ReplayListResponse:
    stored = {
        str(payload["identifier"]): payload
        for payload in resources.replays.list_payloads()
    }
    identifiers = set(resources.snapshots.replay_identifiers()) | set(stored)
    items = [
        ReplayReference(
            identifier=identifier,
            available=identifier in stored,
            created_at=(stored.get(identifier) or {}).get("created_at"),
            relative_return=(
                stored.get(identifier) or {}
            ).get("relative_return"),
            lesson=(stored.get(identifier) or {}).get("lesson"),
        )
        for identifier in sorted(identifiers)
    ]
    return ReplayListResponse(items=items, total=len(items))


@router.get(
    "/{replay_identifier:path}",
    response_model=dict,
    responses={404: {"model": ErrorResponse}},
)
def replay(
    replay_identifier: str,
    resources: ApiResources = Depends(get_resources),
) -> dict:
    payload = resources.replays.get(replay_identifier)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="decision replay artifact is not available",
        )
    return payload
