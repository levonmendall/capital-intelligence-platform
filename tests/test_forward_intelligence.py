from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cio.models import SpecialistAnalysis, SpecialistPosition, SpecialistRole
from intelligence.forward import (
    AssetPolicySensitivity,
    CurrencyExposure,
    CurrencyObservation,
    CurrencyRegime,
    CurrencyTransmissionEngine,
    MarketTrendEngine,
    MarketTrendObservation,
    MonetaryPolicyObservation,
    MonetaryPolicyTransmissionEngine,
    PolicyMotive,
    PolicyRegime,
    StrategicBusinessEngine,
    StrategicBusinessObservation,
    StructuralThemeEngine,
    StructuralThemeObservation,
    ThemeLink,
    ThemeNodeObservation,
    ThemeStage,
    TrendStage,
    build_forward_intelligence_bundle,
)

AS_OF = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _node(
    name: str,
    *,
    demand: float,
    capacity: float,
    utilization: float,
    lead_time: float,
    pricing: float,
    concentration: float,
    substitution: float,
    symbols: tuple[str, ...],
) -> ThemeNodeObservation:
    return ThemeNodeObservation(
        name=name,
        demand_growth=demand,
        capacity_growth=capacity,
        utilization=utilization,
        lead_time_pressure=lead_time,
        pricing_power=pricing,
        supplier_concentration=concentration,
        substitution_risk=substitution,
        beneficiary_symbols=symbols,
        evidence_identifiers=(f"evidence:theme:{name.lower().replace(' ', '-')}",),
    )


def test_ai_value_chain_identifies_memory_as_next_bottleneck() -> None:
    observation = StructuralThemeObservation(
        identifier="theme:ai-infrastructure",
        name="AI infrastructure",
        as_of=AS_OF,
        demand_origin="AI applications",
        candidate_node="High bandwidth memory",
        nodes=(
            _node(
                "AI applications",
                demand=0.85,
                capacity=0.60,
                utilization=0.70,
                lead_time=0.20,
                pricing=0.30,
                concentration=0.20,
                substitution=0.10,
                symbols=(),
            ),
            _node(
                "Accelerators",
                demand=0.80,
                capacity=0.50,
                utilization=0.90,
                lead_time=0.65,
                pricing=0.60,
                concentration=0.75,
                substitution=0.25,
                symbols=("GPU",),
            ),
            _node(
                "High bandwidth memory",
                demand=0.90,
                capacity=0.25,
                utilization=0.98,
                lead_time=0.90,
                pricing=0.85,
                concentration=0.85,
                substitution=0.10,
                symbols=("MEM1", "MEM2"),
            ),
            _node(
                "Power and cooling",
                demand=0.65,
                capacity=0.35,
                utilization=0.80,
                lead_time=0.55,
                pricing=0.50,
                concentration=0.40,
                substitution=0.20,
                symbols=("PWR",),
            ),
        ),
        links=(
            ThemeLink("AI applications", "Accelerators", 0.95, 30),
            ThemeLink("Accelerators", "High bandwidth memory", 0.95, 60),
            ThemeLink("High bandwidth memory", "Power and cooling", 0.70, 120),
        ),
        theme_demand_growth=0.85,
        market_pricing_score=0.35,
        evidence=(
            "Hyperscaler capital spending, accelerator orders, memory content, capacity, lead times, and pricing were measured point in time",
        ),
    )

    result = StructuralThemeEngine().analyze(observation)

    assert result.stage is ThemeStage.SUPPLY_CONSTRAINED
    assert result.bottlenecks[0][0] == "High bandwidth memory"
    assert result.next_beneficiaries[:2] == ("MEM1", "MEM2")
    assert result.signal.expected_return_impact > 0.0
    assert {item.label for item in result.scenarios} == {"bull", "base", "bear"}


def test_theme_already_priced_reduces_candidate_edge() -> None:
    base = StructuralThemeObservation(
        identifier="theme:memory",
        name="Memory demand",
        as_of=AS_OF,
        demand_origin="AI demand",
        candidate_node="Memory",
        nodes=(
            _node(
                "AI demand",
                demand=0.80,
                capacity=0.50,
                utilization=0.80,
                lead_time=0.30,
                pricing=0.30,
                concentration=0.20,
                substitution=0.10,
                symbols=(),
            ),
            _node(
                "Memory",
                demand=0.90,
                capacity=0.30,
                utilization=0.95,
                lead_time=0.80,
                pricing=0.80,
                concentration=0.80,
                substitution=0.10,
                symbols=("MEM",),
            ),
        ),
        links=(ThemeLink("AI demand", "Memory", 0.95, 60),),
        theme_demand_growth=0.80,
        market_pricing_score=0.10,
        evidence=("Point-in-time value-chain evidence",),
    )
    expensive = StructuralThemeObservation(
        identifier="theme:memory-priced",
        name=base.name,
        as_of=base.as_of,
        demand_origin=base.demand_origin,
        candidate_node=base.candidate_node,
        nodes=base.nodes,
        links=base.links,
        theme_demand_growth=base.theme_demand_growth,
        market_pricing_score=0.95,
        evidence=base.evidence,
    )

    early = StructuralThemeEngine().analyze(base)
    priced = StructuralThemeEngine().analyze(expensive)

    assert priced.signal.expected_return_impact < early.signal.expected_return_impact
    assert priced.stage is ThemeStage.CROWDED


def test_qe_is_conditional_not_an_automatic_risk_on_rule() -> None:
    sensitivity = AssetPolicySensitivity(
        liquidity=0.90,
        duration=0.40,
        credit=0.70,
        inflation=-0.30,
        growth=0.80,
    )
    stable = MonetaryPolicyObservation(
        identifier="policy:stable-qe",
        as_of=AS_OF,
        regime=PolicyRegime.ACCELERATING_QE,
        motive=PolicyMotive.STABLE_DISINFLATION,
        inflation_trend=-0.50,
        growth_trend=0.25,
        financial_stress=0.10,
        liquidity_impulse=0.80,
        real_yield_change=-0.40,
        credit_spread_change=-0.30,
        market_pricing_score=0.30,
        evidence=("Balance sheet, reserves, real yields, spreads, inflation, and growth",),
        evidence_identifiers=("evidence:policy:stable-qe",),
    )
    crisis = MonetaryPolicyObservation(
        identifier="policy:crisis-qe",
        as_of=AS_OF,
        regime=PolicyRegime.EMERGENCY_EASING,
        motive=PolicyMotive.FINANCIAL_CRISIS,
        inflation_trend=-0.20,
        growth_trend=-0.80,
        financial_stress=0.95,
        liquidity_impulse=0.80,
        real_yield_change=-0.40,
        credit_spread_change=0.90,
        market_pricing_score=0.20,
        evidence=("Emergency facilities, recession, spreads, and funding stress",),
        evidence_identifiers=("evidence:policy:crisis-qe",),
    )

    engine = MonetaryPolicyTransmissionEngine()
    stable_result = engine.analyze(stable, sensitivity)
    crisis_result = engine.analyze(crisis, sensitivity)

    assert stable_result.signal.expected_return_impact > 0.0
    assert crisis_result.signal.expected_return_impact < stable_result.signal.expected_return_impact
    assert any("Emergency easing" in risk for risk in crisis_result.signal.risks)


def test_peak_rate_duration_case_requires_disinflation_and_falling_real_yields() -> None:
    duration = AssetPolicySensitivity(
        liquidity=0.20,
        duration=1.0,
        credit=0.10,
        inflation=-0.70,
        growth=-0.20,
    )
    disinflation = MonetaryPolicyObservation(
        identifier="policy:peak-disinflation",
        as_of=AS_OF,
        regime=PolicyRegime.RATE_CUTTING,
        motive=PolicyMotive.STABLE_DISINFLATION,
        inflation_trend=-0.70,
        growth_trend=-0.20,
        financial_stress=0.20,
        liquidity_impulse=0.30,
        real_yield_change=-0.80,
        credit_spread_change=0.10,
        market_pricing_score=0.30,
        evidence=("Disinflation and declining real yields",),
        evidence_identifiers=("evidence:duration:good",),
    )
    inflation = MonetaryPolicyObservation(
        identifier="policy:peak-inflation",
        as_of=AS_OF,
        regime=PolicyRegime.RESTRICTIVE_HOLD,
        motive=PolicyMotive.INFLATION_CONTROL,
        inflation_trend=0.80,
        growth_trend=0.10,
        financial_stress=0.10,
        liquidity_impulse=-0.20,
        real_yield_change=0.60,
        credit_spread_change=0.00,
        market_pricing_score=0.30,
        evidence=("Inflation reacceleration and rising term premium",),
        evidence_identifiers=("evidence:duration:bad",),
    )

    engine = MonetaryPolicyTransmissionEngine()
    favorable = engine.analyze(disinflation, duration)
    unfavorable = engine.analyze(inflation, duration)

    assert favorable.signal.expected_return_impact > 0.0
    assert unfavorable.signal.expected_return_impact < favorable.signal.expected_return_impact


def test_strong_dollar_has_asset_specific_not_blanket_effects() -> None:
    observation = CurrencyObservation(
        identifier="currency:strong-dollar",
        as_of=AS_OF,
        base_currency="EUR",
        reporting_currency="USD",
        dollar_strength=0.80,
        real_yield_differential=0.50,
        dollar_funding_stress=0.60,
        fx_volatility=0.40,
        commodity_dollar_beta=-0.70,
        market_pricing_score=0.25,
        evidence=("Broad dollar, real yields, funding spreads, and FX volatility",),
        evidence_identifiers=("evidence:currency:usd",),
    )
    unhedged_foreign_asset = CurrencyExposure(
        unhedged_foreign_asset_share=0.90,
        foreign_revenue_share=0.10,
        usd_revenue_share=0.00,
        local_cost_share=0.50,
        usd_debt_share=0.50,
        commodity_input_share=0.00,
        commodity_revenue_share=0.00,
        emerging_market_funding_sensitivity=0.50,
        hedge_ratio=0.00,
    )
    exporter = CurrencyExposure(
        unhedged_foreign_asset_share=0.00,
        foreign_revenue_share=0.00,
        usd_revenue_share=0.90,
        local_cost_share=0.90,
        usd_debt_share=0.00,
        commodity_input_share=0.00,
        commodity_revenue_share=0.00,
        emerging_market_funding_sensitivity=0.00,
        hedge_ratio=0.00,
    )
    hedged = CurrencyExposure(
        unhedged_foreign_asset_share=0.90,
        foreign_revenue_share=0.10,
        usd_revenue_share=0.00,
        local_cost_share=0.50,
        usd_debt_share=0.00,
        commodity_input_share=0.00,
        commodity_revenue_share=0.00,
        emerging_market_funding_sensitivity=0.00,
        hedge_ratio=1.00,
    )

    engine = CurrencyTransmissionEngine()
    foreign = engine.analyze(observation, unhedged_foreign_asset)
    export = engine.analyze(observation, exporter)
    protected = engine.analyze(observation, hedged)

    assert foreign.regime is CurrencyRegime.STRONG_DOLLAR
    assert foreign.signal.expected_return_impact < 0.0
    assert export.signal.expected_return_impact > foreign.signal.expected_return_impact
    assert protected.signal.expected_return_impact > foreign.signal.expected_return_impact


def test_broad_earnings_supported_trend_beats_narrow_crowded_rally() -> None:
    broad = MarketTrendObservation(
        identifier="trend:broad",
        as_of=AS_OF,
        absolute_trend=0.80,
        relative_trend=0.70,
        breadth=0.75,
        earnings_revision_breadth=0.70,
        volume_confirmation=0.65,
        leadership_concentration=0.25,
        crowding=0.30,
        valuation_expansion_share=0.25,
        reversal_signal=0.10,
        evidence=("Broad price, volume, and earnings-revision confirmation",),
        evidence_identifiers=("evidence:trend:broad",),
    )
    narrow = MarketTrendObservation(
        identifier="trend:narrow",
        as_of=AS_OF,
        absolute_trend=0.90,
        relative_trend=0.85,
        breadth=0.10,
        earnings_revision_breadth=0.05,
        volume_confirmation=0.20,
        leadership_concentration=0.95,
        crowding=0.90,
        valuation_expansion_share=0.90,
        reversal_signal=0.25,
        evidence=("Narrow price leadership without broad earnings confirmation",),
        evidence_identifiers=("evidence:trend:narrow",),
    )

    engine = MarketTrendEngine()
    broad_result = engine.analyze(broad)
    narrow_result = engine.analyze(narrow)

    assert broad_result.stage in {TrendStage.BROADENING, TrendStage.CONFIRMED}
    assert narrow_result.stage is TrendStage.CROWDED
    assert broad_result.signal.expected_return_impact > narrow_result.signal.expected_return_impact


def test_business_analysis_translates_exposure_and_already_priced_value() -> None:
    observation = StrategicBusinessObservation(
        identifier="business:memory",
        as_of=AS_OF,
        revenue_exposure=0.70,
        demand_growth=0.80,
        pricing_power=0.70,
        capacity_adequacy=0.50,
        incremental_margin=0.80,
        market_share_trend=0.40,
        capital_allocation_quality=0.60,
        customer_concentration=0.30,
        supplier_concentration=0.20,
        valuation_priced_in=0.20,
        evidence=("Segment revenue, orders, capacity, pricing, margins, share, and valuation",),
        risks=("Customer spending or capacity assumptions can change",),
        evidence_identifiers=("evidence:business:memory",),
    )
    priced = StrategicBusinessObservation(
        identifier="business:memory-priced",
        as_of=observation.as_of,
        revenue_exposure=observation.revenue_exposure,
        demand_growth=observation.demand_growth,
        pricing_power=observation.pricing_power,
        capacity_adequacy=observation.capacity_adequacy,
        incremental_margin=observation.incremental_margin,
        market_share_trend=observation.market_share_trend,
        capital_allocation_quality=observation.capital_allocation_quality,
        customer_concentration=observation.customer_concentration,
        supplier_concentration=observation.supplier_concentration,
        valuation_priced_in=0.95,
        evidence=observation.evidence,
        risks=observation.risks,
        evidence_identifiers=("evidence:business:memory-priced",),
    )

    engine = StrategicBusinessEngine()
    attractive = engine.analyze(observation)
    expensive = engine.analyze(priced)

    assert attractive.expected_return_impact > 0.0
    assert expensive.expected_return_impact < attractive.expected_return_impact


def test_bundle_enriches_existing_six_specialist_analysis_without_new_authority() -> None:
    business = StrategicBusinessEngine().analyze(
        StrategicBusinessObservation(
            identifier="business:test",
            as_of=AS_OF,
            revenue_exposure=0.60,
            demand_growth=0.60,
            pricing_power=0.50,
            capacity_adequacy=0.40,
            incremental_margin=0.60,
            market_share_trend=0.30,
            capital_allocation_quality=0.50,
            customer_concentration=0.20,
            supplier_concentration=0.20,
            valuation_priced_in=0.20,
            evidence=("Business evidence",),
            risks=("Business risk",),
            evidence_identifiers=("evidence:shared-forward",),
        )
    )
    bundle = build_forward_intelligence_bundle(
        identifier="forward:candidate:test",
        candidate_identifier="candidate:test",
        as_of=AS_OF,
        business=business,
    )
    base = SpecialistAnalysis(
        candidate_identifier="candidate:test",
        role=SpecialistRole.FUNDAMENTAL_VALUATION,
        completed_at=AS_OF,
        independent_first_pass=True,
        position=SpecialistPosition.NEUTRAL,
        conclusion="Base fundamental analysis",
        expected_return_impact=0.0,
        confidence=0.70,
        supporting_evidence=("Base evidence",),
        contradictory_evidence=(),
        critical_assumptions=("Base assumption",),
        risks=("Base risk",),
        limitations=(),
        change_conditions=("Base review",),
        evidence_origin_identifiers=("evidence:base",),
    )

    enriched = bundle.enrich_analysis(base)

    assert enriched.role is SpecialistRole.FUNDAMENTAL_VALUATION
    assert enriched.expected_return_impact > base.expected_return_impact
    assert "evidence:shared-forward" in enriched.evidence_origin_identifiers
    assert enriched.position is SpecialistPosition.SUPPORTIVE
