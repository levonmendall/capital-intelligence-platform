"""Versioned investor objectives and Personal CIO brief contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Any


class GoalPriority(str, Enum):
    ESSENTIAL = "essential"
    IMPORTANT = "important"
    ASPIRATIONAL = "aspirational"


class GoalType(str, Enum):
    RETIREMENT = "retirement"
    LIQUIDITY = "liquidity"
    PURCHASE = "purchase"
    INCOME = "income"
    LEGACY = "legacy"
    LONG_TERM_GROWTH = "long_term_growth"
    OTHER = "other"


class RiskCapacity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskPreference(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


class ActionStatus(str, Enum):
    NO_ACTION = "no_action"
    MONITOR = "monitor"
    REVIEW = "review"
    CONSIDER_CHANGE = "consider_change"
    URGENT_REVIEW = "urgent_review"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _optional_money(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or None")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field_name} must be non-negative and finite")
    return round(normalized, 2)


def _optional_ratio(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or None")
    normalized = float(value)
    if not isfinite(normalized) or not 0 <= normalized <= 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(normalized, 6)


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class InvestorGoal:
    identifier: str
    goal_key: str
    investor_identifier: str
    version: str
    name: str
    goal_type: GoalType
    priority: GoalPriority
    effective_at: datetime
    target_date: date | None = None
    target_amount: float | None = None
    funded_amount: float | None = None
    portfolio_codes: tuple[str, ...] = ()
    liquidity_required: bool = False
    supersedes_identifier: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "goal_key",
            "investor_identifier",
            "version",
            "name",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        if not isinstance(self.goal_type, GoalType):
            raise TypeError("goal_type must be a GoalType")
        if not isinstance(self.priority, GoalPriority):
            raise TypeError("priority must be a GoalPriority")
        _aware(self.effective_at, "effective_at")
        if self.target_date is not None and not isinstance(self.target_date, date):
            raise TypeError("target_date must be a date or None")
        object.__setattr__(
            self,
            "target_amount",
            _optional_money(self.target_amount, "target_amount"),
        )
        object.__setattr__(
            self,
            "funded_amount",
            _optional_money(self.funded_amount, "funded_amount"),
        )
        if (
            self.target_amount is not None
            and self.funded_amount is not None
            and self.funded_amount > self.target_amount
        ):
            raise ValueError("funded_amount cannot exceed target_amount")
        object.__setattr__(
            self,
            "portfolio_codes",
            tuple(
                code.upper()
                for code in _strings(self.portfolio_codes, "portfolio_codes")
            ),
        )
        if not isinstance(self.liquidity_required, bool):
            raise TypeError("liquidity_required must be a bool")
        if self.supersedes_identifier is not None:
            object.__setattr__(
                self,
                "supersedes_identifier",
                _text(self.supersedes_identifier, "supersedes_identifier"),
            )


@dataclass(frozen=True, slots=True)
class InvestmentPolicyProfile:
    identifier: str
    investor_identifier: str
    version: str
    effective_at: datetime
    primary_objective: str
    time_horizon_years: int
    risk_capacity: RiskCapacity
    risk_preference: RiskPreference
    required_return: float | None = None
    maximum_tolerable_drawdown: float | None = None
    minimum_liquidity_months: int = 0
    income_requirement: float | None = None
    tax_sensitivity: str = "medium"
    rebalance_tolerance: str = "moderate"
    supersedes_identifier: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "investor_identifier",
            "version",
            "primary_objective",
            "tax_sensitivity",
            "rebalance_tolerance",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        _aware(self.effective_at, "effective_at")
        if isinstance(self.time_horizon_years, bool) or not isinstance(
            self.time_horizon_years,
            int,
        ):
            raise TypeError("time_horizon_years must be an int")
        if not 1 <= self.time_horizon_years <= 100:
            raise ValueError("time_horizon_years must be between 1 and 100")
        if not isinstance(self.risk_capacity, RiskCapacity):
            raise TypeError("risk_capacity must be a RiskCapacity")
        if not isinstance(self.risk_preference, RiskPreference):
            raise TypeError("risk_preference must be a RiskPreference")
        object.__setattr__(
            self,
            "required_return",
            _optional_ratio(self.required_return, "required_return"),
        )
        object.__setattr__(
            self,
            "maximum_tolerable_drawdown",
            _optional_ratio(
                self.maximum_tolerable_drawdown,
                "maximum_tolerable_drawdown",
            ),
        )
        if isinstance(self.minimum_liquidity_months, bool) or not isinstance(
            self.minimum_liquidity_months,
            int,
        ):
            raise TypeError("minimum_liquidity_months must be an int")
        if not 0 <= self.minimum_liquidity_months <= 120:
            raise ValueError("minimum_liquidity_months must be between 0 and 120")
        object.__setattr__(
            self,
            "income_requirement",
            _optional_money(self.income_requirement, "income_requirement"),
        )
        if self.supersedes_identifier is not None:
            object.__setattr__(
                self,
                "supersedes_identifier",
                _text(self.supersedes_identifier, "supersedes_identifier"),
            )


@dataclass(frozen=True, slots=True)
class PortfolioAlignment:
    investor_identifier: str
    as_of: datetime
    score: int | None
    status: str
    policy_identifier: str | None
    goal_identifiers: tuple[str, ...]
    supports: tuple[str, ...]
    conflicts: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "investor_identifier",
            _text(self.investor_identifier, "investor_identifier"),
        )
        _aware(self.as_of, "as_of")
        if self.score is not None:
            if isinstance(self.score, bool) or not isinstance(self.score, int):
                raise TypeError("score must be an int or None")
            if not 0 <= self.score <= 100:
                raise ValueError("score must be between 0 and 100")
        object.__setattr__(self, "status", _text(self.status, "status"))
        if self.policy_identifier is not None:
            object.__setattr__(
                self,
                "policy_identifier",
                _text(self.policy_identifier, "policy_identifier"),
            )
        for field_name in ("goal_identifiers", "supports", "conflicts"):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "explanation",
            _text(self.explanation, "explanation"),
        )


@dataclass(frozen=True, slots=True)
class PersonalCIOBrief:
    identifier: str
    investor_identifier: str
    as_of: datetime
    generated_at: datetime
    snapshot_identifier: str
    policy_identifier: str | None
    what_changed: str
    why_it_matters: str
    portfolio_effect: str
    action_status: ActionStatus
    recommended_action: str
    review_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    confidence: int | None
    data_status: str
    portfolio_alignment: PortfolioAlignment

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "investor_identifier",
            "snapshot_identifier",
            "what_changed",
            "why_it_matters",
            "portfolio_effect",
            "recommended_action",
            "data_status",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        if self.policy_identifier is not None:
            object.__setattr__(
                self,
                "policy_identifier",
                _text(self.policy_identifier, "policy_identifier"),
            )
        if not isinstance(self.action_status, ActionStatus):
            raise TypeError("action_status must be an ActionStatus")
        for field_name in ("review_conditions", "evidence_identifiers"):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name),
            )
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(
                self.confidence,
                int,
            ):
                raise TypeError("confidence must be an int or None")
            if not 0 <= self.confidence <= 100:
                raise ValueError("confidence must be between 0 and 100")
        if not isinstance(self.portfolio_alignment, PortfolioAlignment):
            raise TypeError("portfolio_alignment must be a PortfolioAlignment")


def goal_to_dict(goal: InvestorGoal) -> dict[str, Any]:
    return {
        "schema_version": "investor-goal.v1",
        "identifier": goal.identifier,
        "goal_key": goal.goal_key,
        "investor_identifier": goal.investor_identifier,
        "version": goal.version,
        "name": goal.name,
        "goal_type": goal.goal_type.value,
        "priority": goal.priority.value,
        "effective_at": goal.effective_at.isoformat(),
        "target_date": (
            None if goal.target_date is None else goal.target_date.isoformat()
        ),
        "target_amount": goal.target_amount,
        "funded_amount": goal.funded_amount,
        "portfolio_codes": list(goal.portfolio_codes),
        "liquidity_required": goal.liquidity_required,
        "supersedes_identifier": goal.supersedes_identifier,
    }


def policy_to_dict(profile: InvestmentPolicyProfile) -> dict[str, Any]:
    return {
        "schema_version": "investment-policy-profile.v1",
        "identifier": profile.identifier,
        "investor_identifier": profile.investor_identifier,
        "version": profile.version,
        "effective_at": profile.effective_at.isoformat(),
        "primary_objective": profile.primary_objective,
        "time_horizon_years": profile.time_horizon_years,
        "risk_capacity": profile.risk_capacity.value,
        "risk_preference": profile.risk_preference.value,
        "required_return": profile.required_return,
        "maximum_tolerable_drawdown": profile.maximum_tolerable_drawdown,
        "minimum_liquidity_months": profile.minimum_liquidity_months,
        "income_requirement": profile.income_requirement,
        "tax_sensitivity": profile.tax_sensitivity,
        "rebalance_tolerance": profile.rebalance_tolerance,
        "supersedes_identifier": profile.supersedes_identifier,
    }


def alignment_to_dict(alignment: PortfolioAlignment) -> dict[str, Any]:
    return {
        "schema_version": "portfolio-alignment.v1",
        "investor_identifier": alignment.investor_identifier,
        "as_of": alignment.as_of.isoformat(),
        "score": alignment.score,
        "status": alignment.status,
        "policy_identifier": alignment.policy_identifier,
        "goal_identifiers": list(alignment.goal_identifiers),
        "supports": list(alignment.supports),
        "conflicts": list(alignment.conflicts),
        "explanation": alignment.explanation,
        "is_goal_success_probability": False,
    }


def brief_to_dict(brief: PersonalCIOBrief) -> dict[str, Any]:
    return {
        "schema_version": "personal-cio-brief.v1",
        "identifier": brief.identifier,
        "investor_identifier": brief.investor_identifier,
        "as_of": brief.as_of.isoformat(),
        "generated_at": brief.generated_at.isoformat(),
        "snapshot_identifier": brief.snapshot_identifier,
        "policy_identifier": brief.policy_identifier,
        "what_changed": brief.what_changed,
        "why_it_matters": brief.why_it_matters,
        "portfolio_effect": brief.portfolio_effect,
        "action_status": brief.action_status.value,
        "recommended_action": brief.recommended_action,
        "review_conditions": list(brief.review_conditions),
        "evidence_identifiers": list(brief.evidence_identifiers),
        "confidence": brief.confidence,
        "data_status": brief.data_status,
        "portfolio_alignment": alignment_to_dict(brief.portfolio_alignment),
    }
