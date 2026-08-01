"""Generate a research-only Push 2 strategy replay evaluation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.strategy_replay import evaluate_strategy_replay_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Canonical replay JSON report")
    parser.add_argument("--output", required=True, help="Evaluation JSON output")
    parser.add_argument(
        "--development-fraction",
        type=float,
        default=0.70,
        help="Chronological development share; remaining cutoffs are evaluation-only",
    )
    parser.add_argument("--source-commit")
    parser.add_argument("--workflow-run-id", type=int)
    parser.add_argument("--artifact-id", type=int)
    parser.add_argument("--artifact-digest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = {
        key: value
        for key, value in {
            "source_commit": args.source_commit,
            "workflow_run_id": args.workflow_run_id,
            "artifact_id": args.artifact_id,
            "artifact_digest": args.artifact_digest,
        }.items()
        if value is not None
    }
    result = evaluate_strategy_replay_file(
        args.input,
        source_artifact=source,
        development_fraction=args.development_fraction,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["strategy_go_no_go"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
