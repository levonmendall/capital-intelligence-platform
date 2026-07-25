"""Read-only personal CIO memory and conviction routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import ApiSettings
from api.dependencies import get_settings
from api.schemas import (
    ConvictionTrendResponse,
    InvestorMemoryHistoryResponse,
    InvestorMemoryResponse,
)
from personalization import (
    SQLiteInvestorMemoryStore,
    build_investor_memory_profile,
    investor_memory_event_to_dict,
    investor_memory_profile_to_dict,
)
from reporting.conviction_trend import (
    build_conviction_trend_from_store,
    conviction_trend_to_dict,
)


router = APIRouter(prefix="/v1", tags=["personal CIO"])


@router.get(
    "/conviction/latest",
    response_model=ConvictionTrendResponse,
)
def latest_conviction(
    lookback: int | None = Query(default=None, ge=2),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    resolved_lookback = lookback or settings.conviction_default_lookback
    if resolved_lookback > settings.conviction_max_lookback:
        raise HTTPException(
            status_code=422,
            detail=(
                "lookback exceeds the configured maximum of "
                f"{settings.conviction_max_lookback}"
            ),
        )
    trend = build_conviction_trend_from_store(
        settings.snapshot_database,
        lookback=resolved_lookback,
    )
    return conviction_trend_to_dict(trend)


@router.get(
    "/investor-memory/{investor_identifier}",
    response_model=InvestorMemoryResponse,
)
def investor_memory_profile(
    investor_identifier: str,
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.investor_memory_database.exists():
        profile = build_investor_memory_profile(investor_identifier, ())
        return investor_memory_profile_to_dict(profile)
    try:
        store = SQLiteInvestorMemoryStore(
            settings.investor_memory_database,
            read_only=True,
        )
        profile = store.profile(investor_identifier)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"investor memory is unavailable: {error}",
        ) from error
    return investor_memory_profile_to_dict(profile)


@router.get(
    "/investor-memory/{investor_identifier}/events",
    response_model=InvestorMemoryHistoryResponse,
)
def investor_memory_events(
    investor_identifier: str,
    limit: int = Query(default=50, ge=1, le=200),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.investor_memory_database.exists():
        return {"items": [], "total": 0}
    try:
        store = SQLiteInvestorMemoryStore(
            settings.investor_memory_database,
            read_only=True,
        )
        events = store.events(investor_identifier, limit=limit)
        total = store.count(investor_identifier)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"investor memory is unavailable: {error}",
        ) from error
    return {
        "items": [investor_memory_event_to_dict(event) for event in events],
        "total": total,
    }


__all__ = ["router"]
