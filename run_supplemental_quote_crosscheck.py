"""Compare Alpha Vantage and Twelve Data as non-execution quote corroborators."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from providers.supplemental_quotes import SupplementalQuoteError, SupplementalQuoteProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--maximum-divergence-bps", type=float, default=100.0)
    parser.add_argument("--require-agreement", action="store_true")
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = SupplementalQuoteProvider().cross_check(
            args.symbol,
            maximum_divergence_bps=args.maximum_divergence_bps,
        ).to_dict()
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            target = Path(args.output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        if args.require_agreement and payload["state"] != "agree":
            return 3
        return 0
    except (SupplementalQuoteError, OSError, TypeError, ValueError) as error:
        payload = {
            "schema_version": "supplemental-quote-cross-check.v1",
            "state": "blocked",
            "error": str(error),
            "canonical_execution_authority": False,
            "paper_execution_authority": False,
            "real_money_authorized": False,
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
