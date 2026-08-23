"""Independently verify Render telemetry timestamp freshness against capture time."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

_MAX_AGE_DISAGREEMENT_SECONDS = 120.0
_EXIT_FRESHNESS_INVALID = 8


def _parse(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 and parsed == parsed else None


def verify_snapshot_freshness(
    snapshot: Mapping[str, object],
    *,
    max_disagreement_seconds: float = _MAX_AGE_DISAGREEMENT_SECONDS,
) -> tuple[dict[str, object], bool]:
    """Return an annotated snapshot and whether its source-reported ages are trustworthy."""

    annotated = dict(snapshot)
    diagnostic_raw = snapshot.get("diagnostic")
    if not isinstance(diagnostic_raw, Mapping):
        annotated["freshness_integrity_valid"] = False
        annotated["freshness_integrity_reason"] = "diagnostic_missing"
        return annotated, False
    diagnostic = dict(diagnostic_raw)
    captured = _parse(snapshot.get("captured_at"))
    requested = _parse(diagnostic.get("requested_at"))
    completed = _parse(diagnostic.get("completed_at"))
    if captured is None or requested is None:
        annotated["diagnostic"] = diagnostic
        annotated["freshness_integrity_valid"] = False
        annotated["freshness_integrity_reason"] = "timestamp_missing_or_invalid"
        return annotated, False

    derived_diagnostic_age = max(0.0, (captured - requested).total_seconds())
    derived_terminal_age = (
        None if completed is None else max(0.0, (captured - completed).total_seconds())
    )
    diagnostic["captured_at_derived_diagnostic_age_seconds"] = round(derived_diagnostic_age, 3)
    diagnostic["captured_at_derived_terminal_age_seconds"] = (
        None if derived_terminal_age is None else round(derived_terminal_age, 3)
    )

    source_diagnostic_age = _number(diagnostic.get("diagnostic_age_seconds"))
    source_terminal_age = _number(diagnostic.get("terminal_age_seconds"))
    discrepancies: list[str] = []
    if source_diagnostic_age is None or abs(source_diagnostic_age - derived_diagnostic_age) > max_disagreement_seconds:
        discrepancies.append("diagnostic_age_disagrees_with_timestamps")
    if completed is not None and (
        source_terminal_age is None
        or derived_terminal_age is None
        or abs(source_terminal_age - derived_terminal_age) > max_disagreement_seconds
    ):
        discrepancies.append("terminal_age_disagrees_with_timestamps")

    valid = not discrepancies
    annotated["diagnostic"] = diagnostic
    annotated["freshness_integrity_valid"] = valid
    annotated["freshness_integrity_reason"] = None if valid else ",".join(discrepancies)
    if not valid:
        annotated["failure_class"] = "telemetry_freshness_invalid"
    return annotated, valid


def _write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _EXIT_FRESHNESS_INVALID
    if not isinstance(payload, Mapping):
        return _EXIT_FRESHNESS_INVALID
    annotated, valid = verify_snapshot_freshness(payload)
    _write(args.input, annotated)
    print(json.dumps(annotated, sort_keys=True, allow_nan=False), flush=True)
    return 0 if valid else _EXIT_FRESHNESS_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
