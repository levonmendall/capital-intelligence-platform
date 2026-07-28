"""Validate and append one complete all-market provider activation package."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from governance.market_data_bundle import load_all_market_provider_bundle
from governance.provider_activation import (
    ProviderActivation,
    SQLiteProviderActivationStore,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def _documents(directory: str | Path) -> tuple[ProviderActivation, ...]:
    source = Path(directory).expanduser()
    if not source.is_dir():
        raise ValueError(f"activation directory does not exist: {source}")
    documents: list[ProviderActivation] = []
    for path in sorted(source.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"activation must encode an object: {path}")
        documents.append(ProviderActivation.from_dict(payload))
    if not documents:
        raise ValueError("activation directory contains no JSON documents")
    provider_ids = tuple(item.provider_identifier for item in documents)
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("activation package contains duplicate providers")
    return tuple(documents)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", default="config/all_market_provider_bundle.json"
    )
    parser.add_argument("--activation-directory", required=True)
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            "database/provider-activations.db",
        ),
    )
    parser.add_argument("--evaluated-at")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        bundle = load_all_market_provider_bundle(args.bundle)
        documents = _documents(args.activation_directory)
        expected = {
            item.provider_identifier
            for item in bundle.members
            if item.activation_required and item.required
        }
        actual = {item.provider_identifier for item in documents}
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        blockers: list[str] = []
        if missing:
            blockers.append("missing provider activations: " + ", ".join(missing))
        if extra:
            blockers.append("unexpected provider activations: " + ", ".join(extra))
        disabled = sorted(
            item.provider_identifier for item in documents if not item.enabled
        )
        if disabled:
            blockers.append("provider activations are disabled: " + ", ".join(disabled))
        evaluated_at = _timestamp(args.evaluated_at)
        inactive = sorted(
            item.provider_identifier
            for item in documents
            if not item.active_at(evaluated_at)
        )
        if inactive:
            blockers.append(
                "provider activations are outside their effective window: "
                + ", ".join(inactive)
            )
        sequences: list[int] = []
        if not blockers and not args.validate_only:
            store = SQLiteProviderActivationStore(args.database)
            store.verify_integrity()
            for item in documents:
                sequences.append(store.append(item))
            store.verify_integrity()
        print(
            json.dumps(
                {
                    "bundle_identifier": bundle.identifier,
                    "evaluated_at": evaluated_at.isoformat(),
                    "valid": not blockers,
                    "appended": not blockers and not args.validate_only,
                    "appended_sequences": sequences,
                    "provider_identifiers": sorted(actual),
                    "blockers": blockers,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not blockers else 3
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "error": str(error),
                    "valid": False,
                    "appended": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
