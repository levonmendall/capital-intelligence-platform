"""Validate the free listed-wrapper paper pilot against the live Alpaca paper account."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    assess_free_paper_pilot_readiness,
    default_alpaca_client,
    load_free_paper_pilot_universe,
    write_pilot_profiles,
)


def _evaluated_at(value: str | None) -> datetime | None:
    """Return an explicit point-in-time cutoff or preserve live evaluation mode."""

    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output")
    parser.add_argument("--profiles-output")
    parser.add_argument("--require-configuration-ready", action="store_true")
    parser.add_argument("--require-execution-ready-now", action="store_true")
    args = parser.parse_args(argv)
    try:
        universe = load_free_paper_pilot_universe(args.universe)
        report = assess_free_paper_pilot_readiness(
            universe=universe,
            client=default_alpaca_client(),
            evaluated_at=_evaluated_at(args.evaluated_at),
        )
        payload = report.to_dict()
        if args.profiles_output and report.configuration_ready:
            payload["profiles_path"] = str(
                write_pilot_profiles(universe, args.profiles_output)
            )
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.require_execution_ready_now and not report.execution_ready_now:
            return 3
        if args.require_configuration_ready and not report.configuration_ready:
            return 2
        return 0 if report.configuration_ready else 2
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
