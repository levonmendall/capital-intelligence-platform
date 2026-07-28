from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data.market import (
    MarketDataBatch,
    MarketDataProvenance,
    MarketQuote,
)
from data.observation import DataQualityState
from operations.crypto_venue_validation import validate_crypto_venues
from providers.crypto_venues import CryptoVenueBinding, CryptoVenueBindingRegistry

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class Provider:
    def __init__(self, venue: str, price: float) -> None:
        self.venue = venue
        self.price = price

    def fetch(self, query):
        quote = MarketQuote(
            instrument_id=query.instrument_id,
            currency="USD",
            bid=self.price - 0.5,
            ask=self.price + 0.5,
            bid_size=10.0,
            ask_size=10.0,
            provenance=MarketDataProvenance(
                provider=self.venue,
                venue=self.venue,
                observed_at=AS_OF - timedelta(seconds=5),
                retrieved_at=AS_OF,
                quality_state=DataQualityState.LIVE,
            ),
        )
        return MarketDataBatch(query=query, records=(quote,))


def test_independent_crypto_validation_requires_both_venues() -> None:
    bindings = CryptoVenueBindingRegistry(
        (
            CryptoVenueBinding(
                instrument_id="instrument:crypto:btcusd",
                quote_currency="USD",
                coinbase_product_id="BTC-USD",
                kraken_symbol="XBT/USD",
            ),
        )
    )
    report = validate_crypto_venues(
        bindings=bindings,
        coinbase_provider=Provider("COINBASE", 100.0),
        kraken_provider=Provider("KRAKEN", 100.25),
        evaluated_at=AS_OF,
    )

    assert report.complete is True
    assert report.ready_pair_count == 1
    assert report.to_dict()["provider_certification_granted"] is False


def test_cross_venue_divergence_fails_closed() -> None:
    bindings = CryptoVenueBindingRegistry(
        (
            CryptoVenueBinding(
                instrument_id="instrument:crypto:btcusd",
                quote_currency="USD",
                coinbase_product_id="BTC-USD",
                kraken_symbol="XBT/USD",
            ),
        )
    )
    report = validate_crypto_venues(
        bindings=bindings,
        coinbase_provider=Provider("COINBASE", 100.0),
        kraken_provider=Provider("KRAKEN", 110.0),
        evaluated_at=AS_OF,
        maximum_midpoint_divergence_bps=100.0,
    )

    assert report.complete is False
    assert any("divergence" in item for item in report.blockers)
