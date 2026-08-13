from __future__ import annotations

from datetime import datetime, timezone

import pytest

from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryError,
    _futures_catalog,
)
from providers.massive_multi_asset import MassiveFuturesContract


AS_OF = datetime(2026, 8, 13, 20, 0, tzinfo=timezone.utc)


def _root(symbol: str):
    return {
        "root": symbol,
        "name": symbol,
        "economic_exposure": "us_equity",
        "contract_multiplier": 50.0,
        "month_codes": ["H", "M", "U", "Z"],
        "years_forward": 2,
        "quote_spread_bps": 1.0,
    }


def _config() -> ComprehensiveMarketDiscoveryConfig:
    return ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=(),
        futures_roots=(_root("ES"), _root("NQ")),
        option_underlyings=(),
        yahoo_exchange_suffixes=(),
    )


def _contract(root: str) -> MassiveFuturesContract:
    ticker = f"{root}Z26"
    return MassiveFuturesContract(
        ticker=ticker,
        product_code=root,
        trading_venue="XCME",
        first_trade_date="2025-12-15",
        last_trade_date="2026-12-18",
        settlement_date="2026-12-18",
        active=True,
        source_identifier=f"massive:futures-contract:{ticker}:2026-08-13",
    )


class Massive:
    configured = True

    def __init__(self, contracts):
        self.contracts = tuple(contracts)
        self.calls = []

    def futures_contracts(self, **kwargs):
        self.calls.append(kwargs)
        return self.contracts


def test_configured_massive_contract_index_replaces_synthetic_contracts() -> None:
    massive = Massive((_contract("ES"), _contract("NQ")))

    records = _futures_catalog(
        as_of=AS_OF,
        config=_config(),
        massive_futures_provider=massive,
    )

    assert [record.symbol for record in records] == ["ESZ26", "NQZ26"]
    assert all(record.provider_kind == "massive" for record in records)
    assert all(record.provider_dataset == "futures/v1/contracts" for record in records)
    assert all(record.venue == "XCME" for record in records)
    assert massive.calls == [
        {"as_of": AS_OF, "product_codes": ("ES", "NQ")}
    ]


def test_massive_contract_index_cannot_silently_drop_a_configured_root() -> None:
    with pytest.raises(
        ComprehensiveMarketDiscoveryError,
        match="complete configured-root coverage: NQ",
    ):
        _futures_catalog(
            as_of=AS_OF,
            config=_config(),
            massive_futures_provider=Massive((_contract("ES"),)),
        )
