from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import EODHDBindingRegistry, EODHDProvider


NOW = datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)


class FakeResponse:
    status_code = 200

    @staticmethod
    def json():
        return {"General": {"Code": "AAPL", "Exchange": "US"}}


def provider_at(retrieved_at: datetime) -> EODHDProvider:
    return EODHDProvider(
        api_token="secret-token",
        bindings=EODHDBindingRegistry(()),
        clock=lambda: retrieved_at,
        http_get=lambda *_args, **_kwargs: FakeResponse(),
        sleeper=lambda _seconds: None,
    )


def query() -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.FUNDAMENTALS,
        provider_symbol="AAPL.US",
        as_of=NOW,
    )


def test_live_retrieval_at_five_minute_boundary_is_recorded_at_collection_time() -> None:
    retrieved_at = NOW + timedelta(minutes=5)

    snapshot = provider_at(retrieved_at).fetch_dataset(query())

    assert snapshot.query.as_of == retrieved_at
    assert snapshot.available_at == retrieved_at


def test_retrieval_beyond_live_boundary_remains_fail_closed() -> None:
    with pytest.raises(ValueError, match="snapshot was not available at query as_of"):
        provider_at(NOW + timedelta(minutes=5, seconds=1)).fetch_dataset(query())
