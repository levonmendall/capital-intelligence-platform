"""Evaluate and persist current paper-trading launch evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from governance import (
    PaperTradingLaunchEvidence,
    PaperTradingLaunchEvaluator,
    PaperTradingLaunchPolicy,
    PaperTradingLaunchState,
    SQLitePaperTradingLaunchStore,
)


def _load(path: str) -> object:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON file {path!r}") from error


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--policy")
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE",
            str(data_dir / "paper_trading_launch.db"),
        ),
    )
    parser.add_argument("--output")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence_payload = _load(args.evidence)
        if not isinstance(evidence_payload, Mapping):
            raise ValueError("launch evidence JSON must encode an object")
        policy = PaperTradingLaunchPolicy()
        if args.policy:
            policy_payload = _load(args.policy)
            if not isinstance(policy_payload, Mapping):
                raise ValueError("launch policy JSON must encode an object")
            policy = PaperTradingLaunchPolicy.from_dict(policy_payload)
        evidence = PaperTradingLaunchEvidence.from_dict(evidence_payload)
        report = PaperTradingLaunchEvaluator(policy).evaluate(evidence)
        store = SQLitePaperTradingLaunchStore(args.database)
        sequence = store.append(report)
        store.verify_integrity()
        payload = report.to_dict()
        payload["registry_sequence"] = sequence
        payload["secret_values_disclosed"] = False
        if args.output:
            _write(args.output, payload)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "secret_values_disclosed": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    print(
        json.dumps(
            payload,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    if args.require_ready and report.state is not PaperTradingLaunchState.READY:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
