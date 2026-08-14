"""Canonical command gateway for supported Capital Intelligence topologies."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


MANIFEST_PATH = Path(__file__).with_name("config") / "runtime_topologies.json"
GOLDEN_MANIFEST_PATH = Path(__file__).with_name("config") / "golden_end_to_end_scenarios.json"


def load_manifest(path: str | Path = MANIFEST_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "capital-intelligence-runtime-topologies.v1":
        raise ValueError("unsupported runtime topology manifest")
    return payload


def command_tokens(name: str, manifest: Mapping[str, Any]) -> tuple[str, ...]:
    commands = dict(manifest["commands"])
    if name not in commands:
        raise ValueError(f"unsupported canonical command: {name}")
    return tuple(
        sys.executable if str(token) == "{python}" else str(token)
        for token in commands[name]
    )


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    repository_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(repository_root)
    inventory = dict(manifest["root_script_inventory"])
    classified = (
        set(inventory["runtime_active"])
        | set(inventory["specialized_supported"])
        | set(inventory["legacy"])
    )
    # Only executable/operator-facing run_*.py scripts belong in the command inventory.
    # Adjacent *_core.py modules are implementation details behind governed wrappers and
    # must not become independently supported command surfaces merely because they live
    # at repository root.
    actual = {
        path.name
        for path in root.glob("run_*.py")
        if not path.name.endswith("_core.py")
    }
    duplicates = sum(len(inventory[key]) for key in inventory) - len(classified)
    missing = sorted(actual - classified)
    extra = sorted(classified - actual)
    ready = not missing and not extra and duplicates == 0
    return {
        "ready": ready,
        "root_script_count": len(actual),
        "classified_script_count": len(classified),
        "missing": missing,
        "extra": extra,
        "duplicate_classifications": duplicates,
        "legacy": sorted(inventory["legacy"]),
        "schema_version": "capital-intelligence-command-inventory.v1",
        "real_money_authorized": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("command", choices=tuple(load_manifest()["commands"]))
    topology = subparsers.add_parser("topology")
    topology.add_argument("environment", choices=tuple(load_manifest()["topologies"]))
    subparsers.add_parser("inventory")
    subparsers.add_parser("validate")
    golden = subparsers.add_parser("golden-gate")
    golden.add_argument("--manifest", default=str(GOLDEN_MANIFEST_PATH))
    golden.add_argument("--report", default="reports/golden-end-to-end-gate.json")
    benchmark = subparsers.add_parser("event-quality-benchmark")
    benchmark.add_argument(
        "--benchmark",
        default=str(Path(__file__).with_name("config") / "event_quality_benchmark.v1.json"),
    )
    benchmark.add_argument("--report", default="reports/event-quality-benchmark.json")
    benchmark.add_argument("--require-certified", action="store_true")
    experiment = subparsers.add_parser("paper-experiment-register")
    experiment.add_argument(
        "--protocol",
        default=str(Path(__file__).with_name("config") / "paper_experiment_protocol.v1.json"),
    )
    experiment.add_argument("--gate-evidence", required=True)
    experiment.add_argument("--code-version", required=True)
    experiment.add_argument("--deployed-git-sha", required=True)
    experiment.add_argument("--start-date", required=True)
    experiment.add_argument("--database", default="database/paper-experiment.db")
    cash = subparsers.add_parser("persistent-cash-report")
    cash.add_argument("--journal-database", default="database/cio_journal.db")
    cash.add_argument("--report", default="reports/persistent-cash-summary.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest()
    if args.action == "topology":
        print(json.dumps(manifest["topologies"][args.environment], indent=2, sort_keys=True))
        return 0
    if args.action in {"inventory", "validate"}:
        report = validate_manifest(manifest, repository_root=Path(__file__).parent)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ready"] else 2
    if args.action == "golden-gate":
        from operations.golden_end_to_end import run_golden_gate

        report = run_golden_gate(
            manifest_path=args.manifest,
            repository_root=Path(__file__).parent,
            report_path=args.report,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "passed" else 2
    if args.action == "event-quality-benchmark":
        from operations.event_quality_benchmark import evaluate_event_quality_benchmark

        report = evaluate_event_quality_benchmark(args.benchmark)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.require_certified and not report["certified"]:
            return 2
        return 0
    if args.action == "paper-experiment-register":
        from governance.paper_experiment import register_paper_experiment

        result = register_paper_experiment(
            protocol_path=args.protocol,
            gate_evidence_path=args.gate_evidence,
            code_version=args.code_version,
            deployed_git_sha=args.deployed_git_sha,
            start_date=date.fromisoformat(args.start_date),
            database_path=args.database,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.action == "persistent-cash-report":
        from operations.persistent_cash_diagnostic import build_persistent_cash_summary

        report = build_persistent_cash_summary(args.journal_database)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.action == "run":
        command = command_tokens(args.command, manifest)
        completed = subprocess.run(command, check=False, env=os.environ.copy())
        return int(completed.returncode)
    raise ValueError(f"unsupported action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
