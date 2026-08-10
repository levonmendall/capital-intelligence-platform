from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)
from providers.public_decision_information import PublicDecisionInformationProvider
from providers.public_forward_research import PublicForwardResearchProvider


def test_cftc_managed_money_record_becomes_positioning_research_only_when_matched(tmp_path) -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    record = DecisionInformationRecord(
        identifier="cftc:gold",
        topic="CFTC positioning: GOLD - COMMODITY EXCHANGE INC.",
        summary="Open interest 500000; managed-money long 180000; managed-money short 60000",
        event_at=now - timedelta(days=2),
        published_at=now - timedelta(days=2),
        available_at=now - timedelta(days=1),
        knowledge_cutoff=now - timedelta(days=1),
        provenance=InformationProvenance(
            provider="CFTC",
            source_identifier="gold-weekly",
            source_type=InformationSourceType.REGULATORY,
            retrieved_at=now - timedelta(days=1),
            license_identifier="CFTC-public-reporting",
            usage_rights_identifier="official-open-data.internal-analysis",
            raw_content_hash="b" * 64,
            quality_state=InformationQualityState.LIVE,
        ),
        canonical_event_identifier="event:cftc:gold",
        entities=("COMMODITY EXCHANGE INC.",),
        instruments=(),
        geographies=("United States",),
        sectors=(),
        tags=("cftc-positioning-observation", "gold"),
        impact_channels=(PortfolioImpactChannel.POSITIONING,),
        reliability=0.98,
        relevance=0.80,
        materiality=0.65,
        independence=1.0,
    )
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"records": [record.to_dict()]}), encoding="utf-8")
    provider = PublicForwardResearchProvider(PublicDecisionInformationProvider(path))
    candidate = SimpleNamespace(
        as_of=now,
        instrument=SimpleNamespace(symbol="GC", name="Gold Future"),
    )
    research = provider.fetch(candidate)
    assert research is not None
    assert research.positioning is not None
    assert research.positioning.direction > 0.0
    assert research.positioning.derivative_coverage is False
    assert research.positioning.evidence_identifiers


def test_unmatched_cftc_record_remains_unavailable(tmp_path) -> None:
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"records": []}), encoding="utf-8")
    provider = PublicForwardResearchProvider(PublicDecisionInformationProvider(path))
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    candidate = SimpleNamespace(
        as_of=now,
        instrument=SimpleNamespace(symbol="AAPL", name="Apple Inc."),
    )
    assert provider.fetch(candidate) is None
