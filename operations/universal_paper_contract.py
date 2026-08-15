"""Normalized paper ownership contract with asset-family lifecycle adapters.

The CIO and portfolio construction can express economic target exposure without
knowing provider symbols or asset-specific lot mechanics. Adapters translate only
paper intent. There is intentionally no live-money routing interface here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from typing import Mapping, Protocol

from operations.universal_capability_graph import AssetFamily, CapabilityEvaluation


def _positive(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    resolved = float(value)
    if not isfinite(resolved) or resolved <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return resolved


@dataclass(frozen=True, slots=True)
class NormalizedInvestmentView:
    instrument_identifier: str
    asset_family: AssetFamily
    reference_price: float
    contract_multiplier: float = 1.0
    trading_currency: str = "USD"
    settlement_currency: str = "USD"

    def __post_init__(self) -> None:
        if not str(self.instrument_identifier).strip():
            raise ValueError("instrument_identifier cannot be empty")
        if not isinstance(self.asset_family, AssetFamily):
            raise TypeError("asset_family must be AssetFamily")
        object.__setattr__(self, "reference_price", _positive(self.reference_price, name="reference_price"))
        object.__setattr__(self, "contract_multiplier", _positive(self.contract_multiplier, name="contract_multiplier"))
        for name in ("trading_currency", "settlement_currency"):
            value = str(getattr(self, name)).strip().upper()
            if not value:
                raise ValueError(f"{name} cannot be empty")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PaperOrderIntent:
    instrument_identifier: str
    target_notional: float
    side: str
    order_type: str = "market"
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if not str(self.instrument_identifier).strip():
            raise ValueError("instrument_identifier cannot be empty")
        side = str(self.side).strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        object.__setattr__(self, "side", side)
        if isinstance(self.target_notional, bool) or not isinstance(self.target_notional, (int, float)):
            raise TypeError("target_notional must be numeric")
        if not isfinite(float(self.target_notional)) or float(self.target_notional) <= 0.0:
            raise ValueError("target_notional must be finite and positive")
        if self.real_money_authorized:
            raise ValueError("universal order intent is paper-only")


@dataclass(frozen=True, slots=True)
class PaperExecutionInstruction:
    instrument_identifier: str
    asset_family: AssetFamily
    signed_quantity: float
    notional: float
    quantity_kind: str
    execution_mode: str = "paper"
    real_money_authorized: bool = False


class AssetLifecycleAdapter(Protocol):
    asset_family: AssetFamily

    def translate(
        self,
        intent: PaperOrderIntent,
        view: NormalizedInvestmentView,
        evaluation: CapabilityEvaluation,
    ) -> PaperExecutionInstruction:
        ...


@dataclass(frozen=True, slots=True)
class _BaseAdapter:
    asset_family: AssetFamily
    quantity_kind: str
    integral_quantity: bool = False
    price_scale: float = 1.0

    def translate(
        self,
        intent: PaperOrderIntent,
        view: NormalizedInvestmentView,
        evaluation: CapabilityEvaluation,
    ) -> PaperExecutionInstruction:
        if intent.instrument_identifier != view.instrument_identifier:
            raise ValueError("order intent and investment view identify different instruments")
        if view.asset_family is not self.asset_family:
            raise ValueError("asset lifecycle adapter family mismatch")
        if evaluation.instrument_identifier != view.instrument_identifier:
            raise ValueError("capability evaluation identifies a different instrument")
        if not evaluation.certifiable:
            raise ValueError("instrument is not capability-certifiable for paper execution")
        unit_notional = view.reference_price * self.price_scale * view.contract_multiplier
        raw_quantity = float(intent.target_notional) / unit_notional
        quantity = float(floor(raw_quantity)) if self.integral_quantity else raw_quantity
        if quantity <= 0.0:
            raise ValueError("target notional is below the minimum executable unit")
        signed = quantity if intent.side == "buy" else -quantity
        return PaperExecutionInstruction(
            instrument_identifier=view.instrument_identifier,
            asset_family=self.asset_family,
            signed_quantity=signed,
            notional=quantity * unit_notional,
            quantity_kind=self.quantity_kind,
        )


DEFAULT_LIFECYCLE_ADAPTERS: Mapping[AssetFamily, AssetLifecycleAdapter] = {
    AssetFamily.EQUITY: _BaseAdapter(AssetFamily.EQUITY, "shares"),
    AssetFamily.FUND: _BaseAdapter(AssetFamily.FUND, "shares"),
    # Bond prices conventionally quote percent of par; a price of 99.5 means
    # 99.5 currency units per 100 face units.
    AssetFamily.FIXED_INCOME: _BaseAdapter(
        AssetFamily.FIXED_INCOME, "face_value_units", price_scale=0.01
    ),
    AssetFamily.FUTURE: _BaseAdapter(
        AssetFamily.FUTURE, "contracts", integral_quantity=True
    ),
    AssetFamily.OPTION: _BaseAdapter(
        AssetFamily.OPTION, "contracts", integral_quantity=True
    ),
    AssetFamily.FX: _BaseAdapter(AssetFamily.FX, "base_currency_units"),
    AssetFamily.CRYPTO: _BaseAdapter(AssetFamily.CRYPTO, "asset_units"),
}


def translate_paper_intent(
    intent: PaperOrderIntent,
    view: NormalizedInvestmentView,
    evaluation: CapabilityEvaluation,
    *,
    adapters: Mapping[AssetFamily, AssetLifecycleAdapter] = DEFAULT_LIFECYCLE_ADAPTERS,
) -> PaperExecutionInstruction:
    adapter = adapters.get(view.asset_family)
    if adapter is None:
        raise ValueError(f"no paper lifecycle adapter for {view.asset_family.value}")
    return adapter.translate(intent, view, evaluation)


__all__ = [
    "AssetLifecycleAdapter",
    "DEFAULT_LIFECYCLE_ADAPTERS",
    "NormalizedInvestmentView",
    "PaperExecutionInstruction",
    "PaperOrderIntent",
    "translate_paper_intent",
]
