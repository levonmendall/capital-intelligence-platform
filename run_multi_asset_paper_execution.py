"""Run governed paper execution across all classified liquid public markets."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from governance import (
    AssetClassApprovalState,
    SQLitePaperTradingControlStore,
    SQLitePaperTradingLaunchStore,
    TradingSessionModel,
    require_paper_execution_authorization,
)
from governance.eligible_universe import SQLiteCertifiedEligibleUniverseStore
from portfolio import (
    MultiAssetExecutionPolicy,
    MultiAssetExecutionStatus,
    MultiAssetInstrumentProfile,
    MultiAssetPaperExecutionOrchestrator,
    SQLiteCanonicalPortfolioStore,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.construction_models import (
    ConstructionStatus,
    ConstraintCheck,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.multi_asset_execution import batch_to_dict


def _factory(specification: str):
    try:
        module_name, attribute_name = specification.split(":", 1)
        factory = getattr(importlib.import_module(module_name), attribute_name)
        return factory()
    except (ValueError, ImportError, AttributeError, TypeError) as error:
        raise ValueError(f"invalid provider factory {specification!r}") from error


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
            blocks=tuple(str(item) for item in value.get("blocks", ())),
            eligible_universe_publication_identifier=(
                None
                if value.get("eligible_universe_publication_identifier") is None
                else str(value["eligible_universe_publication_identifier"])
            ),
            instrument_identifiers=tuple(
                (str(item["symbol"]), str(item["instrument_identifier"]))
                for item in value.get("instrument_identifiers", ())
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid canonical construction payload") from error


def _profile(value: Mapping[str, Any]) -> MultiAssetInstrumentProfile:
    try:
        return MultiAssetInstrumentProfile(
            symbol=str(value["symbol"]),
            instrument_identifier=str(value["instrument_identifier"]),
            asset_class=CandidateAssetClass(str(value["asset_class"])),
            venue=str(value["venue"]),
            country_code=str(value["country_code"]),
            price_currency=str(value["price_currency"]),
            settlement_currency=str(value["settlement_currency"]),
            approval_identifier=str(value["approval_identifier"]),
            approval_state=AssetClassApprovalState(str(value["approval_state"])),
            unlevered=bool(value["unlevered"]),
            spot_only=bool(value["spot_only"]),
            custody_settlement_identifier=str(
                value["custody_settlement_identifier"]
            ),
            execution_model_version=str(value["execution_model_version"]),
            instrument_type=str(value.get("instrument_type", "spot")),
            gross_leverage=float(value.get("gross_leverage", 1.0)),
            defined_risk=bool(value.get("defined_risk", True)),
            margin_required=bool(value.get("margin_required", False)),
            contract_multiplier=float(value.get("contract_multiplier", 1.0)),
            contract_model_version=(
                None
                if value.get("contract_model_version") is None
                else str(value["contract_model_version"])
            ),
            margin_model_version=(
                None
                if value.get("margin_model_version") is None
                else str(value["margin_model_version"])
            ),
            lifecycle_model_version=(
                None
                if value.get("lifecycle_model_version") is None
                else str(value["lifecycle_model_version"])
            ),
            roll_model_version=(
                None
                if value.get("roll_model_version") is None
                else str(value["roll_model_version"])
            ),
            trading_session_model=(
                None
                if value.get("trading_session_model") is None
                else TradingSessionModel(str(value["trading_session_model"]))
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid multi-asset instrument profile") from error


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
        "--eligible-universe-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ELIGIBLE_UNIVERSE_DATABASE",
            str(data_dir / "eligible_universe.db"),
        ),
    )
    parser.add_argument(
        "--execution-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_MULTI_ASSET_EXECUTION_DATABASE",
            str(data_dir / "multi_asset_paper_execution.db"),
        ),
    )
    parser.add_argument(
        "--paper-launch-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE",
            str(data_dir / "paper_trading_launch.db"),
        ),
    )
    parser.add_argument(
        "--paper-control-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_CONTROL_DATABASE",
            str(data_dir / "paper_trading_control.db"),
        ),
    )
    parser.add_argument(
        "--baseline-identifier",
        default=os.getenv("CAPITAL_INTELLIGENCE_TEST_BASELINE"),
    )
    parser.add_argument(
        "--process-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_PROCESS_VERSION"),
    )
    parser.add_argument(
        "--code-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_RELEASE"),
    )
    parser.add_argument(
        "--development-bypass-launch-gate",
        action="store_true",
        help=(
            "Explicit local-development bypass. Refused in staging or production "
            "and never considered launch evidence."
        ),
    )
    parser.add_argument("--portfolio-code", default="COMPOUNDING")
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    authorization = None
    try:
        construction_payload = _load(args.construction)
        if not isinstance(construction_payload, Mapping):
            raise ValueError("construction JSON must encode an object")
        construction = _construction(construction_payload)
        profiles_payload = _load(args.profiles)
        if not isinstance(profiles_payload, list):
            raise ValueError("profiles JSON must encode a list")
        profiles = tuple(_profile(item) for item in profiles_payload)
        profile_map = {item.symbol: item for item in profiles}
        if len(profile_map) != len(profiles):
            raise ValueError("profiles cannot contain duplicate symbols")
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must be timezone-aware")

        environment = os.getenv(
            "CAPITAL_INTELLIGENCE_DEPLOYMENT_ENVIRONMENT", "development"
        ).strip().lower()
        if args.development_bypass_launch_gate:
            if environment in {"staging", "production"}:
                raise ValueError(
                    "paper launch bypass is prohibited in staging and production"
                )
        else:
            missing = [
                name
                for name, value in (
                    ("--baseline-identifier", args.baseline_identifier),
                    ("--process-version", args.process_version),
                    ("--code-version", args.code_version),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "paper execution requires exact launch versions: "
                    + ", ".join(missing)
                )
            authorization = require_paper_execution_authorization(
                launch_store=SQLitePaperTradingLaunchStore(
                    args.paper_launch_database
                ),
                control_store=SQLitePaperTradingControlStore(
                    args.paper_control_database
                ),
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                as_of=as_of,
            )
            if (
                construction.turnover
                > authorization.launch_report.maximum_single_batch_turnover + 1e-9
            ):
                raise ValueError(
                    "construction turnover exceeds the active paper-launch circuit breaker"
                )

        portfolio_store = SQLiteCanonicalPortfolioStore(args.portfolio_database)
        portfolio_store.verify_integrity()
        portfolio = portfolio_store.latest(args.portfolio_code)
        if portfolio is None:
            raise ValueError(
                f"canonical portfolio {args.portfolio_code!r} is unavailable"
            )
        if authorization is not None:
            drawdown = max(
                0.0,
                1.0 - (portfolio.nav / portfolio.starting_capital),
            )
            if (
                drawdown
                > authorization.launch_report.maximum_drawdown_fraction + 1e-9
            ):
                raise ValueError(
                    "paper portfolio drawdown circuit breaker is active"
                )

        execution_store = SQLiteMultiAssetPaperExecutionStore(
            args.execution_database
        )
        execution_store.verify_integrity()
        universe_store = SQLiteCertifiedEligibleUniverseStore(
            args.eligible_universe_database
        )
        universe_store.verify_integrity()
        batch = MultiAssetPaperExecutionOrchestrator(
            session_provider=_factory(args.session_provider),
            quote_provider=_factory(args.quote_provider),
            store=execution_store,
            portfolio_store=portfolio_store,
            universe_store=universe_store,
            policy=MultiAssetExecutionPolicy(),
        ).execute(
            construction=construction,
            decision_identifier=args.decision_identifier,
            portfolio=portfolio,
            profiles=profile_map,
            as_of=as_of,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "development_bypass_used": bool(
                        args.development_bypass_launch_gate
                    ),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    payload = batch_to_dict(batch)
    payload["paper_launch_authorization"] = (
        None
        if authorization is None
        else {
            "launch_report_identifier": authorization.launch_report.identifier,
            "launch_evidence_identifier": (
                authorization.launch_report.evidence_identifier
            ),
            "control_event_identifier": authorization.control_event.identifier,
            "source_identifiers": list(authorization.source_identifiers),
        }
    )
    payload["development_bypass_used"] = bool(
        args.development_bypass_launch_gate
    )
    payload["real_money_authorized"] = False
    print(json.dumps(payload, sort_keys=True))
    if args.require_complete and batch.status not in {
        MultiAssetExecutionStatus.COMPLETED,
        MultiAssetExecutionStatus.NO_ACTION,
    }:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
