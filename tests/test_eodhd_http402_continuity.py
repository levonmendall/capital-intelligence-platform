"""Regression coverage for bounded EODHD directory continuity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import (
    EODHDBindingRegistry,
    EODHDProvider,
    EODHDProviderError,
    EODHDRetrievalPolicy,
)


NOW = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def provider(
    responses,
    *,
    cache_dir: Path,
    now: datetime = NOW,
    calls: list[tuple[str, dict[str, object]]] | None = None,
) -> EODHDProvider:
    queue = list(responses)

    def get(url, *, params, timeout):
        del timeout
        if calls is not None:
            calls.append((url, dict(params)))
        return queue.pop(0)

    return EODHDProvider(
        api_token="secret-token",
        bindings=EODHDBindingRegistry(()),
        http_get=get,
        clock=lambda: now,
        sleeper=lambda _: None,
        retrieval_policy=EODHDRetrievalPolicy(max_attempts=1),
        directory_cache_dir=cache_dir,
        directory_cache_max_age=timedelta(hours=72),
    )


def query(
    as_of: datetime = NOW,
    *,
    provider_symbol: str = "CC",
) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol=provider_symbol,
        as_of=as_of,
    )


def live_payload(exchange: str = "CC"):
    return [
        {
            "Code": "BTC-USD" if exchange == "CC" else "VOD",
            "Name": "Bitcoin / US Dollar" if exchange == "CC" else "Vodafone",
            "Exchange": exchange,
            "Currency": "USD" if exchange == "CC" else "GBP",
            "Type": "Currency" if exchange == "CC" else "Common Stock",
        }
    ]


@pytest.mark.parametrize("status_code", (402, 404))
def test_recent_directory_cache_skips_status_probe(
    tmp_path: Path,
    status_code: int,
) -> None:
    provider(
        [Response(live_payload())],
        cache_dir=tmp_path,
    ).fetch_dataset(query())
    later = NOW + timedelta(hours=2)
    calls: list[tuple[str, dict[str, object]]] = []

    snapshot = provider(
        [Response({}, status_code)],
        cache_dir=tmp_path,
        now=later,
        calls=calls,
    ).fetch_dataset(query(later))

    assert snapshot.quality_state is DataQualityState.CACHED
    assert snapshot.observed_at == NOW
    assert snapshot.payload["active"] == live_payload()
    assert calls == []
    assert any("cache before live refresh" in item for item in snapshot.limitations)


@pytest.mark.parametrize("status_code", (402, 404))
def test_lse_recent_active_cache_keeps_bounded_delisted_probe(
    tmp_path: Path,
    status_code: int,
) -> None:
    provider(
        [Response(live_payload("LSE")), Response([])],
        cache_dir=tmp_path,
    ).fetch_dataset(query(provider_symbol="LSE"))
    later = NOW + timedelta(hours=2)
    calls: list[tuple[str, dict[str, object]]] = []

    snapshot = provider(
        [Response({}, status_code)],
        cache_dir=tmp_path,
        now=later,
        calls=calls,
    ).fetch_dataset(query(later, provider_symbol="LSE"))

    assert snapshot.quality_state is DataQualityState.CACHED
    assert snapshot.observed_at == NOW
    assert snapshot.payload["active"] == live_payload("LSE")
    assert snapshot.payload["delisted"] == []
    assert len(calls) == 1
    assert calls[0][0].endswith("/exchange-symbol-list/LSE")
    assert calls[0][1].get("delisted") == 1
    assert any("cache before live refresh" in item for item in snapshot.limitations)
    assert any("delisted-symbol directory" in item for item in snapshot.limitations)
    assert any(f"HTTP {status_code}" in item for item in snapshot.limitations)


def test_http_402_without_recent_active_cache_remains_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(EODHDProviderError, match="HTTP 402"):
        provider(
            [Response({}, 402)],
            cache_dir=tmp_path,
        ).fetch_dataset(query())


def test_authentication_failure_never_uses_expired_continuity_cache(
    tmp_path: Path,
) -> None:
    provider(
        [Response(live_payload())],
        cache_dir=tmp_path,
    ).fetch_dataset(query())
    later = NOW + timedelta(hours=73)

    with pytest.raises(EODHDProviderError, match="HTTP 403.*non-retryable"):
        provider(
            [Response({}, 403)],
            cache_dir=tmp_path,
            now=later,
        ).fetch_dataset(query(later))
