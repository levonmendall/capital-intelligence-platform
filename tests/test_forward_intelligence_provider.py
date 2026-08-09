from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from data.provider_dataset import ProviderDatasetType
from intelligence.forward import CurrencyRegime, PolicyRegime, ThemeStage, TrendStage
from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderSettings,
    TransportResponse,
)
from providers.forward_intelligence import ConfiguredForwardIntelligenceProvider
from tests.test_production_context_assembly import _candidate

AS_OF = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


def _provider():
    payloads = {
        "/business": {
            "identifier": "business:test",
            "revenue_exposure": 0.7,
            "demand_growth": 0.8,
            "pricing_power": 0.7,
            "capacity_adequacy": 0.5,
            "incremental_margin": 0.8,
            "market_share_trend": 0.4,
            "capital_allocation_quality": 0.6,
            "customer_concentration": 0.3,
            "supplier_concentration": 0.2,
            "valuation_priced_in": 0.2,
            "evidence": ["Certified segment and pricing evidence"],
            "risks": ["Demand can weaken"],
        },
        "/trend": {
            "identifier": "trend:test",
            "absolute_trend": 0.8,
            "relative_trend": 0.7,
            "breadth": 0.75,
            "earnings_revision_breadth": 0.7,
            "volume_confirmation": 0.65,
            "leadership_concentration": 0.25,
            "crowding": 0.3,
            "valuation_expansion_share": 0.25,
            "reversal_signal": 0.1,
            "evidence": ["Certified broad trend evidence"],
        },
        "/theme": {
            "identifier": "theme:test",
            "name": "AI infrastructure",
            "demand_origin": "AI applications",
            "candidate_node": "Power",
            "nodes": [
                {
                    "name": "AI applications",
                    "demand_growth": 0.85,
                    "capacity_growth": 0.6,
                    "utilization": 0.7,
                    "lead_time_pressure": 0.2,
                    "pricing_power": 0.3,
                    "supplier_concentration": 0.2,
                    "substitution_risk": 0.1,
                    "beneficiary_symbols": [],
                },
                {
                    "name": "Power",
                    "demand_growth": 0.8,
                    "capacity_growth": 0.25,
                    "utilization": 0.95,
                    "lead_time_pressure": 0.8,
                    "pricing_power": 0.75,
                    "supplier_concentration": 0.7,
                    "substitution_risk": 0.1,
                    "beneficiary_symbols": ["TEST"],
                },
            ],
            "links": [
                {
                    "source": "AI applications",
                    "target": "Power",
                    "transmission_strength": 0.9,
                    "lag_days": 60,
                }
            ],
            "theme_demand_growth": 0.8,
            "market_pricing_score": 0.3,
            "evidence": ["Certified value-chain evidence"],
        },
        "/monetary": {
            "identifier": "monetary:test",
            "regime": "rate_cutting",
            "motive": "stable_disinflation",
            "inflation_trend": -0.6,
            "growth_trend": 0.1,
            "financial_stress": 0.1,
            "liquidity_impulse": 0.5,
            "real_yield_change": -0.5,
            "credit_spread_change": -0.2,
            "market_pricing_score": 0.3,
            "evidence": ["Certified policy transmission evidence"],
            "sensitivity": {
                "liquidity": 0.8,
                "duration": 0.4,
                "credit": 0.5,
                "inflation": -0.2,
                "growth": 0.7,
            },
        },
        "/currency": {
            "identifier": "currency:test",
            "base_currency": "EUR",
            "reporting_currency": "USD",
            "dollar_strength": -0.3,
            "real_yield_differential": -0.2,
            "dollar_funding_stress": 0.1,
            "fx_volatility": 0.2,
            "commodity_dollar_beta": -0.5,
            "market_pricing_score": 0.25,
            "evidence": ["Certified FX transmission evidence"],
            "exposure": {
                "unhedged_foreign_asset_share": 0.4,
                "foreign_revenue_share": 0.3,
                "usd_revenue_share": 0.2,
                "local_cost_share": 0.5,
                "usd_debt_share": 0.1,
                "commodity_input_share": 0.0,
                "commodity_revenue_share": 0.0,
                "emerging_market_funding_sensitivity": 0.1,
                "hedge_ratio": 0.2,
            },
        },
        "/graph": {
            "nodes": [
                {
                    "identifier": "theme:ai_infrastructure",
                    "kind": "theme",
                    "label": "ai_infrastructure",
                }
            ],
            "edges": [
                {
                    "identifier": "edge:test-ai",
                    "source_identifier": "instrument:instrument:configured-forward-test",
                    "target_identifier": "theme:ai_infrastructure",
                    "relationship": "benefits_from",
                    "confidence": 0.9,
                    "explicit_reviewed": True,
                }
            ],
        },
    }

    def transport(request, _timeout):
        return TransportResponse(
            status=200,
            body=json.dumps(payloads[request.full_url.removeprefix("https://example.test")]).encode(),
            headers={},
        )

    configured = ConfiguredDatasetProvider(
        ConfiguredDatasetProviderSettings(
            provider_identifier="test-phase5-provider",
            source_version="v1",
            base_url="https://example.test",
            bindings=(
                ConfiguredDatasetBinding(ProviderDatasetType.FORWARD_BUSINESS, "/business"),
                ConfiguredDatasetBinding(ProviderDatasetType.FORWARD_TREND, "/trend"),
                ConfiguredDatasetBinding(ProviderDatasetType.FORWARD_THEME, "/theme"),
                ConfiguredDatasetBinding(ProviderDatasetType.FORWARD_MONETARY, "/monetary"),
                ConfiguredDatasetBinding(ProviderDatasetType.FORWARD_CURRENCY, "/currency"),
                ConfiguredDatasetBinding(ProviderDatasetType.EXPOSURE_GRAPH, "/graph"),
            ),
        ),
        transport=transport,
        clock=lambda: AS_OF,
    )
    return ConfiguredForwardIntelligenceProvider(configured)


def test_configured_provider_materializes_all_phase5_engines():
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
    bundle = _provider().fetch(candidate)
    assert bundle is not None
    assert len(bundle.signals) == 5
    assert bundle.trend_stage in {TrendStage.CONFIRMED, TrendStage.BROADENING}
    assert bundle.theme_stage in {ThemeStage.ACCELERATING, ThemeStage.SUPPLY_CONSTRAINED, ThemeStage.BROADENING}
    assert bundle.policy_regime is PolicyRegime.RATE_CUTTING
    assert isinstance(bundle.currency_regime, CurrencyRegime)
    assert {
        "strategic-business.v1",
        "market-trend.v1",
        "structural-theme.v1",
        "monetary-policy-transmission.v1",
        "currency-market-transmission.v1",
    }.issubset(set(bundle.model_versions))


def test_configured_exposure_graph_uses_only_reviewed_edges():
    instrument = SimpleNamespace(
        instrument_identifier="instrument:configured-forward-test",
        symbol="TEST",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        country_code="US",
        currency="USD",
        venue="NYSE",
        underlying_symbol=None,
    )
    graph = _provider().exposure_graph((instrument,), as_of=AS_OF)
    exposures = graph.research_exposures("ai_infrastructure")
    assert len(exposures) == 1
    assert exposures[0].symbol == "TEST"
    assert any(item.explicit_reviewed for item in graph.edges)
