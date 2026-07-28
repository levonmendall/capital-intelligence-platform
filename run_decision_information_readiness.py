"""Evaluate maximum decision-relevant information coverage without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from governance.decision_information_readiness import (
    DecisionInformationReadinessError,
    DecisionInformationReadinessState,
    MaximumDecisionInformationReadinessEvaluator,
    load_maximum_decision_information_manifest,
)


def _default_manifest() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_MANIFEST",
        "config/maximum_decision_information_scope.json",
    )


def _environment_file(path: str | None) -> dict[str, str]:
    values = dict(os.environ)
    if path is None:
        return values
    file_path = Path(path).expanduser()
    for line_number, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"invalid environment assignment on line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"environment variable name is empty on line {line_number}")
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        values[name] = normalized
    return values


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=_default_manifest())
    parser.add_argument("--env-file")
    parser.add_argument("--show-required-environment", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_maximum_decision_information_manifest(args.manifest)
        if args.show_required_environment:
            payload = {
                "manifest_identifier": manifest.identifier,
                "required_environment_variables": list(manifest.required_environment_variables),
                "secret_values_disclosed": False,
            }
            print(json.dumps(payload, indent=None if args.compact else 2, sort_keys=True))
            return 0
        report = MaximumDecisionInformationReadinessEvaluator().evaluate(
            manifest,
            environment=_environment_file(args.env_file),
        )
        payload = report.to_dict()
        if args.output:
            _write(args.output, payload)
    except (DecisionInformationReadinessError, KeyError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"state": "blocked", "error": str(error), "real_money_authorized": False}, sort_keys=True))
        return 4
    print(json.dumps(payload, indent=None if args.compact else 2, sort_keys=True))
    if report.state is DecisionInformationReadinessState.READY:
        return 0
    if report.state is DecisionInformationReadinessState.PARTIAL:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
