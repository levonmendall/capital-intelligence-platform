from __future__ import annotations

from datetime import datetime, timezone

from operations.provider_validation import (
    ProviderValidationCheck,
    ProviderValidationReport,
)
from run_provider_validation import release_preflight_report


AS_OF = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def _check(
    name: str,
    *,
    state: str,
    required: bool = True,
) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider="EODHD" if name.startswith("eodhd") else "TEST",
        required=required,
        state=state,
        detail=f"{name} {state}",
        observed_at=AS_OF,
    )


def test_exchange_directory_failure_is_diagnostic_at_release_preflight() -> None:
    report = ProviderValidationReport(
        release="test-release",
        generated_at=AS_OF,
        checks=(
            _check("eodhd_account_entitlement", state="passed"),
            _check("eodhd_exchange_directory", state="failed"),
            _check("yahoo_chart_evidence", state="passed"),
            _check("databento_account_entitlement", state="passed"),
        ),
    )

    resolved = release_preflight_report(report)
    directory = next(
        item for item in resolved.checks if item.name == "eodhd_exchange_directory"
    )

    assert resolved.ready is True
    assert resolved.failed_required_checks == ()
    assert directory.state == "failed"
    assert directory.required is False
    assert "aggregate governed discovery" in directory.detail


def test_eodhd_authentication_failure_remains_release_blocking() -> None:
    report = ProviderValidationReport(
        release="test-release",
        generated_at=AS_OF,
        checks=(
            _check("eodhd_account_entitlement", state="failed"),
            _check("eodhd_exchange_directory", state="failed"),
            _check("yahoo_chart_evidence", state="passed"),
            _check("databento_account_entitlement", state="passed"),
        ),
    )

    resolved = release_preflight_report(report)

    assert resolved.ready is False
    assert resolved.failed_required_checks == ("eodhd_account_entitlement",)
