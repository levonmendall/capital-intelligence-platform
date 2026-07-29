"""Governed champion-challenger promotion for decision policies.

Policy versions may be evaluated in shadow, but they never promote themselves.
Promotion requires sufficient out-of-sample evidence, regime coverage, integrity,
calibration, drawdown, turnover, and missed-opportunity controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class PolicyVersionStatus(str, Enum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"
    RETIRED = "retired"


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


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class PolicyPerformanceEvidence:
    sample_count: int
    out_of_sample_count: int
    regime_identifiers: tuple[str, ...]
    mean_decision_brier: float
    calibration_error: float
    maximum_drawdown: float
    mean_turnover: float
    missed_opportunity_rate: float
    integrity_failure_count: int = 0

    def __post_init__(self) -> None:
        for name in ("sample_count", "out_of_sample_count", "integrity_failure_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.out_of_sample_count > self.sample_count:
            raise ValueError("out_of_sample_count cannot exceed sample_count")
        if not isinstance(self.regime_identifiers, tuple):
            raise TypeError("regime_identifiers must be a tuple")
        regimes = tuple(_text(item, name="regime_identifier") for item in self.regime_identifiers)
        if len(regimes) != len(set(regimes)):
            raise ValueError("regime_identifiers cannot contain duplicates")
        object.__setattr__(self, "regime_identifiers", regimes)
        for name in (
            "mean_decision_brier",
            "calibration_error",
            "mean_turnover",
            "missed_opportunity_rate",
        ):
            value = _number(getattr(self, name), name=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        drawdown = _number(self.maximum_drawdown, name="maximum_drawdown")
        if drawdown > 0.0:
            raise ValueError("maximum_drawdown must be zero or negative")
        object.__setattr__(self, "maximum_drawdown", drawdown)


@dataclass(frozen=True, slots=True)
class PolicyVersionCandidate:
    identifier: str
    component: str
    version: str
    status: PolicyVersionStatus
    evidence: PolicyPerformanceEvidence
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    rollback_version: str | None = None

    def __post_init__(self) -> None:
        for name in ("identifier", "component", "version"):
            object.__setattr__(self, name, _text(getattr(self, name), name=name))
        if not isinstance(self.status, PolicyVersionStatus):
            raise TypeError("status must be PolicyVersionStatus")
        if not isinstance(self.evidence, PolicyPerformanceEvidence):
            raise TypeError("evidence must be PolicyPerformanceEvidence")
        _aware(self.created_at, name="created_at")
        if self.approved_by is not None:
            object.__setattr__(self, "approved_by", _text(self.approved_by, name="approved_by"))
        if self.approved_at is not None:
            _aware(self.approved_at, name="approved_at")
            if self.approved_at < self.created_at:
                raise ValueError("approved_at cannot predate created_at")
        if self.rollback_version is not None:
            object.__setattr__(self, "rollback_version", _text(self.rollback_version, name="rollback_version"))


@dataclass(frozen=True, slots=True)
class PolicyPromotionPolicy:
    version: str = "policy-promotion.v1"
    minimum_sample_count: int = 50
    minimum_out_of_sample_count: int = 30
    minimum_regime_count: int = 3
    maximum_decision_brier: float = 0.25
    maximum_calibration_error: float = 0.12
    minimum_maximum_drawdown: float = -0.25
    maximum_mean_turnover: float = 0.25
    maximum_missed_opportunity_rate: float = 0.20

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, name="version"))
        for name in (
            "minimum_sample_count",
            "minimum_out_of_sample_count",
            "minimum_regime_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        for name in (
            "maximum_decision_brier",
            "maximum_calibration_error",
            "maximum_mean_turnover",
            "maximum_missed_opportunity_rate",
        ):
            value = _number(getattr(self, name), name=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        floor = _number(self.minimum_maximum_drawdown, name="minimum_maximum_drawdown")
        if floor >= 0.0:
            raise ValueError("minimum_maximum_drawdown must be negative")
        object.__setattr__(self, "minimum_maximum_drawdown", floor)


@dataclass(frozen=True, slots=True)
class PolicyPromotionDecision:
    champion_identifier: str
    challenger_identifier: str
    permitted: bool
    reasons: tuple[str, ...]
    policy_version: str


class ChampionChallengerRegistry:
    """Evaluate promotion without mutating the active policy registry."""

    def __init__(self, policy: PolicyPromotionPolicy | None = None) -> None:
        self.policy = policy or PolicyPromotionPolicy()

    def evaluate(
        self,
        champion: PolicyVersionCandidate,
        challenger: PolicyVersionCandidate,
        *,
        approver: str,
    ) -> PolicyPromotionDecision:
        if not isinstance(champion, PolicyVersionCandidate) or not isinstance(challenger, PolicyVersionCandidate):
            raise TypeError("champion and challenger must be PolicyVersionCandidate values")
        reviewer = _text(approver, name="approver")
        reasons: list[str] = []
        if champion.status is not PolicyVersionStatus.CHAMPION:
            reasons.append("current version is not marked champion")
        if challenger.status is not PolicyVersionStatus.CHALLENGER:
            reasons.append("proposed version is not marked challenger")
        if champion.component != challenger.component:
            reasons.append("champion and challenger govern different components")
        if champion.identifier == challenger.identifier or champion.version == challenger.version:
            reasons.append("a policy version cannot promote itself")
        if reviewer.lower() in {"system", "model", "challenger", challenger.identifier.lower()}:
            reasons.append("promotion requires an independent human or governance approver")
        evidence = challenger.evidence
        policy = self.policy
        if evidence.sample_count < policy.minimum_sample_count:
            reasons.append("insufficient total evaluation sample")
        if evidence.out_of_sample_count < policy.minimum_out_of_sample_count:
            reasons.append("insufficient out-of-sample evaluation sample")
        if len(evidence.regime_identifiers) < policy.minimum_regime_count:
            reasons.append("insufficient market-regime coverage")
        if evidence.integrity_failure_count:
            reasons.append("unresolved integrity failures prohibit promotion")
        if evidence.mean_decision_brier > policy.maximum_decision_brier:
            reasons.append("decision calibration Brier score exceeds policy")
        if evidence.calibration_error > policy.maximum_calibration_error:
            reasons.append("calibration error exceeds policy")
        if evidence.maximum_drawdown < policy.minimum_maximum_drawdown:
            reasons.append("challenger drawdown exceeds policy")
        if evidence.mean_turnover > policy.maximum_mean_turnover:
            reasons.append("challenger turnover exceeds policy")
        if evidence.missed_opportunity_rate > policy.maximum_missed_opportunity_rate:
            reasons.append("missed-opportunity rate exceeds policy")
        if evidence.mean_decision_brier > champion.evidence.mean_decision_brier:
            reasons.append("challenger does not improve decision calibration")
        return PolicyPromotionDecision(
            champion_identifier=champion.identifier,
            challenger_identifier=challenger.identifier,
            permitted=not reasons,
            reasons=tuple(reasons) or ("challenger satisfies governed promotion criteria",),
            policy_version=policy.version,
        )


__all__ = [
    "ChampionChallengerRegistry",
    "PolicyPerformanceEvidence",
    "PolicyPromotionDecision",
    "PolicyPromotionPolicy",
    "PolicyVersionCandidate",
    "PolicyVersionStatus",
]
