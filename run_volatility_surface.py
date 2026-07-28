"""Build a certified canonical volatility surface from point-in-time option quotes."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from data.derivative_market import OptionQuoteRecord, build_volatility_surface


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--minimum-expirations", type=int, default=2)
    parser.add_argument("--minimum-strikes-per-expiration", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.quotes).expanduser().read_text(encoding="utf-8"))
        records = payload.get("quotes") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise TypeError("quotes input must contain an array or {'quotes': [...]} object")
        surface = build_volatility_surface(
            tuple(OptionQuoteRecord.from_dict(item) for item in records),
            as_of=_timestamp(args.as_of),
            minimum_expirations=args.minimum_expirations,
            minimum_strikes_per_expiration=args.minimum_strikes_per_expiration,
        )
        result = surface.to_dict()
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({"error": str(error), "certified": False}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
