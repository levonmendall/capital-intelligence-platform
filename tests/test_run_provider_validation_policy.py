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
    detail: str | None = None,
    provider: str | None = None,
) -> ProviderValidationCheck:
    resolved_provider = provider or (
        "EODHD"
        if name.startswith("eodhd")
        else "DATABENTO"
        if name.startswith("databento")
        else "TEST"
    )
    return ProviderValidationCheck(
        name=name,
        provider=resolved_provider,
        required=required,
        state=state,
        detail=detail or f"{name} {state}",
        observed_at=AS_OF,
    )


def _baseline(*databento_checks: ProviderValidationCheck) -> ProviderValidationReport:
    return ProviderValidationReport(
        release="test-release",
        generated_at=AS_OF,
        checks=(
            _check("eodhd_account_entitlement", state="passed"),
            _check("eodhd_exchange_directory", state="failed"),
            _check("yahoo_chart_evidence", state="passed"),
            *databento_checks,
        ),
    )


def test_exchange_directory_failure_is_diagnostic_at_release_preflight() -> None:
    report = _baseline(
        _check("databento_account_entitlement", state="passed"),
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


def test_explicit_databento_5xx_is_deferred_to_exact_release_audit() -> None:
    report = _baseline(
        _check(
            "databento_account_entitlement",
            state="failed",
            detail="DatabentoProviderError: unable to retrieve dataset metadata from Databento",
        ),
        _check(
            "databento_opra_definitions",
            state="failed",
            detail="DatabentoOptionsError: Databento OPRA HTTP 502",
        ),
        _check(
            "databento_opra_daily_bars",
            state="failed",
            detail="DatabentoOptionsError: Databento OPRA HTTP 504",
        ),
    )

    resolved = release_preflight_report(report)
    databento = tuple(
        item for item in resolved.checks if item.provider == "DATABENTO"
    )

    assert resolved.ready is True
    assert resolved.failed_required_checks == ()
    assert all(item.required is False for item in databento)
    assert all("deployed exact-release CIO" in item.detail for item in databento)


def test_databento_entitlement_denial_remains_release_blocking() -> None:
    report = _baseline(
        _check(
            "databento_account_entitlement",
            state="failed",
            detail="DatabentoProviderError: Databento HTTP 401 for dataset metadata",
        ),
        _check(
            "databento_opra_definitions",
            state="failed",
            detail="DatabentoOptionsError: Databento OPRA HTTP 401",
        ),
        _check(
            "databento_opra_daily_bars",
            state="failed",
            detail="DatabentoOptionsError: Databento OPRA HTTP 401",
        ),
    )

    resolved = release_preflight_report(report)

    assert resolved.ready is False
    assert resolved.failed_required_checks == (
        "databento_account_entitlement",
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    )


def test_databento_missing_credentials_remains_release_blocking() -> None:
    report = _baseline(
        _check(
            "databento_account_entitlement",
            state="failed",
            detail="required Databento API key is not configured",
        ),
        _check(
            "databento_opra_definitions",
            state="failed",
            detail="required Databento OPRA credentials are not configured",
        ),
        _check(
            "databento_opra_daily_bars",
            state="failed",
            detail="required Databento OPRA credentials are not configured",
        ),
    )

    resolved = release_preflight_report(report)

    assert resolved.ready is False
    assert set(resolved.failed_required_checks) == {
        "databento_account_entitlement",
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    }


def test_single_opra_5xx_does_not_defer_databento_preflight() -> None:
    report = _baseline(
        _check("databento_account_entitlement", state="passed"),
        _check(
            "databento_opra_definitions",
            state="failed",
            detail="DatabentoOptionsError: Databento OPRA HTTP 502",
        ),
        _check(
            "databento_opra_daily_bars",
            state="failed",
            detail="DatabentoOptionsError: option bars were empty",
        ),
    )

    resolved = release_preflight_report(report)

    assert resolved.ready is False
    assert resolved.failed_required_checks == (
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    )
