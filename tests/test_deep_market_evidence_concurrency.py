from __future__ import annotations

import gc
import threading
from datetime import datetime, timedelta, timezone

import pytest

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as discovery_legacy
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
)


AS_OF = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


def _record(index: int) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=f"EQUITY_{index}",
        provider_symbol=f"EQUITY-{index}",
        name=f"Equity {index}",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        economic_exposure="international_equity",
        venue="TEST",
        country_code="GB",
        currency="GBP",
        settlement_currency="GBP",
        instrument_type="common_stock",
        provider_kind="yahoo",
        source_identifier=f"certified-catalog:equity:EQUITY_{index}",
    )


def _history(index: int) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "t": AS_OF - timedelta(days=252 - offset),
            "c": 100.0 + index + offset / 100.0,
            "v": 1_000_000.0 + index,
        }
        for offset in range(253)
    )


def test_deep_market_history_retrieval_is_capped_and_deterministic(
    monkeypatch,
) -> None:
    records = tuple(_record(index) for index in range(8))
    lock = threading.Lock()
    released = threading.Event()
    active = 0
    peak = 0

    def yahoo_rows(record, **_kwargs):
        nonlocal active, peak
        index = int(record.symbol.rsplit("_", 1)[-1])
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 4:
                released.set()
        try:
            assert released.wait(timeout=2.0), "deep history retrieval ran serially"
            return _history(index)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(discovery_legacy, "_yahoo_rows", yahoo_rows)

    result = discovery_legacy.default_market_probe(
        records,
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        eodhd_provider=object(),
        maximum_workers=100,
    )

    assert peak == 4
    assert tuple(result) == tuple(record.symbol for record in records)
    assert all(result[record.symbol].history_bars == 253 for record in records)
    assert all(
        record.source_identifier in result[record.symbol].evidence_identifiers
        for record in records
    )


def test_deep_market_raw_histories_are_released_after_feature_compaction(
    monkeypatch,
) -> None:
    records = tuple(_record(index) for index in range(12))
    lock = threading.Lock()
    counts = {"live": 0, "peak": 0}

    class TrackedRow(dict):
        def __init__(self, value) -> None:
            super().__init__(value)
            with lock:
                counts["live"] += 1
                counts["peak"] = max(counts["peak"], counts["live"])

        def __del__(self) -> None:
            with lock:
                counts["live"] -= 1

    def yahoo_rows(record, **_kwargs):
        index = int(record.symbol.rsplit("_", 1)[-1])
        return tuple(TrackedRow(item) for item in _history(index))

    monkeypatch.setattr(discovery_legacy, "_yahoo_rows", yahoo_rows)

    result = discovery_legacy.default_market_probe(
        records,
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        eodhd_provider=object(),
        maximum_workers=4,
    )

    assert tuple(result) == tuple(record.symbol for record in records)
    assert counts["peak"] <= 4 * 253
    assert counts["live"] == 0


@pytest.mark.parametrize("maximum_workers", (0, -1, True, 1.5))
def test_deep_market_history_retrieval_rejects_invalid_worker_limits(
    maximum_workers,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        discovery_legacy.default_market_probe(
            (),
            AS_OF,
            ComprehensiveMarketDiscoveryPolicy(),
            eodhd_provider=object(),
            maximum_workers=maximum_workers,
        )


def test_alpaca_histories_are_released_between_provider_batches() -> None:
    records = tuple(
        DiscoveryCatalogRecord(
            symbol=f"ALPACA_{index}",
            provider_symbol=f"ALPACA-{index}",
            name=f"Alpaca {index}",
            asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
            economic_exposure="international_equity",
            venue="US",
            country_code="US",
            currency="USD",
            settlement_currency="USD",
            instrument_type="common_stock",
            provider_kind="alpaca",
            source_identifier=f"alpaca-assets:ALPACA-{index}",
        )
        for index in range(401)
    )
    counts = {"live": 0, "peak": 0, "calls": 0}

    class TrackedRows(list):
        def __init__(self, values) -> None:
            super().__init__(values)
            counts["live"] += 1
            counts["peak"] = max(counts["peak"], counts["live"])

        def __del__(self) -> None:
            counts["live"] -= 1

    class Client:
        def historical_bars(self, symbols, **_kwargs):
            gc.collect()
            assert counts["live"] == 0, "prior Alpaca batch is still retained"
            counts["calls"] += 1
            payload = {}
            for symbol in symbols:
                index = int(str(symbol).rsplit("-", 1)[-1])
                payload[str(symbol)] = TrackedRows(
                    [
                        {
                            "t": AS_OF - timedelta(days=2 - offset),
                            "c": 100.0 + index + offset / 100.0,
                            "v": 1_000_000.0 + index,
                        }
                        for offset in range(3)
                    ]
                )
            return payload

    result = discovery_legacy.default_market_probe(
        records,
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(
            minimum_history_bars=3,
            history_days=10,
        ),
        eodhd_provider=object(),
        alpaca_client=Client(),
        maximum_workers=4,
    )

    gc.collect()
    assert counts["calls"] == 3
    assert counts["peak"] <= 200
    assert counts["live"] == 0
    assert tuple(result) == tuple(record.symbol for record in records)
    assert all(result[record.symbol].history_bars == 3 for record in records)
