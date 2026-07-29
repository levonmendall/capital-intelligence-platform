"""Report which provider credentials and bindings are available in this runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from provider_runtime_diagnostics import (
    build_provider_runtime_report,
    load_report,
    merge_runtime_reports,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-name")
    parser.add_argument("--merge-report", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--require-all-configured", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    current = build_provider_runtime_report(environment_name=args.environment_name)
    reports = [current] + [load_report(path) for path in args.merge_report]
    payload = current if len(reports) == 1 else merge_runtime_reports(reports)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if args.require_all_configured and current.get("state") != "ready":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
