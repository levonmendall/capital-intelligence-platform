"""End-to-end tests for the canonical CIO decision cycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from application.cio_cycle import (
    CandidateCycleContext,
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio import (
    CIOAction,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from cio.persistence import SQLiteCIOJournal
from committee.specialists import (
    MacroSpecialistContext,
    MarketSpecialistContext,
)
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunitySetContext,
)
from portfolio.construction_api import (
    ConstructionStatus,
    PortfolioAsset,
    PortfolioConstructionPolicy,
)
from reporting.daily_cio import DailyCIOStatus


AS_OF = datetime(2026, 7, 26, 18, tzinfo=timezone.utc)


def _candidate(
    symbol: str,
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_ETF,
    base_return: float = 0.12,
    bull_return: float = 0.25,
    bear_return: float = -0.10,
    evidence: float = 0.92,
    current_weight: float = 0.0,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}:cycle",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=CandidateInstrument(
            instrument_id=f"instrument:{symbol.lower()}",
            symbol=symbol,
            name=f"{symbol} instrument",
            asset_class=asset_class,
            venue="NYSE",
            country_code="US",
            average_daily_dollar_volume=250_000_000.0,
            data_age_hours=1.0,
            analytical_coverage=0.95,
        ),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=base_return,
        bull_case_return=bull_return,
        bear_case_return=bear_return,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=112.0,
        expected_upside=bull_return,
        expected_downside=bear_return,
        probability_of_success=0.68,
        primary_catalysts=("Expected return improved after new evidence",),
        key_risks=("The opportunity could underperform its expected range",),
        critical_assumptions=("The evidence remains current",),
        invalidation_conditions=("Expected return falls below cash",),
        supporting_evidence=("Primary evidence supports the return estimate",),
        contradictory_evidence=("One market signal remains mixed",),
        evidence_quality=EvidenceQuality(
            reliability=evidence,
            freshness=evidence,
            relevance=evidence,
            independence=evidence,
            completeness=evidence,
            point_in_time_integrity=evidence,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.059,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.08,
        monitoring_indicators=("Expected return and relative strength",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(f"evidence:{symbol.lower()}:1",),
        model_versions=("candidate-test.v1",),
    )


def _opportunity_context(*, cash_weight: float = 0.20) -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-set:cycle",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:treasury-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=cash_weight,
            ),
            AlternativeUse(
                identifier="holding:core",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=0.06,
                implementation_cost_return=0.001,
                evidence_quality=0.95,
                liquidity_score=1.0,
                current_weight=1.0 - cash_weight,
            ),
        ),
    )


def _portfolio(
    candidates: tuple[CandidateDecisionRecord, ...],
    *,
    cash_weight: float = 0.20,
    funding_eligible: bool = False,
) -> CyclePortfolioState:
    return CyclePortfolioState(
        identifier="portfolio:cycle",
        as_of=AS_OF,
        portfolio_value=10_000_000.0,
        cash_weight=cash_weight,
        cash_expected_return=0.04,
        positions=(
            PortfolioAsset(
                symbol="CORE",
                current_weight=1.0 - cash_weight,
                expected_return=0.06,
                sector="Diversified",
                factor_loadings=(("market", 0.50),),
                correlation_bucket="broad-market",
                average_daily_dollar_volume=2_000_000_000.0,
                transaction_cost_bps=2.0,
                slippage_bps=2.0,
                minimum_weight=0.50,
                funding_eligible=funding_eligible,
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


def _context(candidate: CandidateDecisionRecord) -> CandidateCycleContext:
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
            evidence_identifiers=("macro:cycle",),
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


def _construction_policy() -> PortfolioConstructionPolicy:
    return PortfolioConstructionPolicy(
        version="portfolio-construction.cycle-test.v1",
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


def test_successful_etf_cycle_reaches_cio_construction_thesis_and_briefing(tmp_path) -> None:
    candidate = _candidate("QUAL")
    journal = SQLiteCIOJournal(tmp_path / "institutional.db")
    cycle = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    )

    result = cycle.run(
        identifier="cycle:successful-etf",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
        code_version="commit-cycle",
    )

    assert result.opportunity_queue.top is not None
    assert result.decisions[0].action is CIOAction.BUY
    assert result.construction is not None
    assert result.construction.status is ConstructionStatus.FEASIBLE
    assert dict(result.construction.target_weights)["QUAL"] == pytest.approx(0.08)
    assert len(result.theses) == 1
    assert result.briefing.status is DailyCIOStatus.CURRENT
    assert result.briefing.decision_identifier == result.decisions[0].identifier
    assert result.briefing.confidence == result.decisions[0].final_confidence
    assert journal.verify_integrity()
    assert journal.count() == 7


def test_empty_qualified_queue_produces_no_superior_opportunity() -> None:
    weak = _candidate(
        "WEAK",
        base_return=0.01,
        bull_return=0.04,
        bear_return=-0.20,
    )
    cycle = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    )

    result = cycle.run(
        identifier="cycle:no-opportunity",
        candidates=(weak,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(),
        portfolio=_portfolio((), cash_weight=0.20),
    )

    assert not result.opportunity_queue.ranked
    assert result.decisions == ()
    assert result.construction is None
    assert result.theses == ()
    assert result.briefing.status is DailyCIOStatus.NO_SUPERIOR_OPPORTUNITY
    assert "No portfolio action" in result.briefing.portfolio_decision


def test_equity_without_company_analysis_is_vetoed_as_insufficient_evidence() -> None:
    equity = _candidate(
        "EQUITY",
        asset_class=CandidateAssetClass.US_EQUITY,
    )
    cycle = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    )

    result = cycle.run(
        identifier="cycle:missing-company",
        candidates=(equity,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(equity),),
        portfolio=_portfolio((equity,)),
    )

    assert result.decisions[0].action is CIOAction.INSUFFICIENT_EVIDENCE
    assert result.decisions[0].evidence_vetoes
    assert result.construction is None
    assert result.theses == ()
    assert result.briefing.status is DailyCIOStatus.INSUFFICIENT_EVIDENCE


def test_multiple_candidates_compete_for_scarce_cash_in_rank_order() -> None:
    first = _candidate("FIRST", base_return=0.15, bull_return=0.30)
    second = _candidate("SECOND", base_return=0.11, bull_return=0.22)
    portfolio = _portfolio((first, second), cash_weight=0.10)
    context = _opportunity_context(cash_weight=0.10)
    cycle = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    )

    result = cycle.run(
        identifier="cycle:scarce-cash",
        candidates=(second, first),
        opportunity_context=context,
        specialist_contexts=(_context(second), _context(first)),
        portfolio=portfolio,
    )

    assert [
        item.candidate.instrument.symbol
        for item in result.opportunity_queue.ranked
    ][0] == "FIRST"
    assert all(item.action is CIOAction.BUY for item in result.decisions)
    assert result.construction is not None
    assert result.construction.status is ConstructionStatus.PARTIAL
    weights = dict(result.construction.target_weights)
    assert weights["FIRST"] == pytest.approx(0.08)
    assert "SECOND" not in weights
    assert len(result.theses) == 1
    assert result.theses[0].asset == "FIRST"


def test_specialist_analyses_are_independent_and_complete(tmp_path) -> None:
    candidate = _candidate("QUAL")
    journal = SQLiteCIOJournal(tmp_path / "institutional.db")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:specialists",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
    )

    packet_event = next(
        item
        for item in journal.events()
        if item.event_type.value == "specialist_packet"
    )
    analyses = packet_event.payload["analyses"]
    assert len(analyses) == 5
    assert all(item["independent_first_pass"] for item in analyses)
    assert len({item["role"] for item in analyses}) == 5
    assert all(
        datetime.fromisoformat(item["completed_at"]) >= candidate.as_of
        for item in analyses
    )
    assert result.decisions


def test_daily_briefing_answers_five_questions_without_primary_score() -> None:
    candidate = _candidate("QUAL")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:briefing",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
    )

    payload = result.briefing.to_dict()
    assert "score" not in payload
    assert payload["what_changed"]
    assert payload["why_it_matters"]
    assert payload["opportunity_or_risk"]
    assert payload["portfolio_decision"]
    assert payload["confidence"] is not None
    assert payload["evidence_that_changes_conclusion"]
    markdown = result.briefing.to_markdown()
    assert "What changed?" in markdown
    assert "Why does it matter?" in markdown
    assert "Should the portfolio change?" in markdown


def test_cycle_rejects_candidate_weight_that_disagrees_with_portfolio() -> None:
    candidate = replace(_candidate("QUAL"), current_portfolio_weight=0.05)

    with pytest.raises(ValueError, match="current weight"):
        CanonicalCIOCycle(
            construction_policy=_construction_policy(),
        ).run(
            identifier="cycle:weight-mismatch",
            candidates=(candidate,),
            opportunity_context=_opportunity_context(),
            specialist_contexts=(_context(candidate),),
            portfolio=_portfolio((candidate,)),
        )


def test_cycle_requires_context_for_every_qualified_candidate() -> None:
    candidate = _candidate("QUAL")

    with pytest.raises(KeyError, match="missing specialist context"):
        CanonicalCIOCycle(
            construction_policy=_construction_policy(),
        ).run(
            identifier="cycle:missing-context",
            candidates=(candidate,),
            opportunity_context=_opportunity_context(),
            specialist_contexts=(),
            portfolio=_portfolio((candidate,)),
        )
