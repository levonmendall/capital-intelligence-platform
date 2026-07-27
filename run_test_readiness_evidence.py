"""Record immutable product-test-readiness gate or operational evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from governance import (
    OperationalReadinessSnapshot,
    ReadinessGateCertification,
    SQLiteReadinessEvidenceStore,
)


def _payload(path: str) -> Mapping[str, object]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read readiness evidence JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("readiness evidence JSON must encode an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-certification")
    parser.add_argument("--operational-snapshot")
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_READINESS_EVIDENCE_DATABASE",
            str(data_dir / "product_readiness_evidence.db"),
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.gate_certification) == bool(args.operational_snapshot):
        parser.error(
            "choose exactly one of --gate-certification or --operational-snapshot"
        )
    try:
        store = SQLiteReadinessEvidenceStore(args.database)
        if args.gate_certification:
            value = ReadinessGateCertification.from_dict(
                _payload(args.gate_certification)
            )
            sequence = store.append_gate(value)
            kind = "gate_certification"
            identifier = value.identifier
            aggregate_identifier = value.gate.value
        else:
            value = OperationalReadinessSnapshot.from_dict(
                _payload(args.operational_snapshot)
            )
            sequence = store.append_operational(value)
            kind = "operational_snapshot"
            identifier = value.identifier
            aggregate_identifier = value.baseline_identifier
        store.verify_integrity()
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 4
    print(
        json.dumps(
            {
                "status": "recorded",
                "kind": kind,
                "identifier": identifier,
                "aggregate_identifier": aggregate_identifier,
                "registry_sequence": sequence,
                "real_money_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
