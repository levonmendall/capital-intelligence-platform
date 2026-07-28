"""Certify derivative contracts, margin records, and volatility surfaces."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from data.derivative_market import (
    DerivativeContractRecord,
    ExerciseStyle,
    MarginRequirementRecord,
    OptionRight,
    VolatilitySurfacePoint,
    VolatilitySurfaceSnapshot,
    certify_derivative_data,
)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed


def _array(path: str, key: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    records = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise TypeError(f"{path} must contain an array or {{{key!r}: [...]}}")
    if not all(isinstance(item, dict) for item in records):
        raise TypeError(f"{path} contains a non-object record")
    return records


def _surface(payload: dict[str, Any]) -> VolatilitySurfaceSnapshot:
    if payload.get("schema_version") != "volatility-surface-snapshot.v1":
        raise ValueError("unsupported volatility surface schema")
    points = tuple(
        VolatilitySurfacePoint(
            instrument_id=str(item["instrument_id"]),
            expiration_at=_timestamp(str(item["expiration_at"])),
            strike=float(item["strike"]),
            option_right=OptionRight(str(item["option_right"])),
            midpoint=float(item["midpoint"]),
            implied_volatility=float(item["implied_volatility"]),
            time_to_expiry_years=float(item["time_to_expiry_years"]),
            source_identifier=str(item["source_identifier"]),
            exercise_style=ExerciseStyle(str(item["exercise_style"])),
        )
        for item in payload["points"]
    )
    return VolatilitySurfaceSnapshot(
        underlying_instrument_id=str(payload["underlying_instrument_id"]),
        as_of=_timestamp(str(payload["as_of"])),
        method_version=str(payload["method_version"]),
        points=points,
        source_identifiers=tuple(str(item) for item in payload["source_identifiers"]),
        limitations=tuple(str(item) for item in payload.get("limitations", ())),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", required=True)
    parser.add_argument("--margins", required=True)
    parser.add_argument("--surface", action="append", default=[])
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--required-venue", action="append", default=[])
    parser.add_argument("--maximum-age-hours", type=float, default=36.0)
    parser.add_argument("--output")
    parser.add_argument("--require-certified", action="store_true")
    args = parser.parse_args(argv)
    try:
        contracts = tuple(
            DerivativeContractRecord.from_dict(item)
            for item in _array(args.contracts, "contracts")
        )
        margins = tuple(
            MarginRequirementRecord.from_dict(item)
            for item in _array(args.margins, "margins")
        )
        surfaces = tuple(
            _surface(json.loads(Path(path).expanduser().read_text(encoding="utf-8")))
            for path in args.surface
        )
        report = certify_derivative_data(
            contracts=contracts,
            margins=margins,
            surfaces=surfaces,
            evaluated_at=_timestamp(args.evaluated_at),
            required_venues=(
                tuple(args.required_venue)
                if args.required_venue
                else ("CME", "OCC", "ICE")
            ),
            maximum_age_hours=args.maximum_age_hours,
        )
        payload = report.to_dict()
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        if args.require_certified and not report.certified:
            return 3
        return 0 if report.certified else 2
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({"error": str(error), "certified": False}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
