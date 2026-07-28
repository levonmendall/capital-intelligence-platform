"""Record and inspect governed runtime activation of external data providers."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from governance.provider_activation import (
    ProviderActivation,
    SQLiteProviderActivationStore,
)


def _database(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    root = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            str(root / "provider-activations.db"),
        )
    ).expanduser()


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument(
        "--activation",
        help="Append one immutable ProviderActivation JSON document.",
    )
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--evaluated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.activation and not args.status:
        raise SystemExit("one of --activation or --status is required")
    store = SQLiteProviderActivationStore(_database(args.database))
    try:
        appended_sequence = None
        if args.activation:
            payload = json.loads(
                Path(args.activation).expanduser().read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict):
                raise ValueError("activation JSON must be an object")
            activation = ProviderActivation.from_dict(payload)
            appended_sequence = store.append(activation)
        store.verify_integrity()
        evaluated_at = _timestamp(args.evaluated_at)
        provider_ids = (
            (args.provider,)
            if args.provider
            else tuple(
                dict.fromkeys(
                    item.provider_identifier for item in store.activations()
                )
            )
        )
        status = []
        for provider_identifier in provider_ids:
            active = store.active(
                provider_identifier,
                evaluated_at=evaluated_at,
            )
            status.append(
                {
                    "provider_identifier": provider_identifier,
                    "active_activation": (
                        None if active is None else active.to_dict()
                    ),
                }
            )
        print(
            json.dumps(
                {
                    "evaluated_at": evaluated_at.isoformat(),
                    "appended_sequence": appended_sequence,
                    "providers": status,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
