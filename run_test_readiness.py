"""Assess and persist controlled paper-product test readiness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from governance import (
    ProductTestReadiness,
    ProductTestReadinessEvidence,
    ProductTestReadinessEvaluator,
    SQLiteProductTestReadinessStore,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, help="Readiness evidence JSON")
    parser.add_argument("--database", default="database/product_test_readiness.db")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("readiness evidence must encode an object")
        evidence = ProductTestReadinessEvidence.from_dict(payload)
        report = ProductTestReadinessEvaluator().evaluate(evidence)
        store = SQLiteProductTestReadinessStore(args.database)
        sequence = store.append(report)
        store.verify_integrity()
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True))
        return 4
    output = report.to_dict()
    output["registry_sequence"] = sequence
    print(json.dumps(output, indent=2, sort_keys=True))
    if args.require_ready and report.state is not ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
