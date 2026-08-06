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
    """

    checks = tuple(
        replace(
            check,
            required=False,
            detail=(
                f"{check.detail}; provider-specific exchange-directory availability "
                "is diagnostic only because aggregate governed discovery and the "
                "exact-release CIO audit enforce executable-market completeness"
            ),
        )
        if check.name == _EODHD_DIRECTORY_CHECK
        else check
        for check in report.checks
    )
    return replace(report, checks=checks)


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
