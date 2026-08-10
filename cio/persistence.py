"""Append-only, hash-chained persistence for canonical CIO decisions.

The ledger may share the institutional journal SQLite file while retaining an
independent table and hash chain.  It never mutates the older regime or
portfolio-fit event tables and therefore can be deployed without rewriting
historical records.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from cio.committee import IndependentSpecialistPacket
from cio.models import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    PriorDecisionContext,
    ThesisState,
)
from opportunity import OpportunityQueue
from thesis import LivingThesis, ThesisReview


class CIOJournalEventType(str, Enum):
    """Versioned canonical CIO event types."""

    CANDIDATE_DECISION = "candidate_decision"
    OPPORTUNITY_QUEUE = "opportunity_queue"
    OPPORTUNITY_DECISION_SNAPSHOT = "opportunity_decision_snapshot"
    SPECIALIST_PACKET = "specialist_packet"
    CIO_DECISION = "cio_decision"
    THESIS_SNAPSHOT = "thesis_snapshot"
    THESIS_REVIEW = "thesis_review"
    PORTFOLIO_CONSTRUCTION = "portfolio_construction"
    CONSTRUCTION_RECONCILIATION = "construction_reconciliation"
    CANDIDATE_RISK_ASSESSMENT = "candidate_risk_assessment"
    JOINT_CANDIDATE_ASSESSMENT = "joint_candidate_assessment"
    DECISION_EVIDENCE_SNAPSHOT = "decision_evidence_snapshot"
    DECISION_EVALUATION = "decision_evaluation"
    CONFIDENCE_CALIBRATION = "confidence_calibration"
    WALK_FORWARD_AUDIT = "walk_forward_audit"
    PAPER_TRADE_FILL = "paper_trade_fill"
    DAILY_CIO_BRIEFING = "daily_cio_briefing"
    PERSISTENT_CASH_DIAGNOSTIC = "persistent_cash_diagnostic"
    GLOBAL_ROTATION_CONTEXT = "global_rotation_context"
    COMMITTEE_CIO_INFORMATION_TRACE = "committee_cio_information_trace"


class CIOJournalIntegrityError(RuntimeError):
    """Raised when the CIO ledger hash chain cannot be verified."""


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isinstance(normalized, float):
        raise TypeError(f"{field_name} must be numeric")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _finite(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _canonical_json(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("payload must be a mapping")
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "payload must contain finite JSON-serializable values"
        ) from error


def _code_version(value: str | None) -> str:
    return _required_text(
        value
        or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
        or os.getenv("GITHUB_SHA")
        or "unknown",
        field_name="code_version",
    )


@dataclass(frozen=True, slots=True)
class CIOJournalEvent:
    """One immutable canonical CIO event."""

    sequence: int
    event_identifier: str
    aggregate_identifier: str
    event_type: CIOJournalEventType
    occurred_at: datetime
    recorded_at: datetime
    schema_version: str
    payload_json: str
    previous_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        for field_name in (
            "event_identifier",
            "aggregate_identifier",
            "schema_version",
            "previous_hash",
            "content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.event_type, CIOJournalEventType):
            raise TypeError("event_type must be a CIOJournalEventType")
        _aware(self.occurred_at, field_name="occurred_at")
        _aware(self.recorded_at, field_name="recorded_at")
        try:
            decoded = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("payload_json must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("payload_json must encode an object")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


def serialize_candidate_decision(
    candidate: CandidateDecisionRecord,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, CandidateDecisionRecord):
        raise TypeError("candidate must be a CandidateDecisionRecord")
    instrument = candidate.instrument
    quality = candidate.evidence_quality
    return {
        "code_version": _code_version(code_version),
        "identifier": candidate.identifier,
        "schema_version": candidate.schema_version,
        "as_of": candidate.as_of.isoformat(),
        "instrument": {
            "instrument_id": instrument.instrument_id,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "asset_class": instrument.asset_class.value,
            "venue": instrument.venue,
            "country_code": instrument.country_code,
            "average_daily_dollar_volume": instrument.average_daily_dollar_volume,
            "data_age_hours": instrument.data_age_hours,
            "analytical_coverage": instrument.analytical_coverage,
            "security_master_snapshot_identifier": instrument.security_master_snapshot_identifier,
            "security_master_record_identifiers": list(
                instrument.security_master_record_identifiers
            ),
            "is_us_treasury": instrument.is_us_treasury,
            "effective_duration_years": instrument.effective_duration_years,
            "instrument_type": instrument.instrument_type,
            "economic_exposure_class": (
                None
                if instrument.economic_exposure_class is None
                else instrument.economic_exposure_class.value
            ),
            "leverage_multiplier": instrument.leverage_multiplier,
            "uses_derivatives": instrument.uses_derivatives,
            "replication_method": instrument.replication_method,
        },
        "current_price": candidate.current_price,
        "decision_horizon_days": candidate.decision_horizon_days,
        "base_case_return": candidate.base_case_return,
        "bull_case_return": candidate.bull_case_return,
        "bear_case_return": candidate.bear_case_return,
        "base_case_probability": candidate.base_case_probability,
        "bull_case_probability": candidate.bull_case_probability,
        "bear_case_probability": candidate.bear_case_probability,
        "payoff_distribution": [
            {
                "label": item.label,
                "total_return": item.total_return,
                "probability": item.probability,
            }
            for item in candidate.payoff_distribution
        ],
        "estimated_fair_value": candidate.estimated_fair_value,
        "expected_upside": candidate.expected_upside,
        "expected_downside": candidate.expected_downside,
        "probability_of_success": candidate.probability_of_success,
        "primary_catalysts": list(candidate.primary_catalysts),
        "key_risks": list(candidate.key_risks),
        "critical_assumptions": list(candidate.critical_assumptions),
        "invalidation_conditions": list(candidate.invalidation_conditions),
        "supporting_evidence": list(candidate.supporting_evidence),
        "contradictory_evidence": list(candidate.contradictory_evidence),
        "evidence_quality": {
            "reliability": quality.reliability,
            "freshness": quality.freshness,
            "relevance": quality.relevance,
            "independence": quality.independence,
            "completeness": quality.completeness,
            "point_in_time_integrity": quality.point_in_time_integrity,
            "score": quality.score,
            "ceiling": quality.ceiling,
        },
        "liquidity_score": candidate.liquidity_score,
        "transaction_cost_bps": candidate.transaction_cost_bps,
        "slippage_bps": candidate.slippage_bps,
        "opportunity_cost_return": candidate.opportunity_cost_return,
        "expected_portfolio_contribution": candidate.expected_portfolio_contribution,
        "current_portfolio_weight": candidate.current_portfolio_weight,
        "maximum_position_weight": candidate.maximum_position_weight,
        "monitoring_indicators": list(candidate.monitoring_indicators),
        "review_at": candidate.review_at.isoformat(),
        "evidence_identifiers": list(candidate.evidence_identifiers),
        "model_versions": list(candidate.model_versions),
        "evidence_dependencies": [
            {
                "identifier": item.identifier,
                "parent_identifiers": list(item.parent_identifiers),
            }
            for item in candidate.evidence_dependencies
        ],
    }


# The remainder of this module is unchanged from the canonical persistence
# implementation and follows below.
