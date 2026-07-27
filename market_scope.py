"""Binding all-market analysis scope for the sole compounding portfolio.

This manifest is an analysis obligation, not blanket authorization to allocate.
Direct paper recommendations remain subject to point-in-time universe policy and
asset-specific governance approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from portfolio.constants import CANONICAL_PORTFOLIO_CODE, PORTFOLIO_OBJECTIVE


class MarketFamily(str, Enum):
    GLOBAL_EQUITIES = "global_equities"
    GOVERNMENT_BONDS = "government_bonds"
    CREDIT = "credit"
    CASH_EQUIVALENTS = "cash_equivalents"
    COMMODITIES = "commodities"
    FOREIGN_EXCHANGE = "foreign_exchange"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    OPTIONS = "options"
    VOLATILITY = "volatility"
    OTHER_LIQUID_ALTERNATIVES = "other_liquid_alternatives"


class AllocationStatus(str, Enum):
    POLICY_ELIGIBLE = "policy_eligible"
    POLICY_OR_GOVERNANCE_ELIGIBLE = "policy_or_governance_eligible"
    GOVERNANCE_REQUIRED = "governance_required"


@dataclass(frozen=True, slots=True)
class MarketScopeEntry:
    market_family: MarketFamily
    analysis_required: bool
    allocation_status: AllocationStatus

    def __post_init__(self) -> None:
        if not isinstance(self.market_family, MarketFamily):
            raise TypeError("market_family must be a MarketFamily")
        if not isinstance(self.analysis_required, bool):
            raise TypeError("analysis_required must be boolean")
        if not isinstance(self.allocation_status, AllocationStatus):
            raise TypeError("allocation_status must be an AllocationStatus")


@dataclass(frozen=True, slots=True)
class GlobalMarketScope:
    schema_version: str
    portfolio_code: str
    universe_source: str
    objective: str
    direct_allocation_rule: str
    markets: tuple[MarketScopeEntry, ...]
    static_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "schema_version",
            "portfolio_code",
            "universe_source",
            "objective",
            "direct_allocation_rule",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        normalized_code = self.portfolio_code.strip().upper()
        if normalized_code != CANONICAL_PORTFOLIO_CODE:
            raise ValueError("market scope must belong to the COMPOUNDING portfolio")
        object.__setattr__(self, "portfolio_code", normalized_code)
        if self.universe_source != "provider_driven_point_in_time_security_master":
            raise ValueError(
                "the active universe must come from the provider-driven point-in-time security master"
            )
        if not isinstance(self.markets, tuple) or not all(
            isinstance(item, MarketScopeEntry) for item in self.markets
        ):
            raise TypeError("markets must contain MarketScopeEntry values")
        families = tuple(item.market_family for item in self.markets)
        if len(families) != len(set(families)):
            raise ValueError("market families cannot be duplicated")
        if not isinstance(self.static_symbols, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.static_symbols
        ):
            raise TypeError("static_symbols must contain non-empty strings")
        if self.static_symbols:
            raise ValueError(
                "the active all-market universe cannot be constrained by a static symbol list"
            )

    def require_complete_analysis_scope(self) -> None:
        configured = {item.market_family for item in self.markets}
        required = set(MarketFamily)
        missing = sorted(item.value for item in required - configured)
        if missing:
            raise ValueError(
                "global market analysis scope is incomplete: " + ", ".join(missing)
            )
        disabled = sorted(
            item.market_family.value
            for item in self.markets
            if not item.analysis_required
        )
        if disabled:
            raise ValueError(
                "all configured market families must be analyzed: "
                + ", ".join(disabled)
            )
        if PORTFOLIO_OBJECTIVE.split(".", 1)[0].casefold() not in self.objective.casefold():
            # The manifest may use a concise equivalent, but it must preserve the
            # all-market, evidence-supported, after-cost objective terms.
            required_terms = ("all", "markets", "evidence", "returns", "cost")
            missing_terms = [term for term in required_terms if term not in self.objective.casefold()]
            if missing_terms:
                raise ValueError(
                    "market scope objective is missing binding terms: "
                    + ", ".join(missing_terms)
                )


def _entry(payload: dict[str, Any]) -> MarketScopeEntry:
    return MarketScopeEntry(
        market_family=MarketFamily(str(payload["market_family"])),
        analysis_required=payload["analysis_required"],
        allocation_status=AllocationStatus(str(payload["allocation_status"])),
    )


def load_global_market_scope(
    path: str | Path | None = None,
) -> GlobalMarketScope:
    source = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent / "config" / "investment_universe.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("global market scope configuration must be a JSON object")
    markets = payload.get("markets")
    if not isinstance(markets, list):
        raise ValueError("global market scope markets must be a JSON array")
    static_symbols = payload.get("static_symbols", [])
    if not isinstance(static_symbols, list):
        raise ValueError("static_symbols must be a JSON array")
    scope = GlobalMarketScope(
        schema_version=str(payload["schema_version"]),
        portfolio_code=str(payload["portfolio_code"]),
        universe_source=str(payload["universe_source"]),
        objective=str(payload["objective"]),
        direct_allocation_rule=str(payload["direct_allocation_rule"]),
        markets=tuple(_entry(item) for item in markets),
        static_symbols=tuple(str(item) for item in static_symbols),
    )
    scope.require_complete_analysis_scope()
    return scope


__all__ = [
    "AllocationStatus",
    "GlobalMarketScope",
    "MarketFamily",
    "MarketScopeEntry",
    "load_global_market_scope",
]
