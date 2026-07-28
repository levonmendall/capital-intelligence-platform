"""Publish or inspect governed asset-specific evidence packets."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from application import AssetSpecificEvidencePacket, SQLiteAssetSpecificEvidenceStore


def _load(path: str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("asset-specific evidence JSON must encode an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--packet")
    mode.add_argument("--cycle")
    parser.add_argument("--as-of", help="Required with --cycle; ISO-8601 timestamp.")
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ASSET_SPECIFIC_EVIDENCE_DATABASE",
            "database/asset_specific_evidence.db",
        ),
    )
    args = parser.parse_args(argv)
    try:
        store = SQLiteAssetSpecificEvidenceStore(args.database)
        if args.packet:
            packet = AssetSpecificEvidencePacket.from_dict(_load(args.packet))
            sequence = store.append(packet)
            payload = {**packet.to_dict(), "registry_sequence": sequence}
        else:
            if not args.as_of:
                raise ValueError("--as-of is required with --cycle")
            timestamp = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("--as-of must include a UTC offset")
            packets = store.packets_for_cycle(args.cycle, as_of=timestamp)
            payload = {
                "screening_cycle_identifier": args.cycle,
                "as_of": timestamp.isoformat(),
                "packet_count": len(packets),
                "packets": [item.to_dict() for item in packets],
                "real_money_authorized": False,
            }
        store.verify_integrity()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
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
