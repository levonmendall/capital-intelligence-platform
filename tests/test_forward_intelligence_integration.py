from __future__ import annotations

from dataclasses import replace

from application.production_context import _candidate_from_dict, _candidate_to_dict
from committee.specialists import (
    CandidateSpecialistContext,
    IndependentSpecialistService,
    PortfolioSpecialistContext,
)
from cio import SpecialistRole
from intelligence.forward import (
    MarketTrendEngine,
    MarketTrendObservation,
    StrategicBusinessEngine,
    StrategicBusinessObservation,
    build_forward_intelligence_bundle,
)
from tests.test_canonical_cio_cycle import _candidate, _context
from tests.test_canonical_production_context_adapter import _candidate_evidence


def _bundle(candidate, *, as_of=None):
    point_in_time = candidate.as_of if as_of is None else as_of
    business = StrategicBusinessEngine().analyze(
        StrategicBusinessObservation(
            identifier="business:integration",
            as_of=point_in_time,
            revenue_exposure=0.70,
            demand_growth=0.70,
            pricing_power=0.50,
            capacity_adequacy=0.40,
            incremental_margin=0.60,
            market_share_trend=0.30,
            capital_allocation_quality=0.50,
            customer_concentration=0.20,
            supplier_concentration=0.20,
            valuation_priced_in=0.20,
            evidence=("Segment demand and business economics",),
            risks=("Demand and pricing can change",),
            evidence_identifiers=("evidence:forward:business",),
        )
    )
    trend = MarketTrendEngine().analyze(
        MarketTrendObservation(
            identifier="trend:integration",
            as_of=point_in_time,
            absolute_trend=0.70,
            relative_trend=0.60,
            breadth=0.70,
            earnings_revision_breadth=0.60,
            volume_confirmation=0.60,
            leadership_concentration=0.20,
            crowding=0.20,
            valuation_expansion_share=0.20,
            reversal_signal=0.10,
            evidence=("Broad price, volume, and revision evidence",),
            evidence_identifiers=("evidence:forward:trend",),
        )
    )
    return build_forward_intelligence_bundle(
        identifier=f"forward:{candidate.identifier}",
        candidate_identifier=candidate.identifier,
        as_of=point_in_time,
        business=business,
        trend=trend,
    )


def test_existing_six_specialists_consume_forward_intelligence() -> None:
    candidate = _candidate("FORWARD")
    base = _context(candidate)
    bundle = _bundle(candidate)
    context = CandidateSpecialistContext(
        candidate_identifier=candidate.identifier,
        analysis_completed_at=base.analysis_completed_at,
        macro=base.macro,
        market=base.market,
        forecast=base.forecast,
        company=base.company,
        asset_valuation=base.asset_valuation,
        forward_intelligence=bundle,
        portfolio=PortfolioSpecialistContext(
            as_of=candidate.as_of,
            proposed_position_weight=0.05,
            funding_source="cash",
            expected_portfolio_contribution=0.01,
            opportunity_cost_return=0.04,
            constraint_evidence=("Portfolio preview is feasible",),
            implementation_blocks=(),
            review_conditions=("Reassess after construction",),
        ),
    )

    packet = IndependentSpecialistService().analyze(candidate, context)

    assert len(packet.analyses) == 6
    market = packet.for_role(SpecialistRole.MARKET)
    fundamental = packet.for_role(SpecialistRole.FUNDAMENTAL_VALUATION)
    assert "evidence:forward:trend" in market.evidence_origin_identifiers
    assert "evidence:forward:business" in fundamental.evidence_origin_identifiers
    assert fundamental.expected_return_impact > 0.0


def test_production_candidate_round_trip_preserves_forward_bundle() -> None:
    candidate = _candidate("ROUNDTRIP")
    base = _candidate_evidence(candidate)
    bundle = _bundle(candidate, as_of=base.as_of)
    lineage = replace(
        base.lineage,
        evidence_identifiers=tuple(
            dict.fromkeys(base.lineage.evidence_identifiers + bundle.evidence_identifiers)
        ),
    )
    governed = replace(
        base,
        forward_intelligence=bundle,
        lineage=lineage,
    )

    restored = _candidate_from_dict(_candidate_to_dict(governed))

    assert restored.forward_intelligence is not None
    assert restored.forward_intelligence.identifier == bundle.identifier
    assert restored.forward_intelligence.evidence_identifiers == bundle.evidence_identifiers
    assert restored.forward_intelligence.trend_stage == bundle.trend_stage
