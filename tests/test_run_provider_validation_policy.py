from __future__ import annotations

from datetime import datetime, timezone

from operations.provider_validation import ProviderValidationCheck, ProviderValidationReport
from run_provider_validation import release_preflight_report


AS_OF = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def _check(name: str, *, state: str, required: bool = True, provider: str = "TEST", detail: str | None = None) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=required,
        state=state,
        detail=detail or f"{name} {state}",
        observed_at=AS_OF,
    )


def _baseline(*extra: ProviderValidationCheck) -> ProviderValidationReport:
    return ProviderValidationReport(
        release="test-release",
        generated_at=AS_OF,
        checks=(
            _check("eodhd_account_entitlement", state="passed", provider="EODHD"),
            _check("eodhd_exchange_directory", state="failed", provider="EODHD"),
            _check("yahoo_chart_evidence", state="passed", provider="YAHOO"),
            *extra,
        ),
    )


def test_exchange_directory_failure_is_diagnostic_at_release_preflight() -> None:
    resolved = release_preflight_report(_baseline())
    directory = next(item for item in resolved.checks if item.name == "eodhd_exchange_directory")
    assert resolved.ready is True
    assert directory.state == "failed"
    assert directory.required is False
    assert "aggregate governed discovery" in directory.detail


def test_eodhd_authentication_failure_remains_release_blocking() -> None:
    report = ProviderValidationReport(
        release="test-release",
        generated_at=AS_OF,
        checks=(
            _check("eodhd_account_entitlement", state="failed", provider="EODHD"),
            _check("eodhd_exchange_directory", state="failed", provider="EODHD"),
            _check("yahoo_chart_evidence", state="passed", provider="YAHOO"),
        ),
    )
    resolved = release_preflight_report(report)
    assert resolved.ready is False
    assert resolved.failed_required_checks == ("eodhd_account_entitlement",)


def test_governed_option_failure_remains_release_blocking() -> None:
    resolved = release_preflight_report(
        _baseline(
            _check(
                "governed_opra_definitions",
                state="failed",
                provider="REDUNDANT_OPTIONS",
                detail="opportunity-complete option proof failed",
            )
        )
    )
    assert resolved.ready is False
    assert resolved.failed_required_checks == ("governed_opra_definitions",)


def test_legacy_databento_failure_receives_no_special_waiver() -> None:
    resolved = release_preflight_report(
        _baseline(
            _check(
                "databento_opra_definitions",
                state="failed",
                provider="DATABENTO",
                detail="legacy Databento check",
            )
        )
    )
    legacy = next(item for item in resolved.checks if item.name == "databento_opra_definitions")
    assert legacy.required is True
    assert resolved.ready is False
