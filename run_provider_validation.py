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
_GOVERNED_OPRA_DEFINITIONS_CHECK = "governed_opra_definitions"
_GOVERNED_OPRA_DAILY_BARS_CHECK = "governed_opra_daily_bars"
_OPPORTUNITY_COMPLETE_MAX_EXPIRATIONS = 1_000

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


def _credential_safe_failure_detail(error: BaseException) -> str:
    """Publish enough provider context to repair a blocked proof without credentials."""

    detail = " ".join(str(error).strip().split())
    if not detail:
        detail = type(error).__name__
    return f"{type(error).__name__}: {detail}"[:600]


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


def _failed_option_checks(
    report: ProviderValidationReport,
    detail: str,
) -> tuple[ProviderValidationCheck, ProviderValidationCheck]:
    return (
        ProviderValidationCheck(
            name=_GOVERNED_OPRA_DEFINITIONS_CHECK,
            provider="REDUNDANT_OPTIONS",
            required=True,
            state="failed",
            detail=detail,
            observed_at=report.generated_at,
        ),
        ProviderValidationCheck(
            name=_GOVERNED_OPRA_DAILY_BARS_CHECK,
            provider="REDUNDANT_OPTIONS",
            required=True,
            state="failed",
            detail=detail,
            observed_at=report.generated_at,
        ),
    )


def certify_redundant_option_provider(
    report: ProviderValidationReport,
    *,
    options_provider: RedundantOptionsProvider | None = None,
    http_get: HttpGet = requests.get,
) -> ProviderValidationReport:
    """Require opportunity-complete current option evidence without Databento."""

    provider = options_provider or build_redundant_options_provider()
    if not provider.configured:
        return replace(
            report,
            checks=(
                *report.checks,
                *_failed_option_checks(
                    report,
                    "no governed option provider is configured; Alpaca indicative "
                    "options are the required opportunity-complete primary",
                ),
            ),
        )

    try:
        reference_price = _spy_reference_price(report=report, http_get=http_get)
        selections = provider.select_contracts(
            "SPY",
            underlying_price=reference_price,
            as_of=report.generated_at,
            minimum_days_to_expiry=30,
            maximum_days_to_expiry=365,
            maximum_expirations=_OPPORTUNITY_COMPLETE_MAX_EXPIRATIONS,
            candidates_per_bucket=1,
        )
    except (
        RedundantOptionsError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        requests.RequestException,
    ) as error:
        return replace(
            report,
            checks=(
                *report.checks,
                *_failed_option_checks(
                    report,
                    "expiration-complete governed option proof failed: "
                    + _credential_safe_failure_detail(error),
                ),
            ),
        )
    if not selections:
        return replace(
            report,
            checks=(
                *report.checks,
                *_failed_option_checks(
                    report,
                    "governed option provider returned no opportunity-complete selections",
                ),
            ),
        )

    provider_kinds = tuple(
        sorted(
            {
                str(item.definition.provider_kind).strip().lower()
                for item in selections
                if str(item.definition.provider_kind).strip()
            }
        )
    )
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
    expiration_dates = tuple(
        sorted({item.definition.expiration_at.date().isoformat() for item in selections})
    )
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
                "governed option contract selection succeeded across "
                f"{len(expiration_dates)} eligible expiration dates with "
                f"{len(selections)} priced near-money contracts via {provider_label}"
            ),
            observed_at=report.generated_at,
            source_identifier=definition_sources[0] if definition_sources else None,
            evidence_fingerprint=_fingerprint(
                {
                    "provider_kinds": provider_kinds,
                    "datasets": datasets,
                    "session_date": session_date,
                    "expiration_dates": expiration_dates,
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
                "production-aligned completed-session option pricing succeeded across "
                f"{len(expiration_dates)} eligible expiration dates with "
                f"{len(selections)} priced contracts via {provider_label}"
            ),
            observed_at=report.generated_at,
            source_identifier=bar_sources[0] if bar_sources else None,
            evidence_fingerprint=_fingerprint(
                {
                    "provider_kinds": provider_kinds,
                    "session_date": session_date,
                    "expiration_dates": expiration_dates,
                    "sample_symbols": sample_symbols,
                    "sources": bar_sources,
                }
            ),
        ),
    )
    return replace(report, checks=(*report.checks, *governed_checks))


def release_preflight_report(
    report: ProviderValidationReport,
) -> ProviderValidationReport:
    """Apply the release-level provider authority boundary.

    EODHD exchange-directory availability remains diagnostic because aggregate governed
    discovery and the exact-release CIO audit enforce executable-market completeness.
    No Databento exception or waiver exists.
    """

    checks = []
    for check in report.checks:
        if check.name == _EODHD_DIRECTORY_CHECK:
            checks.append(
                replace(
                    check,
                    required=False,
                    detail=(
                        f"{check.detail}; provider-specific exchange-directory availability "
                        "is diagnostic because aggregate governed discovery and the "
                        "exact-release CIO audit enforce executable-market completeness"
                    ),
                )
            )
        else:
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
