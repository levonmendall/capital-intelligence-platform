"""Read-only analytical and all-markets data governance routes."""

from typing import Any
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.config import ApiSettings
from api.dependencies import get_settings
from governance import (
    AllMarketsDataReadinessEvaluator,
    DataReadinessError,
    load_data_readiness_manifest,
)
from intelligence.governance_store import SQLiteGovernanceStore


router = APIRouter(prefix="/v1/governance", tags=["governance"])


def _store(settings: ApiSettings) -> SQLiteGovernanceStore | None:
    path = settings.snapshot_database.with_name("analytical_engines.db")
    if not path.exists():
        return None
    return SQLiteGovernanceStore(path, read_only=True)


@router.get("/latest", response_model=dict[str, Any])
def latest(settings: ApiSettings = Depends(get_settings)) -> dict[str, Any]:
    store = _store(settings)
    result = None if store is None else store.latest()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="multi-engine governance is not available",
        )
    return result.to_dict()


@router.get("/history", response_model=dict[str, Any])
def history(
    limit: int = Query(default=30, ge=1, le=100),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, Any]:
    store = _store(settings)
    items = () if store is None else store.history(limit=limit)
    return {
        "items": [item.to_dict() for item in items],
        "limit": limit,
        "total": len(items),
    }


@router.get("/policies/latest", response_model=dict[str, Any])
def latest_policy(settings: ApiSettings = Depends(get_settings)) -> dict[str, Any]:
    store = _store(settings)
    policy = None if store is None else store.latest_policy()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="multi-engine governance policy is not available",
        )
    return policy.to_dict()


@router.get("/policies/history", response_model=dict[str, Any])
def policy_history(
    limit: int = Query(default=30, ge=1, le=100),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, Any]:
    store = _store(settings)
    items = () if store is None else store.policy_history(limit=limit)
    return {
        "items": [item.to_dict() for item in items],
        "limit": limit,
        "total": len(items),
    }

@router.get("/data-readiness", response_model=dict[str, Any])
def data_readiness() -> dict[str, Any]:
    """Return credential-redacted readiness for the complete market scope."""

    manifest_path = os.getenv(
        "CAPITAL_INTELLIGENCE_DATA_READINESS_MANIFEST",
        "config/all_markets_data_readiness.json",
    )
    try:
        manifest = load_data_readiness_manifest(manifest_path)
        report = AllMarketsDataReadinessEvaluator().evaluate(manifest)
    except (DataReadinessError, KeyError, OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"all-markets data readiness is unavailable: {error}",
        ) from error
    return report.to_dict()

