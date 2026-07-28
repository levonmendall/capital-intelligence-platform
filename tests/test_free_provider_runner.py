"""Tests for live free-provider runner behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from data import MarketDataQuery, MarketDataType
from providers.crypto_venues import (
    CryptoVenueBinding,
    CryptoVenueBindingRegistry,
)
from run_free_provider_connections import CoinbaseConnectivityProbeProvider

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {
            "sequence": 123,
            "bids": [["6247.58", "6.3578146", 2]],
            "asks": [["6251.52", "2", 1]],
        }


def test_coinbase_connectivity_probe_handles_missing_source_timestamp() -> None:
    binding = CryptoVenueBinding(
        instrument_id="instrument:crypto:btcusd",
        quote_currency="USD",
        coinbase_product_id="BTC-USD",
        kraken_symbol="BTC/USD",
    )
    provider = CoinbaseConnectivityProbeProvider(
        bindings=CryptoVenueBindingRegistry((binding,)),
        http_get=lambda *args, **kwargs: _Response(),
    )
    query = MarketDataQuery(
        instrument_id=binding.instrument_id,
        data_type=MarketDataType.QUOTE,
        as_of=NOW,
        venue="COINBASE",
        limit=1,
    )

    quote = provider.fetch(query).records[0]

    assert quote.provenance.observed_at == NOW
    assert quote.provenance.retrieved_at == NOW
    assert quote.bid == 6247.58
    assert quote.ask == 6251.52
