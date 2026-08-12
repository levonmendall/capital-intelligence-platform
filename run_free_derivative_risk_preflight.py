"""Validate the zero-cost derivative-risk resources without granting activation."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from providers.free_derivative_risk import preflight_free_derivative_risk_resources


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("--as-of must include a UTC offset")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of")
    parser.add_argument("--output")
    parser.add_argument("--require-valid-configured", action="store_true")
    args = parser.parse_args(argv)
    report = preflight_free_derivative_risk_resources(
        as_of=_timestamp(args.as_of),
        environment=os.environ,
    )
    payload = report.to_dict()
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = Path(args.output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if args.require_valid_configured and report.blockers:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
