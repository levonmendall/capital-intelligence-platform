"""Reconcile a completed immutable provider backfill directory."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.provider_reconciliation import (
    ProviderBackfillReconciler,
    ProviderReconciliationError,
    ProviderReconciliationState,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must be timezone-aware")
    return parsed


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill-directory", required=True)
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output")
    parser.add_argument("--require-passed", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = ProviderBackfillReconciler().reconcile(
            args.backfill_directory,
            evaluated_at=_timestamp(args.evaluated_at),
        )
        payload = report.to_dict()
        if args.output:
            _write(args.output, payload)
    except (OSError, TypeError, ValueError, ProviderReconciliationError) as error:
        print(
            json.dumps(
                {
                    "state": ProviderReconciliationState.BLOCKED.value,
                    "error": str(error),
                    "licensing_approved": False,
                    "provider_certified": False,
                    "paper_test_authorized": False,
                    "real_money_authorized": False,
                    "secret_values_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 4
    print(
        json.dumps(
            payload,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    if args.require_passed and report.state is not ProviderReconciliationState.PASSED:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
