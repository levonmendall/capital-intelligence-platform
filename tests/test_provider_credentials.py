from __future__ import annotations

import json
from typing import Any

import pytest

import run_provider_secret_validation as command
from providers.provider_credentials import (
    AlphaVantageCredentialProbe,
    DatabentoCredentialProbe,
    EODHDCredentialProbe,
    ProviderCredentialProbeError,
    TwelveDataCredentialProbe,
    environment_credential,
)


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


def test_environment_credential_uses_first_non_empty_alias(monkeypatch) -> None:
    monkeypatch.setenv("FIRST_PROVIDER_KEY", "  ")
    monkeypatch.setenv("SECOND_PROVIDER_KEY", "second-secret")

    selected = environment_credential(
        "FIRST_PROVIDER_KEY",
        "SECOND_PROVIDER_KEY",
    )

    assert selected is not None
    assert selected.name == "SECOND_PROVIDER_KEY"
    assert selected.value == "second-secret"


def test_alpha_vantage_probe_validates_global_quote() -> None:
    captured: dict[str, Any] = {}

    def http_get(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response(
            {
                "Global Quote": {
                    "01. symbol": "IBM",
                    "05. price": "214.31",
                }
            }
        )

    evidence = AlphaVantageCredentialProbe(
        "alpha-secret",
        http_get=http_get,
    ).probe()

    assert captured["params"]["apikey"] == "alpha-secret"
    assert captured["params"]["function"] == "GLOBAL_QUOTE"
    assert evidence["symbol"] == "IBM"
    assert evidence["execution_authority"] is False


def test_alpha_vantage_provider_notice_fails_closed() -> None:
    provider = AlphaVantageCredentialProbe(
        "alpha-secret",
        http_get=lambda *_args, **_kwargs: _Response(
            {"Information": "request frequency limit reached"}
        ),
    )

    with pytest.raises(ProviderCredentialProbeError, match="provider notice"):
        provider.probe()


def test_twelve_data_probe_validates_quote() -> None:
    captured: dict[str, Any] = {}

    def http_get(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response({"symbol": "AAPL", "close": "212.44"})

    evidence = TwelveDataCredentialProbe(
        "twelve-secret",
        http_get=http_get,
    ).probe()

    assert captured["params"]["apikey"] == "twelve-secret"
    assert evidence["symbol"] == "AAPL"
    assert evidence["execution_authority"] is False


def test_twelve_data_error_payload_fails_closed() -> None:
    provider = TwelveDataCredentialProbe(
        "twelve-secret",
        http_get=lambda *_args, **_kwargs: _Response(
            {"status": "error", "code": 401, "message": "invalid key"}
        ),
    )

    with pytest.raises(ProviderCredentialProbeError, match="rejected"):
        provider.probe()


def test_databento_probe_uses_basic_auth_and_lists_datasets() -> None:
    captured: dict[str, Any] = {}

    def http_get(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response(["DBEQ.BASIC", "GLBX.MDP3"])

    evidence = DatabentoCredentialProbe(
        "db-test-key",
        http_get=http_get,
    ).probe()

    assert captured["auth"] == ("db-test-key", "")
    assert evidence["dataset_count"] == 2
    assert evidence["execution_authority"] is False


def test_eodhd_probe_validates_user_entitlement() -> None:
    captured: dict[str, Any] = {}

    def http_get(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response(
            {
                "name": "Provider Test",
                "subscriptionType": "free",
                "apiRequests": 2,
                "apiRequestsDate": "2026-07-28",
                "dailyRateLimit": 1000,
            }
        )

    evidence = EODHDCredentialProbe(
        "eodhd-secret",
        http_get=http_get,
    ).probe()

    assert captured["params"]["api_token"] == "eodhd-secret"
    assert captured["params"]["fmt"] == "json"
    assert evidence["usage_metadata_available"] is True
    assert evidence["subscription_metadata_available"] is True
    assert evidence["execution_authority"] is False


def test_eodhd_unrecognized_payload_fails_closed() -> None:
    provider = EODHDCredentialProbe(
        "eodhd-secret",
        http_get=lambda *_args, **_kwargs: _Response({"message": "invalid token"}),
    )

    with pytest.raises(ProviderCredentialProbeError, match="entitlement metadata"):
        provider.probe()


def test_command_redacts_every_supported_secret(monkeypatch) -> None:
    monkeypatch.setenv("EODHD_API_KEY", "sensitive-provider-value")

    message = command._safe_error(
        RuntimeError("request failed for sensitive-provider-value")
    )

    assert "sensitive-provider-value" not in message
    assert "[REDACTED]" in message


def test_command_report_remains_non_authoritative(monkeypatch, tmp_path) -> None:
    passing = lambda name: {
        "provider": name,
        "configured": True,
        "passed": True,
        "credential_names": [f"{name.upper()}_KEY"],
        "selected_credential": f"{name.upper()}_KEY",
        "evidence": {"connected": True},
        "provider_certified": False,
        "paper_test_authorized": False,
        "real_money_authorized": False,
    }
    monkeypatch.setattr(command, "_alpaca", lambda: passing("alpaca-paper"))
    monkeypatch.setattr(command, "_fred", lambda: passing("fred"))
    monkeypatch.setattr(command, "_eodhd", lambda: passing("eodhd"))
    monkeypatch.setattr(command, "_openfigi", lambda: passing("openfigi"))
    monkeypatch.setattr(command, "_alpha_vantage", lambda: passing("alpha-vantage"))
    monkeypatch.setattr(command, "_twelve_data", lambda: passing("twelve-data"))
    monkeypatch.setattr(command, "_tradier", lambda: passing("tradier"))
    monkeypatch.setattr(command, "_finra", lambda: passing("finra-fixed-income"))
    output = tmp_path / "provider-validation.json"

    exit_code = command.main(["--require-all", "--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["state"] == "passed"
    assert payload["configured_provider_count"] == 8
    assert payload["passed_provider_count"] == 8
    assert {item["provider"] for item in payload["providers"]} == {
        "alpaca-paper",
        "fred",
        "eodhd",
        "openfigi",
        "alpha-vantage",
        "twelve-data",
        "tradier",
        "finra-fixed-income",
    }
    assert payload["secret_values_disclosed"] is False
    assert payload["provider_certification_granted"] is False
    assert payload["paper_test_authorized"] is False
    assert payload["execution_authority_granted"] is False
    assert payload["real_money_authorized"] is False


def test_screenshot_aliases_are_supported() -> None:
    assert "ALPHAVANTAGE_API_KEY" in AlphaVantageCredentialProbe.environment_names
    assert "DATABENTO_API_KEY" in DatabentoCredentialProbe.environment_names
    assert "EODHD_API_KEY" in EODHDCredentialProbe.environment_names
    assert "OPEN_FIGI_API_KEY" in command.OPENFIGI_NAMES
    assert "TWELVE_API_KEY" in TwelveDataCredentialProbe.environment_names
