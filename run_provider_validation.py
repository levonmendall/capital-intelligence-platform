"""Run and persist credential-safe live provider validation."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from typing import Any, Callable, Mapping

import requests

from operations.provider_validation import (
    ProviderValidationCheck,
    ProviderValidationReport,
    require_provider_validation,
    validate_live_providers,
    write_provider_validation_report,
)
from providers.redundant_options import (
    RedundantOptionsError,
    RedundantOptionsProvider,
    build_redundant_options_provider,
)


_EODHD_DIRECTORY_CHECK = "eodhd_exchange_directory"
_DATABENTO_TRANSIENT_CHECKS = frozenset(
    {
        "databento_account_entitlement",
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    }
)
_DATABENTO_OPRA_CHECKS = frozenset(
    {
        "databento_opra_definitions",
        "databento_opra_daily_bars",
    }
)
_DATABENTO_TRANSIENT_HTTP_MARKERS = (
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
)
_GOVERNED_OPRA_DEFINITIONS_CHECK = "governed_opra_definitions"
_GOVERNED_OPRA_DAILY_BARS_CHECK = "governed_opra_daily_bars"

HttpGet = Callable[..., Any]


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _spy_reference_price(
    *,
    report: ProviderValidationReport,
    http_get: HttpGet = requests.get,
) -> float:
    as_of = report.generated_at
    start = int((as_of - timedelta(days=10)).timestamp())
    end = int(as_of.timestamp())
    response = http_get(
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
        params={
            "period1": start,
            "period2": end,
            "interval": "1d",
            "events": "history",
        },
        headers={"User-Agent": "capital-intelligence-provider-validation/1.0"},
        timeout=20,
    )
    status = int(getattr(response, "status_code", 0))
    if status < 200 or status >= 300:
        raise RuntimeError(f"Yahoo SPY reference-price HTTP {status}")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise RuntimeError("Yahoo SPY reference-price payload is not an object")
    try:
        result = payload["chart"]["result"]
        quote = result[0]["indicators"]["quote"][0]
        closes = tuple(
            float(item) for item in quote.get("close", ()) if item is not None
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("Yahoo SPY reference-price observations are unavailable") from error
    if not closes or closes[-1] <= 0.0:
        raise RuntimeError("Yahoo SPY reference price is unavailable")
    return closes[-1]


def certify_redundant_option_provider(
    report: ProviderValidationReport,
    *,
    options_provider: RedundantOptionsProvider | None = None,
    http_get: HttpGet = requests.get,
) -> ProviderValidationReport:
    """Certify the governed OPRA lane through Databento or its Massive fallback.

    The legacy provider-validation report predates the redundant options router and
    therefore reports the Databento OPRA checks as release-blocking even when the
    production lane can lawfully fail over to Massive. Preserve those provider-specific
    failures as diagnostics, but add required provider-neutral proof only when the exact
    production router returns authentic completed-session near-money option evidence.
    """

    legacy_checks = {
        check.name: check
        for check in report.checks
        if check.name in _DATABENTO_OPRA_CHECKS
    }
    if _DATABENTO_OPRA_CHECKS.issubset(legacy_checks) and all(
        legacy_checks[name].passed for name in _DATABENTO_OPRA_CHECKS
    ):
        return report
    if not legacy_checks:
        return report

    provider = options_provider or build_redundant_options_provider()
    if not provider.configured:
        return report

    try:
        reference_price = _spy_reference_price(report=report, http_get=http_get)
        selections = provider.select_contracts(
            "SPY",
            underlying_price=reference_price,
            as_of=report.generated_at,
            minimum_days_to_expiry=30,
            maximum_days_to_expiry=365,
            maximum_expirations=1,
            candidates_per_bucket=1,
        )
    except (
        RedundantOptionsError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        requests.RequestException,
    ):
        return report
    if not selections:
        return report

    provider_kinds = tuple(
        sorted(
            {
                str(item.definition.provider_kind).strip().lower()
                for item in selections
                if str(item.definition.provider_kind).strip()
            }
        )
    )
    if not provider_kinds:
        return report
    provider_label = (
        provider_kinds[0].upper()
        if len(provider_kinds) == 1
        else "REDUNDANT_OPTIONS"
    )
    sample_symbols = tuple(item.definition.symbol for item in selections[:5])
    definition_sources = tuple(
        dict.fromkeys(
            item.definition.source_identifier
            for item in selections
            if item.definition.source_identifier
        )
    )
    bar_sources = tuple(
        dict.fromkeys(
            item.bar.source_identifier for item in selections if item.bar.source_identifier
        )
    )
    session_date = max(item.bar.observed_at.date() for item in selections).isoformat()
    datasets = tuple(
        sorted(
            {
                str(item.definition.provider_dataset).strip()
                for item in selections
                if str(item.definition.provider_dataset).strip()
            }
        )
    )
    governed_checks = (
        ProviderValidationCheck(
            name=_GOVERNED_OPRA_DEFINITIONS_CHECK,
            provider=provider_label,
            required=True,
            state="passed",
            detail=(
                "governed redundant OPRA contract selection succeeded with "
                f"{len(selections)} priced near-money contracts via {provider_label}"
            ),
            observed_at=report.generated_at,
            source_identifier=definition_sources[0] if definition_sources else None,
            evidence_fingerprint=_fingerprint(
                {
                    "provider_kinds": provider_kinds,
                    "datasets": datasets,
                    "session_date": session_date,
                    "sample_symbols": sample_symbols,
                    "sources": definition_sources,
                }
            ),
        ),
        ProviderValidationCheck(
            name=_GOVERNED_OPRA_DAILY_BARS_CHECK,
            provider=provider_label,
            required=True,
            state="passed",
            detail=(
                "production-aligned completed-session OPRA pricing succeeded with "
                f"{len(selections)} priced contracts via {provider_label}"
            ),
            observed_at=report.generated_at,
            source_identifier=bar_sources[0] if bar_sources else None,
            evidence_fingerprint=_fingerprint(
                {
                    "provider_kinds": provider_kinds,
                    "session_date": session_date,
                    "sample_symbols": sample_symbols,
                    "sources": bar_sources,
                }
            ),
        ),
    )

    checks: list[ProviderValidationCheck] = []
    for check in report.checks:
        if check.name in _DATABENTO_OPRA_CHECKS and not check.passed:
            checks.append(
                replace(
                    check,
                    required=False,
                    detail=(
                        f"{check.detail}; provider-specific Databento OPRA degradation is "
                        f"diagnostic because the governed redundant options lane certified "
                        f"authentic evidence via {provider_label}"
                    ),
                )
            )
        else:
            checks.append(check)
    checks.extend(governed_checks)
    return replace(report, checks=tuple(checks))


def _transient_databento_server_degradation(
    report: ProviderValidationReport,
) -> bool:
    """Return true only for an explicit provider-side Databento outage.

    The metadata endpoint currently collapses its final transport failure into a generic
    credential-safe message.  Therefore it can be deferred only when both independent
    OPRA checks explicitly report a retryable Databento 5xx response in the same report.
    Authentication denials, entitlement failures, missing keys, empty evidence, parsing
    errors, and any future unknown Databento check remain release-blocking.
    """

    failed = tuple(
        check
        for check in report.checks
        if check.provider == "DATABENTO" and check.required and not check.passed
    )
    if not failed:
        return False
    failed_names = {check.name for check in failed}
    if not failed_names.issubset(_DATABENTO_TRANSIENT_CHECKS):
        return False
    if not _DATABENTO_OPRA_CHECKS.issubset(failed_names):
        return False
    by_name = {check.name: check for check in failed}
    return all(
        any(marker in by_name[name].detail for marker in _DATABENTO_TRANSIENT_HTTP_MARKERS)
        for name in _DATABENTO_OPRA_CHECKS
    )


def release_preflight_report(
    report: ProviderValidationReport,
) -> ProviderValidationReport:
    """Apply the release-level provider authority boundary.

    EODHD authentication remains required. Its exchange-directory endpoint is a
    provider-specific catalog path, however, and is no longer an independent release
    authority. Complete executable-market coverage is enforced later by aggregate
    governed discovery and the exact-release CIO audit, which may use certified
    provider-neutral or fallback catalogs. The check remains visible and failed when
    unavailable so provider degradation is never hidden.

    A Databento provider-side 5xx outage may also be diagnostic at deployment preflight,
    but only when both OPRA checks explicitly prove the same transient server condition.
    The deployed CIO still requires complete option definitions and prices, remains
    fail-closed, and cannot certify or recommend an option without authentic evidence.
    """

    defer_databento = _transient_databento_server_degradation(report)
    checks = []
    for check in report.checks:
        if check.name == _EODHD_DIRECTORY_CHECK:
            checks.append(
                replace(
                    check,
                    required=False,
                    detail=(
                        f"{check.detail}; provider-specific exchange-directory availability "
                        "is diagnostic only because aggregate governed discovery and the "
                        "exact-release CIO audit enforce executable-market completeness"
                    ),
                )
            )
            continue
        if (
            defer_databento
            and check.name in _DATABENTO_TRANSIENT_CHECKS
            and not check.passed
        ):
            checks.append(
                replace(
                    check,
                    required=False,
                    detail=(
                        f"{check.detail}; explicit Databento provider-side 5xx degradation "
                        "is diagnostic at deployment preflight only; the deployed exact-release "
                        "CIO must still retrieve complete authentic option evidence and remains "
                        "fail-closed"
                    ),
                )
            )
            continue
        checks.append(check)
    return replace(report, checks=tuple(checks))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate live providers used by comprehensive market discovery."
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Optional report path; defaults to the configured production data directory.",
    )
    parser.add_argument(
        "--allow-failure",
        action="store_true",
        help="Persist and print a failed report without returning a non-zero exit status.",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    report = validate_live_providers()
    report = certify_redundant_option_provider(report)
    report = release_preflight_report(report)
    path = write_provider_validation_report(report, arguments.report)
    payload = report.to_dict()
    payload["report_path"] = str(path)
    print(json.dumps(payload, sort_keys=True, indent=2))
    if not arguments.allow_failure:
        require_provider_validation(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
