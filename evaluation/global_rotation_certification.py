"""Point-in-time outcome certification for global opportunity rotation.

Evaluation is separate from authority. This module measures whether the portfolio found
leadership, deployed into feasible positive opportunities, derisked deteriorating
holdings, avoided unexplained excess cash, and continued to compound during equity-down
periods. Results cannot change policy or authorize capital automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class GlobalRotationOutcomeObservation:
    identifier: str
    decision_as_of: datetime
    knowledge_cutoff: datetime
    outcome_observed_at: datetime
    portfolio_return: float
    equity_market_return: float
    starting_cash_weight: float
    minimum_cash_weight: float
    ending_cash_weight: float
    deployment_opportunity_present: bool
    positive_rotation_action_taken: bool
    deteriorating_owned_leadership: bool
    derisk_action_taken: bool
    strongest_leadership_return: float | None
    selected_rotation_return: float | None
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("rotation observation identifier cannot be empty")
        for name in ("decision_as_of", "knowledge_cutoff", "outcome_observed_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        for name in ("starting_cash_weight", "minimum_cash_weight", "ending_cash_weight"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if self.minimum_cash_weight > self.starting_cash_weight + 1e-12:
            raise ValueError("minimum cash cannot exceed decision-time starting cash")
        if not self.evidence_identifiers or any(not str(item).strip() for item in self.evidence_identifiers):
            raise ValueError("rotation outcomes require non-empty evidence lineage")

    @property
    def point_in_time_valid(self) -> bool:
        return self.knowledge_cutoff <= self.decision_as_of < self.outcome_observed_at

    @property
    def excess_starting_cash(self) -> float:
        return max(0.0, self.starting_cash_weight - self.minimum_cash_weight)


@dataclass(frozen=True, slots=True)
class GlobalRotationCertificationPolicy:
    minimum_observations: int = 100
    minimum_equity_down_observations: int = 20
    minimum_deployment_opportunities: int = 20
    minimum_leadership_participation_rate: float = 0.70
    minimum_derisk_response_rate: float = 0.70
    maximum_unexplained_cash_rate: float = 0.10
    minimum_positive_return_rate_during_equity_down_periods: float = 0.45

    def __post_init__(self) -> None:
        for name in (
            "minimum_observations",
            "minimum_equity_down_observations",
            "minimum_deployment_opportunities",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        for name in (
            "minimum_leadership_participation_rate",
            "minimum_derisk_response_rate",
            "maximum_unexplained_cash_rate",
            "minimum_positive_return_rate_during_equity_down_periods",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")


@dataclass(frozen=True, slots=True)
class GlobalRotationCertificationReport:
    as_of: datetime
    observation_count: int
    point_in_time_valid: bool
    equity_down_observation_count: int
    positive_return_rate_during_equity_down_periods: float
    mean_portfolio_return_during_equity_down_periods: float
    deployment_opportunity_count: int
    leadership_participation_rate: float
    deteriorating_holding_count: int
    derisk_response_rate: float
    unexplained_cash_count: int
    unexplained_cash_rate: float
    mean_excess_cash_when_unexplained: float
    mean_selected_rotation_return: float | None
    mean_strongest_leadership_return: float | None
    gates: tuple[tuple[str, bool], ...]
    rotation_behavior_certified: bool
    performance_claim_authorized: bool = False
    policy_change_authorized: bool = False
    investment_authority: bool = False
    schema_version: str = "global-rotation-certification-report.v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.performance_claim_authorized or self.policy_change_authorized or self.investment_authority:
            raise ValueError("rotation certification is evaluation only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "observation_count": self.observation_count,
            "point_in_time_valid": self.point_in_time_valid,
            "equity_down_observation_count": self.equity_down_observation_count,
            "positive_return_rate_during_equity_down_periods": round(self.positive_return_rate_during_equity_down_periods, 8),
            "mean_portfolio_return_during_equity_down_periods": round(self.mean_portfolio_return_during_equity_down_periods, 8),
            "deployment_opportunity_count": self.deployment_opportunity_count,
            "leadership_participation_rate": round(self.leadership_participation_rate, 8),
            "deteriorating_holding_count": self.deteriorating_holding_count,
            "derisk_response_rate": round(self.derisk_response_rate, 8),
            "unexplained_cash_count": self.unexplained_cash_count,
            "unexplained_cash_rate": round(self.unexplained_cash_rate, 8),
            "mean_excess_cash_when_unexplained": round(self.mean_excess_cash_when_unexplained, 8),
            "mean_selected_rotation_return": self.mean_selected_rotation_return,
            "mean_strongest_leadership_return": self.mean_strongest_leadership_return,
            "gates": [[name, passed] for name, passed in self.gates],
            "rotation_behavior_certified": self.rotation_behavior_certified,
            "performance_claim_authorized": False,
            "policy_change_authorized": False,
            "investment_authority": False,
            "schema_version": self.schema_version,
        }


def _rate(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    return empty if denominator <= 0 else numerator / denominator


def build_global_rotation_certification(
    *,
    observations: Iterable[GlobalRotationOutcomeObservation],
    as_of: datetime,
    policy: GlobalRotationCertificationPolicy | None = None,
) -> GlobalRotationCertificationReport:
    values = tuple(observations)
    resolved = policy or GlobalRotationCertificationPolicy()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if any(not isinstance(item, GlobalRotationOutcomeObservation) for item in values):
        raise TypeError("observations must contain GlobalRotationOutcomeObservation values")
    if any(item.outcome_observed_at > as_of for item in values):
        raise ValueError("rotation outcomes cannot be observed after certification as_of")

    pit = all(item.point_in_time_valid for item in values)
    equity_down = tuple(item for item in values if item.equity_market_return < 0.0)
    deployment = tuple(item for item in values if item.deployment_opportunity_present)
    deterioration = tuple(item for item in values if item.deteriorating_owned_leadership)
    unexplained = tuple(
        item
        for item in deployment
        if item.excess_starting_cash > 1e-8 and not item.positive_rotation_action_taken
    )
    positive_down_rate = _rate(
        sum(item.portfolio_return > 0.0 for item in equity_down), len(equity_down)
    )
    participation_rate = _rate(
        sum(item.positive_rotation_action_taken for item in deployment), len(deployment)
    )
    derisk_rate = _rate(
        sum(item.derisk_action_taken for item in deterioration),
        len(deterioration),
        empty=1.0,
    )
    unexplained_rate = _rate(len(unexplained), len(deployment))
    selected = tuple(
        float(item.selected_rotation_return)
        for item in values
        if item.selected_rotation_return is not None
    )
    strongest = tuple(
        float(item.strongest_leadership_return)
        for item in values
        if item.strongest_leadership_return is not None
    )
    gates = (
        ("point_in_time_integrity", pit),
        ("observation_count", len(values) >= resolved.minimum_observations),
        ("equity_down_sample", len(equity_down) >= resolved.minimum_equity_down_observations),
        ("deployment_opportunity_sample", len(deployment) >= resolved.minimum_deployment_opportunities),
        ("leadership_participation", participation_rate >= resolved.minimum_leadership_participation_rate),
        ("derisk_response", derisk_rate >= resolved.minimum_derisk_response_rate),
        ("unexplained_cash", unexplained_rate <= resolved.maximum_unexplained_cash_rate),
        (
            "positive_equity_down_return",
            positive_down_rate >= resolved.minimum_positive_return_rate_during_equity_down_periods,
        ),
    )
    return GlobalRotationCertificationReport(
        as_of=as_of,
        observation_count=len(values),
        point_in_time_valid=pit,
        equity_down_observation_count=len(equity_down),
        positive_return_rate_during_equity_down_periods=positive_down_rate,
        mean_portfolio_return_during_equity_down_periods=(
            0.0 if not equity_down else fmean(item.portfolio_return for item in equity_down)
        ),
        deployment_opportunity_count=len(deployment),
        leadership_participation_rate=participation_rate,
        deteriorating_holding_count=len(deterioration),
        derisk_response_rate=derisk_rate,
        unexplained_cash_count=len(unexplained),
        unexplained_cash_rate=unexplained_rate,
        mean_excess_cash_when_unexplained=(
            0.0 if not unexplained else fmean(item.excess_starting_cash for item in unexplained)
        ),
        mean_selected_rotation_return=None if not selected else fmean(selected),
        mean_strongest_leadership_return=None if not strongest else fmean(strongest),
        gates=gates,
        rotation_behavior_certified=all(passed for _name, passed in gates),
    )


__all__ = [
    "GlobalRotationCertificationPolicy",
    "GlobalRotationCertificationReport",
    "GlobalRotationOutcomeObservation",
    "build_global_rotation_certification",
]
