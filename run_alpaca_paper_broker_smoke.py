"""Submit and reconcile a neutral round trip in the Alpaca paper environment."""

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
from operations.alpaca_paper_broker import (
    AlpacaPaperBrokerExecutor,
    SQLiteAlpacaPaperBrokerStore,
)
from providers.alpaca_paper_broker import create_alpaca_paper_broker_client


DEFAULT_ACTIVATION = Path("config/alpaca_paper_broker_activation.json")
MINIMUM_SMOKE_NOTIONAL = 10.0


def _write(path: str, payload: dict[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation", default=str(DEFAULT_ACTIVATION))
    parser.add_argument(
        "--provider-activation-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            str(data_dir / "provider_activations.db"),
        ),
    )
    parser.add_argument(
        "--broker-event-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ALPACA_PAPER_BROKER_DATABASE",
            str(data_dir / "alpaca_paper_broker.db"),
        ),
    )
    parser.add_argument("--symbol", default="BTC/USD")
    parser.add_argument(
        "--notional",
        type=float,
        default=MINIMUM_SMOKE_NOTIONAL,
        help="Neutral paper buy notional; Alpaca currently requires at least $10.",
    )
    parser.add_argument("--output")
    parser.add_argument("--require-reconciled", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.notional < MINIMUM_SMOKE_NOTIONAL:
            raise ValueError(
                f"--notional must be at least ${MINIMUM_SMOKE_NOTIONAL:,.2f} "
                "for the Alpaca paper smoke order"
            )
        payload = json.loads(
            Path(args.activation).expanduser().read_text(encoding="utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("provider activation must encode an object")
        activation = ProviderActivation.from_dict(payload)
        activation_store = SQLiteProviderActivationStore(
            args.provider_activation_database
        )
        activation_sequence = activation_store.append(activation)
        activation_store.verify_integrity()
        broker_store = SQLiteAlpacaPaperBrokerStore(args.broker_event_database)
        report = AlpacaPaperBrokerExecutor(
            client=create_alpaca_paper_broker_client(),
            activation_store=activation_store,
            event_store=broker_store,
        ).round_trip_smoke(
            symbol=args.symbol,
            notional=args.notional,
            evaluated_at=datetime.now(timezone.utc),
        )
        result = report.to_dict()
        result["provider_activation_sequence"] = activation_sequence
        result["provider_activation_identifier"] = activation.identifier
        result["broker_event_integrity_verified"] = broker_store.verify_integrity()
        result["secret_values_disclosed"] = False
        if args.output:
            _write(args.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.require_reconciled and not report.reconciled:
            return 3
        return 0 if report.reconciled else 2
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        result = {
            "status": "blocked",
            "error": str(error),
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        }
        if args.output:
            _write(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
