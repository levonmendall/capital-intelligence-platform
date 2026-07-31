"""Read-only analytical, market-data, and decision-information governance routes."""

from pathlib import Path
from typing import Any
import json
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
from governance.coverage_certification import (
    certify_historical_cutoff,
    load_historical_boundaries,
    load_market_coverage,
)
from datetime import datetime, timezone


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


def _public_live_report() -> dict[str, Any] | None:
    path = Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT",
            "database/public-live-information-report.json",
        )
    ).expanduser()
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("public live information report must be a JSON object")
    payload.pop("records", None)
    payload["secret_values_disclosed"] = False
    payload["full_article_text_stored"] = False
    payload["real_money_authorized"] = False
    return payload


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


@router.get("/public-live-information", response_model=dict[str, Any])
def public_live_information() -> dict[str, Any]:
    """Return the latest persisted public live-source coverage report."""

    try:
        payload = _public_live_report()
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"public live information report is unavailable: {error}",
        ) from error
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="public live information has not been collected yet",
        )
    return payload


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
        public_live = _public_live_report()
    except (
        DataReadinessError,
        DecisionInformationReadinessError,
        json.JSONDecodeError,
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
            "public_live_information_available": public_live is not None,
            "public_live_successful_source_count": (
                0 if public_live is None else int(public_live.get("successful_source_count", 0))
            ),
            "public_live_record_count": (
                0 if public_live is None else int(public_live.get("live_record_count", 0))
            ),
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
            "public_live_information": public_live,
            "real_money_authorized": False,
        }
    )
    return payload


@router.get("/market-coverage", response_model=dict[str, Any])
def market_coverage() -> dict[str, Any]:
    """Return monitored, decision-certified, and allocatable scopes separately."""

    path = os.getenv(
        "CAPITAL_INTELLIGENCE_MARKET_COVERAGE_REGISTRY",
        "config/market_coverage_registry.v1.json",
    )
    try:
        return load_market_coverage(path).to_dict()
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"market coverage registry is unavailable: {error}",
        ) from error


@router.get("/historical-certification", response_model=dict[str, Any])
def historical_certification() -> dict[str, Any]:
    """Return the fail-closed point-in-time certification baseline."""

    path = os.getenv(
        "CAPITAL_INTELLIGENCE_HISTORICAL_CERTIFICATION_BOUNDARIES",
        "config/historical_certification_boundaries.v1.json",
    )
    try:
        boundaries = load_historical_boundaries(path)
        return certify_historical_cutoff(
            cutoff=datetime.now(timezone.utc),
            boundaries=boundaries,
            evidence=(),
        ).to_dict()
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"historical certification is unavailable: {error}",
        ) from error
