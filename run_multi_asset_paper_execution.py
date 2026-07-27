"""Run governed paper execution across crypto, FX, and global listed markets."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from portfolio import (
    MultiAssetExecutionStatus,
    MultiAssetPaperExecutionOrchestrator,
    SQLiteCanonicalPortfolioStore,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.construction_api import (
    ConstructionStatus,
    ConstraintCheck,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.multi_asset_execution import batch_to_dict, profile_from_dict


def _factory(specification: str):
    try:
        module_name, attribute_name = specification.split(":", 1)
        factory = getattr(importlib.import_module(module_name), attribute_name)
        value = factory()
    except (ValueError, ImportError, AttributeError, TypeError) as error:
        raise ValueError(f"invalid provider factory {specification!r}") from error
    return value


def _load(path: str) -> object:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON file {path!r}") from error


def _construction(value: Mapping[str, Any]) -> PortfolioConstructionResult:
    try:
        return PortfolioConstructionResult(
            request_identifier=str(value["request_identifier"]),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            status=ConstructionStatus(str(value["status"])),
            policy_version=str(value["policy_version"]),
            target_cash_weight=float(value["target_cash_weight"]),
            target_weights=tuple(
                (str(item["symbol"]), float(item["weight"]))
                for item in value["target_weights"]
            ),
            trades=tuple(
                TradeProposal(
                    symbol=str(item["symbol"]),
                    side=TradeSide(str(item["side"])),
                    from_weight=float(item["from_weight"]),
                    to_weight=float(item["to_weight"]),
                    trade_weight=float(item["trade_weight"]),
                    estimated_cost_return=float(item["estimated_cost_return"]),
                    reason=str(item["reason"]),
                    funding_for=tuple(item.get("funding_for", ())),
                )
                for item in value["trades"]
            ),
            turnover=float(value["turnover"]),
            estimated_cost_return=float(value["estimated_cost_return"]),
            expected_return_before=float(value["expected_return_before"]),
            expected_return_after_cost=float(value["expected_return_after_cost"]),
            expected_return_improvement=float(value["expected_return_improvement"]),
            constraints=tuple(
                ConstraintCheck(
                    name=str(item["name"]),
                    satisfied=bool(item["satisfied"]),
                    value=float(item["value"]),
                    limit=float(item["limit"]),
                    detail=str(item["detail"]),
                )
                for item in value.get("constraints", ())
            ),
            blocks=tuple(value.get("blocks", ()),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid canonical construction payload") from error


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--construction", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--decision-identifier", required=True)
    parser.add_argument("--session-provider", required=True)
    parser.add_argument("--quote-provider", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument(
        "--portfolio-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
            str(data_dir / "canonical_portfolio.db"),
        ),
    )
    parser.add_argument(
        "--execution-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_MULTI_ASSET_EXECUTION_DATABASE",
            str(data_dir / "multi_asset_paper_execution.db"),
        ),
    )
    parser.add_argument("--portfolio-code", default="COMPOUNDING")
    parser.add_argument("--reconciliation-tolerance", type=float, default=0.01)
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        construction_payload = _load(args.construction)
        if not isinstance(construction_payload, Mapping):
            raise ValueError("construction JSON must encode an object")
        profiles_payload = _load(args.profiles)
        if not isinstance(profiles_payload, list):
            raise ValueError("profiles JSON must encode a list")
        profiles = tuple(profile_from_dict(item) for item in profiles_payload)
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must be timezone-aware")
        portfolio_store = SQLiteCanonicalPortfolioStore(args.portfolio_database)
        portfolio = portfolio_store.latest(args.portfolio_code)
        if portfolio is None:
            raise ValueError(
                f"canonical portfolio {args.portfolio_code!r} is unavailable"
            )
        orchestrator = MultiAssetPaperExecutionOrchestrator(
            session_provider=_factory(args.session_provider),
            quote_provider=_factory(args.quote_provider),
            store=SQLiteMultiAssetPaperExecutionStore(
                args.execution_database
            ),
            portfolio_store=portfolio_store,
            reconciliation_tolerance=args.reconciliation_tolerance,
        )
        batch = orchestrator.execute(
            construction=_construction(construction_payload),
            decision_identifier=args.decision_identifier,
            portfolio=portfolio,
            profiles=profiles,
            as_of=as_of,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 4
    print(json.dumps(batch_to_dict(batch), sort_keys=True))
    if args.require_complete and batch.status not in {
        MultiAssetExecutionStatus.COMPLETED,
        MultiAssetExecutionStatus.NO_ACTION,
    }:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
