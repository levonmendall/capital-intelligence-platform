from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery as discovery
from operations import provider_preselection_market_probe as preselection
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
)


AS_OF = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def json(self):
        timestamps = [
            int((AS_OF - timedelta(days=offset)).timestamp())
            for offset in (3, 2, 1)
        ]
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "close": [99.0, 100.0, 101.0],
                                    "volume": [1_000_000, 1_100_000, 1_200_000],
                                }
                            ]
                        },
                    }
                ]
            }
        }


class _EmptyAlpaca:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def historical_bars(self, symbols, *, start, end, timeframe):
        del start, end, timeframe
        self.calls.append(tuple(symbols))
        return {}


def _option(symbol: str, right: str) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=f"O:{symbol}",
        name=symbol,
        asset_class=CandidateAssetClass.OPTION,
        economic_exposure="option_strategies",
        venue="OPRA",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="option",
        provider_kind="massive",
        source_identifier=f"massive:{symbol}",
        expiration_at=AS_OF + timedelta(days=60),
        underlying_symbol="SPY",
        strike=500.0,
        option_right=right,
    )


def test_option_underlying_yahoo_fallback_is_fetched_once_and_reused() -> None:
    http_calls: list[str] = []

    def http_get(url, *, params, headers, timeout):
        del params, headers, timeout
        http_calls.append(url)
        return _Response()

    client = preselection._OptionUnderlyingHistoryClient(
        delegate=_EmptyAlpaca(),
        option_underlyings=("SPY",),
        http_get=http_get,
        maximum_workers=4,
    )
    start = AS_OF - timedelta(days=10)

    first = client.historical_bars(
        ("SPY", "SPY"),
        start=start,
        end=AS_OF,
        timeframe="1Day",
    )
    second = client.historical_bars(
        ("SPY",),
        start=start,
        end=AS_OF,
        timeframe="1Day",
    )

    assert len(first["SPY"]) == 3
    assert len(second["SPY"]) == 3
    assert len(http_calls) == 1


def test_default_preselection_probe_delegates_once_with_bounded_workers(monkeypatch) -> None:
    records = (_option("SPY_CALL", "call"), _option("SPY_PUT", "put"))
    calls: list[tuple[tuple[str, ...], int]] = []
    empty_alpaca = _EmptyAlpaca()
    monkeypatch.setattr(
        preselection,
        "create_alpaca_paper_client",
        lambda: empty_alpaca,
    )

    def fake_legacy_probe(records, as_of, policy, **kwargs):
        del as_of, policy
        calls.append(
            (
                tuple(item.symbol for item in records),
                kwargs["maximum_workers"],
            )
        )
        return {}

    monkeypatch.setattr(preselection._legacy, "default_market_probe", fake_legacy_probe)

    result = preselection.default_provider_preselection_market_probe(
        records,
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        maximum_workers=4,
    )

    assert result == {}
    assert calls == [(("SPY_CALL", "SPY_PUT"), 4)]


def test_canonical_discovery_routes_publication_through_single_pass_probe() -> None:
    source = inspect.getsource(discovery.discover_comprehensive_markets)
    assert "market_probe=default_provider_preselection_market_probe" in source
