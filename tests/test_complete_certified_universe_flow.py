"""Regression coverage for complete-universe committee and CIO consideration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.cio_cycle import (
    CandidateCycleContext,
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from cio.persistence import SQLiteCIOJournal
from committee.specialists import MacroSpecialistContext, MarketSpecialistContext
from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext
from portfolio.construction_api import PortfolioAsset, PortfolioConstructionPolicy


AS_OF = datetime(2026, 8, 3, 15, tzinfo=timezone.utc)


def _candidate(index: int) -> CandidateDecisionRecord:
    symbol = f"Q{index:03d}"
    evidence = EvidenceQuality(
        reliability=0.92,
        freshness=0.92,
        relevance=0.92,
        independence=0.92,
        completeness=0.92,
        point_in_time_integrity=0.92,
    )
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}:complete-universe",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=CandidateInstrument(
            instrument_id=f"instrument:{symbol.lower()}",
            symbol=symbol,
            name=f"{symbol} qualified instrument",
            asset_class=CandidateAssetClass.US_ETF,
            venue="NYSE",
            country_code="US",
            average_daily_dollar_volume=250_000_000.0,
            data_age_hours=1.0,
            analytical_coverage=0.95,
            security_master_snapshot_identifier="security-master:complete-universe:v1",
            security_master_record_identifiers=(
                f"security-master-record:{symbol.lower()}",
            ),
        ),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=0.12,
        bull_case_return=0.25,
        bear_case_return=-0.10,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=112.0,
        expected_upside=0.25,
        expected_downside=-0.10,
        probability_of_success=0.68,
        primary_catalysts=("Expected return improved after new evidence",),
        key_risks=("The opportunity could underperform its expected range",),
        critical_assumptions=("The evidence remains current",),
        invalidation_conditions=("Expected return falls below cash",),
        supporting_evidence=("Primary evidence supports the return estimate",),
        contradictory_evidence=("One market signal remains mixed",),
        evidence_quality=evidence,
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.059,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.08,
        monitoring_indicators=("Expected return and relative strength",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(f"evidence:{symbol.lower()}:1",),
        model_versions=("complete-universe-test.v1",),
    )


def _opportunity_context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-set:complete-universe",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:treasury-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=0.20,
            ),
            AlternativeUse(
                identifier="holding:core",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=0.06,
                implementation_cost_return=0.001,
                evidence_quality=0.95,
                liquidity_score=1.0,
                current_weight=0.80,
            ),
        ),
    )


def _specialist_context(candidate: CandidateDecisionRecord) -> CandidateCycleContext:
    return CandidateCycleContext(
        candidate_identifier=candidate.identifier,
        analysis_completed_at=AS_OF + timedelta(minutes=5),
        macro=MacroSpecialistContext(
            as_of=AS_OF,
            regime="constructive growth",
            expected_return_impact=0.02,
            confidence=0.85,
            tailwinds=("Growth and liquidity are supportive",),
            headwinds=("Inflation remains above target",),
            systemic_risks=("Credit conditions could tighten",),
            scenarios=("Review if growth or liquidity turns negative",),
            evidence_identifiers=("macro:complete-universe",),
        ),
        market=MarketSpecialistContext(
            as_of=AS_OF,
            market_regime="constructive",
            expected_return_impact=0.02,
            confidence=0.85,
            trend=0.70,
            momentum=0.60,
            breadth=0.50,
            liquidity=0.70,
            positioning=0.20,
            evidence=("Trend, breadth, and liquidity are supportive",),
            risks=("Positioning could become crowded",),
            entry_conditions=("Review if trend turns negative",),
        ),
        company=None,
    )


def _portfolio(
    candidates: tuple[CandidateDecisionRecord, ...],
) -> CyclePortfolioState:
    return CyclePortfolioState(
        identifier="portfolio:complete-universe",
        as_of=AS_OF,
        portfolio_value=10_000_000.0,
        cash_weight=0.20,
        cash_expected_return=0.04,
        positions=(
            PortfolioAsset(
                symbol="CORE",
                current_weight=0.80,
                expected_return=0.06,
                sector="Diversified",
                factor_loadings=(("market", 0.50),),
                correlation_bucket="broad-market",
                average_daily_dollar_volume=2_000_000_000.0,
                transaction_cost_bps=2.0,
                slippage_bps=2.0,
                minimum_weight=0.50,
                funding_eligible=False,
            ),
        ),
        exposure_profiles=tuple(
            CandidateExposureProfile(
                candidate_identifier=item.identifier,
                sector="Diversified",
                factor_loadings=(("market", 0.80),),
                correlation_bucket="broad-market",
            )
            for item in candidates
        ),
    )


def _construction_policy() -> PortfolioConstructionPolicy:
    return PortfolioConstructionPolicy(
        version="portfolio-construction.complete-universe-test.v1",
        minimum_cash_weight=0.02,
        maximum_position_weight=0.95,
        default_maximum_sector_weight=0.98,
        default_maximum_correlation_bucket_weight=0.98,
        maximum_turnover=0.25,
        maximum_total_cost_return=0.01,
        minimum_replacement_edge=0.01,
        maximum_daily_volume_participation=0.10,
        execution_days=3,
    )


def test_every_qualified_candidate_reaches_six_specialists_and_cio(tmp_path) -> None:
    # Twenty-five deliberately exceeds the former per-lane shortlist of twenty.
    candidates = tuple(_candidate(index) for index in range(25))
    journal = SQLiteCIOJournal(tmp_path / "complete-universe.db")

    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:complete-qualified-universe",
        candidates=candidates,
        opportunity_context=_opportunity_context(),
        specialist_contexts=tuple(
            _specialist_context(candidate) for candidate in candidates
        ),
        portfolio=_portfolio(candidates),
        code_version="complete-qualified-universe-test",
    )

    assert len(result.opportunity_queue.ranked) == len(candidates)
    assert len(result.decisions) == len(candidates)
    assert {
        item.candidate_identifier for item in result.decisions
    } == {item.identifier for item in candidates}

    specialist_packets = tuple(
        event
        for event in journal.events()
        if event.event_type.value == "specialist_packet"
    )
    assert len(specialist_packets) == len(candidates)
    assert all(len(event.payload["analyses"]) == 6 for event in specialist_packets)
