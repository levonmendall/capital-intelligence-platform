from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)
from intelligence.event_market_forward import (
    EventCausalState,
    EventToForwardEngine,
    MarketObservation,
    SQLiteEventMarketStore,
    TransmissionDirection,
)
from intelligence.event_quality import assess_event_clusters


AS_OF = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)


def _record(
    *,
    identifier: str = "event:1",
    topic: str = "Ceasefire agreement restores shipping",
    summary: str = "A ceasefire lowers disruption risk and shipping has resumed.",
    source_type: InformationSourceType = InformationSourceType.OFFICIAL,
    quality: InformationQualityState = InformationQualityState.LIVE,
    reliability: float = 0.95,
    relevance: float = 0.90,
    materiality: float = 0.85,
    channels: tuple[PortfolioImpactChannel, ...] = (
        PortfolioImpactChannel.GEOPOLITICAL,
        PortfolioImpactChannel.SUPPLY,
    ),
    canonical_event_identifier: str = "event:ceasefire",
    supersedes_identifiers: tuple[str, ...] = (),
) -> DecisionInformationRecord:
    event_at = AS_OF - timedelta(hours=2)
    published_at = AS_OF - timedelta(hours=1, minutes=45)
    available_at = AS_OF - timedelta(hours=1, minutes=30)
    return DecisionInformationRecord(
        identifier=identifier,
        topic=topic,
        summary=summary,
        event_at=event_at,
        published_at=published_at,
        available_at=available_at,
        knowledge_cutoff=available_at,
        provenance=InformationProvenance(
            provider=f"provider:{identifier}",
            source_identifier=f"source:{identifier}",
            source_type=source_type,
            retrieved_at=available_at,
            license_identifier="public",
            usage_rights_identifier="internal-analysis",
            raw_content_hash=f"hash:{identifier}",
            quality_state=quality,
        ),
        canonical_event_identifier=canonical_event_identifier,
        entities=("Persian Gulf",),
        instruments=(),
        geographies=("Middle East",),
        sectors=("Energy", "Transport"),
        tags=("ceasefire", "shipping restored"),
        impact_channels=channels,
        reliability=reliability,
        relevance=relevance,
        materiality=materiality,
        independence=0.90,
        supersedes_identifiers=supersedes_identifiers,
    )


def _cluster(
    record: DecisionInformationRecord,
    *,
    prior: tuple[str, ...] = (),
    confirmation: float = 0.0,
):
    result = assess_event_clusters(
        (record.to_dict(),),
        prior_semantic_keys=prior,
        market_confirmation={
            record.canonical_event_identifier: confirmation,
            "geopolitical": confirmation,
            "supply": confirmation,
        },
    )
    return result[0][0]


def _observations() -> tuple[MarketObservation, ...]:
    values = {
        "broad_equities": 0.012,
        "volatility": -0.025,
        "affected_commodity": -0.018,
        "commodity_consumers": 0.010,
        "commodity_producers": -0.008,
    }
    return tuple(
        MarketObservation(
            identifier=f"obs:{target}",
            exposure_identifier=target,
            observed_at=AS_OF,
            return_change=change,
            evidence_identifiers=(f"price:{target}",),
        )
        for target, change in values.items()
    )


def test_authoritative_event_is_analyzed_before_market_confirmation() -> None:
    record = _record()
    cluster = _cluster(record, confirmation=0.0)
    assert cluster.eligible_for_analysis is True
    assert cluster.authoritative_source is True
    assert cluster.source_sufficient is True
    assert cluster.eligible_for_cio_context is False

    assessment = EventToForwardEngine().assess(
        record,
        event_cluster=cluster,
        observations=(),
        assessed_at=AS_OF,
    )
    assert assessment.state is EventCausalState.MAPPED
    assert assessment.eligible_for_analysis is True
    assert assessment.eligible_for_cio_context is False
    assert EventToForwardEngine().build_forward_bundles(
        assessment,
        candidate_exposure_map={"broad_equities": ("candidate:SPY",)},
    ) == ()


def test_authoritative_event_routes_through_existing_forward_bundle_after_gates() -> None:
    record = _record()
    cluster = _cluster(record, confirmation=0.8)
    assessment = EventToForwardEngine().assess(
        record,
        event_cluster=cluster,
        observations=_observations(),
        assessed_at=AS_OF,
    )
    assert assessment.eligible_for_cio_context is True
    bundles = EventToForwardEngine().build_forward_bundles(
        assessment,
        candidate_exposure_map={
            "broad_equities": ("candidate:SPY",),
            "commodity_consumers": ("candidate:SPY",),
        },
    )
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.candidate_identifier == "candidate:SPY"
    assert bundle.signals[0].name == "governed event-to-market transmission"
    assert "macro" in bundle.signals[0].channels
    assert "market" in bundle.signals[0].channels
    assert bundle.evidence_identifiers


def test_single_non_authoritative_report_remains_analysis_only() -> None:
    record = _record(source_type=InformationSourceType.JOURNALISM)
    cluster = _cluster(record, confirmation=0.9)
    assert cluster.eligible_for_analysis is True
    assert cluster.source_sufficient is False
    assert cluster.eligible_for_cio_context is False


def test_explicit_update_receives_partial_novelty() -> None:
    record = _record(supersedes_identifiers=("event:prior",))
    cluster = _cluster(
        record,
        prior=(record.canonical_event_identifier,),
        confirmation=0.8,
    )
    assert cluster.novelty == 0.75
    assert cluster.eligible_for_cio_context is True


def test_repeated_non_update_has_zero_novelty() -> None:
    record = _record()
    cluster = _cluster(
        record,
        prior=(record.canonical_event_identifier,),
        confirmation=0.8,
    )
    assert cluster.novelty == 0.0
    assert cluster.eligible_for_cio_context is False


def test_disputed_and_low_materiality_records_do_not_enter_analysis() -> None:
    disputed = _record(quality=InformationQualityState.DISPUTED)
    low = _record(identifier="event:low", materiality=0.10)
    assert _cluster(disputed).eligible_for_analysis is False
    assert _cluster(low).eligible_for_analysis is False


def test_opposing_drivers_remain_mixed() -> None:
    record = _record(
        topic="Federal Reserve rate cut as recession risk rises",
        summary="The central bank cut rates while warning that demand weakened and recession risks increased.",
        channels=(
            PortfolioImpactChannel.POLICY,
            PortfolioImpactChannel.LIQUIDITY,
            PortfolioImpactChannel.GROWTH,
            PortfolioImpactChannel.DEMAND,
        ),
        canonical_event_identifier="event:mixed-policy-growth",
    )
    cluster = _cluster(record, confirmation=0.8)
    observations = (
        MarketObservation(
            identifier="obs:growth",
            exposure_identifier="growth_equities",
            observed_at=AS_OF,
            return_change=-0.005,
            evidence_identifiers=("price:growth",),
        ),
        MarketObservation(
            identifier="obs:credit",
            exposure_identifier="credit",
            observed_at=AS_OF,
            return_change=-0.004,
            evidence_identifiers=("price:credit",),
        ),
        MarketObservation(
            identifier="obs:bonds",
            exposure_identifier="bond_prices",
            observed_at=AS_OF,
            return_change=0.010,
            evidence_identifiers=("price:bonds",),
        ),
    )
    assessment = EventToForwardEngine().assess(
        record,
        event_cluster=cluster,
        observations=observations,
        assessed_at=AS_OF,
    )
    assert assessment.state is EventCausalState.MIXED
    assert any(
        item.target_identifier == "growth_equities"
        and item.direction is TransmissionDirection.MIXED
        for item in assessment.transmissions
    )


def test_unfamiliar_material_event_is_unresolved_not_directional() -> None:
    record = _record(
        topic="Novel material infrastructure event",
        summary="A new mechanism affects critical infrastructure without a known market transmission.",
        channels=(PortfolioImpactChannel.OPERATIONAL,),
        canonical_event_identifier="event:novel-infrastructure",
    )
    cluster = _cluster(record, confirmation=0.8)
    assessment = EventToForwardEngine().assess(
        record,
        event_cluster=cluster,
        observations=(),
        assessed_at=AS_OF,
    )
    assert assessment.state is EventCausalState.UNRESOLVED_MAJOR_EVENT
    assert assessment.requires_causal_review is True
    assert assessment.eligible_for_cio_context is False
    assert assessment.unresolved_questions


def test_event_market_store_is_append_only(tmp_path) -> None:
    record = _record()
    cluster = _cluster(record, confirmation=0.8)
    engine = EventToForwardEngine()
    assessment = engine.assess(
        record,
        event_cluster=cluster,
        observations=_observations(),
        assessed_at=AS_OF,
    )
    store = SQLiteEventMarketStore(tmp_path / "events.db")
    store.append(assessment, recorded_at=AS_OF)
    store.append(assessment, recorded_at=AS_OF)
    conflicting = replace(
        assessment,
        state=EventCausalState.UNKNOWN,
    )
    with pytest.raises(ValueError, match="different content"):
        store.append(conflicting, recorded_at=AS_OF)
