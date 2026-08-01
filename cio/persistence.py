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
    SPECIALIST_PACKET = "specialist_packet"
    CIO_DECISION = "cio_decision"
    THESIS_SNAPSHOT = "thesis_snapshot"
    THESIS_REVIEW = "thesis_review"
    PORTFOLIO_CONSTRUCTION = "portfolio_construction"
    DECISION_EVIDENCE_SNAPSHOT = "decision_evidence_snapshot"
    DECISION_EVALUATION = "decision_evaluation"
    CONFIDENCE_CALIBRATION = "confidence_calibration"
    WALK_FORWARD_AUDIT = "walk_forward_audit"
    PAPER_TRADE_FILL = "paper_trade_fill"
    DAILY_CIO_BRIEFING = "daily_cio_briefing"
    PERSISTENT_CASH_DIAGNOSTIC = "persistent_cash_diagnostic"


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
            "average_daily_dollar_volume": (
                instrument.average_daily_dollar_volume
            ),
            "data_age_hours": instrument.data_age_hours,
            "analytical_coverage": instrument.analytical_coverage,
            "security_master_snapshot_identifier": (
                instrument.security_master_snapshot_identifier
            ),
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
        "scenarios": {
            "base": {
                "return": candidate.base_case_return,
                "probability": candidate.base_case_probability,
            },
            "bull": {
                "return": candidate.bull_case_return,
                "probability": candidate.bull_case_probability,
            },
            "bear": {
                "return": candidate.bear_case_return,
                "probability": candidate.bear_case_probability,
            },
            "probability_weighted_expected_return": (
                candidate.probability_weighted_expected_return
            ),
        },
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
            "confidence_ceiling": quality.ceiling,
        },
        "liquidity_score": candidate.liquidity_score,
        "transaction_cost_bps": candidate.transaction_cost_bps,
        "slippage_bps": candidate.slippage_bps,
        "implementation_cost_return": candidate.implementation_cost_return,
        "net_expected_return": candidate.net_expected_return,
        "opportunity_cost_return": candidate.opportunity_cost_return,
        "opportunity_edge": candidate.opportunity_edge,
        "expected_portfolio_contribution": (
            candidate.expected_portfolio_contribution
        ),
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
        "payoff_distribution": [
            {
                "label": item.label,
                "total_return": item.total_return,
                "probability": item.probability,
            }
            for item in candidate.payoff_distribution
        ],
    }


def serialize_opportunity_queue(
    queue: OpportunityQueue,
    *,
    occurred_at: datetime,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(queue, OpportunityQueue):
        raise TypeError("queue must be an OpportunityQueue")
    _aware(occurred_at, field_name="occurred_at")
    return {
        "code_version": _code_version(code_version),
        "context_identifier": queue.context_identifier,
        "policy_version": queue.policy_version,
        "occurred_at": occurred_at.isoformat(),
        "has_qualified_opportunity": queue.has_qualified_opportunity,
        "ranked": [
            {
                "rank": item.rank,
                "candidate_identifier": item.candidate.identifier,
                "instrument_id": item.candidate.instrument.instrument_id,
                "symbol": item.candidate.instrument.symbol,
                "score": item.score,
                "analysis_lane": item.qualification.analysis_lane.value,
                "effective_opportunity_cost": (
                    item.qualification.effective_opportunity_cost
                ),
                "opportunity_edge": item.qualification.opportunity_edge,
                "best_alternative_identifier": item.qualification.best_alternative_identifier,
                "best_alternative_kind": (
                    None
                    if item.qualification.best_alternative_kind is None
                    else item.qualification.best_alternative_kind.value
                ),
                "baseline_alternative_identifier": item.qualification.baseline_alternative_identifier,
                "baseline_opportunity_cost": item.qualification.baseline_opportunity_cost,
                "resolved_policy_profile": item.qualification.resolved_policy_profile,
                "qualification_reasons": list(item.qualification.reasons),
                "components": [
                    {
                        "name": component.name,
                        "raw_value": component.raw_value,
                        "normalized_score": component.normalized_score,
                        "weight": component.weight,
                        "contribution": component.contribution,
                    }
                    for component in item.components
                ],
            }
            for item in queue.ranked
        ],
        "rejected": [
            {
                "candidate_identifier": item.candidate_identifier,
                "outcome": item.outcome.value,
                "analysis_lane": item.analysis_lane.value,
                "universe_disposition": item.universe.disposition.value,
                "universe_policy_version": item.universe.policy_version,
                "effective_opportunity_cost": item.effective_opportunity_cost,
                "opportunity_edge": item.opportunity_edge,
                "best_alternative_identifier": item.best_alternative_identifier,
                "best_alternative_kind": (
                    None if item.best_alternative_kind is None else item.best_alternative_kind.value
                ),
                "baseline_alternative_identifier": item.baseline_alternative_identifier,
                "baseline_opportunity_cost": item.baseline_opportunity_cost,
                "resolved_policy_profile": item.resolved_policy_profile,
                "reasons": list(item.reasons),
            }
            for item in queue.rejected
        ],
    }


def serialize_specialist_packet(
    packet: IndependentSpecialistPacket,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(packet, IndependentSpecialistPacket):
        raise TypeError("packet must be an IndependentSpecialistPacket")
    dissent = packet.strongest_dissent()
    return {
        "code_version": _code_version(code_version),
        "candidate_identifier": packet.candidate_identifier,
        "historical_learning": packet.historical_learning.as_dict(),
        "support_ratio": packet.support_ratio,
        "directional_support_ratio": packet.directional_support_ratio,
        "coverage_ratio": packet.coverage_ratio,
        "evidence_confidence": packet.evidence_confidence,
        "implementation_confidence": packet.implementation_confidence,
        "abstaining_roles": [item.role.value for item in packet.abstentions],
        "median_confidence": packet.median_confidence,
        "evidence_vetoes": list(packet.evidence_vetoes),
        "evidence_veto_categories": [
            item.value for item in packet.evidence_veto_categories
        ],
        "implementation_blocks": list(packet.implementation_blocks),
        "strongest_dissent": (
            None
            if dissent is None
            else {
                "opposing_role": dissent.opposing_role.value,
                "opposing_conclusion": dissent.opposing_conclusion,
                "disagreement_reason": dissent.disagreement_reason,
                "resolving_evidence": list(dissent.resolving_evidence),
            }
        ),
        "analyses": [
            {
                "role": item.role.value,
                "completed_at": item.completed_at.isoformat(),
                "independent_first_pass": item.independent_first_pass,
                "position": item.position.value,
                "conclusion": item.conclusion,
                "expected_return_impact": item.expected_return_impact,
                "confidence": item.confidence,
                "supporting_evidence": list(item.supporting_evidence),
                "contradictory_evidence": list(item.contradictory_evidence),
                "critical_assumptions": list(item.critical_assumptions),
                "risks": list(item.risks),
                "limitations": list(item.limitations),
                "change_conditions": list(item.change_conditions),
                "veto_reasons": list(item.veto_reasons),
                "veto_categories": [
                    category.value for category in item.veto_categories
                ],
                "implementation_blocks": list(item.implementation_blocks),
                "recommended_position_weight": (
                    item.recommended_position_weight
                ),
                "funding_source": item.funding_source,
                "evidence_origin_identifiers": list(
                    item.evidence_origin_identifiers
                ),
                "scenario_adjustments": [
                    {
                        "label": adjustment.label,
                        "return_delta": adjustment.return_delta,
                        "probability_delta": adjustment.probability_delta,
                        "path_drawdown_delta": adjustment.path_drawdown_delta,
                    }
                    for adjustment in item.scenario_adjustments
                ],
                "evidence_dependencies": [
                    {
                        "identifier": dependency.identifier,
                        "parent_identifiers": list(dependency.parent_identifiers),
                    }
                    for dependency in item.evidence_dependencies
                ],
            }
            for item in packet.analyses
        ],
    }


def serialize_cio_decision(
    decision: CIODecision,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(decision, CIODecision):
        raise TypeError("decision must be a CIODecision")
    return {
        "code_version": _code_version(code_version),
        "identifier": decision.identifier,
        "candidate_identifier": decision.candidate_identifier,
        "as_of": decision.as_of.isoformat(),
        "schema_version": decision.schema_version,
        "action": decision.action.value,
        "final_confidence": decision.final_confidence,
        "expected_return": decision.expected_return,
        "decision_horizon_days": decision.decision_horizon_days,
        "recommended_position_weight": decision.recommended_position_weight,
        "funding_source": decision.funding_source,
        "thesis": decision.thesis,
        "rationale": decision.rationale,
        "supporting_evidence": list(decision.supporting_evidence),
        "contradictory_evidence": list(decision.contradictory_evidence),
        "key_assumptions": list(decision.key_assumptions),
        "catalysts": list(decision.catalysts),
        "risks": list(decision.risks),
        "invalidation_conditions": list(decision.invalidation_conditions),
        "portfolio_impact": decision.portfolio_impact,
        "opportunity_cost": decision.opportunity_cost,
        "dissent": (
            None
            if decision.dissent is None
            else {
                "opposing_role": decision.dissent.opposing_role.value,
                "opposing_conclusion": (
                    decision.dissent.opposing_conclusion
                ),
                "disagreement_reason": (
                    decision.dissent.disagreement_reason
                ),
                "resolving_evidence": list(
                    decision.dissent.resolving_evidence
                ),
            }
        ),
        "evidence_vetoes": list(decision.evidence_vetoes),
        "implementation_blocks": list(decision.implementation_blocks),
        "monitoring_indicators": list(decision.monitoring_indicators),
        "review_at": decision.review_at.isoformat(),
        "explanation": decision.explanation,
        "policy_version": decision.policy_version,
        "best_alternative_identifier": decision.best_alternative_identifier,
        "effective_opportunity_cost": decision.effective_opportunity_cost,
        "prior_decision_identifier": decision.prior_decision_identifier,
        "persistence_cycles": decision.persistence_cycles,
        "hysteresis_applied": decision.hysteresis_applied,
        "resolved_policy_profile": decision.resolved_policy_profile,
        "policy_matrix_version": decision.policy_matrix_version,
        "return_reconciliation": (
            None
            if decision.return_reconciliation is None
            else {
                "policy_version": decision.return_reconciliation.policy_version,
                "original_expected_return": (
                    decision.return_reconciliation.original_expected_return
                ),
                "original_probability_of_success": (
                    decision.return_reconciliation.original_probability_of_success
                ),
                "alternative_return": decision.return_reconciliation.alternative_return,
                "horizon_alternative_return": (
                    decision.return_reconciliation.horizon_alternative_return
                ),
                "implementation_cost_return": (
                    decision.return_reconciliation.implementation_cost_return
                ),
                "expected_return": decision.return_reconciliation.expected_return,
                "expected_downside": decision.return_reconciliation.expected_downside,
                "probability_of_success": (
                    decision.return_reconciliation.probability_of_success
                ),
                "evidence_origin_count": (
                    decision.return_reconciliation.evidence_origin_count
                ),
                "bounds_correction_applied": (
                    decision.return_reconciliation.bounds_correction_applied
                ),
                "probability_normalization_applied": (
                    decision.return_reconciliation.probability_normalization_applied
                ),
                "path_drawdown_by_scenario": [
                    {"label": label, "drawdown": drawdown}
                    for label, drawdown in decision.return_reconciliation.path_drawdown_by_scenario
                ],
                "outcomes": [
                    {
                        "label": item.label,
                        "total_return": item.total_return,
                        "probability": item.probability,
                    }
                    for item in decision.return_reconciliation.outcomes
                ],
                "adjustments": [
                    {
                        "role": item.role.value,
                        "raw_impact": item.raw_impact,
                        "confidence": item.confidence,
                        "overlap_discount": item.overlap_discount,
                        "applied_impact": item.applied_impact,
                        "evidence_origin_identifiers": list(
                            item.evidence_origin_identifiers
                        ),
                        "scenario_adjustments": [
                            {
                                "label": adjustment.label,
                                "return_delta": adjustment.return_delta,
                                "probability_delta": adjustment.probability_delta,
                                "path_drawdown_delta": adjustment.path_drawdown_delta,
                            }
                            for adjustment in item.scenario_adjustments
                        ],
                    }
                    for item in decision.return_reconciliation.adjustments
                ],
            }
        ),
    }


def serialize_thesis_snapshot(
    thesis: LivingThesis,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(thesis, LivingThesis):
        raise TypeError("thesis must be a LivingThesis")
    return {
        "code_version": _code_version(code_version),
        "identifier": thesis.identifier,
        "decision_identifier": thesis.decision_identifier,
        "candidate_identifier": thesis.candidate_identifier,
        "asset": thesis.asset,
        "created_at": thesis.created_at.isoformat(),
        "updated_at": thesis.updated_at.isoformat(),
        "state": thesis.state.value,
        "original_rationale": thesis.original_rationale,
        "assumptions": list(thesis.assumptions),
        "expected_return": thesis.expected_return,
        "expected_downside": thesis.expected_downside,
        "horizon_days": thesis.horizon_days,
        "catalysts": list(thesis.catalysts),
        "invalidation_conditions": list(thesis.invalidation_conditions),
        "monitoring_indicators": list(thesis.monitoring_indicators),
        "initial_confidence": thesis.initial_confidence,
        "current_confidence": thesis.current_confidence,
        "evidence_identifiers": list(thesis.evidence_identifiers),
        "performance_since_approval": thesis.performance_since_approval,
        "next_review_at": thesis.next_review_at.isoformat(),
        "review_count": thesis.review_count,
        "ownership_episode_identifier": thesis.ownership_episode_identifier,
    }


def serialize_thesis_review(
    review: ThesisReview,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(review, ThesisReview):
        raise TypeError("review must be a ThesisReview")
    return {
        "code_version": _code_version(code_version),
        "identifier": review.identifier,
        "thesis_identifier": review.thesis_identifier,
        "reviewed_at": review.reviewed_at.isoformat(),
        "prior_state": review.prior_state.value,
        "new_state": review.new_state.value,
        "proposal": review.proposal.value,
        "rationale": review.rationale,
        "evidence_identifiers": list(review.evidence_identifiers),
        "current_expected_return": review.current_expected_return,
        "expected_return_change": review.expected_return_change,
        "current_expected_downside": review.current_expected_downside,
        "downside_change": review.downside_change,
        "current_confidence": review.current_confidence,
        "confidence_change": review.confidence_change,
        "performance_since_approval": review.performance_since_approval,
        "replacement_opportunity_edge": review.replacement_opportunity_edge,
        "triggered_invalidation_conditions": list(
            review.triggered_invalidation_conditions
        ),
        "required_cio_review": review.required_cio_review,
        "next_review_at": review.next_review_at.isoformat(),
        "policy_version": review.policy_version,
    }


class SQLiteCIOJournal:
    """Tamper-evident append-only CIO event chain in SQLite."""

    _GENESIS_HASH = "0" * 64

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("journal path must be a file")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identifier_factory = identifier_factory or (
            lambda: str(uuid.uuid4())
        )
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cio_journal_events (
                    sequence INTEGER PRIMARY KEY,
                    event_identifier TEXT NOT NULL UNIQUE,
                    aggregate_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS cio_journal_aggregate_sequence
                ON cio_journal_events (aggregate_identifier, sequence);

                CREATE INDEX IF NOT EXISTS cio_journal_event_type_sequence
                ON cio_journal_events (event_type, sequence);

                CREATE TRIGGER IF NOT EXISTS cio_journal_prevent_update
                BEFORE UPDATE ON cio_journal_events
                BEGIN
                    SELECT RAISE(ABORT, 'CIO journal is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS cio_journal_prevent_delete
                BEFORE DELETE ON cio_journal_events
                BEGIN
                    SELECT RAISE(ABORT, 'CIO journal is append-only');
                END;
                """
            )

    def append(
        self,
        *,
        event_type: CIOJournalEventType,
        aggregate_identifier: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        schema_version: str,
        event_identifier: str | None = None,
    ) -> CIOJournalEvent:
        if not isinstance(event_type, CIOJournalEventType):
            raise TypeError("event_type must be a CIOJournalEventType")
        aggregate = _required_text(
            aggregate_identifier,
            field_name="aggregate_identifier",
        )
        occurred = _aware(occurred_at, field_name="occurred_at")
        version = _required_text(schema_version, field_name="schema_version")
        identifier = _required_text(
            event_identifier or self._identifier_factory(),
            field_name="event_identifier",
        )
        recorded = _aware(self._clock(), field_name="clock")
        payload_json = _canonical_json(payload)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM cio_journal_events
                WHERE event_identifier = ?
                """,
                (identifier,),
            ).fetchone()
            if existing is not None:
                event = self._event_from_row(existing)
                if (
                    event.aggregate_identifier != aggregate
                    or event.event_type is not event_type
                    or event.occurred_at != occurred
                    or event.schema_version != version
                    or event.payload_json != payload_json
                ):
                    raise ValueError(
                        "event identifier already exists with different content"
                    )
                connection.rollback()
                return event

            previous = connection.execute(
                """
                SELECT sequence, content_hash
                FROM cio_journal_events
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous else 1
            previous_hash = (
                str(previous["content_hash"])
                if previous is not None
                else self._GENESIS_HASH
            )
            content_hash = self._content_hash(
                sequence=sequence,
                event_identifier=identifier,
                aggregate_identifier=aggregate,
                event_type=event_type,
                occurred_at=occurred,
                recorded_at=recorded,
                schema_version=version,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                """
                INSERT INTO cio_journal_events (
                    sequence,
                    event_identifier,
                    aggregate_identifier,
                    event_type,
                    occurred_at,
                    recorded_at,
                    schema_version,
                    payload_json,
                    previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    aggregate,
                    event_type.value,
                    occurred.isoformat(),
                    recorded.isoformat(),
                    version,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return CIOJournalEvent(
            sequence=sequence,
            event_identifier=identifier,
            aggregate_identifier=aggregate,
            event_type=event_type,
            occurred_at=occurred,
            recorded_at=recorded,
            schema_version=version,
            payload_json=payload_json,
            previous_hash=previous_hash,
            content_hash=content_hash,
        )

    def append_candidate(
        self,
        candidate: CandidateDecisionRecord,
        *,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        return self.append(
            event_type=CIOJournalEventType.CANDIDATE_DECISION,
            aggregate_identifier=candidate.identifier,
            occurred_at=candidate.as_of,
            payload=serialize_candidate_decision(
                candidate,
                code_version=code_version,
            ),
            schema_version=candidate.schema_version,
            event_identifier=f"event:{candidate.identifier}",
        )

    def append_opportunity_queue(
        self,
        queue: OpportunityQueue,
        *,
        occurred_at: datetime,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        occurred = _aware(occurred_at, field_name="occurred_at")
        return self.append(
            event_type=CIOJournalEventType.OPPORTUNITY_QUEUE,
            aggregate_identifier=queue.context_identifier,
            occurred_at=occurred,
            payload=serialize_opportunity_queue(
                queue,
                occurred_at=occurred,
                code_version=code_version,
            ),
            schema_version="opportunity-queue.v1",
            event_identifier=(
                f"event:{queue.context_identifier}:{occurred.isoformat()}"
            ),
        )

    def append_specialist_packet(
        self,
        packet: IndependentSpecialistPacket,
        *,
        occurred_at: datetime,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        occurred = _aware(occurred_at, field_name="occurred_at")
        return self.append(
            event_type=CIOJournalEventType.SPECIALIST_PACKET,
            aggregate_identifier=packet.candidate_identifier,
            occurred_at=occurred,
            payload=serialize_specialist_packet(
                packet,
                code_version=code_version,
            ),
            schema_version="specialist-packet.v2",
            event_identifier=(
                f"event:specialists:{packet.candidate_identifier}:"
                f"{occurred.isoformat()}"
            ),
        )

    def append_decision(
        self,
        decision: CIODecision,
        *,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        return self.append(
            event_type=CIOJournalEventType.CIO_DECISION,
            aggregate_identifier=decision.candidate_identifier,
            occurred_at=decision.as_of,
            payload=serialize_cio_decision(
                decision,
                code_version=code_version,
            ),
            schema_version=decision.schema_version,
            event_identifier=f"event:{decision.identifier}",
        )

    def append_thesis_snapshot(
        self,
        thesis: LivingThesis,
        *,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        return self.append(
            event_type=CIOJournalEventType.THESIS_SNAPSHOT,
            aggregate_identifier=thesis.identifier,
            occurred_at=thesis.updated_at,
            payload=serialize_thesis_snapshot(
                thesis,
                code_version=code_version,
            ),
            schema_version="living-thesis.v2",
            event_identifier=(
                f"event:{thesis.identifier}:snapshot:{thesis.review_count}"
            ),
        )

    def append_thesis_review(
        self,
        review: ThesisReview,
        *,
        code_version: str | None = None,
    ) -> CIOJournalEvent:
        return self.append(
            event_type=CIOJournalEventType.THESIS_REVIEW,
            aggregate_identifier=review.thesis_identifier,
            occurred_at=review.reviewed_at,
            payload=serialize_thesis_review(
                review,
                code_version=code_version,
            ),
            schema_version="thesis-review.v1",
            event_identifier=f"event:{review.identifier}",
        )

    def events(
        self,
        *,
        aggregate_identifier: str | None = None,
        event_type: CIOJournalEventType | None = None,
        limit: int = 100,
    ) -> tuple[CIOJournalEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be positive")
        clauses: list[str] = []
        parameters: list[object] = []
        if aggregate_identifier is not None:
            clauses.append("aggregate_identifier = ?")
            parameters.append(
                _required_text(
                    aggregate_identifier,
                    field_name="aggregate_identifier",
                )
            )
        if event_type is not None:
            if not isinstance(event_type, CIOJournalEventType):
                raise TypeError("event_type must be a CIOJournalEventType")
            clauses.append("event_type = ?")
            parameters.append(event_type.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM cio_journal_events
                {where}
                ORDER BY sequence ASC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def latest(
        self,
        *,
        aggregate_identifier: str | None = None,
        event_type: CIOJournalEventType | None = None,
    ) -> CIOJournalEvent | None:
        clauses: list[str] = []
        parameters: list[object] = []
        if aggregate_identifier is not None:
            clauses.append("aggregate_identifier = ?")
            parameters.append(
                _required_text(
                    aggregate_identifier,
                    field_name="aggregate_identifier",
                )
            )
        if event_type is not None:
            if not isinstance(event_type, CIOJournalEventType):
                raise TypeError("event_type must be a CIOJournalEventType")
            clauses.append("event_type = ?")
            parameters.append(event_type.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM cio_journal_events
                {where}
                ORDER BY sequence DESC
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
        return None if row is None else self._event_from_row(row)


    def prior_decision_contexts(
        self,
        candidates: tuple[CandidateDecisionRecord, ...],
        *,
        as_of: datetime,
    ) -> tuple[PriorDecisionContext, ...]:
        """Reconstruct state by instrument, not timestamp-specific candidate ID."""

        decision_time = _aware(as_of, field_name="as_of")
        if not self.verify_integrity():
            raise CIOJournalIntegrityError("CIO journal integrity is unavailable")
        limit = max(1, self.count())
        candidate_events = self.events(
            event_type=CIOJournalEventType.CANDIDATE_DECISION,
            limit=limit,
        )
        decision_events = self.events(
            event_type=CIOJournalEventType.CIO_DECISION,
            limit=limit,
        )
        thesis_events = self.events(
            event_type=CIOJournalEventType.THESIS_SNAPSHOT,
            limit=limit,
        )
        results: list[PriorDecisionContext] = []
        supportive = {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.HOLD,
            CIOAction.NO_MATERIAL_CHANGE,
        }
        opposing = {CIOAction.REDUCE, CIOAction.EXIT}
        material = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT}
        for candidate in candidates:
            historical_ids = {
                event.aggregate_identifier
                for event in candidate_events
                if event.occurred_at < decision_time
                and event.payload.get("instrument", {}).get("instrument_id")
                == candidate.instrument.instrument_id
            }
            history = [
                event
                for event in decision_events
                if event.occurred_at < decision_time
                and event.aggregate_identifier in historical_ids
            ]
            if not history:
                continue
            history.sort(key=lambda item: item.sequence)
            latest = history[-1]
            payload = latest.payload
            action = CIOAction(payload["action"])
            supportive_cycles = 0
            opposing_cycles = 0
            for event in reversed(history):
                item_action = CIOAction(event.payload["action"])
                if item_action in supportive:
                    if opposing_cycles:
                        break
                    supportive_cycles += 1
                elif item_action in opposing:
                    if supportive_cycles:
                        break
                    opposing_cycles += 1
                else:
                    break
            last_change = next(
                (
                    event.occurred_at
                    for event in reversed(history)
                    if CIOAction(event.payload["action"]) in material
                ),
                None,
            )
            latest_thesis = next(
                (
                    event
                    for event in reversed(thesis_events)
                    if event.occurred_at < decision_time
                    and event.payload.get("asset") == candidate.instrument.symbol
                ),
                None,
            )
            thesis_state = (
                ThesisState.CANDIDATE
                if latest_thesis is None
                else ThesisState(latest_thesis.payload["state"])
            )
            results.append(
                PriorDecisionContext(
                    candidate_identifier=candidate.identifier,
                    prior_decision_identifier=payload["identifier"],
                    prior_action=action,
                    prior_target_weight=payload.get("recommended_position_weight"),
                    decided_at=latest.occurred_at,
                    thesis_state=thesis_state,
                    consecutive_supportive_cycles=supportive_cycles,
                    consecutive_opposing_cycles=opposing_cycles,
                    last_material_change_at=last_change,
                    emergency_override=False,
                )
            )
        return tuple(results)

    def active_theses(
        self,
        candidates: tuple[CandidateDecisionRecord, ...],
        *,
        as_of: datetime,
    ) -> tuple[LivingThesis, ...]:
        decision_time = _aware(as_of, field_name="as_of")
        symbols = {item.instrument.symbol for item in candidates}
        limit = max(1, self.count())
        events = self.events(
            event_type=CIOJournalEventType.THESIS_SNAPSHOT,
            limit=limit,
        )
        latest: dict[str, CIOJournalEvent] = {}
        for event in events:
            if event.occurred_at >= decision_time or event.payload.get("asset") not in symbols:
                continue
            episode = event.payload.get("ownership_episode_identifier") or event.payload["identifier"]
            latest[episode] = event
        active_states = {
            ThesisState.ACTIVE,
            ThesisState.STRENGTHENING,
            ThesisState.STABLE,
            ThesisState.WEAKENING,
            ThesisState.REDUCED,
        }
        values: list[LivingThesis] = []
        for event in latest.values():
            payload = event.payload
            state = ThesisState(payload["state"])
            if state not in active_states:
                continue
            values.append(
                LivingThesis(
                    identifier=payload["identifier"],
                    decision_identifier=payload["decision_identifier"],
                    candidate_identifier=payload["candidate_identifier"],
                    asset=payload["asset"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                    updated_at=datetime.fromisoformat(payload["updated_at"]),
                    state=state,
                    original_rationale=payload["original_rationale"],
                    assumptions=tuple(payload["assumptions"]),
                    expected_return=payload["expected_return"],
                    expected_downside=payload["expected_downside"],
                    horizon_days=payload["horizon_days"],
                    catalysts=tuple(payload["catalysts"]),
                    invalidation_conditions=tuple(payload["invalidation_conditions"]),
                    monitoring_indicators=tuple(payload["monitoring_indicators"]),
                    initial_confidence=payload["initial_confidence"],
                    current_confidence=payload["current_confidence"],
                    evidence_identifiers=tuple(payload["evidence_identifiers"]),
                    performance_since_approval=payload["performance_since_approval"],
                    next_review_at=datetime.fromisoformat(payload["next_review_at"]),
                    review_count=payload.get("review_count", 0),
                    ownership_episode_identifier=(
                        payload.get("ownership_episode_identifier")
                        or payload["identifier"]
                    ),
                )
            )
        return tuple(sorted(values, key=lambda item: item.asset))

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM cio_journal_events"
            ).fetchone()
        return int(row["count"])

    def verify_integrity(self) -> bool:
        previous_hash = self._GENESIS_HASH
        expected_sequence = 1
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cio_journal_events ORDER BY sequence ASC"
            ).fetchall()
        for row in rows:
            event = self._event_from_row(row)
            if event.sequence != expected_sequence:
                raise CIOJournalIntegrityError(
                    "CIO journal sequence is not contiguous"
                )
            if event.previous_hash != previous_hash:
                raise CIOJournalIntegrityError(
                    "CIO journal previous hash does not match"
                )
            expected_hash = self._content_hash(
                sequence=event.sequence,
                event_identifier=event.event_identifier,
                aggregate_identifier=event.aggregate_identifier,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                schema_version=event.schema_version,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if event.content_hash != expected_hash:
                raise CIOJournalIntegrityError(
                    "CIO journal content hash does not match"
                )
            previous_hash = event.content_hash
            expected_sequence += 1
        return True

    @staticmethod
    def _content_hash(
        *,
        sequence: int,
        event_identifier: str,
        aggregate_identifier: str,
        event_type: CIOJournalEventType,
        occurred_at: datetime,
        recorded_at: datetime,
        schema_version: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        canonical = json.dumps(
            {
                "sequence": sequence,
                "event_identifier": event_identifier,
                "aggregate_identifier": aggregate_identifier,
                "event_type": event_type.value,
                "occurred_at": occurred_at.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "schema_version": schema_version,
                "payload_json": payload_json,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> CIOJournalEvent:
        return CIOJournalEvent(
            sequence=int(row["sequence"]),
            event_identifier=str(row["event_identifier"]),
            aggregate_identifier=str(row["aggregate_identifier"]),
            event_type=CIOJournalEventType(str(row["event_type"])),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
            schema_version=str(row["schema_version"]),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


__all__ = [
    "CIOJournalEvent",
    "CIOJournalEventType",
    "CIOJournalIntegrityError",
    "SQLiteCIOJournal",
    "serialize_candidate_decision",
    "serialize_cio_decision",
    "serialize_opportunity_queue",
    "serialize_specialist_packet",
    "serialize_thesis_review",
    "serialize_thesis_snapshot",
]
