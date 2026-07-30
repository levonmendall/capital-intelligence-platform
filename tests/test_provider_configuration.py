from __future__ import annotations

from provider_configuration import (
    alpaca_credential_readiness,
    fred_credential_readiness,
    safe_provider_error,
)


def test_fred_missing_and_placeholder_credentials_are_not_configured() -> None:
    missing = fred_credential_readiness({})
    assert missing.state == "missing"
    assert not missing.configured
    assert "FRED_API_KEY" in missing.detail

    placeholder = fred_credential_readiness(
        {"FRED_API_KEY": "PASTE_YOUR_FRED_API_KEY"}
    )
    assert placeholder.state == "placeholder"
    assert not placeholder.configured
    assert "placeholder" in placeholder.detail.lower()
    assert "PASTE_YOUR_FRED_API_KEY" not in placeholder.detail


def test_fred_configured_key_is_reported_without_exposing_value() -> None:
    readiness = fred_credential_readiness({"FRED_API_KEY": "abc123-real-key"})
    assert readiness.configured
    assert readiness.state == "configured"
    assert "abc123-real-key" not in readiness.detail


def test_alpaca_requires_matching_nonplaceholder_pair() -> None:
    missing = alpaca_credential_readiness({"APCA_API_KEY_ID": "paper-key"})
    assert missing.state == "missing"
    assert "APCA_API_SECRET_KEY" in missing.detail

    placeholder = alpaca_credential_readiness(
        {
            "APCA_API_KEY_ID": "paper-key",
            "APCA_API_SECRET_KEY": "REPLACE_ME",
        }
    )
    assert placeholder.state == "placeholder"
    assert not placeholder.configured

    configured = alpaca_credential_readiness(
        {
            "APCA_API_KEY_ID": "paper-key",
            "APCA_API_SECRET_KEY": "paper-secret",
        }
    )
    assert configured.configured
    assert "paper-key" not in configured.detail
    assert "paper-secret" not in configured.detail


def test_provider_errors_are_actionable_and_secret_safe() -> None:
    fred = safe_provider_error(
        "fred",
        RuntimeError(
            "400 Client Error for url: https://api.example.test?api_key=secret-value"
        ),
    )
    assert "FRED_API_KEY" in fred
    assert "secret-value" not in fred
    assert "https://" not in fred

    alpaca = safe_provider_error("alpaca", RuntimeError("Alpaca returned HTTP 401"))
    assert "HTTP 401" in alpaca
    assert "APCA_API_KEY_ID" in alpaca
    assert "APCA_API_SECRET_KEY" in alpaca
