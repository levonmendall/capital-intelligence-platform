from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from cio import CandidateAssetClass
from data.provider_dataset import ProviderDatasetType
from intelligence.forward_decision import (
    DecisionTimingPosture,
    EvidenceAvailability,
    ForwardDecisionDimension,
    build_forward_decision_context,
)
from intelligence.forward_research import enrich_forward_decision_context
from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderSettings,
    TransportResponse,
)
from providers.forward_research import ConfiguredForwardResearchProvider
from tests.test_production_context_assembly import _candidate

AS_OF = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


def _provider():
    payloads = {
        "/expectations": [{
            "identifier": "eps-consensus",
            "kind": "analyst_eps",
            "market_expectation": 5.0,
            "internal_expectation": 5.5,
            "uncertainty": 0.25,
            "confidence": 0.8,
        }],
        "/events": {
            "expectations": [{
                "identifier": "event-probability",
                "kind": "event_probability",
                "market_expectation": 0.50,
                "internal_expectation": 0.65,
                "uncertainty": 0.10,
                "confidence": 0.75,
            }],
            "value_of_waiting": {
                "invest_now_expected_return": 0.06,
                "downside_if_unresolved": -0.18,
                "probability_uncertainty_resolves": 0.65,
                "expected_upside_lost_by_waiting": 0.02,
                "expected_post_event_entry_drag": 0.005,
                "transaction_cost_return": 0.001,
                "alternative_return_while_waiting": 0.002,
                "thesis_decay_return": 0.0,
                "evidence_identifiers": ["event:earnings"],
            },
        },
        "/positioning": [{
            "identifier": "dealer-gamma",
            "kind": "dealer_gamma",
            "directional_pressure": 0.2,
            "crowding": 0.4,
            "confidence": 0.75,
        }],
        "/leading": [{
            "identifier": "revenue-nowcast",
            "target": "company_revenue",
            "signal": 101.0,
            "weight": 1.0,
            "confidence": 0.8,
        }],
    }

    def transport(request, _timeout):
        return TransportResponse(
            status=200,
            body=json.dumps(payloads[request.full_url.removeprefix("https://example.test")]).encode(),
            headers={},
        )

    configured = ConfiguredDatasetProvider(
        ConfiguredDatasetProviderSettings(
            provider_identifier="test-forward-provider",
            source_version="v1",
            base_url="https://example.test",
            bindings=(
                ConfiguredDatasetBinding(ProviderDatasetType.EXPECTATIONS, "/expectations"),
                ConfiguredDatasetBinding(ProviderDatasetType.EVENT_EXPECTATIONS, "/events"),
                ConfiguredDatasetBinding(ProviderDatasetType.DERIVATIVE_POSITIONING, "/positioning"),
                ConfiguredDatasetBinding(ProviderDatasetType.LEADING_INDICATORS, "/leading"),
            ),
        ),
        transport=transport,
        clock=lambda: AS_OF,
    )
    return ConfiguredForwardResearchProvider(configured)


def test_configured_forward_provider_materializes_certified_research():
    base = _candidate()
    candidate = replace(
        base,
        instrument=replace(
            base.instrument,
            instrument_id="instrument:configured-forward-test",
            symbol="TEST",
            name="Configured Forward Test Equity",
            asset_class=CandidateAssetClass.US_EQUITY,
        ),
    )
    research = _provider().fetch(candidate)
    assert research is not None
    assert research.expectations is not None
    assert research.positioning is not None and research.positioning.derivative_coverage
    assert len(research.nowcasts) == 1
    assert research.value_of_waiting is not None
    assert research.value_of_waiting.posture is DecisionTimingPosture.WAIT_FOR_EVENT
    context = build_forward_decision_context(
        identifier="fd:test",
        candidate_identifier=candidate.identifier,
        as_of=candidate.as_of,
        asset_class=candidate.instrument.asset_class,
    )
    enriched = enrich_forward_decision_context(context, research)
    dimensions = {item.dimension: item for item in enriched.dimensions}
    assert dimensions[ForwardDecisionDimension.EXPECTATIONS].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.DERIVATIVES].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.ALTERNATIVE_DATA].availability is EvidenceAvailability.AVAILABLE
    assert enriched.timing is not None
    assert enriched.timing.posture is DecisionTimingPosture.WAIT_FOR_EVENT
