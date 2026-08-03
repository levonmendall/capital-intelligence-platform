"""Research-only attribution of value and regret to governed decision stages.

The analyzer consumes immutable point-in-time snapshots and completed evaluations.
It does not reconstruct decisions, change policy, promote models, size portfolios, or
authorize execution. Exact portfolio contribution is reported only for the
selection, sizing, timing, and implementation-cost components already reconciled
by :class:`PointInTimeDecisionEvaluation`. Veto and abstention stages are reported
as realized return spreads because no counterfactual portfolio weight is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any

from cio import CIOAction
from evaluation.point_in_time import (
    DecisionEvidenceSnapshot,
    EvaluationOutcome,
    PointInTimeDecisionEvaluation,
)


class GateContributionStage(str, Enum):
    """Governed stage whose realized effect is being measured."""

    EVIDENCE_VETO = "evidence_veto"
    IMPLEMENTATION_BLOCK = "implementation_block"
    CIO_ABSTENTION = "cio_abstention"
    CIO_SELECTION = "cio_selection"
    CONSTRUCTION_SIZING = "construction_sizing"
    IMPLEMENTATION_TIMING = "implementation_timing"
    IMPLEMENTATION_COST = "implementation_cost"


class GateContributionEffect(str, Enum):
    """Ex-post effect classification without changing the original decision."""

    PROTECTED_CAPITAL = "protected_capital"
    COSTLY_RESTRAINT = "costly_restraint"
    ADDED_VALUE = "added_value"
    DESTROYED_VALUE = "destroyed_value"
    NEUTRAL = "neutral"


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return round(normalized, 10)


def _positive_int(value: object, *, field_name: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be {qualifier}")
    return value


@dataclass(frozen=True, slots=True)
class GateContributionObservation:
    """One decision-stage observation.

    ``exact_portfolio_contribution`` is populated only when the existing
    point-in-time evaluator provides an exactly reconciled portfolio component.
    Veto and abstention observations instead use ``realized_return_spread``.
    """

    decision_identifier: str
    snapshot_identifier: str
    evaluation_identifier: str
    stage: GateContributionStage
    effect: GateContributionEffect
    exact_portfolio_contribution: float | None
    realized_return_spread: float | None
    constrained_weight: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "decision_identifier",
            "snapshot_identifier",
            "evaluation_identifier",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.stage, GateContributionStage):
            raise TypeError("stage must be GateContributionStage")
        if not isinstance(self.effect, GateContributionEffect):
            raise TypeError("effect must be GateContributionEffect")
        for field_name in (
            "exact_portfolio_contribution",
            "realized_return_spread",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _finite(value, field_name=field_name),
                )
        object.__setattr__(
            self,
            "constrained_weight",
            _finite(self.constrained_weight, field_name="constrained_weight"),
        )
        if not 0.0 <= self.constrained_weight <= 1.0:
            raise ValueError("constrained_weight must be between 0 and 1")
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("reasons must contain at least one explanation")
        if not all(isinstance(item, str) and item.strip() for item in self.reasons):
            raise TypeError("reasons must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_identifier": self.decision_identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "evaluation_identifier": self.evaluation_identifier,
            "stage": self.stage.value,
            "effect": self.effect.value,
            "exact_portfolio_contribution": self.exact_portfolio_contribution,
            "realized_return_spread": self.realized_return_spread,
            "constrained_weight": self.constrained_weight,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class GateContributionMetric:
    stage: GateContributionStage
    activation_count: int
    protected_count: int
    costly_count: int
    added_value_count: int
    destroyed_value_count: int
    neutral_count: int
    exact_portfolio_contribution: float
    mean_realized_return_spread: float | None
    constrained_weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.stage, GateContributionStage):
            raise TypeError("stage must be GateContributionStage")
        for field_name in (
            "activation_count",
            "protected_count",
            "costly_count",
            "added_value_count",
            "destroyed_value_count",
            "neutral_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _positive_int(
                    getattr(self, field_name),
                    field_name=field_name,
                    allow_zero=field_name != "activation_count",
                ),
            )
        classified = (
            self.protected_count
            + self.costly_count
            + self.added_value_count
            + self.destroyed_value_count
            + self.neutral_count
        )
        if classified != self.activation_count:
            raise ValueError("effect counts must reconcile to activation_count")
        object.__setattr__(
            self,
            "exact_portfolio_contribution",
            _finite(
                self.exact_portfolio_contribution,
                field_name="exact_portfolio_contribution",
            ),
        )
        if self.mean_realized_return_spread is not None:
            object.__setattr__(
                self,
                "mean_realized_return_spread",
                _finite(
                    self.mean_realized_return_spread,
                    field_name="mean_realized_return_spread",
                ),
            )
        object.__setattr__(
            self,
            "constrained_weight",
            _finite(self.constrained_weight, field_name="constrained_weight"),
        )
        if self.constrained_weight < 0.0:
            raise ValueError("constrained_weight cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "activation_count": self.activation_count,
            "protected_count": self.protected_count,
            "costly_count": self.costly_count,
            "added_value_count": self.added_value_count,
            "destroyed_value_count": self.destroyed_value_count,
            "neutral_count": self.neutral_count,
            "exact_portfolio_contribution": self.exact_portfolio_contribution,
            "mean_realized_return_spread": self.mean_realized_return_spread,
            "constrained_weight": self.constrained_weight,
        }


@dataclass(frozen=True, slots=True)
class GateContributionReport:
    as_of: datetime
    decision_count: int
    observation_count: int
    total_net_active_contribution: float
    reconciled_exact_contribution: float
    metrics: tuple[GateContributionMetric, ...]
    observations: tuple[GateContributionObservation, ...]
    policy_version: str = "gate-contribution-analysis.v1"
    research_only: bool = True
    automatic_policy_change: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "decision_count",
            _positive_int(self.decision_count, field_name="decision_count"),
        )
        object.__setattr__(
            self,
            "observation_count",
            _positive_int(self.observation_count, field_name="observation_count"),
        )
        for field_name in (
            "total_net_active_contribution",
            "reconciled_exact_contribution",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        if abs(
            self.total_net_active_contribution
            - self.reconciled_exact_contribution
        ) > 0.0000001:
            raise ValueError(
                "exact gate contributions must reconcile to net active contribution"
            )
        if not isinstance(self.metrics, tuple) or not self.metrics:
            raise ValueError("metrics must contain at least one stage")
        if not all(isinstance(item, GateContributionMetric) for item in self.metrics):
            raise TypeError("metrics must contain GateContributionMetric values")
        stages = tuple(item.stage for item in self.metrics)
        if len(stages) != len(set(stages)):
            raise ValueError("gate contribution metric stages must be unique")
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, GateContributionObservation)
            for item in self.observations
        ):
            raise TypeError(
                "observations must contain GateContributionObservation values"
            )
        if len(self.observations) != self.observation_count:
            raise ValueError("observation_count must match observations")
        if sum(item.activation_count for item in self.metrics) != self.observation_count:
            raise ValueError("metric activations must reconcile to observation_count")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not self.research_only:
            raise ValueError("gate contribution analysis must remain research-only")
        if self.automatic_policy_change:
            raise ValueError("gate contribution analysis cannot change policy")
        if self.execution_authority:
            raise ValueError("gate contribution analysis cannot authorize execution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "decision_count": self.decision_count,
            "observation_count": self.observation_count,
            "total_net_active_contribution": self.total_net_active_contribution,
            "reconciled_exact_contribution": self.reconciled_exact_contribution,
            "metrics": [item.to_dict() for item in self.metrics],
            "observations": [item.to_dict() for item in self.observations],
            "policy_version": self.policy_version,
            "research_only": self.research_only,
            "automatic_policy_change": self.automatic_policy_change,
            "execution_authority": self.execution_authority,
        }


class GateContributionAnalyzer:
    """Aggregate exact attribution and gate outcomes across matured decisions."""

    _ABSTENTION_ACTIONS = {
        CIOAction.WATCH,
        CIOAction.INSUFFICIENT_EVIDENCE,
        CIOAction.NO_SUPERIOR_OPPORTUNITY,
        CIOAction.NO_MATERIAL_CHANGE,
    }
    _PROTECTED_OUTCOMES = {
        EvaluationOutcome.CORRECT_ABSTENTION,
        EvaluationOutcome.AVOIDED_LOSS,
        EvaluationOutcome.INSUFFICIENT_EVIDENCE_CONFIRMED,
    }
    _COSTLY_OUTCOMES = {
        EvaluationOutcome.MISSED_OPPORTUNITY,
        EvaluationOutcome.IMPLEMENTATION_BLOCK_COSTLY,
    }

    def __init__(self, *, flat_tolerance: float = 0.000001) -> None:
        self.flat_tolerance = abs(
            _finite(flat_tolerance, field_name="flat_tolerance")
        )

    def analyze(
        self,
        pairs: tuple[
            tuple[DecisionEvidenceSnapshot, PointInTimeDecisionEvaluation], ...
        ],
        *,
        as_of: datetime,
    ) -> GateContributionReport:
        _aware(as_of, field_name="as_of")
        if not isinstance(pairs, tuple) or not pairs:
            raise ValueError("gate contribution analysis requires completed pairs")
        decision_ids: set[str] = set()
        observations: list[GateContributionObservation] = []
        total_net = 0.0
        for snapshot, evaluation in pairs:
            if not isinstance(snapshot, DecisionEvidenceSnapshot):
                raise TypeError("pair snapshots must be DecisionEvidenceSnapshot values")
            if not isinstance(evaluation, PointInTimeDecisionEvaluation):
                raise TypeError(
                    "pair evaluations must be PointInTimeDecisionEvaluation values"
                )
            if evaluation.snapshot_identifier != snapshot.identifier:
                raise ValueError("snapshot and evaluation identifiers do not match")
            if snapshot.decision_identifier in decision_ids:
                raise ValueError("each decision may appear only once")
            if evaluation.evaluated_at > as_of:
                raise ValueError("as_of cannot predate a completed evaluation")
            decision_ids.add(snapshot.decision_identifier)
            total_net += evaluation.attribution.net_active_contribution
            observations.extend(self._observations(snapshot, evaluation))
        exact_total = sum(
            item.exact_portfolio_contribution or 0.0 for item in observations
        )
        metrics = self._metrics(tuple(observations))
        return GateContributionReport(
            as_of=as_of,
            decision_count=len(decision_ids),
            observation_count=len(observations),
            total_net_active_contribution=total_net,
            reconciled_exact_contribution=exact_total,
            metrics=metrics,
            observations=tuple(observations),
        )

    def _observations(
        self,
        snapshot: DecisionEvidenceSnapshot,
        evaluation: PointInTimeDecisionEvaluation,
    ) -> tuple[GateContributionObservation, ...]:
        values: list[GateContributionObservation] = []
        exact = (
            (
                GateContributionStage.CIO_SELECTION,
                evaluation.attribution.selection,
                "CIO candidate selection versus the best original capital alternative",
            ),
            (
                GateContributionStage.CONSTRUCTION_SIZING,
                evaluation.attribution.sizing,
                "difference between the CIO-recommended and constructed position weight",
            ),
            (
                GateContributionStage.IMPLEMENTATION_TIMING,
                evaluation.attribution.timing,
                "difference between decision-time and implementation-time return",
            ),
            (
                GateContributionStage.IMPLEMENTATION_COST,
                evaluation.attribution.implementation_cost,
                "realized implementation cost and slippage",
            ),
        )
        recommended = (
            snapshot.current_portfolio_weight
            if snapshot.recommended_position_weight is None
            else snapshot.recommended_position_weight
        )
        constrained_weight = abs(
            snapshot.implemented_position_weight - recommended
        )
        for stage, contribution, reason in exact:
            stage_weight = (
                constrained_weight
                if stage is GateContributionStage.CONSTRUCTION_SIZING
                else snapshot.implemented_position_weight
            )
            values.append(
                GateContributionObservation(
                    decision_identifier=snapshot.decision_identifier,
                    snapshot_identifier=snapshot.identifier,
                    evaluation_identifier=evaluation.identifier,
                    stage=stage,
                    effect=self._exact_effect(contribution),
                    exact_portfolio_contribution=contribution,
                    realized_return_spread=None,
                    constrained_weight=stage_weight,
                    reasons=(reason,),
                )
            )

        spread = evaluation.best_original_alternative_return - evaluation.candidate_return
        if snapshot.evidence_vetoes:
            values.append(
                GateContributionObservation(
                    decision_identifier=snapshot.decision_identifier,
                    snapshot_identifier=snapshot.identifier,
                    evaluation_identifier=evaluation.identifier,
                    stage=GateContributionStage.EVIDENCE_VETO,
                    effect=self._restraint_effect(evaluation.outcome, spread),
                    exact_portfolio_contribution=None,
                    realized_return_spread=spread,
                    constrained_weight=max(
                        recommended - snapshot.implemented_position_weight, 0.0
                    ),
                    reasons=tuple(snapshot.evidence_vetoes),
                )
            )
        if snapshot.implementation_blocks:
            values.append(
                GateContributionObservation(
                    decision_identifier=snapshot.decision_identifier,
                    snapshot_identifier=snapshot.identifier,
                    evaluation_identifier=evaluation.identifier,
                    stage=GateContributionStage.IMPLEMENTATION_BLOCK,
                    effect=self._restraint_effect(evaluation.outcome, spread),
                    exact_portfolio_contribution=None,
                    realized_return_spread=spread,
                    constrained_weight=max(
                        recommended - snapshot.implemented_position_weight, 0.0
                    ),
                    reasons=tuple(snapshot.implementation_blocks),
                )
            )
        if (
            snapshot.action in self._ABSTENTION_ACTIONS
            and snapshot.implemented_position_weight
            <= snapshot.current_portfolio_weight + self.flat_tolerance
        ):
            values.append(
                GateContributionObservation(
                    decision_identifier=snapshot.decision_identifier,
                    snapshot_identifier=snapshot.identifier,
                    evaluation_identifier=evaluation.identifier,
                    stage=GateContributionStage.CIO_ABSTENTION,
                    effect=self._restraint_effect(evaluation.outcome, spread),
                    exact_portfolio_contribution=None,
                    realized_return_spread=spread,
                    constrained_weight=0.0,
                    reasons=(
                        f"CIO action={snapshot.action.value}",
                        f"evaluation outcome={evaluation.outcome.value}",
                    ),
                )
            )
        return tuple(values)

    def _exact_effect(self, contribution: float) -> GateContributionEffect:
        if contribution > self.flat_tolerance:
            return GateContributionEffect.ADDED_VALUE
        if contribution < -self.flat_tolerance:
            return GateContributionEffect.DESTROYED_VALUE
        return GateContributionEffect.NEUTRAL

    def _restraint_effect(
        self,
        outcome: EvaluationOutcome,
        realized_return_spread: float,
    ) -> GateContributionEffect:
        if outcome in self._PROTECTED_OUTCOMES:
            return GateContributionEffect.PROTECTED_CAPITAL
        if outcome in self._COSTLY_OUTCOMES:
            return GateContributionEffect.COSTLY_RESTRAINT
        if realized_return_spread > self.flat_tolerance:
            return GateContributionEffect.PROTECTED_CAPITAL
        if realized_return_spread < -self.flat_tolerance:
            return GateContributionEffect.COSTLY_RESTRAINT
        return GateContributionEffect.NEUTRAL

    @staticmethod
    def _metrics(
        observations: tuple[GateContributionObservation, ...],
    ) -> tuple[GateContributionMetric, ...]:
        grouped: dict[
            GateContributionStage, list[GateContributionObservation]
        ] = {}
        for item in observations:
            grouped.setdefault(item.stage, []).append(item)
        metrics: list[GateContributionMetric] = []
        for stage in GateContributionStage:
            values = grouped.get(stage)
            if not values:
                continue
            spreads = [
                item.realized_return_spread
                for item in values
                if item.realized_return_spread is not None
            ]
            metrics.append(
                GateContributionMetric(
                    stage=stage,
                    activation_count=len(values),
                    protected_count=sum(
                        item.effect is GateContributionEffect.PROTECTED_CAPITAL
                        for item in values
                    ),
                    costly_count=sum(
                        item.effect is GateContributionEffect.COSTLY_RESTRAINT
                        for item in values
                    ),
                    added_value_count=sum(
                        item.effect is GateContributionEffect.ADDED_VALUE
                        for item in values
                    ),
                    destroyed_value_count=sum(
                        item.effect is GateContributionEffect.DESTROYED_VALUE
                        for item in values
                    ),
                    neutral_count=sum(
                        item.effect is GateContributionEffect.NEUTRAL
                        for item in values
                    ),
                    exact_portfolio_contribution=sum(
                        item.exact_portfolio_contribution or 0.0
                        for item in values
                    ),
                    mean_realized_return_spread=(
                        None if not spreads else sum(spreads) / len(spreads)
                    ),
                    constrained_weight=sum(
                        item.constrained_weight for item in values
                    ),
                )
            )
        return tuple(metrics)


__all__ = [
    "GateContributionAnalyzer",
    "GateContributionEffect",
    "GateContributionMetric",
    "GateContributionObservation",
    "GateContributionReport",
    "GateContributionStage",
]
