"""Lifecycle and nonlinear-risk controls for derivative allocation.

A derivative may be analyzed without this profile, but positive portfolio
allocation fails closed until contract, notional, Greeks, expiry, collateral,
maximum-loss, assignment, settlement, and roll behavior are governed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _number(value: object, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return normalized


@dataclass(frozen=True, slots=True)
class DerivativeLifecycleProfile:
    identifier: str
    instrument_identifier: str
    contract_multiplier: float
    notional_per_contract: float
    delta: float
    gamma: float
    vega: float
    theta: float
    expires_at: datetime
    roll_review_days: int
    initial_margin_return: float
    maintenance_margin_return: float
    collateral_return: float
    maximum_loss_return: float
    assignment_supported: bool
    exercise_style: str
    settlement_type: str
    source_identifiers: tuple[str, ...]
    model_versions: tuple[str, ...]
    schema_version: str = "derivative-lifecycle-profile.v1"

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "instrument_identifier",
            "exercise_style",
            "settlement_type",
            "schema_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name=name))
        for name in ("contract_multiplier", "notional_per_contract"):
            value = _number(getattr(self, name), name=name, minimum=0.0)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        for name in ("delta", "gamma", "vega", "theta"):
            object.__setattr__(self, name, _number(getattr(self, name), name=name))
        _aware(self.expires_at, name="expires_at")
        if isinstance(self.roll_review_days, bool) or not isinstance(self.roll_review_days, int):
            raise TypeError("roll_review_days must be an integer")
        if self.roll_review_days < 1:
            raise ValueError("roll_review_days must be positive")
        for name in (
            "initial_margin_return",
            "maintenance_margin_return",
            "collateral_return",
        ):
            value = _number(getattr(self, name), name=name, minimum=0.0)
            if value > 1.0:
                raise ValueError(f"{name} must not exceed 1.0")
            object.__setattr__(self, name, value)
        maximum_loss = _number(self.maximum_loss_return, name="maximum_loss_return")
        if not -1.0 <= maximum_loss <= 0.0:
            raise ValueError("maximum_loss_return must be between -1.0 and 0.0")
        object.__setattr__(self, "maximum_loss_return", maximum_loss)
        if not isinstance(self.assignment_supported, bool):
            raise TypeError("assignment_supported must be a bool")
        for name in ("source_identifiers", "model_versions"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise TypeError(f"{name} must be a tuple")
            normalized = tuple(_text(item, name=name) for item in values)
            if not normalized:
                raise ValueError(f"{name} cannot be empty")
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{name} cannot contain duplicates")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class DerivativeLifecyclePolicy:
    version: str = "derivative-lifecycle-policy.v1"
    minimum_days_to_expiry: int = 7
    maximum_absolute_delta: float = 1.0
    maximum_absolute_gamma: float = 1.0
    maximum_absolute_vega: float = 10.0
    maximum_margin_return: float = 0.50
    require_bounded_maximum_loss: bool = True


@dataclass(frozen=True, slots=True)
class DerivativeLifecycleAssessment:
    authorized: bool
    reasons: tuple[str, ...]
    policy_version: str


class DerivativeLifecycleAuthority:
    def __init__(self, policy: DerivativeLifecyclePolicy | None = None) -> None:
        self.policy = policy or DerivativeLifecyclePolicy()

    def assess(
        self,
        profile: DerivativeLifecycleProfile | None,
        *,
        instrument_identifier: str,
        as_of: datetime,
    ) -> DerivativeLifecycleAssessment:
        if profile is None:
            return DerivativeLifecycleAssessment(
                authorized=False,
                reasons=("derivative lifecycle profile is missing",),
                policy_version=self.policy.version,
            )
        if not isinstance(profile, DerivativeLifecycleProfile):
            raise TypeError("profile must be DerivativeLifecycleProfile or None")
        decision_time = _aware(as_of, name="as_of")
        identifier = _text(instrument_identifier, name="instrument_identifier")
        reasons: list[str] = []
        if profile.instrument_identifier != identifier:
            reasons.append("derivative lifecycle profile does not match the instrument")
        days_to_expiry = (profile.expires_at - decision_time).total_seconds() / 86400.0
        if days_to_expiry < self.policy.minimum_days_to_expiry:
            reasons.append("contract is inside the minimum expiry window")
        if abs(profile.delta) > self.policy.maximum_absolute_delta:
            reasons.append("absolute delta exceeds policy")
        if abs(profile.gamma) > self.policy.maximum_absolute_gamma:
            reasons.append("absolute gamma exceeds policy")
        if abs(profile.vega) > self.policy.maximum_absolute_vega:
            reasons.append("absolute vega exceeds policy")
        if max(profile.initial_margin_return, profile.maintenance_margin_return) > self.policy.maximum_margin_return:
            reasons.append("margin requirement exceeds policy")
        if self.policy.require_bounded_maximum_loss and profile.maximum_loss_return <= -1.0:
            reasons.append("bounded maximum loss is not demonstrated")
        if profile.settlement_type.lower() not in {"cash", "physical"}:
            reasons.append("settlement type is unsupported")
        return DerivativeLifecycleAssessment(
            authorized=not reasons,
            reasons=tuple(reasons) or ("derivative lifecycle controls are complete",),
            policy_version=self.policy.version,
        )


__all__ = [
    "DerivativeLifecycleAssessment",
    "DerivativeLifecycleAuthority",
    "DerivativeLifecyclePolicy",
    "DerivativeLifecycleProfile",
]
