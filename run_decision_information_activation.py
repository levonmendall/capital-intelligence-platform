"""Append or inspect governed decision-information source activations."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance import (
    DecisionInformationSourceActivation,
    SQLiteDecisionInformationActivationStore,
)


def _default_database() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_ACTIVATION_DATABASE",
        "database/decision_information_activations.db",
    )


def _load(path: str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("source activation JSON must encode an object")
    return payload


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--activation")
    mode.add_argument("--status", action="store_true")
    parser.add_argument("--source-identifier")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--database", default=_default_database())
    args = parser.parse_args(argv)
    try:
        store = SQLiteDecisionInformationActivationStore(args.database)
        if args.activation:
            activation = DecisionInformationSourceActivation.from_dict(
                _load(args.activation)
            )
            sequence = store.append(activation)
            payload = {**activation.to_dict(), "registry_sequence": sequence}
        else:
            evaluated_at = _timestamp(args.evaluated_at)
            activations = store.activations(args.source_identifier)
            payload = {
                "evaluated_at": evaluated_at.isoformat(),
                "source_identifier": args.source_identifier,
                "activation_count": len(activations),
                "activations": [
                    {
                        **item.to_dict(),
                        "active": item.active_at(evaluated_at),
                    }
                    for item in activations
                ],
                "real_money_authorized": False,
            }
        store.verify_integrity()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
