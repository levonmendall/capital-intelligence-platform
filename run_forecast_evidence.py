"""Record or inspect supporting-only forecast evidence and candidate references."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from application import CandidateForecastSupport, SQLiteCandidateForecastSupportStore
from governance import GovernedForecastEvidence, SQLiteForecastEvidenceStore


def _load(path: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON document {path!r}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("JSON document must encode an object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--forecast")
    mode.add_argument("--candidate-support")
    mode.add_argument("--latest-target")
    mode.add_argument("--cycle")
    parser.add_argument("--as-of")
    parser.add_argument("--knowledge-cutoff")
    parser.add_argument(
        "--forecast-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FORECAST_EVIDENCE_DATABASE",
            str(data_dir / "forecast_evidence.db"),
        ),
    )
    parser.add_argument(
        "--support-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FORECAST_SUPPORT_DATABASE",
            str(data_dir / "forecast_support.db"),
        ),
    )
    return parser


def _timestamp(value: str | None, *, field_name: str) -> datetime:
    if value is None:
        raise ValueError(f"--{field_name.replace('_', '-')} is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        forecasts = SQLiteForecastEvidenceStore(args.forecast_database)
        supports = SQLiteCandidateForecastSupportStore(args.support_database)
        if args.forecast:
            forecast = GovernedForecastEvidence.from_dict(_load(args.forecast))
            sequence = forecasts.append(forecast)
            forecasts.verify_integrity()
            payload = {**forecast.to_dict(), "registry_sequence": sequence}
        elif args.candidate_support:
            support = CandidateForecastSupport.from_dict(
                _load(args.candidate_support)
            )
            sequence = supports.append(support)
            supports.verify_integrity()
            payload = {**support.to_dict(), "registry_sequence": sequence}
        elif args.latest_target:
            cutoff = _timestamp(
                args.knowledge_cutoff,
                field_name="knowledge_cutoff",
            )
            forecast = forecasts.latest_for_target(
                args.latest_target,
                knowledge_cutoff=cutoff,
            )
            if forecast is None:
                raise ValueError("no usable forecast exists for the target and cutoff")
            payload = forecast.to_dict()
        else:
            as_of = _timestamp(args.as_of, field_name="as_of")
            payload = {
                "screening_cycle_identifier": args.cycle,
                "as_of": as_of.isoformat(),
                "references": [
                    item.to_dict()
                    for item in supports.references_for_cycle(
                        args.cycle,
                        as_of=as_of,
                    )
                ],
                "supporting_only": True,
                "independent_decision_authority": False,
            }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "independent_decision_authority": False,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
