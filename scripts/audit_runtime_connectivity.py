"""Audit whole-system runtime reachability and declared decision influence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from governance.runtime_influence_registry import ComponentLifecycle, audit_repository
from governance.runtime_module_dispositions import MODULE_DISPOSITION_BY_NAME


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
        help=(
            "Return non-zero when a declared capability contract is invalid, an "
            "unreachable decision-capable module lacks an explicit disposition, or "
            "an intentionally non-live module becomes runtime-reachable."
        ),
    )
    return parser


def _converged_payload(audit) -> tuple[dict[str, object], tuple[str, ...]]:
    """Apply explicit non-live dispositions and reject any remaining ambiguity."""

    payload = audit.to_dict()
    modules = payload["modules"]
    if not isinstance(modules, list):
        raise TypeError("runtime audit modules must be a list")

    actual_modules = {item.module for item in audit.modules}
    issues: list[str] = []
    stale = sorted(set(MODULE_DISPOSITION_BY_NAME) - actual_modules)
    issues.extend(f"stale explicit module disposition: {name}" for name in stale)

    effective_counts: Counter[str] = Counter()
    explicit_payload: list[dict[str, object]] = []
    for record, item in zip(audit.modules, modules, strict=True):
        disposition = MODULE_DISPOSITION_BY_NAME.get(record.module)
        effective = record.lifecycle
        if record.lifecycle is ComponentLifecycle.ORPHANED:
            if disposition is None:
                issues.append(
                    "unclassified unreachable production-capable module: "
                    + record.module
                )
            else:
                effective = disposition.lifecycle
        elif disposition is not None:
            # A shadow/experimental/superseded module becoming reachable is a real
            # architecture change and must be promoted deliberately rather than
            # silently inheriting its old non-live disposition.
            if record.reachable and disposition.lifecycle in {
                ComponentLifecycle.SHADOW,
                ComponentLifecycle.EXPERIMENTAL,
                ComponentLifecycle.SUPERSEDED,
            }:
                issues.append(
                    f"intentionally non-live module became runtime-reachable: {record.module}"
                )
            effective = disposition.lifecycle

        if isinstance(item, dict):
            item["inferred_lifecycle"] = record.lifecycle.value
            item["lifecycle"] = effective.value
            item["explicitly_dispositioned"] = disposition is not None
            item["disposition_rationale"] = (
                None if disposition is None else disposition.rationale
            )
        effective_counts[effective.value] += 1
        if disposition is not None:
            explicit_payload.append(
                {
                    "module": disposition.module,
                    "lifecycle": disposition.lifecycle.value,
                    "rationale": disposition.rationale,
                    "reachable": record.reachable,
                }
            )

    payload["lifecycle_counts"] = dict(sorted(effective_counts.items()))
    payload["explicit_module_dispositions"] = explicit_payload
    payload["ambiguous_orphan_count"] = sum(
        1
        for record in audit.modules
        if record.lifecycle is ComponentLifecycle.ORPHANED
        and record.module not in MODULE_DISPOSITION_BY_NAME
    )
    payload["base_registry_passed"] = audit.passed
    payload["convergence_issues"] = issues
    payload["passed"] = audit.passed and not issues
    return payload, tuple(issues)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = audit_repository(args.root)
    payload, convergence_issues = _converged_payload(audit)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "passed": bool(payload["passed"]),
        "module_count": audit.module_count,
        "reachable_module_count": audit.reachable_module_count,
        "unreachable_module_count": audit.unreachable_module_count,
        "ambiguous_orphan_count": payload["ambiguous_orphan_count"],
        "explicit_module_disposition_count": len(MODULE_DISPOSITION_BY_NAME),
        "lifecycle_counts": payload["lifecycle_counts"],
        "runtime_roots": list(audit.runtime_roots),
        "invalid_capabilities": [
            {
                "name": item.name,
                "issues": list(item.issues),
            }
            for item in audit.capabilities
            if not item.valid
        ],
        "convergence_issues": list(convergence_issues),
        "report": str(destination),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if args.require_valid and not bool(payload["passed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
