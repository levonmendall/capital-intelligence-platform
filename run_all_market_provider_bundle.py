"""Assess the selected all-market provider bundle and external activation inputs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from governance.market_data_bundle import (
    assess_all_market_provider_bundle,
    load_all_market_provider_bundle,
)
from governance.provider_activation import SQLiteProviderActivationStore


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def _environment(path: str | None) -> dict[str, str]:
    values = dict(os.environ)
    if path is None:
        return values
    for line_number, raw in enumerate(
        Path(path).expanduser().read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"invalid environment assignment on line {line_number}")
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", default="config/all_market_provider_bundle.json"
    )
    parser.add_argument(
        "--provider-activation-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            "database/provider-activations.db",
        ),
    )
    parser.add_argument("--env-file")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output")
    parser.add_argument("--require-implementation-ready", action="store_true")
    parser.add_argument("--require-external-inputs", action="store_true")
    parser.add_argument("--require-active", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = assess_all_market_provider_bundle(
            load_all_market_provider_bundle(args.bundle),
            evaluated_at=_timestamp(args.evaluated_at),
            environment=_environment(args.env_file),
            provider_activation_store=SQLiteProviderActivationStore(
                args.provider_activation_database
            ),
        )
        payload = report.to_dict()
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        if args.require_active:
            return 0 if report.active else 3
        if args.require_implementation_ready:
            return 0 if report.implementation_ready else 3
        if args.require_external_inputs:
            return 0 if report.external_inputs_ready else 3
        return 0 if report.active else 2 if report.implementation_ready else 3
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "error": str(error),
                    "implementation_ready": False,
                    "external_inputs_ready": False,
                    "active": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
