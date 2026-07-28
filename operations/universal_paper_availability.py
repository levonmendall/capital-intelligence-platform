"""Exact internal paper-availability authority for every classified asset class.

This module proves mechanical availability only. Provider-backed paper readiness
remains governed by the separate all-markets data, activation, certification,
eligible-universe, launch, human-entry, and runtime-control authorities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from cio import CandidateAssetClass
from governance import TradingSessionModel
from portfolio.multi_asset_controls import MultiAssetConstructionPolicy
from portfolio.multi_asset_execution import MultiAssetExecutionPolicy


DEFAULT_SCOPE_PATH = Path("config/universal_paper_asset_classes.json")
ALL_CLASSIFIED_ASSET_CLASSES = frozenset(
    set(CandidateAssetClass) - {CandidateAssetClass.OTHER}
)
_DERIVATIVE_CLASSES = frozenset(
    {
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
        CandidateAssetClass.VOLATILITY,
    }
)
_ALLOWED_ACCOUNTING_MODELS = frozenset(
    {
        "cash_security",
        "cash_security_with_fx_translation",
        "cash_backed_or_fully_collateralized_notional",
        "unlevered_cash_spot",
        "fully_collateralized_notional",
        "long_premium_defined_risk",
        "long_premium_or_fully_collateralized_notional",
    }
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class UniversalPaperAssetClassCapability:
    asset_class: CandidateAssetClass
    permitted_instrument_types: tuple[str, ...]
    permitted_session_models: tuple[TradingSessionModel, ...]
    accounting_model: str
    external_provider_activation_required: bool

    def __post_init__(self) -> None:
        if self.asset_class is CandidateAssetClass.OTHER:
            raise ValueError("unclassified assets cannot be paper available")
        object.__setattr__(
            self,
            "permitted_instrument_types",
            tuple(item.lower() for item in _texts(
                self.permitted_instrument_types,
                field_name="permitted_instrument_types",
            )),
        )
        if not isinstance(self.permitted_session_models, tuple) or not all(
            isinstance(item, TradingSessionModel)
            for item in self.permitted_session_models
        ):
            raise TypeError(
                "permitted_session_models must contain TradingSessionModel values"
            )
        if not self.permitted_session_models:
            raise ValueError("permitted_session_models cannot be empty")
        if len(self.permitted_session_models) != len(
            set(self.permitted_session_models)
        ):
            raise ValueError("permitted_session_models cannot contain duplicates")
        accounting = _text(
            self.accounting_model,
            field_name="accounting_model",
        ).lower()
        if accounting not in _ALLOWED_ACCOUNTING_MODELS:
            raise ValueError(f"unsupported accounting model {accounting!r}")
        object.__setattr__(self, "accounting_model", accounting)
        if not isinstance(self.external_provider_activation_required, bool):
            raise TypeError(
                "external_provider_activation_required must be a bool"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class.value,
            "permitted_instrument_types": list(
                self.permitted_instrument_types
            ),
            "permitted_session_models": [
                item.value for item in self.permitted_session_models
            ],
            "accounting_model": self.accounting_model,
            "external_provider_activation_required": (
                self.external_provider_activation_required
            ),
        }


@dataclass(frozen=True, slots=True)
class UniversalPaperAssetClassScope:
    identifier: str
    objective: str
    operating_mode: str
    portfolio_code: str
    base_currency: str
    long_only: bool
    maximum_gross_leverage: float
    real_money_authorized: bool
    unclassified_assets_prohibited: bool
    asset_classes: tuple[UniversalPaperAssetClassCapability, ...]
    limitations: tuple[str, ...]
    schema_version: str = "universal-paper-asset-class-scope.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "objective",
            "operating_mode",
            "portfolio_code",
            "base_currency",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if self.operating_mode != "governed_internal_simulation":
            raise ValueError("universal scope must remain internal simulation")
        if self.portfolio_code != "COMPOUNDING":
            raise ValueError("universal paper scope must target COMPOUNDING")
        if self.base_currency.upper() != "USD":
            raise ValueError("universal paper scope base currency must be USD")
        if self.long_only is not True:
            raise ValueError("universal paper scope must remain long-only")
        if isinstance(self.maximum_gross_leverage, bool) or not isinstance(
            self.maximum_gross_leverage,
            (int, float),
        ):
            raise TypeError("maximum_gross_leverage must be numeric")
        leverage = float(self.maximum_gross_leverage)
        if leverage <= 0.0 or leverage > 1.0:
            raise ValueError(
                "universal paper scope cannot exceed 1.0 gross leverage"
            )
        object.__setattr__(self, "maximum_gross_leverage", leverage)
        if self.real_money_authorized is not False:
            raise ValueError("universal paper scope cannot authorize real money")
        if self.unclassified_assets_prohibited is not True:
            raise ValueError("unclassified assets must remain prohibited")
        if not isinstance(self.asset_classes, tuple) or not all(
            isinstance(item, UniversalPaperAssetClassCapability)
            for item in self.asset_classes
        ):
            raise TypeError(
                "asset_classes must contain UniversalPaperAssetClassCapability values"
            )
        classes = tuple(item.asset_class for item in self.asset_classes)
        if len(classes) != len(set(classes)):
            raise ValueError("asset_classes cannot contain duplicates")
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )

    def capability_for(
        self,
        asset_class: CandidateAssetClass,
    ) -> UniversalPaperAssetClassCapability:
        return next(
            item for item in self.asset_classes if item.asset_class is asset_class
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identifier": self.identifier,
            "objective": self.objective,
            "operating_mode": self.operating_mode,
            "portfolio_code": self.portfolio_code,
            "base_currency": self.base_currency,
            "long_only": self.long_only,
            "maximum_gross_leverage": self.maximum_gross_leverage,
            "real_money_authorized": self.real_money_authorized,
            "unclassified_assets_prohibited": (
                self.unclassified_assets_prohibited
            ),
            "asset_classes": [item.to_dict() for item in self.asset_classes],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class UniversalPaperAvailabilityReport:
    evaluated_at: datetime
    scope_identifier: str
    available: bool
    expected_asset_classes: tuple[str, ...]
    declared_asset_classes: tuple[str, ...]
    policy_ready_asset_classes: tuple[str, ...]
    rehearsed_asset_classes: tuple[str, ...]
    accounting_models: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "universal-paper-availability-report.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "scope_identifier": self.scope_identifier,
            "available": self.available,
            "expected_asset_classes": list(self.expected_asset_classes),
            "declared_asset_classes": list(self.declared_asset_classes),
            "policy_ready_asset_classes": list(
                self.policy_ready_asset_classes
            ),
            "rehearsed_asset_classes": list(self.rehearsed_asset_classes),
            "accounting_models": [list(item) for item in self.accounting_models],
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "provider_backed_live_paper_ready": False,
            "live_order_routing_authorized": False,
            "real_money_authorized": False,
        }


def load_universal_paper_asset_class_scope(
    path: str | Path = DEFAULT_SCOPE_PATH,
) -> UniversalPaperAssetClassScope:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"cannot load universal paper scope {str(source)!r}"
        ) from error
    if not isinstance(payload, Mapping):
        raise ValueError("universal paper scope must encode an object")
    if payload.get("schema_version") != (
        "universal-paper-asset-class-scope.v1"
    ):
        raise ValueError("unsupported universal paper scope schema")
    raw_classes = payload.get("asset_classes")
    if not isinstance(raw_classes, list):
        raise ValueError("asset_classes must be an array")
    capabilities: list[UniversalPaperAssetClassCapability] = []
    for item in raw_classes:
        if not isinstance(item, Mapping):
            raise ValueError("every asset-class capability must be an object")
        capabilities.append(
            UniversalPaperAssetClassCapability(
                asset_class=CandidateAssetClass(str(item["asset_class"])),
                permitted_instrument_types=tuple(
                    str(value)
                    for value in item["permitted_instrument_types"]
                ),
                permitted_session_models=tuple(
                    TradingSessionModel(str(value))
                    for value in item["permitted_session_models"]
                ),
                accounting_model=str(item["accounting_model"]),
                external_provider_activation_required=bool(
                    item["external_provider_activation_required"]
                ),
            )
        )
    return UniversalPaperAssetClassScope(
        identifier=str(payload["identifier"]),
        objective=str(payload["objective"]),
        operating_mode=str(payload["operating_mode"]),
        portfolio_code=str(payload["portfolio_code"]),
        base_currency=str(payload["base_currency"]),
        long_only=bool(payload["long_only"]),
        maximum_gross_leverage=float(payload["maximum_gross_leverage"]),
        real_money_authorized=bool(payload["real_money_authorized"]),
        unclassified_assets_prohibited=bool(
            payload["unclassified_assets_prohibited"]
        ),
        asset_classes=tuple(capabilities),
        limitations=tuple(str(item) for item in payload["limitations"]),
        schema_version=str(payload["schema_version"]),
    )


def assess_universal_paper_availability(
    *,
    scope: UniversalPaperAssetClassScope,
    evaluated_at: datetime,
    rehearsed_asset_classes: tuple[str, ...],
) -> UniversalPaperAvailabilityReport:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if not isinstance(scope, UniversalPaperAssetClassScope):
        raise TypeError("scope must be UniversalPaperAssetClassScope")
    blockers: list[str] = []
    expected = tuple(
        sorted(item.value for item in ALL_CLASSIFIED_ASSET_CLASSES)
    )
    declared = tuple(
        sorted(item.asset_class.value for item in scope.asset_classes)
    )
    if declared != expected:
        missing = sorted(set(expected) - set(declared))
        extra = sorted(set(declared) - set(expected))
        blockers.append(
            "scope does not exactly cover every classified asset class: "
            f"missing={missing} extra={extra}"
        )

    execution_policy = MultiAssetExecutionPolicy()
    construction_policy = MultiAssetConstructionPolicy()
    policy_ready: list[str] = []
    for capability in scope.asset_classes:
        asset_class = capability.asset_class
        class_blockers: list[str] = []
        try:
            canonical_session = execution_policy.session_model(asset_class)
        except (KeyError, ValueError, RuntimeError) as error:
            class_blockers.append(f"session model unavailable: {error}")
        else:
            if canonical_session not in capability.permitted_session_models:
                class_blockers.append(
                    "canonical session model is outside the declared capability"
                )
        try:
            commission = execution_policy.commission_bps(asset_class)
            if commission < 0.0:
                class_blockers.append("commission model is negative")
        except (KeyError, ValueError, RuntimeError) as error:
            class_blockers.append(f"commission model unavailable: {error}")
        try:
            limit = construction_policy.class_limit(asset_class)
            if limit <= 0.0:
                class_blockers.append("construction class limit is not positive")
        except (KeyError, ValueError, RuntimeError) as error:
            class_blockers.append(f"construction policy unavailable: {error}")

        types = set(capability.permitted_instrument_types)
        if asset_class in {CandidateAssetClass.FX, CandidateAssetClass.CRYPTO}:
            if not types & {"spot", "token", "stablecoin", "fund"}:
                class_blockers.append("unlevered spot or listed wrapper is missing")
            if capability.accounting_model != "unlevered_cash_spot":
                class_blockers.append(
                    "direct FX and crypto require unlevered cash accounting"
                )
        if asset_class is CandidateAssetClass.OPTION:
            if types != {"option"}:
                class_blockers.append("option scope must contain only options")
            if capability.accounting_model != "long_premium_defined_risk":
                class_blockers.append(
                    "options require long-premium defined-risk accounting"
                )
        if asset_class in _DERIVATIVE_CLASSES:
            if capability.accounting_model not in {
                "fully_collateralized_notional",
                "long_premium_defined_risk",
                "long_premium_or_fully_collateralized_notional",
            }:
                class_blockers.append(
                    "derivatives require defined-risk collateralized accounting"
                )
        if not capability.external_provider_activation_required:
            class_blockers.append(
                "provider-backed operation must require external activation"
            )
        if class_blockers:
            blockers.extend(
                f"{asset_class.value}: {item}" for item in class_blockers
            )
        else:
            policy_ready.append(asset_class.value)

    rehearsed = tuple(sorted(set(rehearsed_asset_classes)))
    if rehearsed != expected:
        missing = sorted(set(expected) - set(rehearsed))
        extra = sorted(set(rehearsed) - set(expected))
        blockers.append(
            "mechanical rehearsal does not exactly fill every classified asset "
            f"class: missing={missing} extra={extra}"
        )

    return UniversalPaperAvailabilityReport(
        evaluated_at=evaluated_at,
        scope_identifier=scope.identifier,
        available=not blockers,
        expected_asset_classes=expected,
        declared_asset_classes=declared,
        policy_ready_asset_classes=tuple(sorted(policy_ready)),
        rehearsed_asset_classes=rehearsed,
        accounting_models=tuple(
            sorted(
                (
                    item.asset_class.value,
                    item.accounting_model,
                )
                for item in scope.asset_classes
            )
        ),
        blockers=tuple(blockers),
        limitations=scope.limitations,
    )


__all__ = [
    "ALL_CLASSIFIED_ASSET_CLASSES",
    "DEFAULT_SCOPE_PATH",
    "UniversalPaperAssetClassCapability",
    "UniversalPaperAssetClassScope",
    "UniversalPaperAvailabilityReport",
    "assess_universal_paper_availability",
    "load_universal_paper_asset_class_scope",
]
