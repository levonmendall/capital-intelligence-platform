"""Append point-in-time evaluation artifacts to the canonical CIO journal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cio.persistence import (
    CIOJournalEvent,
    CIOJournalEventType,
    SQLiteCIOJournal,
)
from evaluation.point_in_time import (
    ConfidenceCalibrationReport,
    DecisionEvidenceSnapshot,
    PointInTimeDecisionEvaluation,
)
from evaluation.walk_forward import PaperTradeFill, WalkForwardAudit
from portfolio.construction_api import PortfolioConstructionResult


def serialize_construction(
    result: PortfolioConstructionResult,
    *,
    code_version: str,
) -> dict[str, Any]:
    if not isinstance(result, PortfolioConstructionResult):
        raise TypeError("result must be PortfolioConstructionResult")
    return {
        "code_version": code_version,
        "request_identifier": result.request_identifier,
        "as_of": result.as_of.isoformat(),
        "status": result.status.value,
        "policy_version": result.policy_version,
        "target_cash_weight": result.target_cash_weight,
        "target_weights": [
            {"symbol": symbol, "weight": weight}
            for symbol, weight in result.target_weights
        ],
        "trades": [
            {
                "symbol": item.symbol,
                "side": item.side.value,
                "from_weight": item.from_weight,
                "to_weight": item.to_weight,
                "trade_weight": item.trade_weight,
                "estimated_cost_return": item.estimated_cost_return,
                "reason": item.reason,
                "funding_for": list(item.funding_for),
            }
            for item in result.trades
        ],
        "turnover": result.turnover,
        "estimated_cost_return": result.estimated_cost_return,
        "expected_return_before": result.expected_return_before,
        "expected_return_after_cost": result.expected_return_after_cost,
        "expected_return_improvement": result.expected_return_improvement,
        "constraints": [
            {
                "name": item.name,
                "satisfied": item.satisfied,
                "value": item.value,
                "limit": item.limit,
                "detail": item.detail,
            }
            for item in result.constraints
        ],
        "blocks": list(result.blocks),
        "eligible_universe_publication_identifier": (
            result.eligible_universe_publication_identifier
        ),
        "instrument_identifiers": [
            {
                "symbol": symbol,
                "instrument_identifier": instrument_identifier,
            }
            for symbol, instrument_identifier in result.instrument_identifiers
        ],
    }


def append_construction(
    journal: SQLiteCIOJournal,
    result: PortfolioConstructionResult,
    *,
    code_version: str,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.PORTFOLIO_CONSTRUCTION,
        aggregate_identifier=result.request_identifier,
        occurred_at=result.as_of,
        payload=serialize_construction(result, code_version=code_version),
        schema_version="portfolio-construction-result.v2",
        event_identifier=f"event:{result.request_identifier}",
    )


def append_evidence_snapshot(
    journal: SQLiteCIOJournal,
    snapshot: DecisionEvidenceSnapshot,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.DECISION_EVIDENCE_SNAPSHOT,
        aggregate_identifier=snapshot.decision_identifier,
        occurred_at=snapshot.captured_at,
        payload=snapshot.to_dict(),
        schema_version=snapshot.schema_version,
        event_identifier=f"event:{snapshot.identifier}",
    )


def append_decision_evaluation(
    journal: SQLiteCIOJournal,
    evaluation: PointInTimeDecisionEvaluation,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.DECISION_EVALUATION,
        aggregate_identifier=evaluation.snapshot_identifier,
        occurred_at=evaluation.evaluated_at,
        payload=evaluation.to_dict(),
        schema_version=evaluation.schema_version,
        event_identifier=f"event:{evaluation.identifier}",
    )


def append_calibration_report(
    journal: SQLiteCIOJournal,
    report: ConfidenceCalibrationReport,
) -> CIOJournalEvent:
    payload = {
        "as_of": report.as_of.isoformat(),
        "count": report.count,
        "mean_brier_score": report.mean_brier_score,
        "calibration_error": report.calibration_error,
        "policy_version": report.policy_version,
        "buckets": [
            {
                "lower_bound": item.lower_bound,
                "upper_bound": item.upper_bound,
                "count": item.count,
                "mean_confidence": item.mean_confidence,
                "observed_success_rate": item.observed_success_rate,
                "mean_brier_score": item.mean_brier_score,
            }
            for item in report.buckets
        ],
    }
    return journal.append(
        event_type=CIOJournalEventType.CONFIDENCE_CALIBRATION,
        aggregate_identifier="confidence-calibration",
        occurred_at=report.as_of,
        payload=payload,
        schema_version="confidence-calibration.v1",
        event_identifier=f"event:confidence-calibration:{report.as_of.isoformat()}",
    )


def append_walk_forward_audit(
    journal: SQLiteCIOJournal,
    audit: WalkForwardAudit,
    *,
    occurred_at: datetime,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.WALK_FORWARD_AUDIT,
        aggregate_identifier=audit.fold_identifier,
        occurred_at=occurred_at,
        payload={
            "fold_identifier": audit.fold_identifier,
            "verdict": audit.verdict.value,
            "violations": list(audit.violations),
            "training_record_count": audit.training_record_count,
            "evaluated_symbol_count": audit.evaluated_symbol_count,
        },
        schema_version="walk-forward-audit.v1",
        event_identifier=f"event:walk-forward:{audit.fold_identifier}",
    )


def append_paper_trade_fill(
    journal: SQLiteCIOJournal,
    fill: PaperTradeFill,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.PAPER_TRADE_FILL,
        aggregate_identifier=fill.decision_identifier,
        occurred_at=fill.filled_at,
        payload={
            "identifier": fill.identifier,
            "decision_identifier": fill.decision_identifier,
            "construction_request_identifier": (
                fill.construction_request_identifier
            ),
            "symbol": fill.symbol,
            "side": fill.side.value,
            "proposed_at": fill.proposed_at.isoformat(),
            "filled_at": fill.filled_at.isoformat(),
            "proposed_weight": fill.proposed_weight,
            "filled_weight": fill.filled_weight,
            "completion_ratio": fill.completion_ratio,
            "reference_price": fill.reference_price,
            "fill_price": fill.fill_price,
            "slippage_return": fill.slippage_return,
            "estimated_cost_return": fill.estimated_cost_return,
            "realized_cost_return": fill.realized_cost_return,
            "source_identifier": fill.source_identifier,
        },
        schema_version="paper-trade-fill.v1",
        event_identifier=f"event:{fill.identifier}",
    )


__all__ = [
    "append_calibration_report",
    "append_construction",
    "append_decision_evaluation",
    "append_evidence_snapshot",
    "append_paper_trade_fill",
    "append_walk_forward_audit",
    "serialize_construction",
]
