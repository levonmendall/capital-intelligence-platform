"""Separated cross-asset forecast and scenario specialist tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    SpecialistPosition,
    SpecialistRole,
)
from committee.specialists import (
    CandidateSpecialistContext,
    CrossAssetForecastSpecialistContext,
    ForecastScenarioAssessment,
    IndependentSpecialistService,
    MacroSpecialistContext,
    MarketSpecialistContext,
    PortfolioSpecialistContext,
)

AS_OF = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)


def _candidate() -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:global-etf:forecast",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:global-etf",
            symbol="ACWI",
            name="Global Equity ETF",
            asset_class=CandidateAssetClass.US_ETF,
            venue="NASDAQ",
            country_code="US",
            average_daily_dollar_volume=100_000_000.0,
            data_age_hours=1.0,
            analytical_coverage=0.98,
            security_master_snapshot_identifier="security-master:forecast",
            security_master_record_identifiers=("security-master:acwi",),
        ),
        current_price=120.0,
        decision_horizon_days=180,
        base_case_return=0.08,
        bull_case_return=0.18,
        bear_case_return=-0.14,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=130.0,
        expected_upside=0.18,
        expected_downside=-0.14,
        probability_of_success=0.65,
        primary_catalysts=("Global earnings breadth improves",),
        key_risks=("Growth weakens across regions",),
        critical_assumptions=("Cross-asset relationships remain stable",),
        invalidation_conditions=("Global growth forecast contracts materially",),
        supporting_evidence=("Point-in-time global market evidence",),
        contradictory_evidence=("Policy remains restrictive",),
        evidence_quality=EvidenceQuality(
            reliability=0.92,
            freshness=0.95,
            relevance=0.93,
            independence=0.88,
            completeness=0.90,
            point_in_time_integrity=1.0,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=4.0,
        slippage_bps=4.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("Cross-asset forecast dispersion",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=("candidate-evidence:acwi",),
        model_versions=("candidate.v1",),
    )


def _forecast() -> CrossAssetForecastSpecialistContext:
    return CrossAssetForecastSpecialistContext(
        as_of=AS_OF,
        forecast_horizon_days=180,
        scenarios=(
            ForecastScenarioAssessment(
                label="growth:base",
                probability=0.50,
                candidate_return_impact=0.04,
                expected_path_drawdown=-0.08,
                rationale="Moderate global expansion supports risk assets.",
                evidence_identifiers=("forecast:growth",),
            ),
            ForecastScenarioAssessment(
                label="growth:upside",
                probability=0.30,
                candidate_return_impact=0.08,
                expected_path_drawdown=-0.05,
                rationale="Reacceleration broadens earnings growth.",
                evidence_identifiers=("forecast:growth",),
            ),
            ForecastScenarioAssessment(
                label="growth:downside",
                probability=0.20,
                candidate_return_impact=-0.10,
                expected_path_drawdown=-0.22,
                rationale="A synchronized slowdown compresses equity returns.",
                evidence_identifiers=("forecast:growth",),
            ),
        ),
        aggregate_confidence=0.78,
        calibration_score=0.72,
        model_agreement=0.70,
        forecast_stability=0.68,
        path_drawdown_probability=0.28,
        cross_asset_signals=(
            "Rates, credit, currencies, commodities, and global equities are jointly assessed",
        ),
        contradictory_evidence=("Credit spreads have stopped improving",),
        limitations=("Tail events remain underrepresented",),
        change_conditions=("Reassess after material forecast or regime changes",),
        model_versions=("global-growth:v3", "cross-asset-path:v2"),
        evidence_identifiers=("forecast:growth", "forecast:cross-asset"),
    )


def _context(
    forecast: CrossAssetForecastSpecialistContext | None,
) -> CandidateSpecialistContext:
    return CandidateSpecialistContext(
        candidate_identifier=_candidate().identifier,
        analysis_completed_at=AS_OF + timedelta(minutes=5),
        macro=MacroSpecialistContext(
            as_of=AS_OF,
            regime="moderate growth",
            expected_return_impact=0.01,
            confidence=0.80,
            tailwinds=("Growth remains positive",),
            headwinds=("Policy is restrictive",),
            systemic_risks=("Inflation reaccelerates",),
            scenarios=("Review if growth contracts",),
            evidence_identifiers=("macro:current-state",),
        ),
        market=MarketSpecialistContext(
            as_of=AS_OF,
            market_regime="constructive",
            expected_return_impact=0.01,
            confidence=0.80,
            trend=0.60,
            momentum=0.55,
            breadth=0.50,
            liquidity=0.75,
            positioning=0.20,
            evidence=("Trend and participation remain constructive",),
            risks=("Momentum can reverse",),
            entry_conditions=("Trend remains positive",),
            evidence_identifiers=("market:technicals",),
        ),
        forecast=forecast,
        portfolio=PortfolioSpecialistContext(
            as_of=AS_OF,
            proposed_position_weight=0.06,
            funding_source="cash",
            expected_portfolio_contribution=0.01,
            opportunity_cost_return=0.04,
            constraint_evidence=("Position fits portfolio constraints",),
            implementation_blocks=(),
            review_conditions=("Reassess if portfolio risk changes",),
        ),
    )


def test_forecast_specialist_is_separate_and_makes_a_calibrated_recommendation() -> None:
    candidate = _candidate()
    packet = IndependentSpecialistService().analyze(
        candidate,
        _context(_forecast()),
    )

    forecast = packet.for_role(SpecialistRole.CROSS_ASSET_FORECAST)
    market = packet.for_role(SpecialistRole.MARKET)

    assert len(packet.analyses) == 6
    assert forecast.position is SpecialistPosition.SUPPORTIVE
    assert forecast.expected_return_impact == pytest.approx(0.024)
    assert forecast.recommended_position_weight is None
    assert forecast.funding_source is None
    assert "probability=" in forecast.supporting_evidence[0]
    assert market.evidence_origin_identifiers == ("market:technicals",)
    assert set(forecast.evidence_origin_identifiers).isdisjoint(
        market.evidence_origin_identifiers
    )


def test_forecast_specialist_abstains_when_calibration_is_not_good_enough() -> None:
    candidate = _candidate()
    weak = replace(_forecast(), calibration_score=0.40)

    analysis = IndependentSpecialistService().analyze(
        candidate,
        _context(weak),
    ).for_role(SpecialistRole.CROSS_ASSET_FORECAST)

    assert analysis.position is SpecialistPosition.ABSTAIN
    assert analysis.expected_return_impact == 0.0
    assert any("calibration is below threshold" in item for item in analysis.contradictory_evidence)


def test_missing_forecast_packet_abstains_without_blocking_other_specialists() -> None:
    analysis = IndependentSpecialistService().analyze(
        _candidate(),
        _context(None),
    ).for_role(SpecialistRole.CROSS_ASSET_FORECAST)

    assert analysis.position is SpecialistPosition.ABSTAIN
    assert analysis.confidence == 0.0
    assert analysis.expected_return_impact == 0.0
