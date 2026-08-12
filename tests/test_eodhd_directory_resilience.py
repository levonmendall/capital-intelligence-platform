"""Regression coverage for fail-closed EODHD directory resilience."""

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


NOW = datetime(2026, 8, 2, 15, 45, tzinfo=timezone.utc)


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
    calls: list[tuple[str, dict[str, object], int]] | None = None,
    cache_age: timedelta = timedelta(hours=72),
) -> EODHDProvider:
    queue = list(responses)

    def get(url, *, params, timeout):
        if calls is not None:
            calls.append((url, dict(params), timeout))
        return queue.pop(0)

    return EODHDProvider(
        api_token="secret-token",
        bindings=EODHDBindingRegistry(()),
        http_get=get,
        clock=lambda: now,
        sleeper=lambda _: None,
        retrieval_policy=EODHDRetrievalPolicy(max_attempts=1),
        directory_cache_dir=cache_dir,
        directory_cache_max_age=cache_age,
    )


def query(as_of: datetime = NOW) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="CC",
        as_of=as_of,
    )


def live_payload():
    return [
        {
            "Code": "BTC-USD",
            "Name": "Bitcoin / US Dollar",
            "Exchange": "CC",
            "Currency": "USD",
            "Type": "Currency",
        }
    ]


def test_cc_directory_uses_active_endpoint_without_delisted_parameter(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object], int]] = []
    snapshot = provider(
        [Response(live_payload())],
        cache_dir=tmp_path,
        calls=calls,
    ).fetch_dataset(query())

    assert snapshot.quality_state is DataQualityState.LIVE
    assert snapshot.payload["active"] == live_payload()
    assert snapshot.payload["delisted"] == []
    assert len(calls) == 1
    assert calls[0][0].endswith("/exchange-symbol-list/CC")
    assert "delisted" not in calls[0][1]
    assert calls[0][2] == 90


def test_recent_successful_directory_cache_skips_live_refresh(
    tmp_path: Path,
) -> None:
    provider([Response(live_payload())], cache_dir=tmp_path).fetch_dataset(query())
    later = NOW + timedelta(hours=2)
    calls: list[tuple[str, dict[str, object], int]] = []
    snapshot = provider(
        [Response({}, 503)],
        cache_dir=tmp_path,
        now=later,
        calls=calls,
    ).fetch_dataset(query(later))

    assert snapshot.quality_state is DataQualityState.CACHED
    assert snapshot.observed_at == NOW
    assert snapshot.payload["active"] == live_payload()
    assert calls == []
    assert any("cache before live refresh" in item for item in snapshot.limitations)
    assert any("cache age=2.0 hours" in item for item in snapshot.limitations)


def test_expired_directory_cache_remains_fail_closed(tmp_path: Path) -> None:
    provider([Response(live_payload())], cache_dir=tmp_path).fetch_dataset(query())
    later = NOW + timedelta(hours=73)

    with pytest.raises(EODHDProviderError, match="HTTP 503"):
        provider(
            [Response({}, 503)],
            cache_dir=tmp_path,
            now=later,
        ).fetch_dataset(query(later))


def test_authentication_failure_never_uses_cache(tmp_path: Path) -> None:
    provider([Response(live_payload())], cache_dir=tmp_path).fetch_dataset(query())
    later = NOW + timedelta(hours=1)

    with pytest.raises(EODHDProviderError, match="HTTP 403.*non-retryable"):
        provider(
            [Response({}, 403)],
            cache_dir=tmp_path,
            now=later,
        ).fetch_dataset(query(later))


def test_failure_diagnostic_is_precise_and_secret_free(tmp_path: Path) -> None:
    with pytest.raises(EODHDProviderError) as captured:
        provider(
            [Response({}, 429)],
            cache_dir=tmp_path,
        ).fetch_dataset(query())

    detail = str(captured.value)
    assert "HTTP 429" in detail
    assert "retryable" in detail
    assert "secret-token" not in detail
