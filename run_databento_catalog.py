"""Inspect Databento entitlements and configured canonical symbol bindings safely."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from providers.databento import DatabentoProviderError, build_databento_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Optional credential-safe JSON report path.")
    parser.add_argument(
        "--require-bindings-available",
        action="store_true",
        help="Return nonzero when a configured binding dataset is unavailable.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_databento_provider().capability_report()
        unavailable = [
            item
            for item in report["bindings"]
            if item.get("state") != "available"
        ]
        report["available_binding_count"] = len(report["bindings"]) - len(unavailable)
        report["state"] = "available" if not unavailable else "partial"
        report["blockers"] = [
            f"{item['instrument_id']}:{','.join(item.get('blockers', []))}"
            for item in unavailable
        ]
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            target = Path(args.output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        if args.require_bindings_available and unavailable:
            return 3
        return 0
    except (DatabentoProviderError, OSError, TypeError, ValueError) as error:
        payload = {
            "schema_version": "databento-capability-report.v1",
            "state": "blocked",
            "error": str(error),
            "secret_values_disclosed": False,
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            target = Path(args.output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
