"""Run and persist credential-safe live provider validation."""

from __future__ import annotations

import argparse
import json

from operations.provider_validation import (
    require_provider_validation,
    validate_live_providers,
    write_provider_validation_report,
)


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
    path = write_provider_validation_report(report, arguments.report)
    payload = report.to_dict()
    payload["report_path"] = str(path)
    print(json.dumps(payload, sort_keys=True, indent=2))
    if not arguments.allow_failure:
        require_provider_validation(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
