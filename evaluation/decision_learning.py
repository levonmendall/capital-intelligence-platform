"""Statistically cautious learning from completed point-in-time decisions.

This module converts already-matured, out-of-sample decision outcomes into a
version-specific governance report.  It measures calibration, regret, net value
added, implementation drag, drawdown, regime breadth, and multiple-testing risk.
It can recommend review, watch, or suspension, but it cannot change a model,
policy, portfolio, or execution authority automatically.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite, log, sqrt
from statistics import NormalDist, mean, median, stdev
from typing import Any


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return normalized


class DecisionLearningState(str, Enum):
    """Governance state for one immutable model and decision-policy version."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RETAIN = "retain"
    WATCH = "watch"
    SUSPEND = "suspend"
    ELIGIBLE_FOR_GOVERNANCE_REVIEW = "eligible_for_governance_review"


@dataclass(frozen=True, slots=True)
class DecisionLearningObservation:
    """One matured out-of-sample decision outcome."""

    identifier: str
    decision_identifier: str
    evaluation_identifier: str
    model_version: str
    decision_policy_version: str
    asset_class: str
    market_regime: str
    decision_at: datetime
    evaluated_at: datetime
    horizon_days: int
    forecast_probability: float
    realized_success: bool
    value_added_vs_best_alternative: float
    value_added_vs_cash: float
    implementation_cost_return: float
    maximum_drawdown: float
    candidate_count_considered: int
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "evaluation_identifier",
            "model_version",
            "decision_policy_version",
            "asset_class",
            "market_regime",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.decision_at, field_name="decision_at")
        _aware(self.evaluated_at, field_name="evaluated_at")
        if isinstance(self.horizon_days, bool) or not isinstance(
            self.horizon_days,
            int,
        ):
            raise TypeError("horizon_days must be an integer")
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be positive")
        if self.evaluated_at < self.decision_at + timedelta(days=self.horizon_days):
            raise ValueError(
                "evaluated_at cannot predate the complete decision horizon"
            )
        object.__setattr__(
            self,
            "forecast_probability",
            _finite(
                self.forecast_probability,
                field_name="forecast_probability",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if not isinstance(self.realized_success, bool):
            raise TypeError("realized_success must be a bool")
        for field_name in (
            "value_added_vs_best_alternative",
            "value_added_vs_cash",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "implementation_cost_return",
            _finite(
                self.implementation_cost_return,
                field_name="implementation_cost_return",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "maximum_drawdown",
            _finite(
                self.maximum_drawdown,
                field_name="maximum_drawdown",
                minimum=-1.0,
                maximum=0.0,
            ),
        )
        if isinstance(self.candidate_count_considered, bool) or not isinstance(
            self.candidate_count_considered,
            int,
        ):
            raise TypeError("candidate_count_considered must be an integer")
        if self.candidate_count_considered < 1:
            raise ValueError("candidate_count_considered must be positive")
        if not isinstance(self.evidence_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.evidence_identifiers
        ):
            raise TypeError("evidence_identifiers must contain non-empty strings")
        if not self.evidence_identifiers:
            raise ValueError("evidence_identifiers cannot be empty")
        if len(self.evidence_identifiers) != len(set(self.evidence_identifiers)):
            raise ValueError("evidence_identifiers cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class DecisionLearningPolicy:
    """Minimum evidence required before a model version may be promoted."""

    version: str = "decision-learning.v1"
    minimum_observations: int = 30
    minimum_regimes: int = 2
    minimum_asset_classes: int = 2
    minimum_observation_span_days: int = 180
    maximum_brier_score: float = 0.24
    maximum_log_loss: float = 0.70
    maximum_absolute_calibration_gap: float = 0.10
    minimum_mean_value_added: float = 0.0
    minimum_median_value_added: float = 0.0
    minimum_adjusted_lower_bound_value_added: float = 0.0
    minimum_posterior_success_lower_bound: float = 0.50
    maximum_mean_implementation_cost: float = 0.02
    minimum_acceptable_drawdown: float = -0.50
    significance_alpha: float = 0.05
    material_failure_value_added: float = -0.01
    material_calibration_excess: float = 0.10

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "minimum_observations",
            "minimum_regimes",
            "minimum_asset_classes",
            "minimum_observation_span_days",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        for field_name in (
            "maximum_brier_score",
            "maximum_log_loss",
            "maximum_absolute_calibration_gap",
            "minimum_posterior_success_lower_bound",
            "maximum_mean_implementation_cost",
            "significance_alpha",
            "material_calibration_excess",
        ):
            value = _finite(getattr(self, field_name), field_name=field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if self.significance_alpha <= 0.0:
            raise ValueError("significance_alpha must be positive")
        if not -1.0 <= self.minimum_acceptable_drawdown <= 0.0:
            raise ValueError(
                "minimum_acceptable_drawdown must be between -1.0 and 0.0"
            )


@dataclass(frozen=True, slots=True)
class DecisionLearningReport:
    """Deterministic governance report for one model/policy version pair."""

    identifier: str
    generated_at: datetime
    model_version: str
    decision_policy_version: str
    learning_policy_version: str
    state: DecisionLearningState
    observation_count: int
    regime_count: int
    asset_class_count: int
    observation_span_days: int
    effective_selection_trials: int
    success_rate: float
    posterior_success_mean: float
    posterior_success_lower_bound: float
    brier_score: float
    log_loss: float
    calibration_gap: float
    mean_value_added_vs_best_alternative: float
    median_value_added_vs_best_alternative: float
    adjusted_lower_bound_value_added: float
    mean_value_added_vs_cash: float
    mean_implementation_cost: float
    worst_drawdown: float
    reasons: tuple[str, ...]
    automatic_model_change: bool = False
    real_money_authorized: bool = False
    performance_claims_permitted: bool = False

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(include_fingerprint=False),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        payload["state"] = self.state.value
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


class DecisionLearningEvaluator:
    """Evaluate whether outcomes justify retain, watch, suspend, or review."""

    def __init__(self, policy: DecisionLearningPolicy | None = None) -> None:
        self.policy = policy or DecisionLearningPolicy()

    def evaluate(
        self,
        observations: tuple[DecisionLearningObservation, ...],
        *,
        generated_at: datetime,
    ) -> DecisionLearningReport:
        if not isinstance(observations, tuple) or not all(
            isinstance(item, DecisionLearningObservation) for item in observations
        ):
            raise TypeError(
                "observations must be a tuple of DecisionLearningObservation values"
            )
        if not observations:
            raise ValueError("at least one matured observation is required")
        generated = _aware(generated_at, field_name="generated_at")
        identifiers = tuple(item.identifier for item in observations)
        decision_ids = tuple(item.decision_identifier for item in observations)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("observation identifiers must be unique")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("each decision may appear only once")
        model_versions = {item.model_version for item in observations}
        policy_versions = {item.decision_policy_version for item in observations}
        if len(model_versions) != 1:
            raise ValueError("one report cannot mix model versions")
        if len(policy_versions) != 1:
            raise ValueError("one report cannot mix decision-policy versions")
        if any(item.evaluated_at > generated for item in observations):
            raise ValueError("generated_at cannot predate an evaluation")

        ordered = tuple(sorted(observations, key=lambda item: item.decision_at))
        count = len(ordered)
        regimes = {item.market_regime for item in ordered}
        asset_classes = {item.asset_class for item in ordered}
        span_days = (ordered[-1].evaluated_at - ordered[0].decision_at).days
        effective_trials = max(item.candidate_count_considered for item in ordered)
        outcomes = [1.0 if item.realized_success else 0.0 for item in ordered]
        probabilities = [
            min(max(item.forecast_probability, 0.000001), 0.999999)
            for item in ordered
        ]
        value_added = [item.value_added_vs_best_alternative for item in ordered]
        value_added_cash = [item.value_added_vs_cash for item in ordered]
        costs = [item.implementation_cost_return for item in ordered]
        drawdowns = [item.maximum_drawdown for item in ordered]

        success_rate = mean(outcomes)
        brier = mean(
            (probability - outcome) ** 2
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        )
        log_loss_value = -mean(
            outcome * log(probability) + (1.0 - outcome) * log(1.0 - probability)
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        )
        calibration_gap = mean(probabilities) - success_rate
        posterior_alpha = 1.0 + sum(outcomes)
        posterior_beta = 1.0 + count - sum(outcomes)
        posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
        posterior_variance = (
            posterior_alpha
            * posterior_beta
            / (
                (posterior_alpha + posterior_beta) ** 2
                * (posterior_alpha + posterior_beta + 1.0)
            )
        )
        posterior_lower = max(
            0.0,
            posterior_mean - 1.6448536269514722 * sqrt(posterior_variance),
        )
        mean_value = mean(value_added)
        median_value = median(value_added)
        if count > 1:
            standard_error = stdev(value_added) / sqrt(count)
        else:
            standard_error = float("inf")
        adjusted_alpha = self.policy.significance_alpha / max(effective_trials, 1)
        adjusted_z = NormalDist().inv_cdf(1.0 - adjusted_alpha)
        adjusted_lower = (
            mean_value - adjusted_z * standard_error
            if isfinite(standard_error)
            else float("-inf")
        )
        mean_cash = mean(value_added_cash)
        mean_cost = mean(costs)
        worst_drawdown = min(drawdowns)

        evidence_reasons: list[str] = []
        if count < self.policy.minimum_observations:
            evidence_reasons.append("observation count is below the minimum")
        if len(regimes) < self.policy.minimum_regimes:
            evidence_reasons.append("market-regime coverage is below the minimum")
        if len(asset_classes) < self.policy.minimum_asset_classes:
            evidence_reasons.append("asset-class coverage is below the minimum")
        if span_days < self.policy.minimum_observation_span_days:
            evidence_reasons.append("out-of-sample observation span is too short")

        performance_reasons: list[str] = []
        if brier > self.policy.maximum_brier_score:
            performance_reasons.append("Brier score exceeds policy")
        if log_loss_value > self.policy.maximum_log_loss:
            performance_reasons.append("log loss exceeds policy")
        if abs(calibration_gap) > self.policy.maximum_absolute_calibration_gap:
            performance_reasons.append("forecast calibration gap exceeds policy")
        if mean_value < self.policy.minimum_mean_value_added:
            performance_reasons.append(
                "mean net value added versus the best original alternative is insufficient"
            )
        if median_value < self.policy.minimum_median_value_added:
            performance_reasons.append(
                "median net value added versus the best original alternative is insufficient"
            )
        if adjusted_lower < self.policy.minimum_adjusted_lower_bound_value_added:
            performance_reasons.append(
                "multiple-testing-adjusted lower bound on value added is insufficient"
            )
        if posterior_lower < self.policy.minimum_posterior_success_lower_bound:
            performance_reasons.append(
                "posterior lower bound on decision success is insufficient"
            )
        if mean_cost > self.policy.maximum_mean_implementation_cost:
            performance_reasons.append("mean implementation cost exceeds policy")
        if worst_drawdown < self.policy.minimum_acceptable_drawdown:
            performance_reasons.append("realized drawdown exceeds policy")

        material_failure = (
            mean_value < self.policy.material_failure_value_added
            or brier
            > self.policy.maximum_brier_score
            + self.policy.material_calibration_excess
            or abs(calibration_gap)
            > self.policy.maximum_absolute_calibration_gap
            + self.policy.material_calibration_excess
            or worst_drawdown < self.policy.minimum_acceptable_drawdown
        )
        if evidence_reasons:
            state = DecisionLearningState.INSUFFICIENT_EVIDENCE
            reasons = tuple(evidence_reasons + performance_reasons)
        elif material_failure:
            state = DecisionLearningState.SUSPEND
            reasons = tuple(performance_reasons or ("material outcome failure",))
        elif performance_reasons:
            state = DecisionLearningState.WATCH
            reasons = tuple(performance_reasons)
        else:
            state = DecisionLearningState.ELIGIBLE_FOR_GOVERNANCE_REVIEW
            reasons = (
                "out-of-sample calibration, value-added, implementation, drawdown, breadth, and selection-bias gates passed; human governance review is still required",
            )

        model_version = next(iter(model_versions))
        decision_policy_version = next(iter(policy_versions))
        return DecisionLearningReport(
            identifier=(
                f"decision-learning:{model_version}:{decision_policy_version}:"
                f"{generated.isoformat()}"
            ),
            generated_at=generated,
            model_version=model_version,
            decision_policy_version=decision_policy_version,
            learning_policy_version=self.policy.version,
            state=state,
            observation_count=count,
            regime_count=len(regimes),
            asset_class_count=len(asset_classes),
            observation_span_days=span_days,
            effective_selection_trials=effective_trials,
            success_rate=round(success_rate, 10),
            posterior_success_mean=round(posterior_mean, 10),
            posterior_success_lower_bound=round(posterior_lower, 10),
            brier_score=round(brier, 10),
            log_loss=round(log_loss_value, 10),
            calibration_gap=round(calibration_gap, 10),
            mean_value_added_vs_best_alternative=round(mean_value, 10),
            median_value_added_vs_best_alternative=round(median_value, 10),
            adjusted_lower_bound_value_added=round(adjusted_lower, 10),
            mean_value_added_vs_cash=round(mean_cash, 10),
            mean_implementation_cost=round(mean_cost, 10),
            worst_drawdown=round(worst_drawdown, 10),
            reasons=reasons,
        )


__all__ = [
    "DecisionLearningEvaluator",
    "DecisionLearningObservation",
    "DecisionLearningPolicy",
    "DecisionLearningReport",
    "DecisionLearningState",
]
