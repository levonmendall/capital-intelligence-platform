from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from providers.crypto_venue_history import CoinbaseHistoryProvider, KrakenHistoryProvider
from providers.massive_multi_asset import MassiveMultiAssetProvider
from providers.tradier_market_data import TradierMarketDataProvider


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


def test_tradier_history_and_active_chain_are_evidence_only() -> None:
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
                            "bid": 42,
                            "ask": 43,
                            "last": 42.5,
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
    assert calls == [
        "https://api.tradier.com/v1/markets/history",
        "https://api.tradier.com/v1/markets/options/chains",
    ]


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
