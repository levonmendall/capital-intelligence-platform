"""Non-authoritative instrumentation for the governed candidate funnel.

The diagnostic observes immutable screening and CIO-cycle outputs.  It cannot
qualify a candidate, issue a CIO action, change construction, or execute a
trade.  Execution is intentionally reported as pending at the decision-cycle
boundary and is joined later from canonical paper-fill events.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from cio import CIOAction, CIODecision, CandidateDecisionRecord
from cio.persistence import CIOJournalEvent, CIOJournalEventType, SQLiteCIOJournal
from screening import FullUniverseScreeningPublication

if TYPE_CHECKING:
    from application.cio_cycle import CanonicalCIOCycleResult


class CashNoActionReason(str, Enum):
    NO_ATTRACTIVE_OPPORTUNITY = "no_attractive_opportunity"
    INCOMPLETE_OR_STALE_EVIDENCE = "incomplete_or_stale_evidence"
    PROVIDER_DEGRADATION = "provider_degradation"
    SCREENING_REJECTION = "screening_rejection"
    INSUFFICIENT_EXPECTED_RETURN = "insufficient_expected_return"
    FAILURE_TO_EXCEED_CASH_HURDLE = "failure_to_exceed_cash_hurdle"
    DOWNSIDE_OR_TAIL_RISK_REJECTION = "downside_or_tail_risk_rejection"
    LIQUIDITY_OR_COST_REJECTION = "liquidity_or_cost_rejection"
    SPECIALIST_CONCERN = "specialist_concern"
    HIDDEN_SPECIALIST_VETO = "hidden_specialist_veto"
    COMMITTEE_AGGREGATION_ISSUE = "committee_aggregation_issue"
    CIO_REJECTION = "cio_rejection"
    CONSTRUCTION_CONSTRAINT = "construction_constraint"
    APPROVED_TARGET_REDUCED_TO_ZERO = "approved_target_reduced_to_zero"
    MINIMUM_POSITION_RULE = "minimum_position_rule"
    OPERATIONAL_OR_EXECUTION_FAILURE = "operational_or_execution_failure"


class FunnelStage(str, Enum):
    ELIGIBLE_UNIVERSE = "eligible_universe"
    DECISION_ELIGIBLE = "decision_eligible"
    COMPLETE_EVIDENCE = "complete_evidence"
    SCREENING = "screening"
    SIX_SPECIALIST_ANALYSIS = "six_specialist_analysis"
    COMMITTEE_SYNTHESIS = "committee_synthesis"
    CIO_CONSIDERATION = "cio_consideration"
    CIO_QUALIFICATION = "cio_qualification"
    RISK_ADJUSTED_INITIAL_TARGET = "risk_adjusted_initial_target"
    PORTFOLIO_CONSTRUCTION = "portfolio_construction"
    NONZERO_FINAL_TARGET = "nonzero_final_target"
    PAPER_IMPLEMENTATION = "paper_implementation"


_STAGE_ORDER = tuple(FunnelStage)
_MATERIAL_ACTIONS = {
    CIOAction.BUY,
    CIOAction.INCREASE,
    CIOAction.REDUCE,
    CIOAction.EXIT,
}


def _ordered_unique(values: list[CashNoActionReason]) -> tuple[CashNoActionReason, ...]:
    return tuple(dict.fromkeys(values))


def _reason_from_text(text: str, *, fallback: CashNoActionReason) -> CashNoActionReason:
    value = text.lower()
    if any(marker in value for marker in ("provider", "feed", "upstream", "source unavailable")):
        return CashNoActionReason.PROVIDER_DEGRADATION
    if any(marker in value for marker in ("stale", "missing", "incomplete", "evidence", "coverage")):
        return CashNoActionReason.INCOMPLETE_OR_STALE_EVIDENCE
    if any(marker in value for marker in ("minimum position", "minimum weight", "minimum trade")):
        return CashNoActionReason.MINIMUM_POSITION_RULE
    if any(marker in value for marker in ("liquidity", "volume", "slippage", "implementation cost", "transaction cost")):
        return CashNoActionReason.LIQUIDITY_OR_COST_REJECTION
    if any(marker in value for marker in ("downside", "tail risk", "drawdown", "expected shortfall", "worst-case")):
        return CashNoActionReason.DOWNSIDE_OR_TAIL_RISK_REJECTION
    if any(marker in value for marker in ("cash", "best alternative", "opportunity edge", "advantage over", "superior")):
        return CashNoActionReason.FAILURE_TO_EXCEED_CASH_HURDLE
    if any(marker in value for marker in ("expected return", "return hurdle", "absolute hurdle", "return is below")):
        return CashNoActionReason.INSUFFICIENT_EXPECTED_RETURN
    if any(marker in value for marker in ("specialist disagreement", "specialist concern", "dissent", "opposition")):
        return CashNoActionReason.SPECIALIST_CONCERN
    if any(marker in value for marker in ("constraint", "feasible", "funding source", "allocation")):
        return CashNoActionReason.CONSTRUCTION_CONSTRAINT
    if any(marker in value for marker in ("execution", "order", "quote", "reconciliation", "operational")):
        return CashNoActionReason.OPERATIONAL_OR_EXECUTION_FAILURE
    return fallback


def _classified_reasons(
    texts: tuple[str, ...],
    *,
    fallback: CashNoActionReason,
) -> tuple[CashNoActionReason, ...]:
    values = [_reason_from_text(item, fallback=fallback) for item in texts]
    return _ordered_unique(values or [fallback])


@dataclass(frozen=True, slots=True)
class CandidateFunnelObservation:
    instrument_identifier: str
    symbol: str
    candidate_identifier: str | None
    reached_stages: tuple[FunnelStage, ...]
    primary_reason: CashNoActionReason | None
    contributing_reasons: tuple[CashNoActionReason, ...]
    reason_evidence: tuple[str, ...]
    cio_action: str | None = None
    decision_identifier: str | None = None
    risk_adjusted_initial_target: float | None = None
    final_target: float | None = None
    construction_request_identifier: str | None = None
    paper_implementation_state: str = "not_observed_at_decision_boundary"
    hidden_specialist_veto_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_identifier": self.instrument_identifier,
            "symbol": self.symbol,
            "candidate_identifier": self.candidate_identifier,
            "reached_stages": [item.value for item in self.reached_stages],
            "primary_reason": None if self.primary_reason is None else self.primary_reason.value,
            "contributing_reasons": [item.value for item in self.contributing_reasons],
            "reason_evidence": list(self.reason_evidence),
            "cio_action": self.cio_action,
            "decision_identifier": self.decision_identifier,
            "risk_adjusted_initial_target": self.risk_adjusted_initial_target,
            "final_target": self.final_target,
            "construction_request_identifier": self.construction_request_identifier,
            "paper_implementation_state": self.paper_implementation_state,
            "hidden_specialist_veto_detected": self.hidden_specialist_veto_detected,
        }


@dataclass(frozen=True, slots=True)
class PersistentCashCycleDiagnostic:
    cycle_identifier: str
    screening_cycle_identifier: str
    as_of: datetime
    code_version: str
    cash_weight_before: float
    target_cash_weight: float | None
    portfolio_remained_all_cash_at_construction: bool
    implementation_observation_complete: bool
    funnel_counts: tuple[tuple[FunnelStage, int], ...]
    primary_reason: CashNoActionReason | None
    contributing_reasons: tuple[CashNoActionReason, ...]
    observations: tuple[CandidateFunnelObservation, ...]
    policy_versions: tuple[str, ...]
    schema_version: str = "persistent-cash-diagnostic.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cycle_identifier": self.cycle_identifier,
            "screening_cycle_identifier": self.screening_cycle_identifier,
            "as_of": self.as_of.isoformat(),
            "code_version": self.code_version,
            "cash_weight_before": self.cash_weight_before,
            "target_cash_weight": self.target_cash_weight,
            "portfolio_remained_all_cash_at_construction": self.portfolio_remained_all_cash_at_construction,
            "implementation_observation_complete": self.implementation_observation_complete,
            "funnel_counts": {stage.value: count for stage, count in self.funnel_counts},
            "primary_reason": None if self.primary_reason is None else self.primary_reason.value,
            "contributing_reasons": [item.value for item in self.contributing_reasons],
            "observations": [item.to_dict() for item in self.observations],
            "policy_versions": list(self.policy_versions),
            "authority": {
                "diagnostic_only": True,
                "cio_authority_changed": False,
                "construction_authority_changed": False,
                "execution_authority_changed": False,
                "real_money_authorized": False,
            },
        }


def _primary_reason(
    reasons: tuple[CashNoActionReason, ...],
) -> CashNoActionReason:
    precedence = (
        CashNoActionReason.OPERATIONAL_OR_EXECUTION_FAILURE,
        CashNoActionReason.APPROVED_TARGET_REDUCED_TO_ZERO,
        CashNoActionReason.MINIMUM_POSITION_RULE,
        CashNoActionReason.CONSTRUCTION_CONSTRAINT,
        CashNoActionReason.HIDDEN_SPECIALIST_VETO,
        CashNoActionReason.COMMITTEE_AGGREGATION_ISSUE,
        CashNoActionReason.SPECIALIST_CONCERN,
        CashNoActionReason.CIO_REJECTION,
        CashNoActionReason.DOWNSIDE_OR_TAIL_RISK_REJECTION,
        CashNoActionReason.LIQUIDITY_OR_COST_REJECTION,
        CashNoActionReason.FAILURE_TO_EXCEED_CASH_HURDLE,
        CashNoActionReason.INSUFFICIENT_EXPECTED_RETURN,
        CashNoActionReason.SCREENING_REJECTION,
        CashNoActionReason.PROVIDER_DEGRADATION,
        CashNoActionReason.INCOMPLETE_OR_STALE_EVIDENCE,
        CashNoActionReason.NO_ATTRACTIVE_OPPORTUNITY,
    )
    return next(item for item in precedence if item in reasons)


def _decision_reasons(decision: CIODecision) -> tuple[CashNoActionReason, ...]:
    reasons: list[CashNoActionReason] = []
    for item in decision.evidence_vetoes:
        reasons.append(
            _reason_from_text(
                item,
                fallback=CashNoActionReason.INCOMPLETE_OR_STALE_EVIDENCE,
            )
        )
    if decision.evidence_vetoes:
        reasons.append(CashNoActionReason.SPECIALIST_CONCERN)
    for item in decision.implementation_blocks:
        reasons.append(
            _reason_from_text(item, fallback=CashNoActionReason.CONSTRUCTION_CONSTRAINT)
        )
    if decision.dissent is not None:
        reasons.append(CashNoActionReason.SPECIALIST_CONCERN)
    reasons.append(
        _reason_from_text(decision.rationale, fallback=CashNoActionReason.CIO_REJECTION)
    )
    if decision.action in {CIOAction.HOLD, CIOAction.NO_MATERIAL_CHANGE}:
        reasons.append(CashNoActionReason.NO_ATTRACTIVE_OPPORTUNITY)
    return _ordered_unique(reasons)


def build_persistent_cash_diagnostic(
    *,
    publication: FullUniverseScreeningPublication,
    candidates: tuple[CandidateDecisionRecord, ...],
    context_candidate_identifiers: tuple[str, ...],
    result: "CanonicalCIOCycleResult",
    cash_weight_before: float,
    minimum_evidence_score: float,
    minimum_evidence_dimension: float,
    code_version: str,
) -> PersistentCashCycleDiagnostic:
    """Classify one completed decision cycle without changing its outputs."""

    candidate_by_identifier = {item.identifier: item for item in candidates}
    decision_by_candidate = {item.candidate_identifier: item for item in result.decisions}
    snapshot_by_candidate = {
        item.candidate_identifier: item for item in result.evaluation_snapshots
    }
    ranked = {
        item.candidate.identifier: item for item in result.opportunity_queue.ranked
    }
    rejected = {
        item.candidate_identifier: item for item in result.opportunity_queue.rejected
    }
    contexts = set(context_candidate_identifiers)
    construction = result.construction
    target_by_symbol = {} if construction is None else dict(construction.target_weights)
    construction_identifier = (
        None if construction is None else construction.request_identifier
    )
    observations: list[CandidateFunnelObservation] = []

    for exclusion in publication.exclusions:
        raw_reasons = tuple(str(item) for item in exclusion.get("reasons", ()))
        classified = _classified_reasons(
            raw_reasons,
            fallback=CashNoActionReason.SCREENING_REJECTION,
        )
        observations.append(
            CandidateFunnelObservation(
                instrument_identifier=str(exclusion["instrument_identifier"]),
                symbol=str(exclusion["symbol"]),
                candidate_identifier=None,
                reached_stages=(FunnelStage.ELIGIBLE_UNIVERSE,),
                primary_reason=_primary_reason(classified),
                contributing_reasons=classified,
                reason_evidence=raw_reasons,
            )
        )

    for candidate in candidates:
        stages = [FunnelStage.ELIGIBLE_UNIVERSE, FunnelStage.DECISION_ELIGIBLE]
        complete_evidence = (
            candidate.evidence_quality.score >= minimum_evidence_score
            and candidate.evidence_quality.ceiling >= minimum_evidence_dimension
        )
        if complete_evidence:
            stages.append(FunnelStage.COMPLETE_EVIDENCE)
        qualification = ranked.get(candidate.identifier) or rejected.get(candidate.identifier)
        decision = decision_by_candidate.get(candidate.identifier)
        snapshot = snapshot_by_candidate.get(candidate.identifier)
        evidence: list[str] = []
        reasons: tuple[CashNoActionReason, ...] = ()

        if candidate.identifier in ranked:
            stages.append(FunnelStage.SCREENING)
            if candidate.identifier in contexts and snapshot is not None and len(snapshot.specialist_roles) == 6:
                stages.append(FunnelStage.SIX_SPECIALIST_ANALYSIS)
            if decision is not None:
                stages.extend((FunnelStage.COMMITTEE_SYNTHESIS, FunnelStage.CIO_CONSIDERATION))
                reasons = _decision_reasons(decision)
                evidence.extend(decision.evidence_vetoes)
                evidence.extend(decision.implementation_blocks)
                evidence.append(decision.rationale)
        elif qualification is not None:
            evidence.extend(qualification.reasons)
            reasons = _classified_reasons(
                qualification.reasons,
                fallback=CashNoActionReason.SCREENING_REJECTION,
            )

        initial_target = None if decision is None else decision.recommended_position_weight
        if decision is not None and decision.action in _MATERIAL_ACTIONS:
            stages.append(FunnelStage.CIO_QUALIFICATION)
        if initial_target is not None and initial_target > 0.0:
            stages.append(FunnelStage.RISK_ADJUSTED_INITIAL_TARGET)
        final_target = target_by_symbol.get(candidate.instrument.symbol)
        if construction is not None and decision is not None and decision.action in _MATERIAL_ACTIONS:
            stages.append(FunnelStage.PORTFOLIO_CONSTRUCTION)
        if final_target is not None and final_target > 0.0:
            stages.append(FunnelStage.NONZERO_FINAL_TARGET)
        if initial_target is not None and initial_target > 0.0 and not (final_target and final_target > 0.0):
            reasons = _ordered_unique(
                [CashNoActionReason.APPROVED_TARGET_REDUCED_TO_ZERO, *reasons]
            )
        if construction is not None and construction.blocks:
            construction_reasons = _classified_reasons(
                construction.blocks,
                fallback=CashNoActionReason.CONSTRUCTION_CONSTRAINT,
            )
            reasons = _ordered_unique([*construction_reasons, *reasons])
            evidence.extend(construction.blocks)
        if not reasons and final_target is None:
            reasons = (CashNoActionReason.NO_ATTRACTIVE_OPPORTUNITY,)

        observations.append(
            CandidateFunnelObservation(
                instrument_identifier=candidate.instrument.instrument_id,
                symbol=candidate.instrument.symbol,
                candidate_identifier=candidate.identifier,
                reached_stages=tuple(dict.fromkeys(stages)),
                primary_reason=(
                    None if final_target is not None and final_target > 0.0 else _primary_reason(reasons)
                ),
                contributing_reasons=(
                    () if final_target is not None and final_target > 0.0 else reasons
                ),
                reason_evidence=tuple(dict.fromkeys(evidence)),
                cio_action=None if decision is None else decision.action.value,
                decision_identifier=None if decision is None else decision.identifier,
                risk_adjusted_initial_target=initial_target,
                final_target=final_target,
                construction_request_identifier=construction_identifier,
            )
        )

    counts = tuple(
        (stage, sum(stage in item.reached_stages for item in observations))
        for stage in _STAGE_ORDER
    )
    target_cash = None if construction is None else construction.target_cash_weight
    stayed_cash = cash_weight_before >= 0.999999 and (
        target_cash is None or target_cash >= 0.999999
    )
    cash_reasons = _ordered_unique(
        [
            reason
            for item in observations
            if item.primary_reason is not None
            for reason in item.contributing_reasons
        ]
    )
    cycle_primary = _primary_reason(cash_reasons) if stayed_cash and cash_reasons else None
    policy_versions = tuple(
        dict.fromkeys(
            (
                result.opportunity_queue.policy_version,
                *(item.policy_version for item in result.decisions),
                *(() if construction is None else (construction.policy_version,)),
            )
        )
    )
    return PersistentCashCycleDiagnostic(
        cycle_identifier=result.identifier,
        screening_cycle_identifier=publication.cycle_identifier,
        as_of=result.as_of,
        code_version=code_version,
        cash_weight_before=round(float(cash_weight_before), 8),
        target_cash_weight=target_cash,
        portfolio_remained_all_cash_at_construction=stayed_cash,
        implementation_observation_complete=False,
        funnel_counts=counts,
        primary_reason=cycle_primary,
        contributing_reasons=cash_reasons if stayed_cash else (),
        observations=tuple(observations),
        policy_versions=policy_versions,
    )


def append_persistent_cash_diagnostic(
    journal: SQLiteCIOJournal,
    diagnostic: PersistentCashCycleDiagnostic,
) -> CIOJournalEvent:
    """Append one idempotent diagnostic snapshot to the CIO hash chain."""

    return journal.append(
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
        aggregate_identifier=diagnostic.cycle_identifier,
        occurred_at=diagnostic.as_of,
        payload=diagnostic.to_dict(),
        schema_version=diagnostic.schema_version,
        event_identifier=f"event:persistent-cash:{diagnostic.cycle_identifier}",
    )


def summarize_persistent_cash_journal(journal: SQLiteCIOJournal) -> dict[str, Any]:
    """Reduce all available diagnostic cycles and later paper fills."""

    journal.verify_integrity()
    limit = max(1, journal.count())
    diagnostics = journal.events(
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
        limit=limit,
    )
    fills = journal.events(
        event_type=CIOJournalEventType.PAPER_TRADE_FILL,
        limit=limit,
    )
    filled_decisions = {item.aggregate_identifier for item in fills}
    primary_counts: Counter[str] = Counter()
    contributing_counts: Counter[str] = Counter()
    funnel_totals: Counter[str] = Counter()
    cycle_values: list[dict[str, Any]] = []
    for event in diagnostics:
        payload = event.payload
        if payload.get("primary_reason") is not None:
            primary_counts[str(payload["primary_reason"])] += 1
        contributing_counts.update(str(item) for item in payload.get("contributing_reasons", ()))
        funnel_totals.update(
            {str(key): int(value) for key, value in dict(payload.get("funnel_counts", {})).items()}
        )
        observations = tuple(payload.get("observations", ()))
        implemented = sum(
            1
            for item in observations
            if isinstance(item, Mapping)
            and item.get("decision_identifier") in filled_decisions
        )
        cycle_values.append(
            {
                "cycle_identifier": payload["cycle_identifier"],
                "as_of": payload["as_of"],
                "remained_all_cash_at_construction": payload[
                    "portfolio_remained_all_cash_at_construction"
                ],
                "primary_reason": payload.get("primary_reason"),
                "paper_implemented_count": implemented,
            }
        )
    return {
        "schema_version": "persistent-cash-summary.v1",
        "available_cycle_count": len(diagnostics),
        "all_cash_cycle_count": sum(
            bool(item["remained_all_cash_at_construction"]) for item in cycle_values
        ),
        "primary_reason_counts": dict(sorted(primary_counts.items())),
        "contributing_reason_counts": dict(sorted(contributing_counts.items())),
        "funnel_totals": dict(sorted(funnel_totals.items())),
        "paper_fill_event_count": len(fills),
        "cycles": cycle_values,
        "authority": {
            "diagnostic_only": True,
            "investment_behavior_changed": False,
            "real_money_authorized": False,
        },
    }


__all__ = [
    "CandidateFunnelObservation",
    "CashNoActionReason",
    "FunnelStage",
    "PersistentCashCycleDiagnostic",
    "append_persistent_cash_diagnostic",
    "build_persistent_cash_diagnostic",
    "summarize_persistent_cash_journal",
]
