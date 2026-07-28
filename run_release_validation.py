"""Run the complete deterministic Capital Intelligence release validation plan."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from operations.release_validation import (
    ReleaseValidationRunner,
    ReleaseValidationStep,
)


ROOT = Path(__file__).resolve().parent


def _steps(*, include_container: bool) -> tuple[ReleaseValidationStep, ...]:
    python = sys.executable
    steps = [
        ReleaseValidationStep(
            "compile_python",
            (python, "-m", "compileall", "-q", "."),
            300,
        ),
        ReleaseValidationStep(
            "initialize_platform",
            (python, "initialize.py"),
            300,
        ),
        ReleaseValidationStep(
            "validate_daily_plan",
            (python, "run_daily_operations.py", "--validate-plan"),
            120,
        ),
        ReleaseValidationStep(
            "run_intelligence",
            (python, "run_intelligence.py"),
            300,
        ),
        ReleaseValidationStep(
            "validate_all_markets_internal_readiness",
            (
                python,
                "run_all_markets_paper_readiness.py",
                "--provider-activation-database",
                "reports/release-provider-activations.db",
                "--asset-class-governance-database",
                "reports/release-asset-class-governance.db",
                "--evaluated-at",
                "2026-07-28T00:00:00+00:00",
                "--require-internal-ready",
            ),
            120,
        ),
        ReleaseValidationStep(
            "rehearse_all_markets_paper_execution",
            (
                python,
                "run_all_markets_paper_rehearsal.py",
                "--evaluated-at",
                "2026-07-28T00:00:00+00:00",
                "--working-directory",
                "reports/all-markets-paper-rehearsal",
                "--require-complete",
            ),
            180,
        ),
        ReleaseValidationStep(
            "full_test_suite",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                "--junitxml=reports/pytest-results.xml",
            ),
            1500,
        ),
    ]
    if include_container:
        steps.extend(
            (
                ReleaseValidationStep(
                    "build_validation_image",
                    (
                        "docker",
                        "build",
                        "--target",
                        "validation",
                        "--tag",
                        "capital-intelligence:validation",
                        ".",
                    ),
                    600,
                ),
                ReleaseValidationStep(
                    "run_container_acceptance",
                    (
                        "docker",
                        "run",
                        "--rm",
                        "capital-intelligence:validation",
                    ),
                    600,
                ),
                ReleaseValidationStep(
                    "build_runtime_image",
                    (
                        "docker",
                        "build",
                        "--target",
                        "runtime",
                        "--tag",
                        "capital-intelligence:runtime",
                        ".",
                    ),
                    600,
                ),
            )
        )
    return tuple(steps)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host-only",
        action="store_true",
        help=(
            "Run only host compilation, initialization, plan validation, "
            "intelligence, and tests. The default release command also validates "
            "the supported Python container and runtime image."
        ),
    )
    parser.add_argument(
        "--report",
        default="reports/release-validation.json",
    )
    parser.add_argument(
        "--maximum-diagnostic-characters",
        type=int,
        default=20_000,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.maximum_diagnostic_characters < 1:
        raise SystemExit("--maximum-diagnostic-characters must be positive")
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(ROOT),
            "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS": str(
                ROOT
                / "deploy"
                / "canonical-daily-stage-bindings.validation.json"
            ),
        }
    )
    runner = ReleaseValidationRunner(
        steps=_steps(include_container=not args.host_only),
        report_path=Path(args.report).expanduser(),
        working_directory=ROOT,
        environment=environment,
        maximum_diagnostic_characters=args.maximum_diagnostic_characters,
    )
    report = runner.run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
