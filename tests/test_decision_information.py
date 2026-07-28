from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from data.decision_information import (
    CurrentEventPortfolioAnalyzer,
    DecisionInformationError,
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)

UTC = timezone.utc
EVENT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
PUBLISHED = EVENT + timedelta(minutes=2)
AVAILABLE = PUBLISHED + timedelta(seconds=10)
RETRIEVED = AVAILABLE + timedelta(seconds=2)
CUTOFF = RETRIEVED


def _record(
    *,
    quality: InformationQualityState = InformationQualityState.LIVE,
    availability: datetime = AVAILABLE,
) -> DecisionInformationRecord:
    return DecisionInformationRecord(
        identifier="information:event:1",
        topic="material current event",
        summary="A governed event with potential portfolio consequences.",
        event_at=EVENT,
        published_at=PUBLISHED,
        available_at=availability,
        knowledge_cutoff=max(availability, CUTOFF),
        provenance=InformationProvenance(
            provider="licensed-newswire",
            source_identifier="newswire:item:1",
            source_type=InformationSourceType.NEWSWIRE,
            retrieved_at=max(availability, RETRIEVED),
            license_identifier="license:newswire:internal-use",
            usage_rights_identifier="rights:derived-paper-analysis",
            raw_content_hash="a" * 64,
            quality_state=quality,
        ),
        canonical_event_identifier="canonical-event:1",
        entities=("entity:issuer:1",),
        instruments=("instrument:us-equity:AAA",),
        geographies=("US",),
        sectors=("technology",),
        tags=("current-event", "portfolio-impact"),
        impact_channels=(
            PortfolioImpactChannel.EARNINGS,
            PortfolioImpactChannel.VOLATILITY,
        ),
        reliability=0.95,
        relevance=0.90,
        materiality=0.80,
        independence=0.85,
        corroborating_source_identifiers=(
            "official-source:event:1",
            "independent-journalism:event:1",
        ),
    )


def test_point_in_time_record_rejects_future_known_use() -> None:
    record = _record()

    assert record.available_to(AVAILABLE - timedelta(microseconds=1)) is False
    with pytest.raises(DecisionInformationError, match="not available"):
        record.require_available_to(AVAILABLE - timedelta(seconds=1))
    assert record.available_to(CUTOFF) is True


def test_record_preserves_source_license_corrections_and_hash() -> None:
    record = _record()
    payload = record.to_dict()

    assert payload["provenance"]["license_identifier"] == (
        "license:newswire:internal-use"
    )
    assert payload["published_at"] == PUBLISHED.isoformat()
    assert payload["available_at"] == AVAILABLE.isoformat()
    assert len(record.content_hash) == 64
    assert record.content_hash == record.content_hash


def test_material_corroborated_event_requires_cio_review() -> None:
    impact = CurrentEventPortfolioAnalyzer().assess(
        _record(),
        portfolio_identifier="portfolio:COMPOUNDING",
        assessed_at=CUTOFF,
        owned_instrument_identifiers=("instrument:us-equity:AAA",),
        market_confirmation=0.70,
    )

    assert impact.requires_cio_review is True
    assert impact.affected_instrument_identifiers == (
        "instrument:us-equity:AAA",
    )
    assert impact.portfolio_relevance == 1.0
    assert set(impact.evidence_identifiers) >= {
        "information:event:1",
        "newswire:item:1",
        "official-source:event:1",
    }


def test_unverified_or_unconfirmed_information_remains_monitoring_only() -> None:
    unverified = _record(quality=InformationQualityState.UNVERIFIED)
    analyzer = CurrentEventPortfolioAnalyzer()

    quality_impact = analyzer.assess(
        unverified,
        portfolio_identifier="portfolio:COMPOUNDING",
        assessed_at=CUTOFF,
        owned_instrument_identifiers=("instrument:us-equity:AAA",),
        market_confirmation=0.80,
    )
    unconfirmed_impact = analyzer.assess(
        _record(),
        portfolio_identifier="portfolio:COMPOUNDING",
        assessed_at=CUTOFF,
        owned_instrument_identifiers=("instrument:us-equity:AAA",),
        market_confirmation=0.0,
    )

    assert quality_impact.requires_cio_review is False
    assert unconfirmed_impact.requires_cio_review is False


def test_naive_timestamps_and_duplicate_evidence_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_record(), available_at=datetime(2026, 7, 27, 12, 2))
    with pytest.raises(ValueError, match="duplicates"):
        replace(
            _record(),
            corroborating_source_identifiers=("source:1", "source:1"),
        )
