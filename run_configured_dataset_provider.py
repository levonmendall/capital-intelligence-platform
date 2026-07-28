"""Retrieve one governed dataset through a reviewed configured-provider binding."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.configured_dataset import ConfiguredDatasetProvider


def _timestamp(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binding",
        default=os.getenv("CAPITAL_INTELLIGENCE_CONFIGURED_DATASET_PROVIDER"),
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=tuple(item.value for item in ProviderDatasetType),
    )
    parser.add_argument("--provider-symbol", default="ALL")
    parser.add_argument("--as-of")
    parser.add_argument("--start-at")
    parser.add_argument("--end-at")
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--output")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.binding:
            raise ValueError(
                "--binding or CAPITAL_INTELLIGENCE_CONFIGURED_DATASET_PROVIDER is required"
            )
        now = datetime.now(timezone.utc)
        as_of = _timestamp(args.as_of, default=now)
        snapshot = ConfiguredDatasetProvider.from_path(args.binding).fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType(args.type),
                provider_symbol=args.provider_symbol,
                as_of=as_of,
                start_at=(
                    None
                    if args.start_at is None
                    else _timestamp(args.start_at, default=as_of)
                ),
                end_at=(
                    None
                    if args.end_at is None
                    else _timestamp(args.end_at, default=as_of)
                ),
                limit=args.limit,
            )
        )
        payload = snapshot.to_dict()
        payload["secret_values_disclosed"] = False
        payload["real_money_authorized"] = False
        rendered = json.dumps(
            payload, indent=None if args.compact else 2, sort_keys=True
        )
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
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
                    "secret_values_disclosed": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
