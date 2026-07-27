"""Asset-specific portfolio construction controls for governed paper markets.

The canonical construction engine remains the sizing authority. This module adds
mandatory market-specific feasibility checks for crypto, unlevered spot FX, and
international listed equities before and after construction. It cannot change CIO
ranking or create intents.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from cio import CandidateAssetClass
from governance import EXPANSION_ASSET_CLASSES, AssetClassApprovalState
from portfolio.construction_engine import PortfolioConstructionEngine
from portfolio.construction_models import (
    ConstructionStatus,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
)


class MultiAssetConstructionError(RuntimeError):
    """Raised when an expanded-market construction boundary is incomplete."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return round(normalized, 12)


@dataclass(frozen=True, slots=True)
class MultiAssetInstrumentProfile:
    symbol: str
    instrument_identifier: str
    asset_class: CandidateAssetClass
    venue: str
    country_code: str
    price_currency: str
    settlement_currency: str
    approval_identifier: str
    approval_state: AssetClassApprovalState
    unlevered: bool
    spot_only: bool
    custody_settlement_identifier: str
    execution_model_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "symbol", "instrument_identifier", "venue", "country_code",
            "price_currency", "settlement_currency", "approval_identifier",
            "custody_settlement_identifier", "execution_model_version",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {"symbol", "venue", "country_code", "price_currency", "settlement_currency"}:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.asset_class not in EXPANSION_ASSET_CLASSES:
            raise ValueError("profile is only valid for expanded markets")
        if not isinstance(self.approval_state, AssetClassApprovalState):
            raise TypeError("approval_state must be AssetClassApprovalState")
        if not isinstance(self.unlevered, bool) or not isinstance(self.spot_only, bool):
            raise TypeError("unlevered and spot_only must be bool values")


@dataclass(frozen=True, slots=True)
class MultiAssetConstructionPolicy:
    version: str = "multi-asset-construction.v1"
    maximum_crypto_weight: float = 0.05
    maximum_spot_fx_weight: float = 0.10
    maximum_international_equity_weight: float = 0.25
    maximum_non_base_currency_weight: float = 0.35
    maximum_single_foreign_currency_weight: float = 0.15
    require_paper_eligible_approval: bool = True
    require_unlevered_spot: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        for field_name in (
            "maximum_crypto_weight", "maximum_spot_fx_weight",
            "maximum_international_equity_weight", "maximum_non_base_currency_weight",
            "maximum_single_foreign_currency_weight",
        ):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.require_paper_eligible_approval, bool):
            raise TypeError("require_paper_eligible_approval must be bool")
        if not isinstance(self.require_unlevered_spot, bool):
            raise TypeError("require_unlevered_spot must be bool")

    def class_limit(self, asset_class: CandidateAssetClass) -> float:
        return {
            CandidateAssetClass.CRYPTO: self.maximum_crypto_weight,
            CandidateAssetClass.FX: self.maximum_spot_fx_weight,
            CandidateAssetClass.INTERNATIONAL_EQUITY: self.maximum_international_equity_weight,
        }.get(asset_class, 1.0)


class GovernedMultiAssetConstructionEngine:
    """Fail-closed wrapper around the canonical construction engine."""

    def __init__(self, *, engine: PortfolioConstructionEngine | None = None, policy: MultiAssetConstructionPolicy | None = None) -> None:
        self.engine = engine or PortfolioConstructionEngine()
        self.policy = policy or MultiAssetConstructionPolicy()

    def construct(
        self,
        request: PortfolioConstructionRequest,
        *,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        required_expanded_symbols: tuple[str, ...] = (),
        base_currency: str = "USD",
    ) -> PortfolioConstructionResult:
        if not isinstance(request, PortfolioConstructionRequest):
            raise TypeError("request must be PortfolioConstructionRequest")
        base = _text(base_currency, field_name="base_currency").upper()
        normalized = {str(key).upper(): value for key, value in profiles.items()}
        required = tuple(_text(item, field_name="required_expanded_symbols").upper() for item in required_expanded_symbols)
        if len(required) != len(set(required)):
            raise MultiAssetConstructionError("required expanded symbols cannot repeat")
        if set(normalized) != set(required):
            raise MultiAssetConstructionError(
                f"expanded-market profiles must exactly match required symbols: missing={sorted(set(required)-set(normalized))} extra={sorted(set(normalized)-set(required))}"
            )
        request_symbols = {item.symbol for item in (*request.positions, *request.intents)}
        unknown = sorted(set(required) - request_symbols)
        if unknown:
            raise MultiAssetConstructionError(f"expanded-market profiles are not present in construction: {unknown}")
        for symbol, profile in normalized.items():
            if not isinstance(profile, MultiAssetInstrumentProfile):
                raise TypeError("profiles must contain MultiAssetInstrumentProfile values")
            if profile.symbol != symbol:
                raise MultiAssetConstructionError("profile key must match profile symbol")
            self._require_profile(profile)
        result = self.engine.construct(request)
        self._validate_result(result, profiles=normalized, base_currency=base)
        return result

    def _require_profile(self, profile: MultiAssetInstrumentProfile) -> None:
        if self.policy.require_paper_eligible_approval and profile.approval_state is not AssetClassApprovalState.PAPER_ELIGIBLE:
            raise MultiAssetConstructionError(f"{profile.symbol} asset-class approval is not paper_eligible")
        if self.policy.require_unlevered_spot and profile.asset_class in {CandidateAssetClass.CRYPTO, CandidateAssetClass.FX}:
            if not profile.unlevered or not profile.spot_only:
                raise MultiAssetConstructionError(f"{profile.symbol} must be unlevered spot exposure")

    def _validate_result(self, result: PortfolioConstructionResult, *, profiles: Mapping[str, MultiAssetInstrumentProfile], base_currency: str) -> None:
        if result.status in {ConstructionStatus.BLOCKED, ConstructionStatus.NO_ACTION}:
            return
        class_weights = {asset_class: 0.0 for asset_class in EXPANSION_ASSET_CLASSES}
        currency_weights: dict[str, float] = {}
        for symbol, weight in result.target_weights:
            profile = profiles.get(symbol)
            if profile is None:
                continue
            class_weights[profile.asset_class] += weight
            if profile.settlement_currency != base_currency:
                currency_weights[profile.settlement_currency] = currency_weights.get(profile.settlement_currency, 0.0) + weight
        violations: list[str] = []
        for asset_class, weight in class_weights.items():
            limit = self.policy.class_limit(asset_class)
            if weight > limit + 1e-9:
                violations.append(f"{asset_class.value} target {weight:.2%} exceeds {limit:.2%}")
        if sum(currency_weights.values()) > self.policy.maximum_non_base_currency_weight + 1e-9:
            violations.append("non-base-currency target exceeds the aggregate currency limit")
        for currency, weight in currency_weights.items():
            if weight > self.policy.maximum_single_foreign_currency_weight + 1e-9:
                violations.append(f"{currency} target exceeds the single-currency limit")
        if violations:
            raise MultiAssetConstructionError("; ".join(violations))


__all__ = [
    "GovernedMultiAssetConstructionEngine", "MultiAssetConstructionError",
    "MultiAssetConstructionPolicy", "MultiAssetInstrumentProfile",
]
