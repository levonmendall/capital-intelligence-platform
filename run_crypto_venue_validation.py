"""Validate every configured Coinbase/Kraken crypto pair independently."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from operations.crypto_venue_validation import validate_crypto_venues
from providers.crypto_venues import (
    CoinbaseExchangeProvider,
    KrakenSpotProvider,
    load_crypto_venue_bindings,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bindings", default="config/crypto_venue_bindings.all_markets.json"
    )
    parser.add_argument("--evaluated-at")
    parser.add_argument("--maximum-divergence-bps", type=float, default=250.0)
    parser.add_argument("--maximum-quote-age-seconds", type=float, default=120.0)
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        bindings = load_crypto_venue_bindings(args.bindings)
        report = validate_crypto_venues(
            bindings=bindings,
            coinbase_provider=CoinbaseExchangeProvider(bindings=bindings),
            kraken_provider=KrakenSpotProvider(bindings=bindings),
            evaluated_at=_timestamp(args.evaluated_at),
            maximum_midpoint_divergence_bps=args.maximum_divergence_bps,
            maximum_quote_age_seconds=args.maximum_quote_age_seconds,
        )
        encoded = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        if args.require_complete and not report.complete:
            return 3
        return 0 if report.complete else 2
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "error": str(error),
                    "complete": False,
                    "provider_certification_granted": False,
                    "paper_test_readiness_granted": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
