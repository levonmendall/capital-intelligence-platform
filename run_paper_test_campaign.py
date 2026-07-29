"""Record and assess controlled paper-test launch-readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import (
    BurnInDayRecord,
    FailureScenarioRecord,
    PaperTestCampaignBaseline,
    PaperTestCampaignEvaluator,
    SQLitePaperTestCampaignStore,
)


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read campaign JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("campaign JSON must encode an object")
    return value


def _database(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_CAMPAIGN_DATABASE",
            str(data_dir / "paper_test_campaign.db"),
        )
    ).expanduser()


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record-baseline")
    group.add_argument("--record-day")
    group.add_argument("--record-scenario")
    group.add_argument("--assess-baseline")
    group.add_argument("--inspect-baseline")
    parser.add_argument("--evaluated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = SQLitePaperTestCampaignStore(_database(args.database))
        if args.record_baseline:
            value = PaperTestCampaignBaseline.from_dict(_load(args.record_baseline))
            sequence = store.append_baseline(value)
            payload = {**value.to_dict(), "registry_sequence": sequence}
        elif args.record_day:
            value = BurnInDayRecord.from_dict(_load(args.record_day))
            sequence = store.append_day(value)
            payload = {**value.to_dict(), "registry_sequence": sequence}
        elif args.record_scenario:
            value = FailureScenarioRecord.from_dict(_load(args.record_scenario))
            sequence = store.append_scenario(value)
            payload = {**value.to_dict(), "registry_sequence": sequence}
        else:
            identifier = args.assess_baseline or args.inspect_baseline
            baseline = store.baseline(identifier)
            if baseline is None:
                raise ValueError(f"campaign baseline {identifier!r} is unavailable")
            if args.inspect_baseline:
                reports = store.reports(identifier)
                payload = {
                    "baseline": baseline.to_dict(),
                    "burn_in_days": [item.to_dict() for item in store.days(identifier)],
                    "failure_scenarios": [
                        item.to_dict() for item in store.scenarios(identifier)
                    ],
                    "latest_report": None if not reports else reports[-1].to_dict(),
                    "integrity_verified": store.verify_integrity(),
                }
            else:
                report = PaperTestCampaignEvaluator().evaluate(
                    baseline=baseline,
                    days=store.days(identifier),
                    scenarios=store.scenarios(identifier),
                    evaluated_at=_timestamp(args.evaluated_at),
                )
                store.append_report(report)
                payload = report.to_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "paper_test_authorized": False,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
