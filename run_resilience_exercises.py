"""Run isolated incident, recovery, and reconciliation exercises."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import (
    ResilienceExerciseHarness,
    ResilienceExercisePolicy,
    SQLiteResilienceExerciseStore,
    policy_from_payload,
    scenario_from_payload,
)


def _json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _provider(value: str):
    if ":" not in value:
        raise ValueError("provider factory must use module:function form")
    module_name, attribute_name = value.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute_name, None)
    if not callable(factory):
        raise ValueError(f"provider factory {value!r} is not callable")
    return factory()


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("evaluated-at must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run isolated operational resilience exercises, persist immutable "
            "evidence, and fail unless all required detection, recovery, and "
            "reconciliation controls pass. This never authorizes live trading."
        )
    )
    parser.add_argument("--suite", required=True, help="Scenario-suite JSON object or list.")
    parser.add_argument("--provider", required=True, help="Provider factory module:function.")
    parser.add_argument("--policy", help="Optional policy JSON object.")
    parser.add_argument("--database", help="Append-only resilience evidence database.")
    parser.add_argument("--evaluated-at", help="ISO-8601 campaign evaluation timestamp.")
    parser.add_argument("--record", action="store_true", help="Persist outcomes and report.")
    parser.add_argument("--require-passed", action="store_true", help="Exit nonzero unless the release gate passes.")
    args = parser.parse_args(argv)
    try:
        raw_suite = _json(args.suite)
        values = raw_suite if isinstance(raw_suite, list) else raw_suite.get("scenarios")
        if not isinstance(values, list):
            raise ValueError("suite must encode a list or an object with scenarios")
        scenarios = tuple(scenario_from_payload(item) for item in values if isinstance(item, dict))
        if len(scenarios) != len(values):
            raise ValueError("every scenario must be an object")
        policy = ResilienceExercisePolicy()
        if args.policy:
            raw_policy = _json(args.policy)
            if not isinstance(raw_policy, dict):
                raise ValueError("policy must encode an object")
            policy = policy_from_payload(raw_policy)
        provider = _provider(args.provider)
        evaluated_at = _timestamp(args.evaluated_at)
    except (ImportError, AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    outcomes, report = ResilienceExerciseHarness(policy).run(scenarios, provider, evaluated_at=evaluated_at)
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    database = Path(args.database).expanduser() if args.database else data_dir / "resilience_exercises.db"
    if args.record:
        store = SQLiteResilienceExerciseStore(database)
        for outcome in outcomes:
            store.append_outcome(outcome, recorded_at=evaluated_at)
        store.append_report(report, recorded_at=evaluated_at)
        store.verify_integrity()
    payload = report.to_dict()
    payload["outcomes"] = [item.to_dict() for item in outcomes]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.release_gate_passed or not args.require_passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
