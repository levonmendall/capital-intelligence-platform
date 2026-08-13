from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import EODHDProvider


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


class _StubProvider(EODHDProvider):
    name = "eodhd"
    timeout = 1.0

    def __init__(self, *, cached: bool) -> None:
        self.cached = cached
        self.requests: list[tuple[str, dict[str, object]]] = []

    def _now(self):
        return NOW

    def _active_symbol_directory(self, provider_symbol: str, *, retrieved_at: datetime):
        assert provider_symbol == "US"
        assert retrieved_at == NOW
        cached_at = NOW - timedelta(hours=1) if self.cached else None
        quality = DataQualityState.CACHED if self.cached else DataQualityState.LIVE
        return ([{"Code": "AAA"}], quality, cached_at, ())

    def _request(self, path: str, *, params, resource: str, timeout: float):
        self.requests.append((path, dict(params)))
        return [{"Code": "OLD", "Delisted": True}]

    def _bounded_payload(self, payload, limit: int):
        return payload

    def _payload_observed_at(self, payload, *, fallback: datetime):
        return fallback


def _query() -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="US",
        as_of=NOW,
        limit=100,
    )


def test_cached_active_directory_defers_live_delisted_refresh():
    provider = _StubProvider(cached=True)

    snapshot = provider.fetch_dataset(_query())

    assert provider.requests == []
    assert snapshot.payload == {"active": [{"Code": "AAA"}], "delisted": []}
    assert snapshot.quality_state is DataQualityState.CACHED
    assert any("live delisted-symbol refresh was deferred" in item for item in snapshot.limitations)
    assert any("remain fail-closed" in item for item in snapshot.limitations)


def test_live_active_directory_preserves_delisted_refresh():
    provider = _StubProvider(cached=False)

    snapshot = provider.fetch_dataset(_query())

    assert provider.requests == [
        ("/exchange-symbol-list/US", {"delisted": 1}),
    ]
    assert snapshot.payload["delisted"] == [{"Code": "OLD", "Delisted": True}]
    assert not any("live delisted-symbol refresh was deferred" in item for item in snapshot.limitations)
