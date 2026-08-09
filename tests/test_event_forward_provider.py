from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from data.provider_dataset import ProviderDatasetType
from intelligence.global_opportunity import (
    CanonicalExposureGraph,
    ExposureGraphEdge,
    ExposureGraphNode,
    ExposureNodeKind,
)
from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderSettings,
    TransportResponse,
)
from providers.configured_information import ConfiguredDecisionInformationProvider
from providers.event_forward import build_governed_event_forward
from tests.test_production_context_assembly import _candidate

AS_OF = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


def _information_provider():
    record = {
        "schema_version": "decision-information-record.v1",
        "identifier": "event:growth-accelerated",
        "topic": "Growth accelerated",
        "summary": "Official data show growth accelerated and orders rose.",
        "event_at": "2026-08-09T16:00:00+00:00",
        "published_at": "2026-08-09T16:05:00+00:00",
        "available_at": "2026-08-09T16:05:00+00:00",
        "knowledge_cutoff": "2026-08-09T16:05:00+00:00",
        "canonical_event_identifier": "growth-accelerated-20260809",
        "entities": [],
        "instruments": ["TEST"],
        "geographies": ["US"],
        "sectors": [],
        "tags": ["growth"],
        "impact_channels": ["growth", "demand"],
        "reliability": 0.95,
        "relevance": 0.9,
        "materiality": 0.9,
        "independence": 0.9,
        "corroborating_source_identifiers": [],
        "supersedes_identifiers": [],
        "provenance": {
            "provider": "official-test",
            "source_identifier": "official:test:growth",
            "source_type": "official",
            "retrieved_at": "2026-08-09T16:06:00+00:00",
            "license_identifier": "public-test",
            "usage_rights_identifier": "internal-analysis-test",
            "raw_content_hash": "abc123",
            "quality_state": "live",
            "correction_of_identifier": None,
            "limitations": [],
        },
    }

    def transport(_request, _timeout):
        return TransportResponse(
            status=200,
            body=json.dumps([record]).encode(),
            headers={},
        )

    configured = ConfiguredDatasetProvider(
        ConfiguredDatasetProviderSettings(
            provider_identifier="test-decision-information",
            source_version="v1",
            base_url="https://example.test",
            bindings=(
                ConfiguredDatasetBinding(
                    ProviderDatasetType.DECISION_INFORMATION,
                    "/events",
                ),
            ),
        ),
        transport=transport,
        clock=lambda: AS_OF,
    )
    return ConfiguredDecisionInformationProvider(configured)


def _graph():
    instrument = SimpleNamespace(
        instrument_identifier="instrument:event-test",
        symbol="TEST",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        country_code="US",
        currency="USD",
        venue="NYSE",
        underlying_symbol=None,
    )
    evidence = ("reviewed:exposure:test",)
    targets = tuple(
        ExposureGraphNode(
            identifier=f"economic_exposure:{name}",
            kind=ExposureNodeKind.ECONOMIC_EXPOSURE,
            label=name,
            as_of=AS_OF,
            evidence_identifiers=evidence,
        )
        for name in ("broad_equities", "cyclical_equities", "credit")
    )
    source = "instrument:instrument:event-test"
    edges = tuple(
        ExposureGraphEdge(
            identifier=f"edge:{name}",
            source_identifier=source,
            target_identifier=f"economic_exposure:{name}",
            relationship="reviewed_event_exposure",
            as_of=AS_OF,
            confidence=0.9,
            evidence_identifiers=evidence,
            explicit_reviewed=True,
        )
        for name in ("broad_equities", "cyclical_equities", "credit")
    )
    return CanonicalExposureGraph.from_instruments(
        (instrument,),
        as_of=AS_OF,
        explicit_nodes=targets,
        explicit_edges=edges,
    )


def test_certified_event_becomes_forward_context_not_new_authority():
    base = _candidate()
    candidate = replace(
        base,
        instrument=replace(
            base.instrument,
            instrument_id="instrument:event-test",
            symbol="TEST",
            name="Event Test Equity",
            asset_class=CandidateAssetClass.US_EQUITY,
        ),
    )
    features = SimpleNamespace(
        one_month_return=0.04,
        evidence_identifiers=("market:test:20260809",),
    )
    result = build_governed_event_forward(
        provider=_information_provider(),
        graph=_graph(),
        candidates=(candidate,),
        features_by_symbol={"TEST": features},
        as_of=AS_OF,
    )
    assert result.authorizes_capital is False
    assert result.assessment_identifiers
    assert result.hypothesis_identifiers
    assert len(result.bundles) == 1
    bundle = result.bundles[0]
    assert bundle.candidate_identifier == candidate.identifier
    assert bundle.signals
    assert any("governed event-to-market" in item.name for item in bundle.signals)
