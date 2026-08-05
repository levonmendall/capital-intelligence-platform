from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.twelve_data_reference import TwelveDataReferenceError
from providers.twelve_data_reference_rate_limited import (
    TwelveDataRateLimitedReferenceProvider,
)


UTC = timezone.utc


class _Response:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload


def _query(as_of: datetime) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="SA",
        as_of=as_of,
        limit=1_000,
    )


def _brazil_row() -> dict[str, str]:
    return {
        "symbol": "PETR4",
        "name": "Petroleo Brasileiro SA Petrobras",
        "currency": "BRL",
        "exchange": "B3",
        "mic_code": "BVMF",
        "country": "Brazil",
        "type": "Common Stock",
    }


def _successful_catalog(calls: list[str]):
    def fetch(
        _url: str,
        *,
        params: dict[str, object],
        timeout: int,
    ) -> _Response:
        assert timeout > 0
        mic = str(params.get("mic_code") or "")
        calls.append(mic)
        if mic == "BVMF":
            return _Response(
                200,
                {
                    "status": "ok",
                    "count": 1,
                    "data": [_brazil_row()],
                },
            )
        if mic == "XBSP":
            return _Response(
                200,
                {
                    "status": "ok",
                    "count": 0,
                    "data": [],
                },
            )
        raise AssertionError(f"unexpected Twelve Data selector: {params}")

    return fetch


def _provider(
    *,
    cache_directory,
    now: datetime,
    http_get,
    cache_max_age_seconds: float = 259_200.0,
) -> TwelveDataRateLimitedReferenceProvider:
    return TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=http_get,
        clock=lambda: now,
        sleeper=lambda _seconds: None,
        max_rate_limit_retries=0,
        minimum_request_interval_seconds=0.0,
        cache_directory=cache_directory,
        cache_max_age_seconds=cache_max_age_seconds,
    )


def test_complete_exchange_snapshot_is_reused_before_more_provider_calls(
    tmp_path,
) -> None:
    now = datetime(2026, 8, 5, 22, 0, tzinfo=UTC)
    calls: list[str] = []
    provider = _provider(
        cache_directory=tmp_path,
        now=now,
        http_get=_successful_catalog(calls),
    )

    live = provider.fetch_dataset(_query(now))
    cached = provider.fetch_dataset(_query(now))

    assert calls == ["BVMF", "XBSP"]
    assert cached.quality_state is DataQualityState.CACHED
    assert cached.payload == live.payload
    assert cached.provider_record_id == live.provider_record_id
    assert any(
        "before making another provider request" in item
        for item in cached.limitations
    )


def test_fresh_snapshot_survives_provider_reconstruction(
    tmp_path,
) -> None:
    now = datetime(2026, 8, 5, 22, 0, tzinfo=UTC)
    calls: list[str] = []
    _provider(
        cache_directory=tmp_path,
        now=now,
        http_get=_successful_catalog(calls),
    ).fetch_dataset(_query(now))

    def unexpected_request(*_args: Any, **_kwargs: Any) -> _Response:
        raise AssertionError("fresh cache must prevent a remote catalog request")

    later = now + timedelta(hours=1)
    cached = _provider(
        cache_directory=tmp_path,
        now=later,
        http_get=unexpected_request,
    ).fetch_dataset(_query(later))

    assert calls == ["BVMF", "XBSP"]
    assert cached.quality_state is DataQualityState.CACHED
    assert cached.payload["active"][0]["Code"] == "PETR4"
    assert cached.retrieved_at == now


def test_default_cache_directory_uses_governed_data_volume(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(
        "CAPITAL_INTELLIGENCE_TWELVE_DATA_REFERENCE_CACHE_DIRECTORY",
        raising=False,
    )

    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=lambda *_args, **_kwargs: None,
        clock=lambda: datetime(2026, 8, 5, 22, 0, tzinfo=UTC),
    )

    assert provider.cache_directory == (
        tmp_path / "provider_cache" / "twelve_data_reference"
    )


@pytest.mark.parametrize("failure_mode", ["stale", "corrupt"])
def test_stale_or_corrupt_snapshot_cannot_mask_terminal_throttling(
    tmp_path,
    failure_mode: str,
) -> None:
    now = datetime(2026, 8, 5, 22, 0, tzinfo=UTC)
    provider = _provider(
        cache_directory=tmp_path,
        now=now,
        http_get=_successful_catalog([]),
    )
    query = _query(now)
    provider.fetch_dataset(query)

    cache_path = provider._cache_path(query)
    if failure_mode == "corrupt":
        envelope = json.loads(cache_path.read_text(encoding="utf-8"))
        envelope["snapshot"]["payload"]["active"][0]["Name"] = "tampered"
        cache_path.write_text(json.dumps(envelope), encoding="utf-8")
        request_time = now + timedelta(minutes=1)
        max_age_seconds = 259_200.0
    else:
        request_time = now + timedelta(hours=2)
        max_age_seconds = 3_600.0

    calls = 0

    def throttled(
        _url: str,
        *,
        params: dict[str, object],
        timeout: int,
    ) -> _Response:
        nonlocal calls
        calls += 1
        assert params["mic_code"] == "BVMF"
        assert timeout > 0
        return _Response(
            429,
            {
                "status": "error",
                "message": "quota exhausted",
            },
        )

    failing_provider = _provider(
        cache_directory=tmp_path,
        now=request_time,
        http_get=throttled,
        cache_max_age_seconds=max_age_seconds,
    )

    with pytest.raises(
        TwelveDataReferenceError,
        match=r"Twelve Data stock catalog returned HTTP 429",
    ):
        failing_provider.fetch_dataset(_query(request_time))

    assert calls == 1
