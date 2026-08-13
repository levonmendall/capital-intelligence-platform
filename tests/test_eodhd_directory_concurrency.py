from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryPolicy,
    _catalog_from_eodhd,
)


AS_OF = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


class _ConcurrentDirectoryProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0
        self.requested: list[str] = []

    def fetch_dataset(self, query):
        exchange = query.provider_symbol
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.requested.append(exchange)
        try:
            time.sleep(0.04)
            return SimpleNamespace(
                payload={
                    "active": [
                        {
                            "Code": f"{exchange}A",
                            "Name": f"{exchange} Company",
                            "Type": "Common Stock",
                            "Currency": "USD",
                            "CountryISO2": "GB",
                            "Exchange": exchange,
                        }
                    ]
                },
                provider_record_id=f"directory:{exchange}",
            )
        finally:
            with self._lock:
                self.active -= 1


def _config(exchanges):
    return ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=tuple(exchanges),
        futures_roots=(),
        option_underlyings=(),
        yahoo_exchange_suffixes=(),
    )


def test_eodhd_directory_reads_are_bounded_concurrent_and_complete():
    exchanges = ("LSE", "XETRA", "PA", "SW")
    provider = _ConcurrentDirectoryProvider()

    result = _catalog_from_eodhd(
        as_of=AS_OF,
        config=_config(exchanges),
        provider=provider,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.INTERNATIONAL_EQUITY}),
    )

    assert provider.maximum_active > 1
    assert provider.maximum_active <= 4
    assert set(provider.requested) == set(exchanges)
    assert len(provider.requested) == len(exchanges)
    assert len(result[CandidateAssetClass.INTERNATIONAL_EQUITY]) == len(exchanges)


def test_eodhd_directory_concurrency_does_not_fetch_unscheduled_lanes():
    provider = _ConcurrentDirectoryProvider()

    result = _catalog_from_eodhd(
        as_of=AS_OF,
        config=_config(("LSE", "CC", "FOREX")),
        provider=provider,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.CRYPTO}),
    )

    assert provider.requested == ["CC"]
    assert len(result[CandidateAssetClass.CRYPTO]) == 1
