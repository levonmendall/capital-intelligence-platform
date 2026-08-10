"""Write the canonical decision-information gap audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from operations.information_gap_audit import build_information_gap_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        default="config/maximum_decision_information_scope.json",
    )
    parser.add_argument(
        "--public-catalog",
        default="config/public_live_information_sources.json",
    )
    parser.add_argument("--runtime-report")
    parser.add_argument(
        "--output",
        default="reports/information-gap-audit.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_information_gap_audit(
        scope_path=args.scope,
        public_catalog_path=args.public_catalog,
        runtime_report_path=args.runtime_report,
    )
    destination = Path(args.output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
