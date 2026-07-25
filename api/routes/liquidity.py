"""Read-only Global Liquidity intelligence routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.config import ApiSettings
from api.dependencies import get_settings
from intelligence.engine_store import SQLiteAnalyticalEngineStore


router = APIRouter(prefix="/v1/liquidity", tags=["global liquidity"])


def _store(settings: ApiSettings) -> SQLiteAnalyticalEngineStore | None:
    path = settings.snapshot_database.with_name("analytical_engines.db")
    if not path.exists():
        return None
    return SQLiteAnalyticalEngineStore(path, read_only=True)


@router.get("/latest", response_model=dict[str, Any])
def latest(
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, Any]:
    store = _store(settings)
    result = None if store is None else store.latest("global_liquidity")
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="global liquidity intelligence is not available",
        )
    return result.to_dict()


@router.get("/history", response_model=dict[str, Any])
def history(
    limit: int = Query(default=30, ge=1, le=100),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, Any]:
    store = _store(settings)
    items = () if store is None else store.history(
        "global_liquidity",
        limit=limit,
    )
    return {
        "items": [item.to_dict() for item in items],
        "limit": limit,
        "total": len(items),
    }
