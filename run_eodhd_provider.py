"""Probe and retrieve governed EODHD multi-asset datasets."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from data.market import BarInterval, MarketDataQuery, MarketDataType
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import (
    EODHDBindingRegistry,
    EODHDProvider,
    EODHDProviderError,
    load_eodhd_bindings,
)


def _timestamp(value: str | None, *, default_now: bool = False) -> datetime:
    if value is None:
        if default_now:
            return datetime.now(timezone.utc)
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed


def _provider(binding_path: str | None) -> EODHDProvider:
    resolved = binding_path or os.getenv("CAPITAL_INTELLIGENCE_EODHD_BINDINGS")
    registry = (
        EODHDBindingRegistry(())
        if not resolved
        else load_eodhd_bindings(resolved)
    )
    return EODHDProvider(bindings=registry)


def _record_payload(record: object) -> dict[str, Any]:
    provenance = getattr(record, "provenance")
    payload: dict[str, Any] = {
        "record_type": type(record).__name__,
        "instrument_id": getattr(record, "instrument_id"),
        "currency": getattr(record, "currency"),
        "provider": provenance.provider,
        "venue": provenance.venue,
        "observed_at": provenance.observed_at.isoformat(),
        "retrieved_at": provenance.retrieved_at.isoformat(),
        "quality_state": provenance.quality_state.value,
        "provider_record_id": provenance.provider_record_id,
    }
    for name in (
        "interval",
        "start_at",
        "end_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "action_type",
        "effective_at",
        "amount",
        "ratio",
        "new_symbol",
    ):
        value = getattr(record, name, None)
        if value is None:
            continue
        if hasattr(value, "value"):
            value = value.value
        elif isinstance(value, datetime):
            value = value.isoformat()
        payload[name] = value
    return payload


def _write(path: str | None, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(encoded, end="")
        return
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(destination)
    print(encoded, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", help="EODHD internal-to-provider symbol map")
    parser.add_argument("--output", help="Optional JSON output path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Validate token and entitlements")
    probe.add_argument("--as-of", help="Knowledge cutoff; defaults to now")

    dataset = subparsers.add_parser("dataset", help="Retrieve a raw dataset snapshot")
    dataset.add_argument(
        "--type",
        required=True,
        choices=[item.value for item in ProviderDatasetType],
    )
    dataset.add_argument("--provider-symbol", required=True)
    dataset.add_argument("--as-of", required=True)
    dataset.add_argument("--start-at")
    dataset.add_argument("--end-at")
    dataset.add_argument("--limit", type=int, default=10_000)

    market = subparsers.add_parser("market", help="Retrieve canonical EOD bars or actions")
    market.add_argument("--instrument-id", required=True)
    market.add_argument(
        "--type",
        required=True,
        choices=[MarketDataType.BAR.value, MarketDataType.CORPORATE_ACTION.value],
    )
    market.add_argument("--as-of", required=True)
    market.add_argument("--start-at")
    market.add_argument("--venue")
    market.add_argument("--limit", type=int, default=500)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        provider = _provider(args.bindings)
        if args.command == "probe":
            as_of = _timestamp(args.as_of, default_now=True)
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                    provider_symbol="ACCOUNT",
                    as_of=as_of,
                    limit=1,
                )
            )
            payload = snapshot.to_dict()
            payload["configured"] = provider.configured
            payload["secret_values_disclosed"] = False
        elif args.command == "dataset":
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType(args.type),
                    provider_symbol=args.provider_symbol,
                    as_of=_timestamp(args.as_of),
                    start_at=(
                        None
                        if args.start_at is None
                        else _timestamp(args.start_at)
                    ),
                    end_at=(
                        None
                        if args.end_at is None
                        else _timestamp(args.end_at)
                    ),
                    limit=args.limit,
                )
            )
            payload = snapshot.to_dict()
            payload["secret_values_disclosed"] = False
        else:
            data_type = MarketDataType(args.type)
            batch = provider.fetch(
                MarketDataQuery(
                    instrument_id=args.instrument_id,
                    data_type=data_type,
                    as_of=_timestamp(args.as_of),
                    start_at=(
                        None
                        if args.start_at is None
                        else _timestamp(args.start_at)
                    ),
                    venue=args.venue,
                    interval=(
                        BarInterval.DAY
                        if data_type is MarketDataType.BAR
                        else None
                    ),
                    limit=args.limit,
                )
            )
            payload = {
                "schema_version": "eodhd-canonical-market-batch.v1",
                "provider": provider.name,
                "query_type": batch.query.data_type.value,
                "instrument_id": batch.query.instrument_id,
                "record_count": len(batch.records),
                "records": [_record_payload(item) for item in batch.records],
                "real_money_authorized": False,
                "secret_values_disclosed": False,
            }
        _write(args.output, payload)
        return 0
    except (EODHDProviderError, KeyError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                    "secret_values_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
