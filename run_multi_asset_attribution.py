"""Validate and persist point-in-time multi-asset return attribution."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from evaluation import (
    MultiAssetEvaluationEventType,
    MultiAssetReturnAttribution,
    MultiAssetReturnObservation,
    SQLiteMultiAssetEvaluationStore,
)


def _payload(path: str) -> Mapping[str, object]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read observation JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("observation JSON must encode an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--implemented-weight", required=True, type=float)
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_MULTI_ASSET_EVALUATION_DATABASE",
            str(data_dir / "multi_asset_evaluation.db"),
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        observation = MultiAssetReturnObservation.from_dict(
            _payload(args.observation)
        )
        attribution = MultiAssetReturnAttribution.from_observation(
            observation,
            implemented_weight=args.implemented_weight,
        )
        store = SQLiteMultiAssetEvaluationStore(args.database)
        observation_sequence = store.append(
            event_identifier=f"event:{observation.identifier}",
            aggregate_identifier=observation.snapshot_identifier,
            event_type=MultiAssetEvaluationEventType.OBSERVATION,
            occurred_at=observation.observed_at,
            payload=observation.to_dict(),
        )
        attribution_identifier = f"attribution:{observation.identifier}"
        attribution_sequence = store.append(
            event_identifier=f"event:{attribution_identifier}",
            aggregate_identifier=observation.snapshot_identifier,
            event_type=MultiAssetEvaluationEventType.ATTRIBUTION,
            occurred_at=observation.observed_at,
            payload=attribution.to_dict(),
        )
        store.verify_integrity()
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 4
    print(
        json.dumps(
            {
                "status": "recorded",
                "observation_identifier": observation.identifier,
                "attribution_identifier": attribution_identifier,
                "snapshot_identifier": observation.snapshot_identifier,
                "observation_sequence": observation_sequence,
                "attribution_sequence": attribution_sequence,
                "local_asset_return": attribution.local_asset_return,
                "currency_return": attribution.currency_return,
                "interaction_return": attribution.interaction_return,
                "implementation_cost_return": (
                    attribution.implementation_cost_return
                ),
                "net_base_return": attribution.net_base_return,
                "net_portfolio_contribution": (
                    attribution.net_portfolio_contribution
                ),
                "real_money_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
