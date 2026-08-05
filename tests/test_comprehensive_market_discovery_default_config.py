from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryPolicy,
    _catalog_from_eodhd,
    load_comprehensive_market_discovery_config,
)


AS_OF = datetime(2026, 8, 5, 19, 30, tzinfo=timezone.utc)


def test_default_discovery_uses_only_documented_gbond_directory() -> None:
    config = load_comprehensive_market_discovery_config()

    assert "GBOND" in config.eodhd_exchange_codes
    assert "BOND" not in config.eodhd_exchange_codes
    assert config.eodhd_exchange_codes.count("GBOND") == 1


def test_fixed_income_catalog_queries_gbond_not_legacy_bond_directory() -> None:
    config = load_comprehensive_market_discovery_config()

    class Provider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def fetch_dataset(self, query):
            self.queries.append(query.provider_symbol)
            return SimpleNamespace(
                payload={
                    "active": [
                        {
                            "Code": "US10Y",
                            "Name": "United States Government Bond 10Y",
                            "Type": "Bond",
                            "Currency": "USD",
                            "CountryISO2": "US",
                            "Exchange": "GBOND",
                        }
                    ]
                },
                provider_record_id="eodhd-symbol-directory:GBOND",
            )

    provider = Provider()
    catalogs = _catalog_from_eodhd(
        as_of=AS_OF,
        config=config,
        provider=provider,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
    )

    assert provider.queries == ["GBOND"]
    assert len(catalogs[CandidateAssetClass.FIXED_INCOME]) == 1
    record = catalogs[CandidateAssetClass.FIXED_INCOME][0]
    assert record.asset_class is CandidateAssetClass.FIXED_INCOME
    assert record.provider_symbol == "US10Y.GBOND"
    assert record.economic_exposure == "government_bonds"
