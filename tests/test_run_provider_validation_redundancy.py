from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operations.provider_validation import ProviderValidationCheck, ProviderValidationReport
from run_provider_validation import certify_redundant_option_provider


NOW = datetime(2026, 8, 11, 18, 51, 30, tzinfo=timezone.utc)


def _check(
    name: str,
    *,
    provider: str,
    state: str = "passed",
    required: bool = True,
    detail: str = "ok",
) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=required,
        state=state,
        detail=detail,
        observed_at=NOW,
        evidence_fingerprint=("a" * 64 if state == "passed" else None),
    )


def _blocked_databento_report() -> ProviderValidationReport:
    return ProviderValidationReport(
        release="release-570",
        generated_at=NOW,
        checks=(
            _check("eodhd_account_entitlement", provider="EODHD"),
            _check("yahoo_chart_evidence", provider="YAHOO"),
            _check("databento_account_entitlement", provider="DATABENTO"),
            _check(
                "databento_opra_definitions",
                provider="DATABENTO",
                state="failed",
                detail="DatabentoOptionsError: Databento OPRA HTTP 402",
            ),
            _check(
                "databento_opra_daily_bars",
                provider="DATABENTO",
                state="failed",
                detail="DatabentoOptionsError: Databento OPRA HTTP 402",
            ),
        ),
    )


class _YahooResponse:
    status_code = 200

    def json(self):
        return {
            "chart": {
                "result": [
                    {
                        "indicators": {
                            "quote": [{"close": [640.0, 645.0, 650.0]}]
                        }
                    }
                ]
            }
        }


def _http_get(url, **_kwargs):
    assert "/chart/SPY" in url
    return _YahooResponse()


class _MassiveFallback:
    configured = True

    def select_contracts(self, underlying, **kwargs):
        assert underlying == "SPY"
        assert kwargs["underlying_price"] == 650.0
        assert kwargs["minimum_days_to_expiry"] == 30
        assert kwargs["maximum_days_to_expiry"] == 365
        return (
            SimpleNamespace(
                definition=SimpleNamespace(
                    provider_kind="massive",
                    provider_dataset="OPRA",
                    source_identifier=(
                        "massive-opra-definition:2026-08-11:O:SPY261010C00650000"
                    ),
                    symbol="SPY261010C00650000",
                ),
                bar=SimpleNamespace(
                    observed_at=datetime(
                        2026, 8, 10, 20, 0, tzinfo=timezone.utc
                    ),
                    source_identifier=(
                        "massive-opra-bar:O:SPY261010C00650000:"
                        "2026-08-10T20:00:00+00:00"
                    ),
                ),
            ),
        )


class _NoFallback:
    configured = False


def test_databento_402_is_replaced_by_required_massive_proof() -> None:
    report = certify_redundant_option_provider(
        _blocked_databento_report(),
        options_provider=_MassiveFallback(),
        http_get=_http_get,
    )

    assert report.ready is True
    by_name = {item.name: item for item in report.checks}
    assert by_name["databento_opra_definitions"].required is False
    assert by_name["databento_opra_definitions"].state == "failed"
    assert by_name["databento_opra_daily_bars"].required is False
    assert by_name["governed_opra_definitions"].required is True
    assert by_name["governed_opra_definitions"].provider == "MASSIVE"
    assert by_name["governed_opra_definitions"].state == "passed"
    assert by_name["governed_opra_daily_bars"].provider == "MASSIVE"
    assert by_name["governed_opra_daily_bars"].state == "passed"
    assert by_name["governed_opra_definitions"].source_identifier.startswith(
        "massive-opra-definition:"
    )
    assert by_name["governed_opra_daily_bars"].source_identifier.startswith(
        "massive-opra-bar:"
    )


def test_missing_redundant_provider_remains_fail_closed() -> None:
    report = certify_redundant_option_provider(
        _blocked_databento_report(),
        options_provider=_NoFallback(),
        http_get=_http_get,
    )

    assert report.ready is False
    assert report.failed_required_checks == (
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    )
