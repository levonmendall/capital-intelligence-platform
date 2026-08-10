from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)
from providers.public_decision_information import PublicDecisionInformationProvider


UTC = timezone.utc


def _record(*, identifier: str, source_type: InformationSourceType, reliability: float = 0.95):
    now = datetime(2026, 8, 9, 20, 0, tzinfo=UTC)
    return DecisionInformationRecord(
        identifier=identifier,
        topic="Policy update",
        summary="Material official policy update",
        event_at=now - timedelta(hours=2),
        published_at=now - timedelta(hours=1),
        available_at=now,
        knowledge_cutoff=now,
        provenance=InformationProvenance(
            provider="Official source",
            source_identifier=f"source:{identifier}",
            source_type=source_type,
            retrieved_at=now,
            license_identifier="public",
            usage_rights_identifier="internal-analysis",
            raw_content_hash="a" * 64,
            quality_state=InformationQualityState.LIVE,
        ),
        canonical_event_identifier=f"event:{identifier}",
        entities=("Issuer",),
        instruments=(),
        geographies=("United States",),
        sectors=(),
        tags=("policy",),
        impact_channels=(PortfolioImpactChannel.POLICY,),
        reliability=reliability,
        relevance=0.80,
        materiality=0.75,
        independence=1.0,
    )


def test_public_provider_admits_high_quality_official_and_rejects_uncorroborated_secondary(tmp_path) -> None:
    official = _record(identifier="official", source_type=InformationSourceType.OFFICIAL)
    secondary = _record(identifier="secondary", source_type=InformationSourceType.ALTERNATIVE)
    path = tmp_path / "public-live-information-records.json"
    path.write_text(
        json.dumps({"records": [official.to_dict(), secondary.to_dict()]}),
        encoding="utf-8",
    )
    provider = PublicDecisionInformationProvider(path)
    rows = provider.records(
        start_at=official.available_at - timedelta(days=1),
        as_of=official.available_at,
    )
    assert tuple(item.identifier for item in rows) == ("official",)
    audit = provider.audit()
    assert audit.admitted_record_count == 1
    assert audit.rejected_record_count == 1
    assert audit.candidate_authority is False


def test_public_provider_preserves_point_in_time_boundary(tmp_path) -> None:
    record = _record(identifier="future", source_type=InformationSourceType.REGULATORY)
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"records": [record.to_dict()]}), encoding="utf-8")
    provider = PublicDecisionInformationProvider(path)
    try:
        provider.records(
            start_at=record.available_at - timedelta(days=1),
            as_of=record.available_at - timedelta(seconds=1),
        )
    except Exception as error:
        assert "not available" in str(error)
    else:
        raise AssertionError("future-known evidence must fail closed")
