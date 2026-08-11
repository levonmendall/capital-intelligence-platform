from __future__ import annotations

from provider_environment import normalize_provider_environment
from providers.provider_activation_audit import activation_summary, audit_provider_activation


def _record(records, provider_id: str):
    return next(item for item in records if item.provider_id == provider_id)


def test_provider_alias_groups_populate_all_supported_names() -> None:
    source = {
        "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY": "massive-secret",
        "DATABENTO_API_TOKEN": "databento-secret",
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID": "finra-id",
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET": "finra-secret",
        "LSEG_MARKET_DATA_API_KEY": "lseg-secret",
    }

    normalized = normalize_provider_environment(source)

    assert normalized["MASSIVE_API_KEY"] == "massive-secret"
    assert normalized["POLYGON_API_KEY"] == "massive-secret"
    assert normalized["DATABENTO_API_KEY"] == "databento-secret"
    assert normalized["CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"] == "databento-secret"
    assert normalized["FINRA_CLIENT_ID"] == "finra-id"
    assert normalized["FINRA_CLIENT_SECRET"] == "finra-secret"
    assert normalized["CAPITAL_INTELLIGENCE_LSEG_MARKET_DATA_API_KEY"] == "lseg-secret"


def test_provider_alias_groups_never_replace_existing_canonical_value() -> None:
    normalized = normalize_provider_environment(
        {
            "MASSIVE_API_KEY": "canonical",
            "POLYGON_API_KEY": "legacy",
        }
    )

    assert normalized["MASSIVE_API_KEY"] == "canonical"
    assert normalized["POLYGON_API_KEY"] == "legacy"
    assert normalized["CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY"] == "canonical"


def test_activation_audit_distinguishes_routed_and_unrouted_sources(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "all_market_provider_bundle.json").write_text(
        """
        {
          "schema_version": "all-market-provider-bundle.v1",
          "members": [
            {
              "provider_identifier": "lseg-global-market-data",
              "roles": ["global_execution_market_data"],
              "credential_environment_variables": [
                "CAPITAL_INTELLIGENCE_LSEG_MARKET_DATA_API_KEY"
              ]
            },
            {
              "provider_identifier": "databento-execution-data",
              "roles": ["derivative_contract_data"],
              "credential_environment_variables": [
                "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    environment = {
        "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY": "massive-secret",
        "DATABENTO_API_KEY": "databento-secret",
        "LSEG_MARKET_DATA_API_KEY": "lseg-secret",
        "FINRA_CLIENT_ID": "finra-id",
        "FINRA_CLIENT_SECRET": "finra-secret",
    }

    records = audit_provider_activation(environment, repository_root=tmp_path)

    assert _record(records, "massive").state == "active"
    assert _record(records, "treasury-fiscal-data").state == "keyless_active"
    assert _record(records, "finra").state == "configured_but_unrouted"
    assert _record(records, "lseg-global-market-data").state == "configured_but_unrouted"
    assert not any(item.provider_id == "databento-execution-data" for item in records)


def test_activation_summary_is_credential_safe(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "all_market_provider_bundle.json").write_text(
        '{"schema_version":"all-market-provider-bundle.v1","members":[]}',
        encoding="utf-8",
    )
    environment = {
        "MASSIVE_API_KEY": "do-not-leak-massive",
        "FINRA_CLIENT_ID": "do-not-leak-id",
        "FINRA_CLIENT_SECRET": "do-not-leak-secret",
    }

    payload = activation_summary(environment, repository_root=tmp_path)
    serialized = str(payload)

    assert payload["credential_values_included"] is False
    assert "do-not-leak" not in serialized
    assert "MASSIVE_API_KEY" in serialized
