"""Publish the latest candidate-level decision-intelligence completeness report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from operations.decision_intelligence_shadow_report import (
    latest_candidate_information_completeness_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path")
    parser.add_argument(
        "--output",
        default="reports/decision-intelligence-shadow-report.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = latest_candidate_information_completeness_report(
        state_path=args.state_path,
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
