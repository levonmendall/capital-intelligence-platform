"""Read-only canonical CIO briefing, thesis, evaluation, and report routes."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.config import ApiSettings
from api.dependencies import get_resources, get_settings
from api.repositories import ApiResources
from api.schemas import CIOBriefingHistoryResponse, CIOBriefingResponse
from cio_pending_transactions import build_pending_transaction_report


router = APIRouter(prefix="/v1/cio", tags=["canonical CIO"])

_BRIEFING = "daily_cio_briefing"
_DECISION = "cio_decision"
_THESIS = "thesis_snapshot"
_EVALUATION = "decision_evaluation"
_EVIDENCE = "decision_evidence_snapshot"
_CONSTRUCTION = "portfolio_construction"


@router.get(
    "/latest",
    response_model=CIOBriefingResponse,
)
def latest(resources: ApiResources = Depends(get_resources)) -> CIOBriefingResponse:
    payload = resources.journal.latest_payload(_BRIEFING)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no canonical CIO briefing is available",
        )
    return CIOBriefingResponse.model_validate(payload)


@router.get(
    "/history",
    response_model=CIOBriefingHistoryResponse,
)
def history(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    settings: ApiSettings = Depends(get_settings),
    resources: ApiResources = Depends(get_resources),
) -> CIOBriefingHistoryResponse:
    resolved_limit = settings.history_default_limit if limit is None else limit
    if resolved_limit > settings.history_max_limit:
        raise HTTPException(
            status_code=422,
            detail=(
                "limit exceeds CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT "
                f"({settings.history_max_limit})"
            ),
        )
    return CIOBriefingHistoryResponse(
        items=[
            CIOBriefingResponse.model_validate(item)
            for item in resources.journal.history(
                _BRIEFING,
                limit=resolved_limit,
                offset=offset,
            )
        ],
        limit=resolved_limit,
        offset=offset,
        total=resources.journal.count(_BRIEFING),
    )


@router.get("/pending-transactions/latest", response_model=dict[str, Any])
def pending_transactions_latest(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    return build_pending_transaction_report(
        construction=resources.journal.latest_payload(_CONSTRUCTION),
        briefing=resources.journal.latest_payload(_BRIEFING),
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/evaluations/latest", response_model=dict[str, Any])
def latest_evaluation(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.journal.latest_payload(_EVALUATION)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no point-in-time decision evaluation is available",
        )
    return payload


@router.get("/decisions/latest", response_model=dict[str, Any])
def latest_decision(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.journal.latest_payload(_DECISION)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no canonical CIO decision is available",
        )
    return payload


@router.get("/construction/latest", response_model=dict[str, Any])
def latest_construction(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.journal.latest_payload(_CONSTRUCTION)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no portfolio construction result is available",
        )
    return payload


@router.get("/evidence/latest", response_model=dict[str, Any])
def latest_evidence_snapshot(
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.journal.latest_payload(_EVIDENCE)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no point-in-time decision evidence snapshot is available",
        )
    return payload


@router.get("/theses", response_model=dict[str, Any])
def theses(
    limit: int = Query(default=100, ge=1, le=500),
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    items = resources.journal.latest_per_aggregate(_THESIS, limit=limit)
    return {"items": list(items), "total": len(items)}


@router.get("/process", response_model=dict[str, Any])
def process() -> dict[str, Any]:
    return {
        "schema_version": "canonical-cio-process.v1",
        "governing_rule": (
            "Every recommendation is compared against all other available uses "
            "of capital, implemented at the portfolio level, continuously "
            "monitored against an explicit thesis, and evaluated afterward "
            "using the exact evidence available when the decision was made."
        ),
        "authority": {
            "opportunity_engine": "qualifies and ranks all available uses of capital",
            "specialists": "perform independent analyses and preserve dissent",
            "cio": "issues the only user-facing investment decision",
            "portfolio_construction": "determines feasible sizing and funding",
            "thesis_monitoring": "challenges active ownership against explicit falsification conditions",
            "evaluation": "scores process and outcomes from frozen point-in-time evidence",
        },
        "legacy_surfaces": {
            "daily_score": "deprecated diagnostic only",
            "weighted_consensus": "not an investment authority",
            "investor_memory": "isolated historical migration data",
        },
    }


__all__ = ["router"]
