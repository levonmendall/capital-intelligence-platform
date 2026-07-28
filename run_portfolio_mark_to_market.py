"""Publish one fully reconciled mark-to-market snapshot of the paper portfolio."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from governance import AssetClassApprovalState, TradingSessionModel
from portfolio import (
    MultiAssetInstrumentProfile,
    PortfolioMarkToMarketService,
    SQLiteCanonicalPortfolioStore,
)


def _factory(specification: str):
    try:
        module_name, attribute_name = specification.split(":", 1)
        return getattr(importlib.import_module(module_name), attribute_name)()
    except (ValueError, ImportError, AttributeError, TypeError) as error:
        raise ValueError(f"invalid provider factory {specification!r}") from error


def _load(path: str) -> object:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON file {path!r}") from error


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
            custody_settlement_identifier=str(value["custody_settlement_identifier"]),
            execution_model_version=str(value["execution_model_version"]),
            instrument_type=str(value.get("instrument_type", "spot")),
            gross_leverage=float(value.get("gross_leverage", 1.0)),
            defined_risk=bool(value.get("defined_risk", True)),
            margin_required=bool(value.get("margin_required", False)),
            contract_multiplier=float(value.get("contract_multiplier", 1.0)),
            contract_model_version=None if value.get("contract_model_version") is None else str(value["contract_model_version"]),
            margin_model_version=None if value.get("margin_model_version") is None else str(value["margin_model_version"]),
            lifecycle_model_version=None if value.get("lifecycle_model_version") is None else str(value["lifecycle_model_version"]),
            roll_model_version=None if value.get("roll_model_version") is None else str(value["roll_model_version"]),
            trading_session_model=None if value.get("trading_session_model") is None else TradingSessionModel(str(value["trading_session_model"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid portfolio valuation profile") from error


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--quote-provider", required=True)
    parser.add_argument("--currency-rate-provider")
    parser.add_argument("--as-of")
    parser.add_argument(
        "--portfolio-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
            str(data_dir / "canonical_portfolio.db"),
        ),
    )
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw_profiles = _load(args.profiles)
        if not isinstance(raw_profiles, list):
            raise ValueError("profiles must encode a JSON array")
        profiles = tuple(_profile(item) for item in raw_profiles if isinstance(item, Mapping))
        if len(profiles) != len(raw_profiles):
            raise ValueError("every profile must encode an object")
        profile_map = {item.symbol: item for item in profiles}
        if len(profile_map) != len(profiles):
            raise ValueError("profiles cannot contain duplicate symbols")
        store = SQLiteCanonicalPortfolioStore(args.portfolio_database)
        store.verify_integrity()
        portfolio = store.latest()
        if portfolio is None:
            raise ValueError("canonical portfolio is unavailable")
        current_symbols = {item.symbol for item in portfolio.positions}
        missing_profiles = sorted(current_symbols - set(profile_map))
        if missing_profiles:
            raise ValueError(
                "profiles are missing current portfolio positions: "
                + ", ".join(missing_profiles)
            )
        current_profiles = {
            symbol: profile_map[symbol] for symbol in sorted(current_symbols)
        }
        report = PortfolioMarkToMarketService(
            quote_provider=_factory(args.quote_provider),
            currency_rate_provider=(
                None
                if args.currency_rate_provider is None
                else _factory(args.currency_rate_provider)
            ),
            portfolio_store=store,
        ).mark(
            portfolio=portfolio,
            profiles=current_profiles,
            as_of=_timestamp(args.as_of),
        )
        payload = report.to_dict()
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 0 if report.complete else (3 if args.require_complete else 2)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
