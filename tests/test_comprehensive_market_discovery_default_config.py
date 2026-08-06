from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryPolicy,
    _catalog_from_eodhd,
    load_comprehensive_market_discovery_config,
    scheduled_discovery_lanes,
)


AS_OF = datetime(2026, 8, 5, 19, 30, tzinfo=timezone.utc)


def test_default_discovery_excludes_benchmark_bond_directories() -> None:
    config = load_comprehensive_market_discovery_config()

    assert "GBOND" not in config.eodhd_exchange_codes
    assert "BOND" not in config.eodhd_exchange_codes
    assert CandidateAssetClass.FIXED_INCOME not in scheduled_discovery_lanes(AS_OF)


def test_fixed_income_catalog_does_not_query_eodhd_without_real_bond_catalog() -> None:
    config = load_comprehensive_market_discovery_config()

    class Provider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def fetch_dataset(self, query):
            self.queries.append(query.provider_symbol)
            raise AssertionError("an evidence-only bond directory was queried")

    provider = Provider()
    catalogs = _catalog_from_eodhd(
        as_of=AS_OF,
        config=config,
        provider=provider,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
    )

    assert provider.queries == []
    assert catalogs == {CandidateAssetClass.FIXED_INCOME: []}


def test_explicit_gbond_configuration_fails_closed() -> None:
    config = ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=("GBOND",),
        futures_roots=(),
        option_underlyings=(),
        yahoo_exchange_suffixes=(),
    )

    with pytest.raises(
        ComprehensiveMarketDiscoveryError,
        match="benchmark-yield directories cannot enter investable discovery",
    ):
        _catalog_from_eodhd(
            as_of=AS_OF,
            config=config,
            provider=object(),
            policy=ComprehensiveMarketDiscoveryPolicy(),
            requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
        )
