from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers.public_live_information import PublicLiveSourceCatalog
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "public_live_information_sources.json"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_operating_catalog_composes_all_governed_public_sources() -> None:
    catalog = load_operating_public_live_source_catalog(CATALOG)
    identifiers = {item.identifier for item in catalog.sources}

    assert len(catalog.sources) >= 41
    assert {
        "bank-of-england-news-live",
        "bank-of-japan-live",
        "bank-of-canada-live",
        "snb-monetary-policy-live",
        "bis-statistics-releases-live",
        "bls-unemployment-live",
        "bls-payrolls-live",
        "ecb-deposit-facility-rate-live",
        "eurostat-hicp-live",
        "oecd-leading-indicators-live",
        "usda-crop-production-live",
    } <= identifiers


def test_usda_quickstats_normalizes_physical_commodity_observation(monkeypatch) -> None:
    monkeypatch.setenv("USDA_NASS_API_KEY", "test-key")
    operating = load_operating_public_live_source_catalog(CATALOG)
    source = next(
        item for item in operating.sources
        if item.identifier == "usda-crop-production-live"
    )
    response = FakeResponse(
        {
            "data": [
                {
                    "year": 2025,
                    "commodity_desc": "CORN",
                    "statisticcat_desc": "PRODUCTION",
                    "reference_period_desc": "YEAR",
                    "Value": "14,867,000,000",
                    "unit_desc": "BU",
                    "state_name": "US TOTAL",
                    "CV": "corn-production",
                }
            ]
        }
    )
    provider = ImpactfulPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (source,)),
        http_get=lambda *args, **kwargs: response,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    record = provider.collect().records[0]

    assert record.event_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert record.geographies == ("US TOTAL",)
    assert record.topic == "USDA CORN PRODUCTION"
    assert "physical-commodity" in record.tags
