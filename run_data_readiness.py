"""Evaluate the complete all-markets data supply chain without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from governance import (
    AllMarketsDataReadinessEvaluator,
    AllMarketsDataReadinessState,
    DataReadinessError,
    load_data_readiness_manifest,
)


def _default_manifest() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_DATA_READINESS_MANIFEST",
        "config/all_markets_data_readiness.json",
    )


def _environment_file(path: str | None) -> dict[str, str]:
    values = dict(os.environ)
    if path is None:
        return values
    file_path = Path(path).expanduser()
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read environment file {path!r}") from error
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(
                f"invalid environment assignment on line {line_number}"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(
                f"environment variable name is empty on line {line_number}"
            )
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and (
            normalized[0] in {"'", '"'}
        ):
            normalized = normalized[1:-1]
        values[name] = normalized
    return values



def _timestamp(value: str, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=_default_manifest(),
        help="Version-controlled all-markets data manifest JSON.",
    )
    parser.add_argument(
        "--env-file",
        help="Optional KEY=VALUE file overlaid on the runtime environment.",
    )
    parser.add_argument(
        "--show-required-environment",
        action="store_true",
        help="Print only credential/configuration variable names; never values.",
    )
    parser.add_argument(
        "--output",
        help="Optional path for the complete JSON readiness report.",
    )
    parser.add_argument(
        "--gate-certification-output",
        help=(
            "Write a certified-data ReadinessGateCertification JSON only when "
            "the all-markets report is ready."
        ),
    )
    parser.add_argument("--gate-identifier")
    parser.add_argument("--baseline-identifier")
    parser.add_argument("--process-version")
    parser.add_argument("--code-version")
    parser.add_argument("--authority-identifier", action="append", default=[])
    parser.add_argument("--certified-at")
    parser.add_argument("--effective-at")
    parser.add_argument("--expires-at")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON for scheduled-operation integration.",
    )
    return parser


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = load_data_readiness_manifest(args.manifest)
        if args.show_required_environment:
            print(
                json.dumps(
                    {
                        "manifest_identifier": manifest.identifier,
                        "required_environment_variables": list(
                            manifest.required_environment_variables
                        ),
                        "secret_values_disclosed": False,
                    },
                    indent=None if args.compact else 2,
                    sort_keys=True,
                )
            )
            return 0
        environment = _environment_file(args.env_file)
        report = AllMarketsDataReadinessEvaluator().evaluate(
            manifest,
            environment=environment,
        )
        payload = report.to_dict()
        if args.output:
            _write(args.output, payload)
        if args.gate_certification_output:
            required = {
                "--gate-identificatior": args.gate_identifier,
                "--baseline-identifier": args.baseline_identifier,
                "--process-version": args.process_version,
                "--code-version": args.code_version,
                "--certified-at": args.certified_at,
                "--effective-at": args.effective_at,
                "--expires-at": args.expires_at,
            }
            missing = tuple(name for name, value in required.items() if not value)
            if not args.authority_identifier:
                missing = missing + ("--authority-identifier",)
            if missing:
                raise ValueError(
                    "gate certification output requires: " + ", ".join(missing)
                )
            certification = report.to_readiness_gate_certification(
                identifier=args.gate_identifier,
                certified_at=_timestamp(
                    args.certified_at, field_name="--certified-at"
                ),
                effective_at=_timestamp(
                    args.effective_at, field_name="--effective-at"
                ),
                expires_at=_timestamp(
                    args.expires_at, field_name="--expires-at"
                ),
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                authority_identifiers=tuple(args.authority_identifier),
            )
            _write(args.gate_certification_output, certification.to_dict())
    except (DataReadinessError, KeyError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
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
    if report.state is AllMarketsDataReadinessState.READY:
        return 0
    if report.state is AllMarketsDataReadinessState.PARTIAL:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
