"""Generate broad secret-free EODHD instrument bindings from licensed directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import EODHDProviderError, build_eodhd_provider


_TYPE_PREFIXES = {
    "common stock": "equity",
    "preferred stock": "preferred-equity",
    "etf": "fund",
    "fund": "fund",
    "mutual fund": "fund",
    "bond": "fixed-income",
    "currency": "fx",
    "forex": "fx",
    "commodity": "commodity",
    "index": "benchmark",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
}


def _slug(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return normalized.strip("-") or "unknown"


def _text(item: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _binding(
    item: Mapping[str, Any],
    *,
    exchange_code: str,
    include_unknown_types: bool,
) -> dict[str, str] | None:
    code = _text(item, "Code", "code", "Symbol", "symbol")
    if not code:
        return None
    raw_type = (_text(item, "Type", "type") or "unknown").lower()
    prefix = next(
        (mapped for key, mapped in _TYPE_PREFIXES.items() if key in raw_type),
        None,
    )
    if prefix is None:
        if not include_unknown_types:
            return None
        prefix = "classified-public-market"
    currency = (_text(item, "Currency", "currency") or "USD").upper()
    exchange = (_text(item, "Exchange", "exchange") or exchange_code).upper()
    provider_symbol = code.upper()
    suffix = f".{exchange_code.upper()}"
    if not provider_symbol.endswith(suffix):
        provider_symbol += suffix
    country = _text(item, "Country", "country", "CountryISO2", "country_iso2")
    identity = ":".join(
        (
            "instrument",
            prefix,
            _slug(country or exchange_code),
            _slug(exchange),
            _slug(code),
        )
    )
    return {
        "instrument_id": identity,
        "provider_symbol": provider_symbol,
        "venue": f"EODHD_{_slug(exchange).replace('-', '_').upper()}",
        "currency": currency,
    }


def _merge_bindings(
    bindings: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    by_provider: dict[tuple[str, str], dict[str, str]] = {}
    by_instrument: dict[str, dict[str, str]] = {}
    for item in bindings:
        provider_key = (item["venue"], item["provider_symbol"])
        current_provider = by_provider.get(provider_key)
        if current_provider is not None and current_provider != item:
            raise ValueError(
                "conflicting EODHD provider binding for "
                f"{item['venue']}:{item['provider_symbol']}"
            )
        current_instrument = by_instrument.get(item["instrument_id"])
        if current_instrument is not None and current_instrument != item:
            raise ValueError(
                f"conflicting canonical EODHD binding for {item['instrument_id']}"
            )
        by_provider[provider_key] = item
        by_instrument[item["instrument_id"]] = item
    return sorted(
        by_instrument.values(),
        key=lambda item: (item["instrument_id"], item["provider_symbol"]),
    )


def _existing(path: str | None) -> list[dict[str, str]]:
    if not path:
        return []
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("bindings"), list):
        raise ValueError("seed binding file must contain a bindings array")
    result: list[dict[str, str]] = []
    for item in payload["bindings"]:
        if not isinstance(item, dict):
            raise ValueError("seed bindings must be JSON objects")
        result.append(
            {
                "instrument_id": str(item["instrument_id"]),
                "provider_symbol": str(item["provider_symbol"]),
                "venue": str(item["venue"]),
                "currency": str(item["currency"]),
            }
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exchange",
        action="append",
        required=True,
        help="EODHD exchange code. Repeat for multiple exchanges.",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed-bindings")
    parser.add_argument(
        "--max-per-exchange",
        type=int,
        help=(
            "Deprecated compatibility option. Complete directories are always "
            "processed; a lower value cannot truncate the certified catalog."
        ),
    )
    parser.add_argument("--include-delisted", action="store_true")
    parser.add_argument("--include-unknown-types", action="store_true")
    parser.add_argument("--as-of")
    return parser


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_per_exchange is not None and args.max_per_exchange < 1:
        raise SystemExit("--max-per-exchange must be positive when supplied")
    as_of = _timestamp(args.as_of)
    provider = build_eodhd_provider()
    generated: list[dict[str, str]] = _existing(args.seed_bindings)
    sources: list[dict[str, Any]] = []
    try:
        for exchange in tuple(dict.fromkeys(item.strip().upper() for item in args.exchange)):
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
                    provider_symbol=exchange,
                    as_of=as_of,
                    # The provider contract requires a finite request sentinel, but
                    # SYMBOL_DIRECTORY payloads are processed to exhaustion below.
                    limit=1_000_000,
                )
            )
            payload = snapshot.payload
            if not isinstance(payload, dict):
                raise ValueError("EODHD symbol-directory snapshot must be an object")
            active = payload.get("active")
            delisted = payload.get("delisted")
            if not isinstance(active, list) or not isinstance(delisted, list):
                raise ValueError("EODHD symbol-directory lists are malformed")
            selected = active + (delisted if args.include_delisted else [])
            accepted = 0
            skipped = 0
            if len(selected) >= 1_000_000:
                raise ValueError(
                    f"{exchange} directory reached the completeness sentinel"
                )
            for item in selected:
                if not isinstance(item, Mapping):
                    skipped += 1
                    continue
                binding = _binding(
                    item,
                    exchange_code=exchange,
                    include_unknown_types=args.include_unknown_types,
                )
                if binding is None:
                    skipped += 1
                    continue
                generated.append(binding)
                accepted += 1
            sources.append(
                {
                    "exchange": exchange,
                    "snapshot_content_hash": snapshot.content_hash,
                    "active_records": len(active),
                    "delisted_records": len(delisted),
                    "accepted_records": accepted,
                    "skipped_records": skipped,
                    "include_delisted": args.include_delisted,
                }
            )
        merged = _merge_bindings(generated)
        payload = {
            "schema_version": "eodhd-instrument-bindings.v1",
            "generated_at": as_of.isoformat(),
            "source_version": "eodhd-directory-expansion.v1",
            "source_snapshots": sources,
            "limitations": [
                "Generated directories are research bindings, not a survivorship-safe security master.",
                "Paper allocation still requires active provider and asset-class governance.",
                "Unknown instrument types are excluded unless explicitly requested.",
            ],
            "bindings": merged,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "state": "generated",
                    "output": str(target),
                    "binding_count": len(merged),
                    "source_exchange_count": len(sources),
                    "manifest_sha256": payload["manifest_sha256"],
                    "secret_values_disclosed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (EODHDProviderError, OSError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "secret_values_disclosed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
