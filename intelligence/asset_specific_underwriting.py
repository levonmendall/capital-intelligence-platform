"""Shadow-first asset-specific economic underwriting.

The engine makes the return drivers required by each asset class explicit and can
calculate a research expected-return view from certified driver observations.  It
cannot promote itself into the live Fundamental/Valuation specialist: decision impact
remains zero until the caller supplies a complete driver set and an explicit governed
``decision_certified`` flag.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from cio.models import CandidateAssetClass


_DRIVER_REQUIREMENTS: dict[CandidateAssetClass, tuple[str, ...]] = {
    CandidateAssetClass.US_EQUITY: (
        "quality", "growth", "earnings_quality", "cash_flow", "valuation", "capital_allocation"
    ),
    CandidateAssetClass.INTERNATIONAL_EQUITY: (
        "quality", "growth", "earnings_quality", "cash_flow", "valuation", "capital_allocation", "currency"
    ),
    CandidateAssetClass.US_ETF: (
        "underlying_valuation", "carry", "tracking", "flows", "liquidity"
    ),
    CandidateAssetClass.CASH_EQUIVALENT: ("carry", "liquidity", "credit_quality"),
    CandidateAssetClass.FIXED_INCOME: (
        "yield", "carry", "roll_down", "duration", "convexity", "real_yield", "spread", "default_loss", "liquidity"
    ),
    CandidateAssetClass.COMMODITY: (
        "curve_carry", "inventory", "production", "demand", "capacity", "outages", "weather", "positioning", "dollar"
    ),
    CandidateAssetClass.FX: (
        "carry", "policy_differential", "real_rate_differential", "valuation", "current_account", "terms_of_trade", "positioning"
    ),
    CandidateAssetClass.CRYPTO: (
        "network_activity", "issuance", "exchange_balances", "stablecoin_liquidity", "funding", "open_interest", "valuation", "protocol_risk"
    ),
    CandidateAssetClass.REAL_ESTATE: (
        "noi_growth", "cap_rate_spread", "occupancy", "rent_growth", "leverage", "financing_cost", "nav_discount"
    ),
    CandidateAssetClass.FUTURE: (
        "curve_carry", "roll_yield", "underlying_driver", "margin_cost", "positioning", "liquidity"
    ),
    CandidateAssetClass.OPTION: (
        "implied_realized_gap", "skew", "term_structure", "carry", "convexity", "positioning", "liquidity"
    ),
    CandidateAssetClass.VOLATILITY: (
        "implied_realized_gap", "term_structure", "skew", "carry", "convexity", "positioning"
    ),
    CandidateAssetClass.ALTERNATIVE: (
        "strategy_edge", "carry", "trend", "turnover_cost", "crowding", "liquidity"
    ),
    CandidateAssetClass.OTHER: ("economic_return_driver", "valuation", "liquidity"),
}


@dataclass(frozen=True, slots=True)
class UnderwritingDriverObservation:
    name: str
    as_of: datetime
    expected_return_contribution: float
    confidence: float
    evidence_identifiers: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("underwriting driver name cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("underwriting driver as_of must be timezone-aware")
        if not isfinite(float(self.expected_return_contribution)):
            raise ValueError("expected_return_contribution must be finite")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if not self.evidence_identifiers:
            raise ValueError("underwriting driver requires evidence identifiers")


@dataclass(frozen=True, slots=True)
class AssetSpecificUnderwritingResult:
    asset_class: CandidateAssetClass
    as_of: datetime
    required_drivers: tuple[str, ...]
    observed_drivers: tuple[str, ...]
    missing_drivers: tuple[str, ...]
    research_expected_return: float
    decision_expected_return_impact: float
    confidence: float
    evidence_identifiers: tuple[str, ...]
    decision_certified: bool
    investment_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "asset-specific-underwriting.v1"


class AssetSpecificUnderwritingEngine:
    version = "asset-specific-underwriting.v1-shadow-first"

    def required_drivers(self, asset_class: CandidateAssetClass) -> tuple[str, ...]:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        return _DRIVER_REQUIREMENTS[asset_class]

    def assess(
        self,
        *,
        asset_class: CandidateAssetClass,
        as_of: datetime,
        observations: tuple[UnderwritingDriverObservation, ...],
        decision_certified: bool = False,
    ) -> AssetSpecificUnderwritingResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        required = self.required_drivers(asset_class)
        by_name: dict[str, UnderwritingDriverObservation] = {}
        for item in observations:
            if item.as_of > as_of:
                raise ValueError("underwriting observation cannot be future-known")
            if item.name in by_name:
                raise ValueError(f"duplicate underwriting driver: {item.name}")
            by_name[item.name] = item
        observed = tuple(name for name in required if name in by_name)
        missing = tuple(name for name in required if name not in by_name)
        selected = tuple(by_name[name] for name in observed)
        research_return = max(
            -1.0,
            min(1.0, sum(float(item.expected_return_contribution) for item in selected)),
        )
        confidence = (
            0.0
            if not selected
            else min(float(item.confidence) for item in selected)
            * (len(observed) / len(required))
        )
        complete_and_certified = bool(decision_certified and not missing)
        evidence = tuple(
            dict.fromkeys(
                identifier
                for item in selected
                for identifier in item.evidence_identifiers
            )
        )
        return AssetSpecificUnderwritingResult(
            asset_class=asset_class,
            as_of=as_of,
            required_drivers=required,
            observed_drivers=observed,
            missing_drivers=missing,
            research_expected_return=round(research_return, 8),
            decision_expected_return_impact=(
                round(research_return, 8) if complete_and_certified else 0.0
            ),
            confidence=round(max(0.0, min(1.0, confidence)), 8),
            evidence_identifiers=evidence,
            decision_certified=complete_and_certified,
        )


__all__ = [
    "AssetSpecificUnderwritingEngine",
    "AssetSpecificUnderwritingResult",
    "UnderwritingDriverObservation",
]
