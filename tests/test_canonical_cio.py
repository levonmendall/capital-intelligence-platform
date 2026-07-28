"""Contract tests for the governing Capital Intelligence CIO domain."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CIOAction,
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
    UniverseDisposition,
)


AS_OF = datetime(2026, 7, 26, 14, tzinfo=timezone.utc)


def _instrument(
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY,
    symbol: str = "ACME",
    venue: str = "NASDAQ",
    country_code: str = "US",
    volume: float = 25_000_000,
    data_age_hours: float = 1.0,
    coverage: float = 0.95,
    treasury: bool = False,
    duration: float | None = None,
) -> CandidateInstrument:
    return CandidateInstrument(
        instrument_id=f"instrument:{symbol.lower()}",
        symbol=symbol,
        name=f"{symbol} Holdings",
        asset_class=asset_class,
        venue=venue,
        country_code=country_code,
        average_daily_dollar_volume=volume,
        data_age_hours=data_age_hours,
        analytical_coverage=coverage,
        security_master_snapshot_identifier="security-master:fixture:v1",
        security_master_record_identifiers=("security-master-record:fixture",),
        is_us_treasury=treasury,
        effective_duration_years=duration,
    )


def _candidate(
    *,
    instrument: CandidateInstrument | None = None,
    base_return: float = 0.12,
    bull_return: float = 0.30,
    bear_return: float = -0.15,
    opportunity_cost: float = 0.04,
    current_weight: float = 0.0,
    evidence: EvidenceQuality | None = None,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:acme:2026-07-26",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=instrument or _instrument(),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=base_return,
        bull_case_return=bull_return,
        bear_case_return=bear_return,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=118.0,
        expected_upside=0.30,
        expected_downside=-0.15,
        probability_of_success=0.68,
        primary_catalysts=("Earnings revisions improved materially",),
        key_risks=("Demand could slow",),
        critical_assumptions=("Margins remain above 20%",),
        invalidation_conditions=("Forward estimates fall by more than 10%",),
        supporting_evidence=("Filed revenue and cash flow accelerated",),
        contradictory_evidence=("Industry inventories remain elevated",),
        evidence_quality=evidence
        or EvidenceQuality(
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
        opportunity_cost_return=opportunity_cost,
        expected_portfolio_contribution=0.012,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.10,
        monitoring_indicators=("Forward earnings revisions",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=("sec-filing:acme:q2", "market:acme:close"),
        model_versions=("fundamental.v1", "valuation.v1"),
    )


def _analysis(
    role: SpecialistRole,
    *,
    candidate_identifier: str = "candidate:acme:2026-07-26",
    position: SpecialistPosition = SpecialistPosition.SUPPORTIVE,
    confidence: float = 0.80,
    vetoes: tuple[str, ...] = (),
    blocks: tuple[str, ...] = (),
    weight: float | None = None,
    funding: str | None = None,
    return_impact: float = 0.02,
) -> SpecialistAnalysis:
    return SpecialistAnalysis(
        candidate_identifier=candidate_identifier,
        role=role,
        completed_at=AS_OF + timedelta(minutes=role.value.__len__()),
        independent_first_pass=True,
        position=position,
        conclusion=f"{role.value} conclusion",
        expected_return_impact=return_impact,
        confidence=confidence,
        supporting_evidence=(f"{role.value} supporting evidence",),
        contradictory_evidence=(),
        critical_assumptions=(f"{role.value} assumption",),
        risks=(f"{role.value} risk",),
        limitations=(),
        change_conditions=(f"new {role.value} evidence",),
        veto_reasons=vetoes,
        implementation_blocks=blocks,
        recommended_position_weight=weight,
        funding_source=funding,
    )


def _packet(
    *,
    evidence_vetoes: tuple[str, ...] = (),
    implementation_blocks: tuple[str, ...] = (),
    opposed_role: SpecialistRole | None = None,
    opposed_confidence: float = 0.80,
    weight: float | None = 0.06,
    return_impact: float = 0.02,
) -> IndependentSpecialistPacket:
    analyses = []
    for role in SpecialistRole:
        position = (
            SpecialistPosition.OPPOSED
            if role is opposed_role
            else SpecialistPosition.SUPPORTIVE
        )
        analyses.append(
            _analysis(
                role,
                position=position,
                confidence=(opposed_confidence if role is opposed_role else 0.82),
                vetoes=(
                    evidence_vetoes
                    if role is SpecialistRole.EVIDENCE_GOVERNANCE
                    else ()
                ),
                blocks=(
                    implementation_blocks
                    if role is SpecialistRole.PORTFOLIO_RISK
                    else ()
                ),
                weight=(weight if role is SpecialistRole.PORTFOLIO_RISK else None),
                funding=(
                    "cash above minimum reserve"
                    if role is SpecialistRole.PORTFOLIO_RISK and weight is not None
                    else None
                ),
                return_impact=return_impact,
            )
        )
    return IndependentSpecialistPacket(
        candidate_identifier="candidate:acme:2026-07-26",
        analyses=tuple(analyses),
    )


def test_candidate_calculates_probability_weighted_and_net_return() -> None:
    candidate = _candidate()

    assert candidate.probability_weighted_expected_return == pytest.approx(0.111)
    assert candidate.implementation_cost_return == pytest.approx(0.001)
    assert candidate.net_expected_return == pytest.approx(0.11)
    assert candidate.opportunity_edge == pytest.approx(0.07)


def test_scenario_probabilities_must_sum_to_one() -> None:
    candidate = _candidate()

    with pytest.raises(ValueError, match="sum to 1.0"):
        replace(candidate, base_case_probability=0.40)


def test_version_one_universe_allows_liquid_us_equity_and_etf() -> None:
    policy = RecommendationUniversePolicy()

    equity = policy.evaluate(_instrument())
    etf = policy.evaluate(
        _instrument(
            asset_class=CandidateAssetClass.US_ETF,
            symbol="SPY",
            venue="NYSEARCA",
        )
    )

    assert equity.direct_recommendation_allowed
    assert etf.direct_recommendation_allowed


def test_version_one_universe_keeps_crypto_and_international_equity_as_evidence() -> None:
    policy = RecommendationUniversePolicy()

    crypto = policy.evaluate(
        _instrument(
            asset_class=CandidateAssetClass.CRYPTO,
            symbol="BTC",
            venue="COINBASE",
        )
    )
    international = policy.evaluate(
        _instrument(
            asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
            symbol="7203",
            venue="TSE",
            country_code="JP",
        )
    )

    assert crypto.disposition is UniverseDisposition.INTELLIGENCE_ONLY
    assert international.disposition is UniverseDisposition.INTELLIGENCE_ONLY
    assert "intelligence-only" in crypto.reasons[0]


def test_short_us_treasury_equivalent_is_eligible_but_long_duration_is_not() -> None:
    policy = RecommendationUniversePolicy()

    short = policy.evaluate(
        _instrument(
            asset_class=CandidateAssetClass.CASH_EQUIVALENT,
            symbol="BIL",
            venue="NYSEARCA",
            treasury=True,
            duration=0.25,
        )
    )
    long = policy.evaluate(
        _instrument(
            asset_class=CandidateAssetClass.CASH_EQUIVALENT,
            symbol="TLT",
            venue="NASDAQ",
            treasury=True,
            duration=16.0,
        )
    )

    assert short.direct_recommendation_allowed
    assert long.disposition is UniverseDisposition.INTELLIGENCE_ONLY


def test_universe_blocks_stale_illiquid_or_undercovered_direct_candidates() -> None:
    policy = RecommendationUniversePolicy()
    assessment = policy.evaluate(
        _instrument(volume=10_000, data_age_hours=72, coverage=0.40)
    )

    assert assessment.disposition is UniverseDisposition.INELIGIBLE
    assert len(assessment.reasons) == 3


def test_specialist_packet_requires_exactly_five_independent_roles() -> None:
    analyses = tuple(_analysis(role) for role in list(SpecialistRole)[:-1])

    with pytest.raises(ValueError, match="exactly the five"):
        IndependentSpecialistPacket(
            candidate_identifier="candidate:acme:2026-07-26",
            analyses=analyses,
        )


def test_only_evidence_officer_can_veto() -> None:
    with pytest.raises(ValueError, match="only the Evidence"):
        _analysis(
            SpecialistRole.MARKET,
            vetoes=("source cannot be reproduced",),
        )


def test_only_portfolio_manager_can_size_or_block_implementation() -> None:
    with pytest.raises(ValueError, match="only the Portfolio"):
        _analysis(
            SpecialistRole.MARKET,
            blocks=("position limit",),
        )
    with pytest.raises(ValueError, match="only the Portfolio"):
        _analysis(
            SpecialistRole.MACRO_ECONOMIC,
            weight=0.05,
        )


def test_cio_buys_qualified_superior_opportunity() -> None:
    candidate = _candidate()
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.06),
    )

    assert decision.action is CIOAction.BUY
    assert decision.recommended_position_weight == pytest.approx(0.06)
    assert decision.funding_source == "cash above minimum reserve"
    assert decision.final_confidence <= candidate.evidence_quality.ceiling


def test_supportive_votes_cannot_override_low_expected_return() -> None:
    candidate = _candidate(
        base_return=0.01,
        bull_return=0.04,
        bear_return=-0.10,
        opportunity_cost=0.04,
    )
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(),
    )

    assert _packet().support_ratio == 1.0
    assert decision.action is CIOAction.NO_SUPERIOR_OPPORTUNITY
    assert decision.recommended_position_weight is None


def test_evidence_veto_forces_insufficient_evidence() -> None:
    candidate = _candidate()
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(evidence_vetoes=("filing timestamp cannot be reproduced",)),
    )

    assert decision.action is CIOAction.INSUFFICIENT_EVIDENCE
    assert decision.evidence_vetoes == (
        "filing timestamp cannot be reproduced",
    )
    assert decision.final_confidence <= 0.25


def test_evidence_veto_reduces_an_existing_holding_instead_of_preserving_risk() -> None:
    candidate = _candidate(current_weight=0.08)
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(
            evidence_vetoes=("filing timestamp cannot be reproduced",),
            weight=0.08,
        ),
    )

    assert decision.action is CIOAction.REDUCE
    assert decision.recommended_position_weight == pytest.approx(0.04)


def test_positive_holding_is_reduced_when_a_superior_alternative_exists() -> None:
    candidate = _candidate(
        current_weight=0.08,
        base_return=0.08,
        bull_return=0.14,
        bear_return=0.01,
        opportunity_cost=0.12,
    )
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.08),
    )

    assert candidate.net_expected_return > 0.0
    assert decision.action in {CIOAction.REDUCE, CIOAction.EXIT}


def test_adverse_specialist_reconciliation_can_block_preliminary_maximum_size() -> None:
    candidate = _candidate()
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.10, return_impact=-0.06),
    )

    assert decision.return_reconciliation.expected_return < candidate.net_expected_return
    assert decision.action is not CIOAction.BUY
    assert decision.recommended_position_weight is None


def test_portfolio_block_produces_watch_without_position_size() -> None:
    candidate = _candidate()
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(
            implementation_blocks=("sector concentration limit would be breached",)
        ),
    )

    assert decision.action is CIOAction.WATCH
    assert decision.recommended_position_weight is None
    assert decision.implementation_blocks


def test_high_confidence_dissent_is_preserved_and_prevents_action() -> None:
    candidate = _candidate()
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(
            opposed_role=SpecialistRole.FUNDAMENTAL_VALUATION,
            opposed_confidence=0.90,
        ),
    )

    assert decision.action is CIOAction.WATCH
    assert decision.dissent is not None
    assert (
        decision.dissent.opposing_role
        is SpecialistRole.FUNDAMENTAL_VALUATION
    )
    assert decision.final_confidence <= 0.75


def test_intelligence_only_asset_cannot_receive_direct_action() -> None:
    instrument = _instrument(
        asset_class=CandidateAssetClass.CRYPTO,
        symbol="BTC",
        venue="COINBASE",
    )
    candidate = _candidate(instrument=instrument)
    universe = RecommendationUniversePolicy().evaluate(instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(),
    )

    assert decision.action is CIOAction.INSUFFICIENT_EVIDENCE
    assert decision.recommended_position_weight is None


def test_existing_holding_can_be_increased_reduced_or_exited() -> None:
    cio = ChiefInvestmentOfficer()

    increase_candidate = _candidate(current_weight=0.03)
    increase = cio.synthesize(
        increase_candidate,
        RecommendationUniversePolicy().evaluate(increase_candidate.instrument),
        _packet(weight=0.07),
    )
    assert increase.action is CIOAction.INCREASE
    assert increase.recommended_position_weight == pytest.approx(0.07)

    reduce_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.01,
        bull_return=0.04,
        bear_return=-0.08,
    )
    reduce = cio.synthesize(
        reduce_candidate,
        RecommendationUniversePolicy().evaluate(reduce_candidate.instrument),
        _packet(weight=0.04),
    )
    assert reduce.action is CIOAction.REDUCE
    assert reduce.recommended_position_weight == pytest.approx(0.04)

    exit_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.08,
        bull_return=-0.02,
        bear_return=-0.25,
    )
    exit_decision = cio.synthesize(
        exit_candidate,
        RecommendationUniversePolicy().evaluate(exit_candidate.instrument),
        _packet(weight=0.0),
    )
    assert exit_decision.action is CIOAction.EXIT
    assert exit_decision.recommended_position_weight == pytest.approx(0.0)


def test_low_evidence_quality_forces_abstention() -> None:
    candidate = _candidate(
        evidence=EvidenceQuality(
            reliability=0.95,
            freshness=0.95,
            relevance=0.95,
            independence=0.20,
            completeness=0.90,
            point_in_time_integrity=1.0,
        )
    )
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(),
    )

    assert decision.action is CIOAction.INSUFFICIENT_EVIDENCE
    assert decision.final_confidence <= 0.20
