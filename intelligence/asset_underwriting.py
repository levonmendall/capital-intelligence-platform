"""Asset-class-specific underwriting completeness contracts.

The existing Fundamental & Valuation specialist remains the analytical authority.
These contracts describe what evidence that specialist should have for each asset
class; they do not create a seventh specialist, change thresholds, or authorize
capital.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cio.models import CandidateAssetClass


class UnderwritingDimension(str, Enum):
    IDENTITY = "identity"
    MARKET_DATA = "market_data"
    LIQUIDITY = "liquidity"
    MACRO = "macro"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    CARRY = "carry"
    CURVE = "curve"
    CREDIT = "credit"
    CURRENCY = "currency"
    PHYSICAL_BALANCE = "physical_balance"
    POSITIONING = "positioning"
    ONCHAIN = "onchain"
    DERIVATIVES = "derivatives"
    CASH_FLOW = "cash_flow"
    CORPORATE_ACTIONS = "corporate_actions"
    HISTORY = "history"
    EXECUTION = "execution"


_COMMON = frozenset(
    {
        UnderwritingDimension.IDENTITY,
        UnderwritingDimension.MARKET_DATA,
        UnderwritingDimension.LIQUIDITY,
        UnderwritingDimension.MACRO,
        UnderwritingDimension.VALUATION,
        UnderwritingDimension.HISTORY,
    }
)

_REQUIREMENTS: dict[CandidateAssetClass, frozenset[UnderwritingDimension]] = {
    CandidateAssetClass.US_EQUITY: _COMMON
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CORPORATE_ACTIONS,
        UnderwritingDimension.CASH_FLOW,
    },
    CandidateAssetClass.INTERNATIONAL_EQUITY: _COMMON
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CORPORATE_ACTIONS,
        UnderwritingDimension.CASH_FLOW,
        UnderwritingDimension.CURRENCY,
    },
    CandidateAssetClass.US_ETF: _COMMON
    | {UnderwritingDimension.POSITIONING},
    CandidateAssetClass.CASH_EQUIVALENT: {
        UnderwritingDimension.IDENTITY,
        UnderwritingDimension.MARKET_DATA,
        UnderwritingDimension.LIQUIDITY,
        UnderwritingDimension.CARRY,
        UnderwritingDimension.MACRO,
    },
    CandidateAssetClass.FIXED_INCOME: _COMMON
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.CREDIT,
        UnderwritingDimension.CURRENCY,
    },
    CandidateAssetClass.COMMODITY: _COMMON
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.PHYSICAL_BALANCE,
        UnderwritingDimension.POSITIONING,
    },
    CandidateAssetClass.FX: _COMMON
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURRENCY,
        UnderwritingDimension.POSITIONING,
    },
    CandidateAssetClass.CRYPTO: _COMMON
    | {
        UnderwritingDimension.ONCHAIN,
        UnderwritingDimension.POSITIONING,
    },
    CandidateAssetClass.REAL_ESTATE: _COMMON
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CASH_FLOW,
        UnderwritingDimension.CREDIT,
    },
    CandidateAssetClass.FUTURE: _COMMON
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.POSITIONING,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.OPTION: _COMMON
    | {
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.POSITIONING,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.VOLATILITY: _COMMON
    | {
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.POSITIONING,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.ALTERNATIVE: _COMMON
    | {
        UnderwritingDimension.POSITIONING,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.OTHER: _COMMON | {UnderwritingDimension.EXECUTION},
}


@dataclass(frozen=True, slots=True)
class UnderwritingCoverage:
    asset_class: CandidateAssetClass
    required: tuple[UnderwritingDimension, ...]
    available: tuple[UnderwritingDimension, ...]
    missing: tuple[UnderwritingDimension, ...]
    completeness: float
    decision_complete: bool
    schema_version: str = "asset-underwriting-coverage.v1"


class AssetUnderwritingPolicy:
    version = "asset-underwriting-policy.v1"

    def required_dimensions(
        self, asset_class: CandidateAssetClass
    ) -> tuple[UnderwritingDimension, ...]:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        return tuple(sorted(_REQUIREMENTS[asset_class], key=lambda item: item.value))

    def assess(
        self,
        asset_class: CandidateAssetClass,
        available: tuple[UnderwritingDimension, ...],
    ) -> UnderwritingCoverage:
        required = self.required_dimensions(asset_class)
        available_set = set(available)
        if any(not isinstance(item, UnderwritingDimension) for item in available_set):
            raise TypeError("available must contain UnderwritingDimension values")
        missing = tuple(item for item in required if item not in available_set)
        completeness = round((len(required) - len(missing)) / len(required), 8)
        return UnderwritingCoverage(
            asset_class=asset_class,
            required=required,
            available=tuple(sorted(available_set, key=lambda item: item.value)),
            missing=missing,
            completeness=completeness,
            decision_complete=not missing,
        )


__all__ = [
    "AssetUnderwritingPolicy",
    "UnderwritingCoverage",
    "UnderwritingDimension",
]
