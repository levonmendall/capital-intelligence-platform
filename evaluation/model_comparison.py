"""Point-in-time champion-versus-challenger comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from governance.model_experiments import ModelExperiment, ShadowModelObservation


@dataclass(frozen=True, slots=True)
class ModelComparisonReport:
    experiment_identifier: str
    as_of: datetime
    sample_size: int
    forecast_loss_improvement: float | None
    realized_return_improvement_after_costs: float | None
    turnover_change: float
    drawdown_change: float | None
    action_disagreement_rate: float
    ranking_disagreement_rate: float
    out_of_sample_complete: bool
    survivorship_safe_complete: bool
    paper_shadow_complete: bool
    multiple_testing_penalty: float
    governance_regression: bool
    promotion_recommended: bool
    rationale: tuple[str, ...]
    schema_version: str = "model-comparison.v1"


class ModelComparisonEngine:
    def compare(
        self,
        experiment: ModelExperiment,
        observations: tuple[ShadowModelObservation, ...],
        *,
        as_of: datetime,
        number_of_challengers_tested: int = 1,
    ) -> ModelComparisonReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        scoped = tuple(
            item
            for item in observations
            if item.experiment_identifier == experiment.identifier
        )
        if len(scoped) != len(observations):
            raise ValueError("all observations must belong to the experiment")
        if number_of_challengers_tested < 1:
            raise ValueError("number_of_challengers_tested must be positive")
        sample_size = len(scoped)
        realized = tuple(
            item for item in scoped if item.realized_outcome is not None
        )
        calibration = tuple(
            item
            for item in scoped
            if item.champion_calibration_loss is not None
            and item.challenger_calibration_loss is not None
        )
        forecast_improvement = None
        if calibration:
            forecast_improvement = sum(
                float(item.champion_calibration_loss)
                - float(item.challenger_calibration_loss)
                for item in calibration
            ) / len(calibration)
        realized_improvement = None
        if realized:
            realized_improvement = sum(
                float(item.realized_outcome)
                * (item.challenger_size - item.champion_size)
                - max(
                    0.0,
                    item.challenger_turnover - item.champion_turnover,
                )
                * 0.001
                for item in realized
            ) / len(realized)
        turnover_change = (
            sum(
                item.challenger_turnover - item.champion_turnover
                for item in scoped
            )
            / sample_size
            if sample_size
            else 0.0
        )
        drawdown_pairs = tuple(
            item
            for item in scoped
            if item.champion_drawdown is not None
            and item.challenger_drawdown is not None
        )
        drawdown_change = None
        if drawdown_pairs:
            drawdown_change = sum(
                float(item.challenger_drawdown)
                - float(item.champion_drawdown)
                for item in drawdown_pairs
            ) / len(drawdown_pairs)
        action_disagreement = (
            sum(
                item.champion_action != item.challenger_action
                for item in scoped
            )
            / sample_size
            if sample_size
            else 0.0
        )
        ranked = tuple(
            item
            for item in scoped
            if item.champion_rank is not None
            and item.challenger_rank is not None
        )
        ranking_disagreement = (
            sum(
                item.champion_rank != item.challenger_rank
                for item in ranked
            )
            / len(ranked)
            if ranked
            else 0.0
        )
        out_of_sample = bool(scoped) and all(
            item.out_of_sample for item in scoped
        )
        survivorship_safe = bool(scoped) and all(
            item.survivorship_safe for item in scoped
        )
        paper_shadow = sample_size >= experiment.minimum_sample_size
        penalty = min(
            0.25,
            max(0, number_of_challengers_tested - 1) * 0.01,
        )
        governance_regression = any(
            item.evidence_cutoff > item.as_of or item.challenger_size < 0.0
            for item in scoped
        )
        sufficient_benefit = (
            realized_improvement is not None
            and isfinite(realized_improvement)
            and realized_improvement > penalty
            and (
                forecast_improvement is None
                or forecast_improvement > 0.0
            )
            and (drawdown_change is None or drawdown_change >= 0.0)
        )
        promote = (
            paper_shadow
            and out_of_sample
            and survivorship_safe
            and sufficient_benefit
            and not governance_regression
        )
        rationale: list[str] = []
        if not paper_shadow:
            rationale.append(
                "Minimum paper-shadow sample size has not been reached."
            )
        if not out_of_sample:
            rationale.append("Out-of-sample coverage is incomplete.")
        if not survivorship_safe:
            rationale.append(
                "Survivorship-safe universe coverage is incomplete."
            )
        if not sufficient_benefit:
            rationale.append(
                "Improvement after costs and multiple-testing penalty is not established."
            )
        if governance_regression:
            rationale.append("A governance regression was detected.")
        if promote:
            rationale.append(
                "The challenger meets the measured promotion recommendation gates; explicit approval is still required."
            )
        return ModelComparisonReport(
            experiment_identifier=experiment.identifier,
            as_of=as_of,
            sample_size=sample_size,
            forecast_loss_improvement=(
                None
                if forecast_improvement is None
                else round(forecast_improvement, 8)
            ),
            realized_return_improvement_after_costs=(
                None
                if realized_improvement is None
                else round(realized_improvement, 8)
            ),
            turnover_change=round(turnover_change, 8),
            drawdown_change=(
                None
                if drawdown_change is None
                else round(drawdown_change, 8)
            ),
            action_disagreement_rate=round(action_disagreement, 8),
            ranking_disagreement_rate=round(ranking_disagreement, 8),
            out_of_sample_complete=out_of_sample,
            survivorship_safe_complete=survivorship_safe,
            paper_shadow_complete=paper_shadow,
            multiple_testing_penalty=round(penalty, 8),
            governance_regression=governance_regression,
            promotion_recommended=promote,
            rationale=tuple(rationale),
        )


__all__ = ["ModelComparisonEngine", "ModelComparisonReport"]
