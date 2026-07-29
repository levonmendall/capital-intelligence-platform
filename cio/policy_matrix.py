"""Asset-class and horizon-specific decision policy profiles.

The matrix centralizes the candidate-specific hurdles used by qualification,
robustness, CIO synthesis, persistence, and final sizing.  It intentionally
returns immutable resolved profiles so every decision can persist the exact
policy applied at the point-in-time boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cio.models import CandidateAssetClass, CandidateDecisionRecord


def _ratio(value: float, *, name: str) -> float:
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
    return normalized


@dataclass(frozen=True, slots=True)
class DecisionPolicyProfile:
    """Resolved candidate-specific decision and sizing controls."""

    identifier: str
    minimum_net_expected_return: float
    minimum_opportunity_edge: float
    minimum_probability_of_success: float
    maximum_expected_downside: float
    maximum_position_weight: float
    minimum_robust_edge: float
    maximum_probability_of_loss: float
    minimum_worst_case_portfolio_return: float
    entry_persistence_cycles: int
    increase_persistence_cycles: int
    reduce_persistence_cycles: int
    cooldown_days: int
    forecast_durability_floor: float
    annualization_cap: float

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("identifier cannot be empty")
        for field_name in (
            "minimum_probability_of_success",
            "maximum_position_weight",
            "maximum_probability_of_loss",
            "forecast_durability_floor",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), name=field_name),
            )
        if self.minimum_net_expected_return <= -1.0:
            raise ValueError("minimum_net_expected_return must exceed -100%")
        if self.minimum_opportunity_edge < 0.0:
            raise ValueError("minimum_opportunity_edge cannot be negative")
        if self.maximum_expected_downside > 0.0:
            raise ValueError("maximum_expected_downside must be zero or negative")
        if self.minimum_robust_edge < 0.0:
            raise ValueError("minimum_robust_edge cannot be negative")
        if self.minimum_worst_case_portfolio_return >= 0.0:
            raise ValueError("minimum_worst_case_portfolio_return must be negative")
        if self.annualization_cap <= 0.0:
            raise ValueError("annualization_cap must be positive")
        for field_name in (
            "entry_persistence_cycles",
            "increase_persistence_cycles",
            "reduce_persistence_cycles",
            "cooldown_days",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")


class DecisionPolicyMatrix:
    """Resolve stricter controls for nonlinear, speculative, and short-horizon risk."""

    version = "decision-policy-matrix.v1"

    _STANDARD = DecisionPolicyProfile(
        identifier="standard-intermediate",
        minimum_net_expected_return=0.05,
        minimum_opportunity_edge=0.01,
        minimum_probability_of_success=0.55,
        maximum_expected_downside=-0.35,
        maximum_position_weight=0.10,
        minimum_robust_edge=0.005,
        maximum_probability_of_loss=0.45,
        minimum_worst_case_portfolio_return=-0.05,
        entry_persistence_cycles=2,
        increase_persistence_cycles=2,
        reduce_persistence_cycles=2,
        cooldown_days=5,
        forecast_durability_floor=0.50,
        annualization_cap=0.60,
    )

    def resolve(self, candidate: CandidateDecisionRecord) -> DecisionPolicyProfile:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")

        asset_class = candidate.instrument.asset_class
        if asset_class in {
            CandidateAssetClass.US_ETF,
            CandidateAssetClass.FIXED_INCOME,
            CandidateAssetClass.CASH_EQUIVALENT,
        }:
            profile = replace(
                self._STANDARD,
                identifier="diversified-liquid-intermediate",
                minimum_net_expected_return=0.04,
                minimum_opportunity_edge=0.008,
                minimum_probability_of_success=0.54,
                maximum_expected_downside=-0.25,
                maximum_position_weight=0.12,
                minimum_robust_edge=0.004,
                maximum_probability_of_loss=0.43,
                minimum_worst_case_portfolio_return=-0.045,
            )
        elif asset_class in {
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.VOLATILITY,
            CandidateAssetClass.ALTERNATIVE,
        }:
            profile = replace(
                self._STANDARD,
                identifier="speculative-intermediate",
                minimum_net_expected_return=0.10,
                minimum_opportunity_edge=0.03,
                minimum_probability_of_success=0.62,
                maximum_expected_downside=-0.60,
                maximum_position_weight=0.05,
                minimum_robust_edge=0.02,
                maximum_probability_of_loss=0.35,
                minimum_worst_case_portfolio_return=-0.035,
                entry_persistence_cycles=3,
                increase_persistence_cycles=3,
                forecast_durability_floor=0.65,
                annualization_cap=0.40,
            )
        elif asset_class in {
            CandidateAssetClass.OPTION,
            CandidateAssetClass.FUTURE,
        } or candidate.instrument.uses_derivatives:
            profile = replace(
                self._STANDARD,
                identifier="nonlinear-derivative-intermediate",
                minimum_net_expected_return=0.12,
                minimum_opportunity_edge=0.04,
                minimum_probability_of_success=0.65,
                maximum_expected_downside=-1.0,
                maximum_position_weight=0.03,
                minimum_robust_edge=0.025,
                maximum_probability_of_loss=0.32,
                minimum_worst_case_portfolio_return=-0.03,
                entry_persistence_cycles=3,
                increase_persistence_cycles=3,
                forecast_durability_floor=0.70,
                annualization_cap=0.35,
            )
        else:
            profile = self._STANDARD

        horizon = candidate.decision_horizon_days
        if horizon <= 30:
            profile = replace(
                profile,
                identifier=f"{profile.identifier}-tactical",
                minimum_net_expected_return=profile.minimum_net_expected_return * 1.25,
                minimum_opportunity_edge=profile.minimum_opportunity_edge * 1.50,
                minimum_probability_of_success=min(
                    0.80, profile.minimum_probability_of_success + 0.05
                ),
                maximum_position_weight=profile.maximum_position_weight * 0.75,
                entry_persistence_cycles=profile.entry_persistence_cycles + 1,
                increase_persistence_cycles=profile.increase_persistence_cycles + 1,
                forecast_durability_floor=max(profile.forecast_durability_floor, 0.70),
                annualization_cap=min(profile.annualization_cap, 0.35),
            )
        elif horizon > 365:
            profile = replace(
                profile,
                identifier=f"{profile.identifier}-strategic",
                minimum_net_expected_return=profile.minimum_net_expected_return * 0.85,
                minimum_opportunity_edge=profile.minimum_opportunity_edge * 0.80,
                minimum_probability_of_success=max(
                    0.50, profile.minimum_probability_of_success - 0.02
                ),
                maximum_position_weight=min(0.15, profile.maximum_position_weight * 1.10),
                forecast_durability_floor=max(0.45, profile.forecast_durability_floor - 0.05),
                annualization_cap=max(0.60, profile.annualization_cap),
            )
        return profile


__all__ = ["DecisionPolicyMatrix", "DecisionPolicyProfile"]
