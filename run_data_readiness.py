"""Evaluate market data, maximum information, and public live coverage safely."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance import (
    AllMarketsDataReadinessEvaluator,
    AllMarketsDataReadinessState,
    DataReadinessError,
    load_data_readiness_manifest,
)
from governance.decision_information_readiness import (
    DecisionInformationReadinessError,
    DecisionInformationReadinessState,
    MaximumDecisionInformationReadinessEvaluator,
    load_maximum_decision_information_manifest,
)


def _default_manifest() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_DATA_READINESS_MANIFEST",
        "config/all_markets_data_readiness.json",
    )


def _default_information_manifest() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_MANIFEST",
        "config/maximum_decision_information_scope.json",
    )


def _default_public_live_report() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT",
        "database/public-live-information-report.json",
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


def _timestamp(value: str, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _load_public_live_report(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    report_path = Path(path).expanduser()
    if not report_path.exists():
        return None
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("public live information report must be a JSON object")
    payload.pop("records", None)
    payload["secret_values_disclosed"] = False
    payload["full_article_text_stored"] = False
    payload["real_money_authorized"] = False
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=_default_manifest(),
        help="Version-controlled all-markets operating-data manifest JSON.",
    )
    parser.add_argument(
        "--information-manifest",
        default=_default_information_manifest(),
        help="Maximum decision-relevant information manifest JSON.",
    )
    parser.add_argument(
        "--public-live-report",
        default=_default_public_live_report(),
        help="Latest persisted public live-information coverage report JSON.",
    )
    parser.add_argument(
        "--env-file",
        help="Optional KEY=VALUE file overlaid on the runtime environment.",
    )
    parser.add_argument(
        "--show-required-environment",
        action="store_true",
        help="Print credential/configuration variable names only; never values.",
    )
    parser.add_argument("--output", help="Optional path for the combined JSON report.")
    parser.add_argument(
        "--gate-certification-output",
        help="Write certified-data gate JSON only when both governed scopes are ready.",
    )
    parser.add_argument("--gate-identifier")
    parser.add_argument("--baseline-identifier")
    parser.add_argument("--process-version")
    parser.add_argument("--code-version")
    parser.add_argument("--authority-identifier", action="append", default=[])
    parser.add_argument("--certified-at")
    parser.add_argument("--effective-at")
    parser.add_argument("--expires-at")
    parser.add_argument("--compact", action="store_true")
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


def _combined_payload(
    market_report,
    information_report,
    public_live_report: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    payload = market_report.to_dict()
    combined_ready = (
        market_report.global_test_data_ready and information_report.all_domains_ready
    )
    if combined_ready:
        state = "ready"
    elif (
        market_report.state is AllMarketsDataReadinessState.PARTIAL
        or information_report.state is DecisionInformationReadinessState.PARTIAL
        or market_report.state is AllMarketsDataReadinessState.READY
        or information_report.state is DecisionInformationReadinessState.READY
    ):
        state = "partial"
    else:
        state = "blocked"
    live_successes = (
        0
        if public_live_report is None
        else int(public_live_report.get("successful_source_count", 0))
    )
    live_records = (
        0
        if public_live_report is None
        else int(public_live_report.get("live_record_count", 0))
    )
    payload.update(
        {
            "schema_version": "combined-market-information-and-live-coverage-report.v1",
            "state": state,
            "market_data_ready": market_report.global_test_data_ready,
            "maximum_decision_information_ready": information_report.all_domains_ready,
            "current_events_and_news_ready": information_report.current_events_and_news_ready,
            "public_live_information_available": public_live_report is not None,
            "public_live_successful_source_count": live_successes,
            "public_live_record_count": live_records,
            "global_test_data_ready": combined_ready,
            "missing_environment_variables": sorted(
                set(market_report.missing_environment_variables)
                | set(information_report.missing_environment_variables)
            ),
            "blockers": [
                *(f"market-data: {item}" for item in market_report.blockers),
                *(f"decision-information: {item}" for item in information_report.blockers),
            ],
            "decision_information": information_report.to_dict(),
            "public_live_information": public_live_report,
            "evidence_identifier": (
                "combined-data-readiness:"
                f"{market_report.manifest_identifier}:"
                f"{information_report.manifest_identifier}:{state}"
            ),
            "real_money_authorized": False,
        }
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        market_manifest = load_data_readiness_manifest(args.manifest)
        information_manifest = load_maximum_decision_information_manifest(
            args.information_manifest
        )
        if args.show_required_environment:
            required = sorted(
                set(market_manifest.required_environment_variables)
                | set(information_manifest.required_environment_variables)
            )
            print(
                json.dumps(
                    {
                        "market_manifest_identifier": market_manifest.identifier,
                        "information_manifest_identifier": information_manifest.identifier,
                        "public_live_report_path": args.public_live_report,
                        "required_environment_variables": required,
                        "secret_values_disclosed": False,
                    },
                    indent=None if args.compact else 2,
                    sort_keys=True,
                )
            )
            return 0
        environment = _environment_file(args.env_file)
        market_report = AllMarketsDataReadinessEvaluator().evaluate(
            market_manifest,
            environment=environment,
        )
        information_report = MaximumDecisionInformationReadinessEvaluator().evaluate(
            information_manifest,
            environment=environment,
        )
        public_live_report = _load_public_live_report(args.public_live_report)
        payload = _combined_payload(
            market_report,
            information_report,
            public_live_report,
        )
        if args.output:
            _write(args.output, payload)
        if args.gate_certification_output:
            if not payload["global_test_data_ready"]:
                raise DataReadinessError(
                    "cannot certify the product data gate until both market data and maximum decision-information coverage are ready"
                )
            required = {
                "--gate-identifier": args.gate_identifier,
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
            additional_evidence = [
                information_report.evidence_identifier,
                information_report.manifest_identifier,
            ]
            if public_live_report is not None:
                additional_evidence.append(
                    "public-live-information:"
                    + str(public_live_report.get("catalog_identifier", "unknown"))
                    + ":"
                    + str(public_live_report.get("evaluated_at", "unknown"))
                )
            certification = market_report.to_readiness_gate_certification(
                identifier=args.gate_identifier,
                certified_at=_timestamp(args.certified_at, field_name="--certified-at"),
                effective_at=_timestamp(args.effective_at, field_name="--effective-at"),
                expires_at=_timestamp(args.expires_at, field_name="--expires-at"),
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                authority_identifiers=tuple(args.authority_identifier),
                additional_evidence_identifiers=tuple(additional_evidence),
                limitations=(
                    "maximum decision-relevant information scope is required for this baseline",
                    "public live coverage supplements but does not replace licensed institutional sources",
                ),
            )
            _write(args.gate_certification_output, certification.to_dict())
    except (
        DataReadinessError,
        DecisionInformationReadinessError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
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

    print(json.dumps(payload, indent=None if args.compact else 2, sort_keys=True))
    if payload["state"] == "ready":
        return 0
    if payload["state"] == "partial":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
