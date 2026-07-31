"""Canonical command gateway for supported Capital Intelligence topologies."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
    actual = {path.name for path in root.glob("run_*.py")}
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
        from intelligence.event_quality import evaluate_benchmark

        report = evaluate_benchmark(args.benchmark)
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        passed = report["certified"] if args.require_certified else report["metrics_passed"]
        return 0 if passed else 2

    command = command_tokens(args.command, manifest)
    if args.command == "api":
        subprocess.run((sys.executable, "initialize.py"), check=True)
    os.execvpe(command[0], command, os.environ.copy())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
