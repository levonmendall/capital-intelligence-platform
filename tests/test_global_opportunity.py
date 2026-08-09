from dataclasses import dataclass
from datetime import datetime, timezone

from cio.models import CandidateAssetClass
from intelligence.event_market_forward import (
    EventCausalState,
    EventMarketAssessment,
    MarketTransmission,
    TransmissionDirection,
)
from intelligence.global_opportunity import (
    BullMarketStage,
    CanonicalExposureGraph,
    GlobalBullMarketRadarEngine,
    PersistentOpportunitySweep,
    RadarObservation,
)

AS_OF = datetime(2026, 8, 9, 22, 45, tzinfo=timezone.utc)


def _observation(
    symbol: str,
    *,
    exposure: str,
    one: float,
    three: float,
    six: float,
    twelve: float,
    vol: float = 0.20,
    drawdown: float = -0.12,
    liquidity: float = 0.9,
) -> RadarObservation:
    return RadarObservation(
        candidate_identifier=f"candidate:{symbol}",
        instrument_identifier=f"instrument:{symbol}",
        symbol=symbol,
        as_of=AS_OF,
        asset_class=CandidateAssetClass.US_ETF,
        economic_exposure=exposure,
        country_code="US",
        currency="USD",
        venue="NYSEARCA",
        one_month_return=one,
        three_month_return=three,
        six_month_return=six,
        twelve_month_return=twelve,
        annualized_volatility=vol,
        maximum_drawdown=drawdown,
        liquidity_score=liquidity,
        evidence_identifiers=(f"bars:{symbol}",),
    )


def test_global_radar_ranks_cross_sectional_bull_leadership():
    report = GlobalBullMarketRadarEngine().scan(
        (
            _observation("LEADER", exposure="semiconductors", one=0.10, three=0.24, six=0.42, twelve=0.66),
            _observation("ROTATE", exposure="industrials", one=0.12, three=0.18, six=0.02, twelve=-0.04),
            _observation("LAG", exposure="defensive", one=-0.04, three=-0.10, six=-0.15, twelve=-0.20),
        )
    )
    assert report.assessments[0].symbol == "LEADER"
    assert report.assessments[0].stage in {
        BullMarketStage.CONFIRMED,
        BullMarketStage.CROWDED_FRAGILE,
    }
    assert report.by_candidate["candidate:ROTATE"].stage is BullMarketStage.EMERGING
    assert report.by_candidate["candidate:LAG"].stage is BullMarketStage.BEAR
    assert report.authorizes_capital is False


def test_radar_uses_multiple_horizons_and_breadth_not_single_return():
    report = GlobalBullMarketRadarEngine().scan(
        (
            _observation("A", exposure="group", one=0.08, three=0.12, six=0.18, twelve=0.25),
            _observation("B", exposure="group", one=0.04, three=0.07, six=0.10, twelve=0.14),
            _observation("C", exposure="other", one=0.20, three=-0.08, six=-0.12, twelve=-0.18, vol=0.65, drawdown=-0.48),
        )
    )
    a = report.by_candidate["candidate:A"]
    c = report.by_candidate["candidate:C"]
    assert dict(a.horizon_scores).keys() == {"1m", "3m", "6m", "12m"}
    assert a.breadth > c.breadth
    assert a.score > c.score


@dataclass(frozen=True)
class _Instrument:
    symbol: str
    instrument_identifier: str
    execution_asset_class: CandidateAssetClass
    economic_exposure: str
    country_code: str = "US"
    currency: str = "USD"
    venue: str = "NYSEARCA"
    underlying_symbol: str | None = None


def _graph() -> CanonicalExposureGraph:
    return CanonicalExposureGraph.from_instruments(
        (
            _Instrument(
                symbol="COPPER",
                instrument_identifier="instrument:COPPER",
                execution_asset_class=CandidateAssetClass.COMMODITY,
                economic_exposure="affected_commodity",
            ),
            _Instrument(
                symbol="AIR",
                instrument_identifier="instrument:AIR",
                execution_asset_class=CandidateAssetClass.US_EQUITY,
                economic_exposure="commodity_consumers",
            ),
        ),
        as_of=AS_OF,
    )


def test_canonical_exposure_graph_maps_only_governed_relationships():
    graph = _graph()
    consumers = graph.research_exposures("commodity_consumers")
    assert len(consumers) == 1
    assert consumers[0].instrument_identifier == "instrument:AIR"
    assert consumers[0].symbol == "AIR"
    assert graph.authorizes_capital is False


def test_exposure_graph_feeds_existing_forward_opportunity_discovery():
    assessment = EventMarketAssessment(
        identifier="event-assessment:1",
        information_identifier="news:1",
        event_cluster_identifier="cluster:1",
        assessed_at=AS_OF,
        state=EventCausalState.MAPPED,
        drivers=(),
        causal_chain=("input costs fall", "consumer margins improve"),
        transmissions=(
            MarketTransmission(
                target_identifier="commodity_consumers",
                direction=TransmissionDirection.POSITIVE,
                magnitude=0.5,
                confidence=0.8,
                mechanism="Lower input costs improve margins.",
                horizon="near_to_medium_term",
                contributing_driver_identifiers=("driver:1",),
                evidence_identifiers=("event:1",),
            ),
        ),
        market_confirmation=0.6,
        confirmation_coverage=0.8,
        confidence=0.8,
        major_event=True,
        requires_causal_review=False,
        contradictory_evidence=(),
        alternative_explanations=(),
        unresolved_questions=(),
        evidence_identifiers=("event:1",),
        eligible_for_analysis=True,
        eligible_for_cio_context=True,
        policy_version="event-market-forward.v1",
    )
    hypotheses = _graph().discover_event_opportunities(assessment)
    assert len(hypotheses) == 1
    assert hypotheses[0].symbol == "AIR"
    assert hypotheses[0].research_only is True
    assert hypotheses[0].authorizes_capital is False


def test_persistent_sweep_nominates_bull_leadership_without_authorizing_capital():
    observations = (
        _observation("AIR", exposure="commodity_consumers", one=0.08, three=0.16, six=0.25, twelve=0.35),
        _observation("COPPER", exposure="affected_commodity", one=-0.03, three=-0.08, six=-0.04, twelve=-0.10),
    )
    radar = GlobalBullMarketRadarEngine().scan(observations)
    sweep = PersistentOpportunitySweep().run(radar, _graph(), minimum_priority=0.45)
    assert sweep.authorizes_capital is False
    assert any(item.symbol == "AIR" for item in sweep.nominations)
    nomination = next(item for item in sweep.nominations if item.symbol == "AIR")
    assessment = radar.by_candidate[nomination.candidate_identifier]
    bundle = PersistentOpportunitySweep().forward_bundle(nomination, assessment)
    assert bundle.signals[0].expected_return_impact == 0.0
    assert "cannot bypass" in bundle.diagnostics[1]
