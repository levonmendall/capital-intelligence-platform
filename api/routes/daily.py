"""Daily snapshot and history routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.config import ApiSettings
from api.dependencies import get_resources, get_settings
from api.repositories import ApiResources
from api.schemas import DailyHistoryResponse, ErrorResponse

router = APIRouter(
    prefix="/v1/daily",
    tags=["legacy daily diagnostics"],
    deprecated=True,
)


@router.get(
    "/latest",
    response_model=dict[str, Any],
    responses={404: {"model": ErrorResponse}},
)
def latest(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.snapshots.latest_payload()
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no canonical daily snapshot is available",
        )
    return payload


@router.get("/history", response_model=DailyHistoryResponse)
def history(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    settings: ApiSettings = Depends(get_settings),
    resources: ApiResources = Depends(get_resources),
) -> DailyHistoryResponse:
    resolved_limit = settings.history_default_limit if limit is None else limit
    if resolved_limit > settings.history_max_limit:
        raise HTTPException(
            status_code=422,
            detail=(
                "limit exceeds CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT "
                f"({settings.history_max_limit})"
            ),
        )
    return DailyHistoryResponse(
        items=list(
            resources.snapshots.history(
                limit=resolved_limit,
                offset=offset,
            )
        ),
        limit=resolved_limit,
        offset=offset,
        total=resources.snapshots.count(),
    )
