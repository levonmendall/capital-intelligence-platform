"""Reusable deterministic fixtures for canonical CIO domain tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    ChiefInvestmentOfficer,
    EvidenceQuality,
    IndependentSpecialistPacket,
    RecommendationUniversePolicy,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistRole,
)
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunityQueue,
    OpportunitySetContext,
)


AS_OF = datetime(2026, 7, 26, 16, tzinfo=timezone.utc)


def build_candidate(
    *,
    symbol: str = "ACME",
    expected_return_shift: float = 0.0,
    current_weight: float = 0.0,
) -> CandidateDecisionRecord:
    instrument = CandidateInstrument(
        instrument_id=f"instrument:{symbol.lower()}",
        symbol=symbol,
        name=f"{symbol} Corporation",
        asset_class=CandidateAssetClass.US_EQUITY,
        venue="NASDAQ",
        country_code="US",
        average_daily_dollar_volume=50_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=0.96,
        security_master_snapshot_identifier="security-master:fixture:v1",
        security_master_record_identifiers=("security-master-record:fixture",),
    )
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}:2026-07-26",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=instrument,
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=0.12 + expected_return_shift,
        bull_case_return=0.30 + expected_return_shift,
        bear_case_return=-0.15 + expected_return_shift,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=118.0,
        expected_upside=0.30 + expected_return_shift,
        expected_downside=-0.15 + expected_return_shift,
        probability_of_success=0.68,
        primary_catalysts=("Forward earnings revisions improved",),
        key_risks=("Demand could weaken",),
        critical_assumptions=("Margins remain above 20%",),
        invalidation_conditions=("Forward estimates fall more than 10%",),
        supporting_evidence=("Filed cash flow accelerated",),
        contradictory_evidence=("Industry inventories remain elevated",),
        evidence_quality=EvidenceQuality(
            reliability=0.95,
            freshness=0.95,
            relevance=0.95,
            independence=0.90,
            completeness=0.90,
            point_in_time_integrity=1.0,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.012,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.10,
        monitoring_indicators=("Forward earnings revisions",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(
            f"sec-filing:{symbol.lower()}:q2",
            f"market:{symbol.lower()}:close",
        ),
        model_versions=("company-quality.v1", "valuation.v1"),
    )


def build_context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-set:2026-07-26",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:treasury-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )


def build_queue(
    candidate: CandidateDecisionRecord | None = None,
) -> OpportunityQueue:
    resolved = candidate or build_candidate()
    return OpportunityEngine().build_queue((resolved,), build_context())


def build_specialist_packet(
    candidate: CandidateDecisionRecord | None = None,
) -> IndependentSpecialistPacket:
    resolved = candidate or build_candidate()
    analyses: list[SpecialistAnalysis] = []
    for index, role in enumerate(SpecialistRole, start=1):
        analyses.append(
            SpecialistAnalysis(
                candidate_identifier=resolved.identifier,
                role=role,
                completed_at=resolved.as_of + timedelta(minutes=index),
                independent_first_pass=True,
                position=SpecialistPosition.SUPPORTIVE,
                conclusion=f"{role.value} supports committee review",
                expected_return_impact=0.02,
                confidence=0.82,
                supporting_evidence=(f"{role.value}:support",),
                contradictory_evidence=(),
                critical_assumptions=(f"{role.value}:assumption",),
                risks=(f"{role.value}:risk",),
                limitations=(),
                change_conditions=(f"{role.value}:change-condition",),
                recommended_position_weight=(
                    0.06 if role is SpecialistRole.PORTFOLIO_RISK else None
                ),
                funding_source=(
                    "cash above minimum reserve"
                    if role is SpecialistRole.PORTFOLIO_RISK
                    else None
                ),
            )
        )
    return IndependentSpecialistPacket(
        candidate_identifier=resolved.identifier,
        analyses=tuple(analyses),
    )


def build_decision(candidate: CandidateDecisionRecord | None = None):
    resolved = candidate or build_candidate()
    universe = RecommendationUniversePolicy().evaluate(resolved.instrument)
    return ChiefInvestmentOfficer().synthesize(
        resolved,
        universe,
        build_specialist_packet(resolved),
    )
