from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderError,
    ConfiguredDatasetProviderSettings,
    TransportResponse,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)


def _settings() -> ConfiguredDatasetProviderSettings:
    return ConfiguredDatasetProviderSettings(
        provider_identifier="configured-test-provider",
        source_version="api.v1",
        base_url="https://provider.example.test/api/",
        credential_environment_variables=("TEST_PROVIDER_TOKEN",),
        default_headers={"Authorization": "Bearer ${TEST_PROVIDER_TOKEN}"},
        bindings=(
            ConfiguredDatasetBinding(
                dataset_type=ProviderDatasetType.MARKET_PRICES,
                path="prices/{symbol}",
                query_parameters={
                    "as_of": "{as_of}",
                    "limit": "{limit}",
                },
                payload_path="data",
                observed_at_path="meta.observed_at",
                available_at_path="meta.available_at",
                provider_record_id_path="meta.request_id",
                quality_state=DataQualityState.LIVE,
                availability_basis=AvailabilityBasis.PROVIDER_TIMESTAMP,
            ),
        ),
    )


def test_configured_provider_renders_secret_without_disclosing_it() -> None:
    captured = {}

    def transport(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return TransportResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=(
                b'{"meta":{"observed_at":"2026-07-28T01:59:00+00:00",'
                b'"available_at":"2026-07-28T01:59:30+00:00",'
                b'"request_id":"request:1"},'
                b'"data":[{"close":100.0}]}'
            ),
        )

    provider = ConfiguredDatasetProvider(
        _settings(),
        environment={"TEST_PROVIDER_TOKEN": "secret-token"},
        transport=transport,
        clock=lambda: datetime(2026, 7, 28, 2, 1, tzinfo=UTC),
    )
    snapshot = provider.fetch_dataset(
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.MARKET_PRICES,
            provider_symbol="ABC.XNYS",
            as_of=AS_OF,
            limit=25,
        )
    )

    assert captured["authorization"] == "Bearer secret-token"
    assert "secret-token" not in captured["url"]
    assert "ABC.XNYS" in captured["url"]
    assert "limit=25" in captured["url"]
    assert snapshot.payload == [{"close": 100.0}]
    assert snapshot.provider_record_id == "request:1"
    assert snapshot.available_at <= AS_OF
    assert snapshot.to_dict()["content_hash"] == snapshot.content_hash


def test_configured_provider_requires_declared_credentials() -> None:
    with pytest.raises(ConfiguredDatasetProviderError, match="credentials"):
        ConfiguredDatasetProvider(_settings(), environment={})


def test_configured_provider_rejects_information_after_as_of() -> None:
    def transport(request, timeout):
        return TransportResponse(
            status=200,
            headers={},
            body=(
                b'{"meta":{"observed_at":"2026-07-28T02:01:00+00:00",'
                b'"available_at":"2026-07-28T02:01:00+00:00",'
                b'"request_id":"future"},"data":[]}'
            ),
        )

    provider = ConfiguredDatasetProvider(
        _settings(),
        environment={"TEST_PROVIDER_TOKEN": "secret-token"},
        transport=transport,
        clock=lambda: datetime(2026, 7, 28, 2, 2, tzinfo=UTC),
    )

    with pytest.raises(ConfiguredDatasetProviderError, match="unavailable"):
        provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.MARKET_PRICES,
                provider_symbol="ABC.XNYS",
                as_of=AS_OF,
            )
        )


def test_configured_provider_fails_closed_for_unbound_dataset() -> None:
    provider = ConfiguredDatasetProvider(
        _settings(),
        environment={"TEST_PROVIDER_TOKEN": "secret-token"},
        transport=lambda request, timeout: TransportResponse(200, b"{}", {}),
    )

    with pytest.raises(ConfiguredDatasetProviderError, match="no binding"):
        provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.VOLATILITY_SURFACES,
                provider_symbol="SPX",
                as_of=AS_OF,
            )
        )
