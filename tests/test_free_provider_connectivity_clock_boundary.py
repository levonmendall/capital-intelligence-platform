from datetime import datetime, timedelta, timezone

from data import MarketDataQuery, MarketDataType
from providers.crypto_venues import CryptoVenueBinding, CryptoVenueBindingRegistry
from run_free_provider_connections import KrakenConnectivityProbeProvider


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def test_kraken_connectivity_probe_uses_query_cutoff_not_inflight_publication_time() -> None:
    cutoff = datetime(2026, 8, 10, 15, 30, 51, tzinfo=timezone.utc)
    future_publication = cutoff + timedelta(seconds=4)
    registry = CryptoVenueBindingRegistry(
        (
            CryptoVenueBinding(
                instrument_id="instrument:crypto:btcusd",
                quote_currency="USD",
                coinbase_product_id="BTC-USD",
                kraken_symbol="BTC/USD",
            ),
        )
    )

    def http_get(*args: object, **kwargs: object) -> _Response:
        del args, kwargs
        return _Response(
            {
                "error": [],
                "result": {
                    "venue": "KRAKEN",
                    "bids": [
                        {
                            "price": "64339.7",
                            "qty": "1.2",
                            "publication_ts": future_publication.isoformat(),
                        }
                    ],
                    "asks": [
                        {
                            "price": "64339.8",
                            "qty": "1.1",
                            "publication_ts": future_publication.isoformat(),
                        }
                    ],
                },
            }
        )

    batch = KrakenConnectivityProbeProvider(
        bindings=registry,
        http_get=http_get,
    ).fetch(
        MarketDataQuery(
            instrument_id="instrument:crypto:btcusd",
            data_type=MarketDataType.QUOTE,
            as_of=cutoff,
            venue="KRAKEN",
            limit=1,
        )
    )

    quote = batch.records[0]
    assert quote.provenance.observed_at == cutoff
    assert quote.provenance.retrieved_at == cutoff
    assert quote.bid == 64339.7
    assert quote.ask == 64339.8


def test_kraken_connectivity_probe_does_not_mutate_source_payload() -> None:
    cutoff = datetime(2026, 8, 10, 15, 30, 51, tzinfo=timezone.utc)
    future_publication = cutoff + timedelta(seconds=4)
    payload = {
        "error": [],
        "result": {
            "venue": "KRAKEN",
            "bids": [
                {
                    "price": "64339.7",
                    "qty": "1.2",
                    "publication_ts": future_publication.isoformat(),
                }
            ],
            "asks": [
                {
                    "price": "64339.8",
                    "qty": "1.1",
                    "publication_ts": future_publication.isoformat(),
                }
            ],
        },
    }
    registry = CryptoVenueBindingRegistry(
        (
            CryptoVenueBinding(
                instrument_id="instrument:crypto:btcusd",
                quote_currency="USD",
                coinbase_product_id="BTC-USD",
                kraken_symbol="BTC/USD",
            ),
        )
    )

    provider = KrakenConnectivityProbeProvider(
        bindings=registry,
        http_get=lambda *args, **kwargs: _Response(payload),
    )
    provider.fetch(
        MarketDataQuery(
            instrument_id="instrument:crypto:btcusd",
            data_type=MarketDataType.QUOTE,
            as_of=cutoff,
            venue="KRAKEN",
            limit=1,
        )
    )

    assert payload["result"]["bids"][0]["publication_ts"] == future_publication.isoformat()
    assert payload["result"]["asks"][0]["publication_ts"] == future_publication.isoformat()
