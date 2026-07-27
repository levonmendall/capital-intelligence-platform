from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.market import MarketDataQuery, MarketDataType
from providers.crypto_venues import (
    CoinbaseExchangeProvider,
    CryptoVenueBinding,
    CryptoVenueBindingRegistry,
    CryptoVenueProviderError,
    KrakenSpotProvider,
    load_crypto_venue_bindings,
)


NOW = datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def binding() -> CryptoVenueBinding:
    return CryptoVenueBinding(
        instrument_id="instrument:crypto:btcusd",
        quote_currency="USD",
        coinbase_product_id="BTC-USD",
        kraken_symbol="BTC/USD",
    )


def query(*, venue=None) -> MarketDataQuery:
    return MarketDataQuery(
        instrument_id=binding().instrument_id,
        data_type=MarketDataType.QUOTE,
        as_of=NOW,
        venue=venue,
    )


def test_coinbase_level_one_book_normalizes_top_of_book() -> None:
    def http_get(url, *, params, timeout):
        assert url.endswith("/products/BTC-USD/book")
        assert params == {"level": 1}
        return FakeResponse(
            {
                "sequence": 123,
                "bids": [["6247.58", "6.3578146", 2]],
                "asks": [["6251.52", "2", 1]],
                "time": "2026-07-27T21:59:59Z",
            }
        )

    provider = CoinbaseExchangeProvider(
        bindings=CryptoVenueBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=http_get,
    )
    batch = provider.fetch(query())
    quote = batch.records[0]
    assert quote.bid == 6247.58
    assert quote.ask == 6251.52
    assert quote.bid_size == 6.3578146
    assert quote.provenance.provider == "COINBASE_EXCHANGE"
    assert quote.provenance.venue == "COINBASE"


def test_kraken_pretrade_book_normalizes_top_of_book() -> None:
    def http_get(url, *, params, timeout):
        assert params == {"symbol": "BTC/USD"}
        return FakeResponse(
            {
                "error": [],
                "result": {
                    "venue": "PGSL",
                    "bids": [
                        {
                            "price": "6248.00",
                            "qty": "1.2",
                            "publication_ts": "2026-07-27T21:59:58Z",
                        }
                    ],
                    "asks": [
                        {
                            "price": "6252.00",
                            "qty": "1.4",
                            "publication_ts": "2026-07-27T21:59:59Z",
                        }
                    ],
                },
            }
        )

    provider = KrakenSpotProvider(
        bindings=CryptoVenueBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=http_get,
    )
    quote = provider.fetch(query()).records[0]
    assert quote.bid == 6248.0
    assert quote.ask == 6252.0
    assert quote.provenance.provider == "KRAKEN_SPOT"
    assert quote.provenance.venue == "PGSL"


def test_venue_specific_query_remains_consistent() -> None:
    provider = KrakenSpotProvider(
        bindings=CryptoVenueBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: FakeResponse(
            {
                "error": [],
                "result": {
                    "venue": "PGSL",
                    "bids": [
                        {
                            "price": "10",
                            "qty": "1",
                            "publication_ts": "2026-07-27T21:59:58Z",
                        }
                    ],
                    "asks": [
                        {
                            "price": "11",
                            "qty": "1",
                            "publication_ts": "2026-07-27T21:59:58Z",
                        }
                    ],
                },
            }
        ),
    )
    quote = provider.fetch(query(venue="KRAKEN")).records[0]
    assert quote.provenance.venue == "KRAKEN"


def test_future_known_crypto_quote_is_rejected() -> None:
    provider = CoinbaseExchangeProvider(
        bindings=CryptoVenueBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: FakeResponse(
            {
                "sequence": 123,
                "bids": [["10", "1", 1]],
                "asks": [["11", "1", 1]],
                "time": "2026-07-27T22:00:01Z",
            }
        ),
    )
    with pytest.raises(CryptoVenueProviderError, match="future-known"):
        provider.fetch(query())


def test_non_quote_requests_fail_closed() -> None:
    provider = CoinbaseExchangeProvider(
        bindings=CryptoVenueBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )
    with pytest.raises(CryptoVenueProviderError, match="quote requests only"):
        provider.fetch(
            MarketDataQuery(
                instrument_id=binding().instrument_id,
                data_type=MarketDataType.TRADE,
                as_of=NOW,
            )
        )


def test_crypto_binding_loader(tmp_path: Path) -> None:
    path = tmp_path / "crypto.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "crypto-venue-bindings.v1",
                "bindings": [
                    {
                        "instrument_id": binding().instrument_id,
                        "quote_currency": "USD",
                        "coinbase_product_id": "BTC-USD",
                        "kraken_symbol": "BTC/USD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_crypto_venue_bindings(path)
    assert registry.resolve(binding().instrument_id).coinbase_product_id == "BTC-USD"
