"""Advisory forecast calibration and decision-value evaluation.

Reports in this module measure error, interval coverage, missed opportunities,
false positives, and the observed value of decision gates. They are append-only
review evidence only: they cannot resolve policy, lower thresholds, create a
candidate, or authorize a portfolio action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Mapping

from cio import CIOAction
from evaluation.point_in_time import (
    DecisionEvidenceSnapshot,
    EvaluationOutcome,
    PointInTimeDecisionEvaluation,
)


_POSITIVE_ACTIONS = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.HOLD}


def _finite(value: float, *, field_name: str) -> float:
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class CalibrationSegment:
    dimension: str
    value: str

    def __post_init__(self) -> None:
        if not self.dimension.strip() or not self.value.strip():
            raise ValueError("calibration segment dimension and value are required")


@dataclass(frozen=True, slots=True)
class AdvisoryDecisionValueMetric:
    segment: CalibrationSegment
    count: int
    mean_signed_return_error: float
    mean_absolute_return_error: float
    mean_forecast_brier_score: float
    downside_breach_rate: float
    scenario_interval_coverage: float
    false_positive_rate: float
    missed_opportunity_rate: float
    avoided_loss_rate: float
    mean_value_added_vs_alternative: float
    advisory_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.segment, CalibrationSegment):
            raise TypeError("segment must be CalibrationSegment")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError("count must be a positive integer")
        for field_name in (
            "mean_signed_return_error",
            "mean_absolute_return_error",
            "mean_forecast_brier_score",
            "downside_breach_rate",
            "scenario_interval_coverage",
            "false_positive_rate",
            "missed_opportunity_rate",
            "avoided_loss_rate",
            "mean_value_added_vs_alternative",
        ):
            object.__setattr__(
                self,
                field_name,
                round(_finite(getattr(self, field_name), field_name=field_name), 8),
            )
        for field_name in (
            "mean_forecast_brier_score",
            "downside_breach_rate",
            "scenario_interval_coverage",
            "false_positive_rate",
            "missed_opportunity_rate",
            "avoided_loss_rate",
        ):
            if not 0.0 <= getattr(self, field_name) <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.mean_absolute_return_error < 0.0:
            raise ValueError("mean_absolute_return_error cannot be negative")
        if not self.advisory_only:
            raise ValueError("decision-value metrics are advisory only")


@dataclass(frozen=True, slots=True)
class GateDecisionValueMetric:
    gate: str
    count: int
    avoided_losses: int
    missed_opportunities: int
    net_observed_value: float
    advisory_only: bool = True

    def __post_init__(self) -> None:
        if not self.gate.strip():
            raise ValueError("gate cannot be empty")
        for field_name in ("count", "avoided_losses", "missed_opportunities"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        if self.count < 1:
            raise ValueError("gate count must be positive")
        object.__setattr__(
            self,
            "net_observed_value",
            round(_finite(self.net_observed_value, field_name="net_observed_value"), 8),
        )
        if not self.advisory_only:
            raise ValueError("gate metrics are advisory only")


@dataclass(frozen=True, slots=True)
class AdvisoryDecisionValueReport:
    as_of: datetime
    metrics: tuple[AdvisoryDecisionValueMetric, ...]
    gate_metrics: tuple[GateDecisionValueMetric, ...]
    policy_version: str = "advisory-decision-value-evaluation.v1"
    advisory_only: bool = True

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.metrics, tuple) or not all(
            isinstance(item, AdvisoryDecisionValueMetric) for item in self.metrics
        ):
            raise TypeError("metrics must contain AdvisoryDecisionValueMetric values")
        if not isinstance(self.gate_metrics, tuple) or not all(
            isinstance(item, GateDecisionValueMetric) for item in self.gate_metrics
        ):
            raise TypeError("gate_metrics must contain GateDecisionValueMetric values")
        if not self.advisory_only:
            raise ValueError("decision-value reports are advisory only")

    def policy_changes(self) -> tuple[()]:
        """Explicitly prove this report has no policy-mutation output."""

        return ()


class AdvisoryDecisionValueEvaluator:
    """Measure calibration and gate value without mutating governed policy."""

    def evaluate(
        self,
        pairs: tuple[
            tuple[DecisionEvidenceSnapshot, PointInTimeDecisionEvaluation], ...
        ],
        *,
        as_of: datetime,
        segment_labels: Mapping[str, Mapping[str, str]] | None = None,
    ) -> AdvisoryDecisionValueReport:
        if not pairs:
            raise ValueError("decision-value evaluation requires at least one pair")
        labels = segment_labels or {}
        observations: list[dict[str, object]] = []
        gates: dict[str, list[tuple[EvaluationOutcome, float]]] = {}
        for snapshot, evaluation in pairs:
            if snapshot.identifier != evaluation.snapshot_identifier:
                raise ValueError("snapshot and evaluation identifiers do not match")
            realized = evaluation.candidate_return
            expected = snapshot.expected_return
            outcomes = snapshot.reconciled_outcomes
            interval_covered = (
                1.0
                if not outcomes
                or min(item.total_return for item in outcomes)
                <= realized
                <= max(item.total_return for item in outcomes)
                else 0.0
            )
            positive = snapshot.action in _POSITIVE_ACTIONS
            false_positive = float(
                positive
                and evaluation.outcome
                in {
                    EvaluationOutcome.VALUE_DESTROYED,
                    EvaluationOutcome.NOT_IMPLEMENTED,
                }
            )
            missed = float(evaluation.outcome is EvaluationOutcome.MISSED_OPPORTUNITY)
            avoided = float(evaluation.outcome is EvaluationOutcome.AVOIDED_LOSS)
            default_segments = {
                "all": "all",
                "horizon": self._horizon_bucket(snapshot.decision_horizon_days),
                "analysis_lane": snapshot.analysis_lane,
                "policy_profile": snapshot.resolved_policy_profile or "unknown",
                "action": snapshot.action.value,
            }
            default_segments.update(labels.get(snapshot.identifier, {}))
            observations.append(
                {
                    "segments": default_segments,
                    "signed_error": realized - expected,
                    "absolute_error": abs(realized - expected),
                    "brier": evaluation.forecast_brier_score,
                    "downside_breach": float(realized < snapshot.expected_downside),
                    "interval_covered": interval_covered,
                    "false_positive": false_positive,
                    "missed": missed,
                    "avoided": avoided,
                    "value_added": evaluation.excess_return_vs_best_original_alternative,
                }
            )
            if snapshot.evidence_vetoes:
                gates.setdefault("evidence_veto", []).append(
                    (evaluation.outcome, evaluation.excess_return_vs_best_original_alternative)
                )
            if snapshot.implementation_blocks:
                gates.setdefault("implementation_block", []).append(
                    (evaluation.outcome, evaluation.excess_return_vs_best_original_alternative)
                )
            if snapshot.hysteresis_applied:
                gates.setdefault("hysteresis", []).append(
                    (evaluation.outcome, evaluation.excess_return_vs_best_original_alternative)
                )

        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for observation in observations:
            for dimension, value in dict(observation["segments"]).items():
                grouped.setdefault((str(dimension), str(value)), []).append(observation)
        metrics = tuple(
            self._metric(dimension, value, values)
            for (dimension, value), values in sorted(grouped.items())
        )
        gate_metrics = tuple(
            self._gate_metric(gate, values)
            for gate, values in sorted(gates.items())
        )
        return AdvisoryDecisionValueReport(
            as_of=as_of,
            metrics=metrics,
            gate_metrics=gate_metrics,
        )

    @staticmethod
    def _metric(
        dimension: str,
        value: str,
        observations: list[dict[str, object]],
    ) -> AdvisoryDecisionValueMetric:
        count = len(observations)
        mean = lambda name: sum(float(item[name]) for item in observations) / count
        return AdvisoryDecisionValueMetric(
            segment=CalibrationSegment(dimension=dimension, value=value),
            count=count,
            mean_signed_return_error=mean("signed_error"),
            mean_absolute_return_error=mean("absolute_error"),
            mean_forecast_brier_score=mean("brier"),
            downside_breach_rate=mean("downside_breach"),
            scenario_interval_coverage=mean("interval_covered"),
            false_positive_rate=mean("false_positive"),
            missed_opportunity_rate=mean("missed"),
            avoided_loss_rate=mean("avoided"),
            mean_value_added_vs_alternative=mean("value_added"),
        )

    @staticmethod
    def _gate_metric(
        gate: str,
        values: list[tuple[EvaluationOutcome, float]],
    ) -> GateDecisionValueMetric:
        avoided = sum(outcome is EvaluationOutcome.AVOIDED_LOSS for outcome, _ in values)
        missed = sum(
            outcome in {
                EvaluationOutcome.MISSED_OPPORTUNITY,
                EvaluationOutcome.IMPLEMENTATION_BLOCK_COSTLY,
            }
            for outcome, _ in values
        )
        return GateDecisionValueMetric(
            gate=gate,
            count=len(values),
            avoided_losses=avoided,
            missed_opportunities=missed,
            net_observed_value=sum(value for _, value in values) / len(values),
        )

    @staticmethod
    def _horizon_bucket(days: int) -> str:
        if days <= 30:
            return "1-30_days"
        if days <= 90:
            return "31-90_days"
        if days <= 365:
            return "91-365_days"
        return "366_plus_days"


__all__ = [
    "AdvisoryDecisionValueEvaluator",
    "AdvisoryDecisionValueMetric",
    "AdvisoryDecisionValueReport",
    "CalibrationSegment",
    "GateDecisionValueMetric",
]
