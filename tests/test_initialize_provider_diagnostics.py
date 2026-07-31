from __future__ import annotations

from datetime import datetime, timezone

from initialize import _log_provider_validation_diagnostics
from operations.provider_validation import (
    ProviderValidationCheck,
    ProviderValidationReport,
)

NOW = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)


def _report(*, state: str, detail: str) -> ProviderValidationReport:
    return ProviderValidationReport(
        release="diagnostic-test",
        generated_at=NOW,
        checks=(
            ProviderValidationCheck(
                name="eodhd_account_entitlement",
                provider="EODHD",
                required=True,
                state=state,
                detail=detail,
                observed_at=NOW,
                evidence_fingerprint=("a" * 64 if state == "passed" else None),
            ),
        ),
    )


def test_failed_provider_diagnostics_are_logged_without_secret_values(
    monkeypatch,
    capsys,
):
    secret = "eodhd-secret-value"
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", secret)
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
        "databento-secret-value",
    )

    _log_provider_validation_diagnostics(
        _report(
            state="failed",
            detail=f"EODHD HTTP 429 while using {secret}",
        )
    )

    output = capsys.readouterr().out
    assert '"eodhd_api_token_configured": true' in output
    assert '"databento_api_key_configured": true' in output
    assert '"check": "eodhd_account_entitlement"' in output
    assert '"detail": "EODHD HTTP 429 while using [REDACTED]"' in output
    assert secret not in output
    assert "databento-secret-value" not in output


def test_ready_provider_report_does_not_emit_failure_diagnostics(capsys):
    _log_provider_validation_diagnostics(
        _report(state="passed", detail="authenticated retrieval succeeded")
    )

    assert capsys.readouterr().out == ""
