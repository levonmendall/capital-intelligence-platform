from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from providers.crypto_venue_history import CoinbaseHistoryProvider, KrakenHistoryProvider
import pytest

from providers.massive_multi_asset import (
    MassiveMultiAssetError,
    MassiveMultiAssetProvider,
)
from providers.tradier_market_data import (
    TradierMarketDataError,
    TradierMarketDataProvider,
)


AS_OF = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def test_massive_stock_history_normalizes_daily_bars() -> None:
    first = int((AS_OF - timedelta(days=2)).timestamp() * 1000)
    second = int((AS_OF - timedelta(days=1)).timestamp() * 1000)

    def get(url, **kwargs):
        assert "/v2/aggs/ticker/SPY/range/1/day/" in url
        return Response(
            {
                "status": "OK",
                "results": [
                    {"t": first, "c": 640.0, "v": 1000},
                    {"t": second, "c": 641.0, "v": 1100},
                ],
            }
        )

    provider = MassiveMultiAssetProvider("secret", http_get=get)
    rows = provider.daily_history("stock", "SPY", as_of=AS_OF, history_days=5)
    assert len(rows) == 2
    assert rows[-1]["c"] == 641.0


def test_massive_fx_and_crypto_ticker_prefixes() -> None:
    seen = []

    def get(url, **kwargs):
        seen.append(url)
        return Response({"status": "OK", "results": []})

    provider = MassiveMultiAssetProvider("secret", http_get=get)
    provider.daily_history("fx", "EUR/USD", as_of=AS_OF, history_days=5)
    provider.daily_history("crypto", "BTC-USD", as_of=AS_OF, history_days=5)
    assert any("C:EURUSD" in url for url in seen)
    assert any("X:BTCUSD" in url for url in seen)


def test_massive_futures_contract_pagination_fails_closed_at_guard() -> None:
    provider = MassiveMultiAssetProvider(
        "secret",
        http_get=lambda *_args, **_kwargs: Response(
            {
                "status": "OK",
                "results": [],
                "next_url": "https://api.massive.com/futures/v1/contracts?cursor=next",
            }
        ),
    )

    with pytest.raises(MassiveMultiAssetError, match="completeness guard"):
        provider.futures_contracts(as_of=AS_OF, maximum_pages=1)


def test_tradier_history_and_active_chain_are_normalized() -> None:
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("/markets/history"):
            return Response(
                {"history": {"day": [{"date": "2026-08-10", "close": 640, "volume": 1000}]}}
            )
        return Response(
            {
                "options": {
                    "option": [
                        {
                            "symbol": "SPY260918C00600000",
                            "option_type": "call",
                            "strike": 600,
                            "contract_size": 100,
                            "volume": 50,
                            "bid": 42,
                            "ask": 43,
                            "last": 42.5,
                            "greeks": {"delta": 0.7, "mid_iv": 0.22},
                        }
                    ]
                }
            }
        )

    provider = TradierMarketDataProvider("secret", http_get=get)
    rows = provider.daily_history("SPY", as_of=AS_OF, history_days=5)
    chain = provider.active_option_chain(
        "SPY", date(2026, 9, 18), as_of=AS_OF
    )
    assert rows[0]["c"] == 640.0
    assert chain[0].option_symbol == "SPY260918C00600000"
    assert chain[0].contract_size == 100
    assert chain[0].delta == 0.7
    assert calls == [
        "https://api.tradier.com/v1/markets/history",
        "https://api.tradier.com/v1/markets/options/chains",
    ]


def test_tradier_selects_both_rights_for_every_eligible_expiration() -> None:
    expirations = (date(2026, 9, 18), date(2026, 10, 16))

    def get(url, **kwargs):
        if url.endswith("/markets/options/expirations"):
            return Response(
                {"expirations": {"date": [item.isoformat() for item in expirations]}}
            )
        if url.endswith("/markets/options/chains"):
            expiration = date.fromisoformat(kwargs["params"]["expiration"])
            compact = expiration.strftime("%y%m%d")
            return Response(
                {
                    "options": {
                        "option": [
                            {
                                "symbol": f"SPY{compact}C00640000",
                                "option_type": "call",
                                "strike": 640,
                                "contract_size": 100,
                                "volume": 100,
                                "bid": 10,
                                "ask": 10.5,
                                "greeks": {"delta": 0.5, "mid_iv": 0.2},
                            },
                            {
                                "symbol": f"SPY{compact}P00640000",
                                "option_type": "put",
                                "strike": 640,
                                "contract_size": 100,
                                "volume": 90,
                                "bid": 9.5,
                                "ask": 10,
                                "greeks": {"delta": -0.5, "mid_iv": 0.21},
                            },
                        ]
                    }
                }
            )
        return Response(
            {
                "history": {
                    "day": [
                        {"date": "2026-08-10", "close": 10.25, "volume": 80}
                    ]
                }
            }
        )

    selections = TradierMarketDataProvider("secret", http_get=get).select_contracts(
        "SPY",
        underlying_price=640.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=90,
    )

    assert len(selections) == 4
    assert {item.definition.option_right for item in selections} == {"call", "put"}
    assert {item.definition.expiration_at.date() for item in selections} == set(
        expirations
    )
    assert all(item.bar.observed_at.date() == date(2026, 8, 10) for item in selections)


def test_tradier_rejects_partial_expiration_right_coverage() -> None:
    def get(url, **kwargs):
        if url.endswith("/markets/options/expirations"):
            return Response({"expirations": {"date": ["2026-09-18"]}})
        if url.endswith("/markets/options/chains"):
            return Response(
                {
                    "options": {
                        "option": {
                            "symbol": "SPY260918C00640000",
                            "option_type": "call",
                            "strike": 640,
                            "contract_size": 100,
                            "volume": 100,
                        }
                    }
                }
            )
        return Response(
            {
                "history": {
                    "day": {"date": "2026-08-10", "close": 10, "volume": 80}
                }
            }
        )

    with pytest.raises(TradierMarketDataError, match="2026-09-18:put"):
        TradierMarketDataProvider("secret", http_get=get).select_contracts(
            "SPY",
            underlying_price=640.0,
            as_of=AS_OF,
            minimum_days_to_expiry=30,
            maximum_days_to_expiry=90,
        )


def test_coinbase_and_kraken_only_keep_completed_daily_buckets() -> None:
    old = int((AS_OF - timedelta(days=3)).timestamp())
    completed = int((AS_OF - timedelta(days=2)).timestamp())
    current = int((AS_OF - timedelta(hours=4)).timestamp())
    coinbase_payload = [
        [old, 100, 110, 101, 108, 10],
        [completed, 108, 112, 109, 111, 11],
        [current, 111, 113, 112, 112.5, 12],
    ]
    kraken_payload = {
        "error": [],
        "result": {
            "XXBTZUSD": [
                [old, "100", "110", "101", "108", "105", "10", 2],
                [completed, "108", "112", "109", "111", "110", "11", 3],
                [current, "111", "113", "112", "112.5", "112", "12", 4],
            ],
            "last": current,
        },
    }

    coinbase = CoinbaseHistoryProvider(http_get=lambda *a, **k: Response(coinbase_payload))
    kraken = KrakenHistoryProvider(http_get=lambda *a, **k: Response(kraken_payload))

    coinbase_rows = coinbase.daily_history("BTC-USD", as_of=AS_OF, history_days=10)
    kraken_rows = kraken.daily_history("XBT/USD", as_of=AS_OF, history_days=10)
    assert len(coinbase_rows) == 2
    assert len(kraken_rows) == 2
    assert all(row["t"] + timedelta(days=1) <= AS_OF for row in coinbase_rows)
    assert all(row["t"] + timedelta(days=1) <= AS_OF for row in kraken_rows)
