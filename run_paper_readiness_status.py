"""Report completion of every remaining controlled paper-readiness objective."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.paper_readiness_status import (
    PaperReadinessStatusAssembler,
    PaperReadinessStatusInputs,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must be timezone-aware")
    return parsed


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
    parser.add_argument("--identifier", default="paper-readiness-status:current")
    parser.add_argument(
        "--baseline-identifier",
        default=os.getenv("CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER"),
    )
    parser.add_argument(
        "--process-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION"),
    )
    parser.add_argument(
        "--code-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_RELEASE") or os.getenv("GITHUB_SHA"),
    )
    parser.add_argument("--evaluated-at")
    parser.add_argument(
        "--provider-requirements",
        default="config/paper_readiness_provider_requirements.json",
    )
    parser.add_argument(
        "--provider-activation-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            str(data_dir / "provider_activations.db"),
        ),
    )
    parser.add_argument(
        "--stage-bindings",
        default=os.getenv("CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS"),
    )
    parser.add_argument(
        "--stage-binding-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_STAGE_BINDING_APPROVAL_DATABASE",
            str(data_dir / "stage_binding_approvals.db"),
        ),
    )
    parser.add_argument(
        "--reconciliation-report",
        action="append",
        default=[],
    )
    parser.add_argument("--execution-calibration-report")
    parser.add_argument(
        "--campaign-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_CAMPAIGN_DATABASE",
            str(data_dir / "paper_test_campaign.db"),
        ),
    )
    parser.add_argument("--recovery-report")
    parser.add_argument(
        "--entry-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE",
            str(data_dir / "paper_test_governance.db"),
        ),
    )
    parser.add_argument(
        "--launch-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE",
            str(data_dir / "paper_trading_launch.db"),
        ),
    )
    parser.add_argument(
        "--control-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_CONTROL_DATABASE",
            str(data_dir / "paper_trading_control.db"),
        ),
    )
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        missing = tuple(
            name
            for name, value in (
                ("--baseline-identifier", args.baseline_identifier),
                ("--process-version", args.process_version),
                ("--code-version", args.code_version),
            )
            if not value
        )
        if missing:
            raise ValueError(
                "paper readiness status requires exact deployment identity: "
                + ", ".join(missing)
            )
        report = PaperReadinessStatusAssembler().assemble(
            identifier=args.identifier,
            evaluated_at=_timestamp(args.evaluated_at),
            baseline_identifier=args.baseline_identifier,
            process_version=args.process_version,
            code_version=args.code_version,
            inputs=PaperReadinessStatusInputs(
                provider_requirements=args.provider_requirements,
                provider_activation_database=args.provider_activation_database,
                stage_bindings=args.stage_bindings,
                stage_binding_database=args.stage_binding_database,
                reconciliation_reports=tuple(args.reconciliation_report),
                execution_calibration_report=args.execution_calibration_report,
                campaign_database=args.campaign_database,
                recovery_report=args.recovery_report,
                entry_database=args.entry_database,
                launch_database=args.launch_database,
                control_database=args.control_database,
            ),
        )
        payload = report.to_dict()
        if args.output:
            _write(args.output, payload)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "paper_test_authorized": False,
                    "real_money_authorized": False,
                    "secret_values_disclosed": False,
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
    if args.require_complete and not report.complete:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
