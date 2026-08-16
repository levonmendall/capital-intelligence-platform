"""Audit whole-system runtime reachability and declared decision influence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from governance.runtime_influence_registry import audit_repository


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="Repository root to audit.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "runtime-connectivity-audit.json"),
        help="JSON report path.",
    )
    parser.add_argument(
        "--require-valid",
        action="store_true",
        help="Return non-zero when a declared capability contract is invalid.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = audit_repository(args.root)
    destination = audit.write_json(args.output)
    summary = {
        "passed": audit.passed,
        "module_count": audit.module_count,
        "reachable_module_count": audit.reachable_module_count,
        "unreachable_module_count": audit.unreachable_module_count,
        "lifecycle_counts": dict(audit.lifecycle_counts),
        "runtime_roots": list(audit.runtime_roots),
        "invalid_capabilities": [
            {
                "name": item.name,
                "issues": list(item.issues),
            }
            for item in audit.capabilities
            if not item.valid
        ],
        "report": str(destination),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if args.require_valid and not audit.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
