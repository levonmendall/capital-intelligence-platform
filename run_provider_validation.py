"""Run and persist credential-safe live provider validation."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

from operations.provider_validation import (
    ProviderValidationReport,
    require_provider_validation,
    validate_live_providers,
    write_provider_validation_report,
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
    report = release_preflight_report(validate_live_providers())
    path = write_provider_validation_report(report, arguments.report)
    payload = report.to_dict()
    payload["report_path"] = str(path)
    print(json.dumps(payload, sort_keys=True, indent=2))
    if not arguments.allow_failure:
        require_provider_validation(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
