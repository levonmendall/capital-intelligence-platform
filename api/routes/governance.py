"""Read-only analytical, market-data, and decision-information governance routes."""

from typing import Any
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.config import ApiSettings
from api.dependencies import get_settings
from governance import (
    AllMarketsDataReadinessEvaluator,
    AllMarketsDataReadinessState,
    DataReadinessError,
    DecisionInformationReadinessError,
    DecisionInformationReadinessState,
    MaximumDecisionInformationReadinessEvaluator,
    load_data_readiness_manifest,
    load_maximum_decision_information_manifest,
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


def _information_report():
    path = os.getenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_MANIFEST",
        "config/maximum_decision_information_scope.json",
    )
    manifest = load_maximum_decision_information_manifest(path)
    return MaximumDecisionInformationReadinessEvaluator().evaluate(manifest)


@router.get("/decision-information-readiness", response_model=dict[str, Any])
def decision_information_readiness() -> dict[str, Any]:
    """Return credential-redacted readiness for news and maximum information scope."""

    try:
        return _information_report().to_dict()
    except (
        DecisionInformationReadinessError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"maximum decision-information readiness is unavailable: {error}",
        ) from error


@router.get("/data-readiness", response_model=dict[str, Any])
def data_readiness() -> dict[str, Any]:
    """Return combined market and maximum-information readiness without secrets."""

    market_path = os.getenv(
        "CAPITAL_INTELLIGENCE_DATA_READINESS_MANIFEST",
        "config/all_markets_data_readiness.json",
    )
    try:
        market_manifest = load_data_readiness_manifest(market_path)
        market = AllMarketsDataReadinessEvaluator().evaluate(market_manifest)
        information = _information_report()
    except (
        DataReadinessError,
        DecisionInformationReadinessError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"combined data readiness is unavailable: {error}",
        ) from error

    payload = market.to_dict()
    combined_ready = market.global_test_data_ready and information.all_domains_ready
    if combined_ready:
        state = "ready"
    elif (
        market.state is AllMarketsDataReadinessState.PARTIAL
        or information.state is DecisionInformationReadinessState.PARTIAL
        or market.state is AllMarketsDataReadinessState.READY
        or information.state is DecisionInformationReadinessState.READY
    ):
        state = "partial"
    else:
        state = "blocked"
    payload.update(
        {
            "schema_version": "combined-market-and-decision-information-readiness-report.v1",
            "state": state,
            "market_data_ready": market.global_test_data_ready,
            "maximum_decision_information_ready": information.all_domains_ready,
            "current_events_and_news_ready": information.current_events_and_news_ready,
            "global_test_data_ready": combined_ready,
            "missing_environment_variables": sorted(
                set(market.missing_environment_variables)
                | set(information.missing_environment_variables)
            ),
            "blockers": [
                *(f"market-data: {item}" for item in market.blockers),
                *(f"decision-information: {item}" for item in information.blockers),
            ],
            "decision_information": information.to_dict(),
            "real_money_authorized": False,
        }
    )
    return payload
