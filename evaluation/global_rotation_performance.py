"""Walk-forward performance certification for the global rotation objective.

This module evaluates realized portfolio behavior only after outcomes are known. It
cannot change policy automatically, authorize capital, or make benchmark-relative
investment decisions. The primary objective is after-cost terminal portfolio wealth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class RotationPerformanceObservation:
    identifier: str
    decision_as_of: datetime
    outcome_observed_at: datetime
    regime: str
    portfolio_return_after_cost: float
    transaction_cost_return: float
    turnover: float
    ending_cash_weight: float
    selected_domain: str | None
    strongest_realized_domain: str | None
    selected_rotation_return: float | None
    strongest_available_return: float | None
    equity_market_return: float
    emerging_leadership_identified: bool
    leadership_lead_days: float | None
    false_rotation: bool
    causal_transition_nominated: bool
    causal_transition_realized: bool
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.regime.strip():
            raise ValueError("identifier and regime cannot be empty")
        for value in (self.decision_as_of, self.outcome_observed_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("performance timestamps must be timezone-aware")
        if self.outcome_observed_at <= self.decision_as_of:
            raise ValueError("outcome must be observed after the decision")
        for name in (
            "portfolio_return_after_cost",
            "transaction_cost_return",
            "turnover",
            "ending_cash_weight",
            "equity_market_return",
        ):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.turnover <= 5.0:
            raise ValueError("turnover must be between zero and five times portfolio value")
        if not 0.0 <= self.ending_cash_weight <= 1.0:
            raise ValueError("ending_cash_weight must be between zero and one")
        if self.leadership_lead_days is not None and not isfinite(float(self.leadership_lead_days)):
            raise ValueError("leadership_lead_days must be finite or None")
        if not self.evidence_identifiers:
            raise ValueError("performance observations require evidence lineage")


@dataclass(frozen=True, slots=True)
class GlobalRotationPerformancePolicy:
    minimum_observations: int = 100
    minimum_regimes: int = 5
    maximum_false_rotation_rate: float = 0.30
    maximum_mean_cash_weight: float = 0.55
    minimum_causal_transition_hit_rate: float = 0.50
    minimum_leadership_capture_ratio: float = 0.45
    maximum_empirical_expected_shortfall: float = -0.20


@dataclass(frozen=True, slots=True)
class GlobalRotationPerformanceReport:
    as_of: datetime
    observation_count: int
    regime_count: int
    terminal_wealth_multiple: float
    annualized_compound_return: float | None
    maximum_drawdown: float
    empirical_expected_shortfall: float
    mean_turnover: float
    mean_transaction_cost_return: float
    mean_cash_weight: float
    mean_return_during_equity_contractions: float
    positive_return_rate_during_equity_contractions: float
    false_rotation_rate: float
    leadership_capture_ratio: float | None
    mean_leadership_lead_days: float | None
    causal_transition_hit_rate: float
    domain_returns: tuple[tuple[str, float], ...]
    regime_returns: tuple[tuple[str, float], ...]
    gates: tuple[tuple[str, bool], ...]
    performance_behavior_certified: bool
    performance_claim_authorized: bool = False
    policy_change_authorized: bool = False
    investment_authority: bool = False
    schema_version: str = "global-rotation-performance.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "observation_count": self.observation_count,
            "regime_count": self.regime_count,
            "terminal_wealth_multiple": self.terminal_wealth_multiple,
            "annualized_compound_return": self.annualized_compound_return,
            "maximum_drawdown": self.maximum_drawdown,
            "empirical_expected_shortfall": self.empirical_expected_shortfall,
            "mean_turnover": self.mean_turnover,
            "mean_transaction_cost_return": self.mean_transaction_cost_return,
            "mean_cash_weight": self.mean_cash_weight,
            "mean_return_during_equity_contractions": self.mean_return_during_equity_contractions,
            "positive_return_rate_during_equity_contractions": self.positive_return_rate_during_equity_contractions,
            "false_rotation_rate": self.false_rotation_rate,
            "leadership_capture_ratio": self.leadership_capture_ratio,
            "mean_leadership_lead_days": self.mean_leadership_lead_days,
            "causal_transition_hit_rate": self.causal_transition_hit_rate,
            "domain_returns": [list(item) for item in self.domain_returns],
            "regime_returns": [list(item) for item in self.regime_returns],
            "gates": [list(item) for item in self.gates],
            "performance_behavior_certified": self.performance_behavior_certified,
            "performance_claim_authorized": False,
            "policy_change_authorized": False,
            "investment_authority": False,
            "schema_version": self.schema_version,
        }


def _compound(values: Iterable[float]) -> float:
    wealth = 1.0
    for value in values:
        wealth *= max(0.0, 1.0 + float(value))
    return wealth


def _maximum_drawdown(values: tuple[float, ...]) -> float:
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        wealth *= max(0.0, 1.0 + value)
        peak = max(peak, wealth)
        if peak > 0.0:
            worst = min(worst, wealth / peak - 1.0)
    return worst


def _expected_shortfall(values: tuple[float, ...], tail_fraction: float = 0.10) -> float:
    if not values:
        return 0.0
    count = max(1, int(round(len(values) * tail_fraction)))
    return fmean(sorted(values)[:count])


def build_global_rotation_performance_report(
    *,
    observations: Iterable[RotationPerformanceObservation],
    as_of: datetime,
    policy: GlobalRotationPerformancePolicy | None = None,
) -> GlobalRotationPerformanceReport:
    values = tuple(sorted(observations, key=lambda item: item.decision_as_of))
    resolved = policy or GlobalRotationPerformancePolicy()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if any(item.outcome_observed_at > as_of for item in values):
        raise ValueError("performance outcome cannot be known after report as_of")

    returns = tuple(float(item.portfolio_return_after_cost) for item in values)
    wealth = _compound(returns)
    annualized = None
    if values:
        years = (values[-1].outcome_observed_at - values[0].decision_as_of).total_seconds() / (365.25 * 86400.0)
        if years > 0.0 and wealth > 0.0:
            annualized = wealth ** (1.0 / years) - 1.0
    equity_down = tuple(item for item in values if item.equity_market_return < 0.0)
    contractions_return = 0.0 if not equity_down else fmean(item.portfolio_return_after_cost for item in equity_down)
    contractions_positive = 0.0 if not equity_down else sum(item.portfolio_return_after_cost > 0.0 for item in equity_down) / len(equity_down)
    false_rate = 0.0 if not values else sum(item.false_rotation for item in values) / len(values)
    causal = tuple(item for item in values if item.causal_transition_nominated)
    causal_hit = 1.0 if not causal else sum(item.causal_transition_realized for item in causal) / len(causal)
    paired = tuple(
        item for item in values
        if item.selected_rotation_return is not None and item.strongest_available_return is not None
    )
    selected_total = sum(max(0.0, float(item.selected_rotation_return)) for item in paired)
    strongest_total = sum(max(0.0, float(item.strongest_available_return)) for item in paired)
    capture = None if strongest_total <= 1e-12 else min(1.0, selected_total / strongest_total)
    leads = tuple(
        float(item.leadership_lead_days)
        for item in values
        if item.emerging_leadership_identified and item.leadership_lead_days is not None
    )

    domain_group: dict[str, list[float]] = {}
    regime_group: dict[str, list[float]] = {}
    for item in values:
        if item.selected_domain:
            domain_group.setdefault(item.selected_domain, []).append(item.portfolio_return_after_cost)
        regime_group.setdefault(item.regime, []).append(item.portfolio_return_after_cost)
    domain_returns = tuple(sorted((key, fmean(items)) for key, items in domain_group.items()))
    regime_returns = tuple(sorted((key, fmean(items)) for key, items in regime_group.items()))
    mean_cash = 1.0 if not values else fmean(item.ending_cash_weight for item in values)
    empirical_es = _expected_shortfall(returns)
    gates = (
        ("observation_count", len(values) >= resolved.minimum_observations),
        ("regime_breadth", len(regime_group) >= resolved.minimum_regimes),
        ("terminal_wealth_positive", wealth > 1.0),
        ("false_rotation_control", false_rate <= resolved.maximum_false_rotation_rate),
        ("cash_not_structurally_dominant", mean_cash <= resolved.maximum_mean_cash_weight),
        ("causal_transition_learning", causal_hit >= resolved.minimum_causal_transition_hit_rate),
        (
            "leadership_capture",
            capture is not None and capture >= resolved.minimum_leadership_capture_ratio,
        ),
        (
            "tail_loss_control",
            empirical_es >= resolved.maximum_empirical_expected_shortfall,
        ),
    )
    return GlobalRotationPerformanceReport(
        as_of=as_of,
        observation_count=len(values),
        regime_count=len(regime_group),
        terminal_wealth_multiple=round(wealth, 8),
        annualized_compound_return=None if annualized is None else round(annualized, 8),
        maximum_drawdown=round(_maximum_drawdown(returns), 8),
        empirical_expected_shortfall=round(empirical_es, 8),
        mean_turnover=0.0 if not values else round(fmean(item.turnover for item in values), 8),
        mean_transaction_cost_return=0.0 if not values else round(fmean(item.transaction_cost_return for item in values), 8),
        mean_cash_weight=round(mean_cash, 8),
        mean_return_during_equity_contractions=round(contractions_return, 8),
        positive_return_rate_during_equity_contractions=round(contractions_positive, 8),
        false_rotation_rate=round(false_rate, 8),
        leadership_capture_ratio=None if capture is None else round(capture, 8),
        mean_leadership_lead_days=None if not leads else round(fmean(leads), 8),
        causal_transition_hit_rate=round(causal_hit, 8),
        domain_returns=domain_returns,
        regime_returns=regime_returns,
        gates=gates,
        performance_behavior_certified=all(passed for _name, passed in gates),
    )


__all__ = [
    "GlobalRotationPerformancePolicy",
    "GlobalRotationPerformanceReport",
    "RotationPerformanceObservation",
    "build_global_rotation_performance_report",
]
