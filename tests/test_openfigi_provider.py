"""Tests for the free OpenFIGI v3 identity adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data import IdentifierScheme
from providers.openfigi import (
    OPENFIGI_MAPPING_URL,
    OpenFigiMappingJob,
    OpenFigiProvider,
    OpenFigiProviderError,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


def test_anonymous_v3_mapping_preserves_identity_and_metadata() -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response(
            [
                {
                    "data": [
                        {
                            "figi": "BBG000B9XRY4",
                            "ticker": "AAPL",
                            "name": "APPLE INC",
                            "exchCode": "US",
                            "marketSector": "Equity",
                            "securityType": "Common Stock",
                            "securityType2": "Common Stock",
                            "compositeFIGI": "BBG000B9Y5X2",
                            "shareClassFIGI": "BBG001S5N8V8",
                        }
                    ]
                }
            ]
        )

    provider = OpenFigiProvider(
        clock=lambda: NOW,
        http_post=post,
    )
    result = provider.map_identifiers(
        (OpenFigiMappingJob("ID_BB_GLOBAL", "BBG000B9XRY4"),)
    )[0]

    assert captured["url"] == OPENFIGI_MAPPING_URL
    assert captured["json"] == [
        {"idType": "ID_BB_GLOBAL", "idValue": "BBG000B9XRY4"}
    ]
    assert "X-OPENFIGI-APIKEY" not in captured["headers"]
    assert provider.maximum_jobs_per_request == 5
    assert result.retrieved_at == NOW
    assert result.matches[0].figi == "BBG000B9XRY4"
    assert {item.scheme for item in result.matches[0].identifiers} == {
        IdentifierScheme.FIGI,
        IdentifierScheme.TICKER,
    }


def test_free_api_key_raises_batch_limit_and_stays_in_header_only() -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> _Response:
        captured.update(kwargs)
        return _Response([{"warning": "No identifier found.", "data": []}])

    provider = OpenFigiProvider(
        api_key="free-key-value",
        clock=lambda: NOW,
        http_post=post,
    )
    result = provider.map_identifiers(
        (OpenFigiMappingJob("ID_ISIN", "US0378331005"),)
    )[0]

    assert provider.authenticated is True
    assert provider.maximum_jobs_per_request == 100
    assert captured["headers"]["X-OPENFIGI-APIKEY"] == "free-key-value"
    assert "free-key-value" not in str(captured["json"])
    assert result.matches == ()
    assert result.warning == "No identifier found."


def test_anonymous_batch_and_provider_errors_fail_closed() -> None:
    provider = OpenFigiProvider(
        clock=lambda: NOW,
        http_post=lambda *args, **kwargs: _Response([], status_code=429),
    )
    jobs = tuple(
        OpenFigiMappingJob("ID_BB_GLOBAL", f"BBG00000000{index}")
        for index in range(6)
    )
    with pytest.raises(OpenFigiProviderError, match="5-job limit"):
        provider.map_identifiers(jobs)

    with pytest.raises(OpenFigiProviderError, match="HTTP 429"):
        provider.map_identifiers((jobs[0],))


def test_mapping_rejects_conflicting_exchange_filters() -> None:
    with pytest.raises(ValueError, match="cannot both"):
        OpenFigiMappingJob(
            "TICKER",
            "AAPL",
            exchange_code="US",
            mic_code="XNAS",
        )
