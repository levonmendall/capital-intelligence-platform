from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations.provider_validation import ProviderValidationCheck, ProviderValidationReport
from run_provider_validation import certify_redundant_option_provider


NOW = datetime(2026, 8, 11, 18, 51, 30, tzinfo=timezone.utc)


def _check(name: str, *, provider: str, state: str = "passed", required: bool = True, detail: str = "ok") -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=required,
        state=state,
        detail=detail,
        observed_at=NOW,
        evidence_fingerprint=("a" * 64 if state == "passed" else None),
    )


def _base_report() -> ProviderValidationReport:
    return ProviderValidationReport(
        release="release-coverage",
        generated_at=NOW,
        checks=(
            _check("eodhd_account_entitlement", provider="EODHD"),
            _check("yahoo_chart_evidence", provider="YAHOO"),
        ),
    )


class _YahooResponse:
    status_code = 200

    def json(self):
        return {"chart": {"result": [{"indicators": {"quote": [{"close": [650.0]}]}}]}}


def _http_get(url, **_kwargs):
    assert "/chart/SPY" in url
    return _YahooResponse()


class _ExpirationCompleteProof:
    configured = True

    def __init__(self) -> None:
        self.maximum_expirations: int | None = None

    def select_contracts(self, underlying, **kwargs):
        assert underlying == "SPY"
        self.maximum_expirations = kwargs["maximum_expirations"]
        selections = []
        for days in (45, 75, 105):
            expiration = NOW + timedelta(days=days)
            for right in ("call", "put"):
                code = "C" if right == "call" else "P"
                symbol = f"SPY{expiration.strftime('%y%m%d')}{code}00650000"
                selections.append(
                    SimpleNamespace(
                        definition=SimpleNamespace(
                            provider_kind="alpaca_indicative",
                            provider_dataset="ALPACA.OPTIONS.INDICATIVE",
                            source_identifier=f"alpaca-option-contract:{symbol}",
                            symbol=symbol,
                            expiration_at=expiration,
                        ),
                        bar=SimpleNamespace(
                            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
                            source_identifier=f"alpaca-indicative-option-bar:{symbol}",
                        ),
                    )
                )
        return tuple(selections)


class _NoProvider:
    configured = False


def test_expiration_complete_alpaca_proof_is_required_directly() -> None:
    provider = _ExpirationCompleteProof()
    report = certify_redundant_option_provider(
        _base_report(),
        options_provider=provider,
        http_get=_http_get,
    )

    assert provider.maximum_expirations == 1_000
    assert report.ready is True
    by_name = {item.name: item for item in report.checks}
    assert by_name["governed_opra_definitions"].required is True
    assert by_name["governed_opra_definitions"].provider == "ALPACA_INDICATIVE"
    assert by_name["governed_opra_definitions"].state == "passed"
    assert "3 eligible expiration dates" in by_name["governed_opra_definitions"].detail
    assert by_name["governed_opra_daily_bars"].state == "passed"


def test_missing_governed_option_provider_remains_fail_closed() -> None:
    report = certify_redundant_option_provider(
        _base_report(),
        options_provider=_NoProvider(),
        http_get=_http_get,
    )

    assert report.ready is False
    assert report.failed_required_checks == (
        "governed_opra_definitions",
        "governed_opra_daily_bars",
    )
    by_name = {item.name: item for item in report.checks}
    assert "is configured" in by_name["governed_opra_definitions"].detail
