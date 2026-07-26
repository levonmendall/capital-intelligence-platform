"""Tests for formal pre-committee opportunity qualification and ranking."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
    QualificationOutcome,
)


AS_OF = datetime(2026, 7, 26, 15, tzinfo=timezone.utc)


def _instrument(
    symbol: str,
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY,
    venue: str = "NASDAQ",
    volume: float = 50_000_000,
    age: float = 1.0,
    coverage: float = 0.95,
) -> CandidateInstrument:
    return CandidateInstrument(
        instrument_id=f"instrument:{symbol.lower()}",
        symbol=symbol,
        name=f"{symbol} Corporation",
        asset_class=asset_class,
        venue=venue,
        country_code="US",
        average_daily_dollar_volume=volume,
        data_age_hours=age,
        analytical_coverage=coverage,
    )


def _candidate(
    symbol: str,
    *,
    base: float = 0.12,
    bull: float = 0.30,
    bear: float = -0.15,
    probability: float = 0.68,
    opportunity_cost: float = 0.04,
    evidence_score: float = 0.92,
    liquidity: float = 0.95,
    transaction_bps: float = 5.0,
    slippage_bps: float = 5.0,
    contribution: float = 0.012,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY,
) -> CandidateDecisionRecord:
    evidence = EvidenceQuality(
        reliability=evidence_score,
        freshness=evidence_score,
        relevance=evidence_score,
        independence=evidence_score,
        completeness=evidence_score,
        point_in_time_integrity=evidence_score,
    )
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}:2026-07-26",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=_instrument(
            symbol,
            asset_class=asset_class,
            venue=("COINBASE" if asset_class is CandidateAssetClass.CRYPTO else "NASDAQ"),
        ),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=base,
        bull_case_return=bull,
        bear_case_return=bear,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=120.0,
        expected_upside=bull,
        expected_downside=bear,
        probability_of_success=probability,
        primary_catalysts=("Forward estimates improved",),
        key_risks=("Demand could weaken",),
        critical_assumptions=("Margins remain resilient",),
        invalidation_conditions=("Forward estimates fall 10%",),
        supporting_evidence=("Cash flow accelerated",),
        contradictory_evidence=("Inventory remains elevated",),
        evidence_quality=evidence,
        liquidity_score=liquidity,
        transaction_cost_bps=transaction_bps,
        slippage_bps=slippage_bps,
        opportunity_cost_return=opportunity_cost,
        expected_portfolio_contribution=contribution,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("Estimate revisions",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(f"filing:{symbol.lower()}",),
        model_versions=("company-quality.v1",),
    )


def _context(
    *,
    cash_return: float = 0.04,
    holding_return: float | None = None,
) -> OpportunitySetContext:
    alternatives = [
        AlternativeUse(
            identifier="cash:treasury-bills",
            kind=AlternativeKind.CASH,
            expected_return=cash_return,
            implementation_cost_return=0.0,
            evidence_quality=1.0,
            liquidity_score=1.0,
            current_weight=(1.0 if holding_return is None else 0.20),
        )
    ]
    if holding_return is not None:
        alternatives.append(
            AlternativeUse(
                identifier="holding:spy",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=holding_return,
                implementation_cost_return=0.001,
                evidence_quality=0.95,
                liquidity_score=1.0,
                current_weight=0.80,
            )
        )
    return OpportunitySetContext(
        identifier="opportunity-set:2026-07-26",
        as_of=AS_OF,
        alternatives=tuple(alternatives),
    )


def test_qualified_candidate_reaches_committee_queue() -> None:
    queue = OpportunityEngine().build_queue(
        (_candidate("ACME"),),
        _context(),
    )

    assert queue.has_qualified_opportunity
    assert queue.top is not None
    assert queue.top.candidate.instrument.symbol == "ACME"
    assert queue.top.qualification.outcome is QualificationOutcome.QUALIFIED
    assert not queue.rejected


def test_unsupported_asset_never_reaches_committee() -> None:
    queue = OpportunityEngine().build_queue(
        (_candidate("BTC", asset_class=CandidateAssetClass.CRYPTO),),
        _context(),
    )

    assert not queue.ranked
    assert queue.rejected[0].outcome is QualificationOutcome.REJECTED
    assert any("intelligence-only" in reason for reason in queue.rejected[0].reasons)


def test_weak_stale_illiquid_or_incomplete_candidate_is_rejected() -> None:
    candidate = _candidate(
        "WEAK",
        base=0.01,
        bull=0.04,
        bear=-0.40,
        probability=0.40,
        evidence_score=0.45,
        liquidity=0.30,
        contribution=-0.01,
    )
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            average_daily_dollar_volume=100_000,
            data_age_hours=72,
            analytical_coverage=0.40,
        ),
    )

    queue = OpportunityEngine().build_queue((candidate,), _context())

    assert not queue.ranked
    reasons = queue.rejected[0].reasons
    assert len(reasons) >= 7
    assert any("expected return" in reason for reason in reasons)
    assert any("evidence" in reason for reason in reasons)
    assert any("liquidity" in reason for reason in reasons)


def test_context_recalculates_opportunity_cost_against_current_holding() -> None:
    context = _context(holding_return=0.08)
    candidate = _candidate("ACME", opportunity_cost=0.079)

    qualification = OpportunityEngine().qualify(candidate, context)

    assert qualification.effective_opportunity_cost == pytest.approx(0.079)
    assert qualification.opportunity_edge == pytest.approx(
        candidate.net_expected_return - 0.079
    )
    assert qualification.qualified


def test_stale_recorded_opportunity_cost_is_rejected() -> None:
    context = _context(holding_return=0.08)
    candidate = _candidate("ACME", opportunity_cost=0.04)

    qualification = OpportunityEngine().qualify(candidate, context)

    assert not qualification.qualified
    assert any(
        "does not match the point-in-time opportunity set" in reason
        for reason in qualification.reasons
    )


def test_ranker_prefers_stronger_total_capital_allocation_quality() -> None:
    high_narrative_return = _candidate(
        "FAST",
        base=0.16,
        bull=0.34,
        bear=-0.28,
        probability=0.60,
        evidence_score=0.72,
        liquidity=0.72,
        transaction_bps=35,
        slippage_bps=35,
        contribution=0.008,
    )
    institutional_quality = _candidate(
        "QUALITY",
        base=0.13,
        bull=0.28,
        bear=-0.10,
        probability=0.75,
        evidence_score=0.98,
        liquidity=0.99,
        transaction_bps=2,
        slippage_bps=2,
        contribution=0.018,
    )

    queue = OpportunityEngine().build_queue(
        (high_narrative_return, institutional_quality),
        _context(),
    )

    assert [item.candidate.instrument.symbol for item in queue.ranked] == [
        "QUALITY",
        "FAST",
    ]
    assert queue.ranked[0].score > queue.ranked[1].score


def test_ranking_is_fully_disclosed_and_reconciles_to_score() -> None:
    ranked = OpportunityEngine().build_queue(
        (_candidate("ACME"),),
        _context(),
    ).ranked[0]

    assert len(ranked.components) == 10
    assert sum(component.weight for component in ranked.components) == pytest.approx(1.0)
    assert sum(
        component.contribution for component in ranked.components
    ) == pytest.approx(ranked.score)
    assert {component.name for component in ranked.components} == {
        "net_expected_return",
        "probability_of_success",
        "downside_protection",
        "evidence_quality",
        "evidence_freshness",
        "evidence_independence",
        "liquidity",
        "opportunity_edge",
        "portfolio_contribution",
        "cost_efficiency",
    }


def test_empty_candidate_set_produces_explicit_empty_queue() -> None:
    queue = OpportunityEngine().build_queue((), _context())

    assert not queue.has_qualified_opportunity
    assert queue.top is None
    assert queue.ranked == ()
    assert queue.rejected == ()


def test_candidate_ids_and_instruments_must_be_unique() -> None:
    candidate = _candidate("ACME")

    with pytest.raises(ValueError, match="candidate identifiers"):
        OpportunityEngine().build_queue((candidate, candidate), _context())

    duplicate_instrument = replace(
        candidate,
        identifier="candidate:other:2026-07-26",
    )
    with pytest.raises(ValueError, match="duplicate instrument"):
        OpportunityEngine().build_queue(
            (candidate, duplicate_instrument),
            _context(),
        )


def test_candidate_and_opportunity_set_must_share_decision_time() -> None:
    candidate = _candidate("ACME")
    context = replace(
        _context(),
        as_of=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="share"):
        OpportunityEngine().build_queue((candidate,), context)