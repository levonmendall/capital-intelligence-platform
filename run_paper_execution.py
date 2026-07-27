"""Run paper-only implementation of a canonical portfolio construction result."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from cio.persistence import SQLiteCIOJournal
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from portfolio.construction_api import (
    ConstructionStatus,
    ConstraintCheck,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.state import SQLiteCanonicalPortfolioStore, ensure_canonical_portfolio_store
from portfolio.execution import (
    PaperExecutionOrchestrator,
    PaperExecutionPolicy,
    PaperExecutionStatus,
    SQLitePaperExecutionStore,
    batch_to_dict,
    portfolio_from_dict,
)


def _factory(specification: str):
    try:
        module_name, attribute_name = specification.split(":", 1)
        value = getattr(importlib.import_module(module_name), attribute_name)
        return value()
    except (ValueError, ImportError, AttributeError, TypeError) as error:
        raise ValueError(f"invalid provider factory {specification!r}") from error


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON file {path!r}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON file {path!r} must contain an object")
    return value


def _construction(value: Mapping[str, Any]) -> PortfolioConstructionResult:
    try:
        return PortfolioConstructionResult(
            request_identifier=str(value["request_identifier"]),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            status=ConstructionStatus(str(value["status"])),
            policy_version=str(value["policy_version"]),
            target_cash_weight=float(value["target_cash_weight"]),
            target_weights=tuple((str(item["symbol"]), float(item["weight"])) for item in value["target_weights"]),
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
            blocks=tuple(value.get("blocks", ())),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid portfolio construction payload") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--construction", required=True, help="Serialized canonical construction JSON")
    parser.add_argument("--portfolio", required=True, help="Paper portfolio state JSON")
    parser.add_argument("--decision-identifier", required=True)
    parser.add_argument("--session-provider", required=True, help="module:factory returning a MarketSessionProvider")
    parser.add_argument("--quote-provider", required=True, help="module:factory returning a PaperQuoteProvider")
    parser.add_argument("--as-of", required=True, help="Timezone-aware execution timestamp")
    parser.add_argument("--store-db", default="database/paper_execution.db")
    parser.add_argument("--portfolio-db", default="database/canonical_portfolio.db")
    parser.add_argument("--portfolio-code", default=CANONICAL_PORTFOLIO_CODE)
    parser.add_argument("--journal-db", default="database/institutional_journal.db")
    parser.add_argument("--without-journal", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--maximum-quote-age-minutes", type=int, default=5)
    parser.add_argument("--maximum-volume-participation", type=float, default=0.10)
    parser.add_argument("--commission-bps", type=float, default=0.0)
    parser.add_argument("--maximum-realized-cost-return", type=float, default=0.01)
    parser.add_argument("--maximum-order-age-hours", type=int, default=24)
    parser.add_argument("--disallow-partial-fills", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        construction = _construction(_load(args.construction))
        portfolio = portfolio_from_dict(_load(args.portfolio))
        as_of = datetime.fromisoformat(args.as_of)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must be timezone-aware")
        journal = None if args.without_journal else SQLiteCIOJournal(args.journal_db)
        ensure_canonical_portfolio_store(args.portfolio_db, as_of=as_of)
        orchestrator = PaperExecutionOrchestrator(
            session_provider=_factory(args.session_provider),
            quote_provider=_factory(args.quote_provider),
            store=SQLitePaperExecutionStore(args.store_db),
            journal=journal,
            portfolio_store=SQLiteCanonicalPortfolioStore(args.portfolio_db),
            portfolio_code=args.portfolio_code,
            policy=PaperExecutionPolicy(
                maximum_quote_age_minutes=args.maximum_quote_age_minutes,
                maximum_daily_volume_participation=args.maximum_volume_participation,
                commission_bps=args.commission_bps,
                maximum_realized_cost_return=args.maximum_realized_cost_return,
                maximum_order_age_hours=args.maximum_order_age_hours,
                allow_partial_fills=not args.disallow_partial_fills,
            ),
        )
        batch = orchestrator.execute(
            construction=construction,
            decision_identifier=args.decision_identifier,
            portfolio=portfolio,
            as_of=as_of,
        )
    except (ValueError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True))
        return 4
    print(json.dumps(batch_to_dict(batch), sort_keys=True))
    if args.require_complete and batch.status not in {PaperExecutionStatus.COMPLETED, PaperExecutionStatus.NO_ACTION}:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
