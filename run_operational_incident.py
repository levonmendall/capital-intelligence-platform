"""Record one immutable operational-incident state transition."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from operations import OperationalIncidentEvent, SQLiteOperationalIncidentStore


def _payload(path: str) -> Mapping[str, object]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read incident JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("incident JSON must encode an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_OPERATIONAL_INCIDENT_DATABASE",
            str(data_dir / "operational_incidents.db"),
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        event = OperationalIncidentEvent.from_dict(_payload(args.event))
        store = SQLiteOperationalIncidentStore(args.database)
        sequence = store.append(event)
        store.verify_integrity()
        active = store.active_incidents(as_of=event.occurred_at)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 4
    print(
        json.dumps(
            {
                "status": "recorded",
                "event_identifier": event.identifier,
                "incident_identifier": event.incident_identifier,
                "incident_state": event.state.value,
                "registry_sequence": sequence,
                "active_incident_count": len(active),
                "real_money_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
