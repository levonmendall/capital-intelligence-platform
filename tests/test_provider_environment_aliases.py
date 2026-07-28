from __future__ import annotations

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import ProviderDatasetType
from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderSettings,
)
from providers.environment_aliases import (
    PROVIDER_ENVIRONMENT_ALIASES,
    install_provider_environment_aliases,
    normalize_provider_environment,
    provider_environment_value,
)
from providers.eodhd import EODHDProvider
from providers.openfigi import OpenFigiProvider


def test_normalize_provider_environment_populates_runtime_canonical_names() -> None:
    source = {
        "DATABENTO_API_KEY": "databento-value",
        "EODHD_API_KEY": "eodhd-value",
        "OPEN_FIGI_API_KEY": "openfigi-value",
        "ALPHAVANTAGE_API_KEY": "alpha-value",
        "TWELVE_API_KEY": "twelve-value",
    }

    normalized = normalize_provider_environment(source)

    assert normalized["CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"] == "databento-value"
    assert normalized["CAPITAL_INTELLIGENCE_EODHD_API_TOKEN"] == "eodhd-value"
    assert normalized["OPENFIGI_API_KEY"] == "openfigi-value"
    assert normalized["ALPHAVANTAGE_API_KEY"] == "alpha-value"
    assert normalized["TWELVE_API_KEY"] == "twelve-value"
    assert "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY" not in source


def test_canonical_provider_secret_always_wins() -> None:
    normalized = normalize_provider_environment(
        {
            "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": "canonical-value",
            "EODHD_API_KEY": "alias-value",
        }
    )

    assert normalized["CAPITAL_INTELLIGENCE_EODHD_API_TOKEN"] == "canonical-value"


def test_install_provider_aliases_mutates_only_missing_canonical_names() -> None:
    environment = {
        "DATABENTO_API_KEY": "databento-value",
        "OPENFIGI_API_KEY": "canonical-openfigi",
        "OPEN_FIGI_API_KEY": "alias-openfigi",
    }

    installed = install_provider_environment_aliases(environment)

    assert installed == ("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",)
    assert environment["CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"] == "databento-value"
    assert environment["OPENFIGI_API_KEY"] == "canonical-openfigi"


def test_runtime_eodhd_and_openfigi_adapters_receive_screenshot_aliases(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    monkeypatch.setenv("EODHD_API_KEY", "runtime-eodhd")
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "runtime-openfigi")

    installed = install_provider_environment_aliases()

    assert "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN" in installed
    assert "OPENFIGI_API_KEY" in installed
    assert EODHDProvider().api_token == "runtime-eodhd"
    assert OpenFigiProvider().api_key == "runtime-openfigi"


def test_configured_databento_binding_receives_short_repository_secret(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY", raising=False)
    monkeypatch.setenv("DATABENTO_API_KEY", "runtime-databento")
    install_provider_environment_aliases()
    settings = ConfiguredDatasetProviderSettings(
        provider_identifier="DATABENTO",
        source_version="test.v1",
        base_url="https://example.test",
        credential_environment_variables=(
            "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
        ),
        bindings=(
            ConfiguredDatasetBinding(
                dataset_type=ProviderDatasetType.MARKET_HISTORY,
                path="/history",
                headers={
                    "X-API-Key": "${CAPITAL_INTELLIGENCE_DATABENTO_API_KEY}"
                },
                quality_state=DataQualityState.LIVE,
                availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            ),
        ),
    )

    provider = ConfiguredDatasetProvider(settings)

    assert provider.environment["CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"] == (
        "runtime-databento"
    )


def test_provider_environment_value_uses_ordered_aliases() -> None:
    value = provider_environment_value(
        "CANONICAL",
        "FIRST_ALIAS",
        "SECOND_ALIAS",
        environment={"FIRST_ALIAS": "first", "SECOND_ALIAS": "second"},
    )

    assert value == "first"


def test_alias_registry_contains_every_runtime_gap() -> None:
    assert PROVIDER_ENVIRONMENT_ALIASES[
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"
    ] == ("DATABENTO_API_KEY",)
    assert "EODHD_API_KEY" in PROVIDER_ENVIRONMENT_ALIASES[
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN"
    ]
    assert PROVIDER_ENVIRONMENT_ALIASES["OPENFIGI_API_KEY"] == (
        "OPEN_FIGI_API_KEY",
    )
