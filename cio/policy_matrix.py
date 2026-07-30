"""Asset-class, exposure, and horizon-specific decision policy profiles.

The matrix centralizes the candidate-specific hurdles used by qualification,
robustness, CIO synthesis, persistence, and final sizing. Execution wrappers do
not dilute the risk classification of the economic exposure they represent: the
resolved profile always combines the wrapper and exposure profiles using the
stricter requirement for every control.
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
    """Resolve coherent controls across execution form, economic exposure, and horizon."""

    version = "decision-policy-matrix.v3"

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

    # Current production uses U.S.-listed wrappers. The publisher now supplies
    # economic_exposure_class, but this map preserves correct governance for
    # already-persisted v1 candidate records created before that correction.
    _CURRENT_WRAPPER_EXPOSURES = {
        "VTI": CandidateAssetClass.US_EQUITY,
        "VXUS": CandidateAssetClass.INTERNATIONAL_EQUITY,
        "GOVT": CandidateAssetClass.FIXED_INCOME,
        "LQD": CandidateAssetClass.FIXED_INCOME,
        "HYG": CandidateAssetClass.FIXED_INCOME,
        "SGOV": CandidateAssetClass.CASH_EQUIVALENT,
        "DBC": CandidateAssetClass.COMMODITY,
        "GLD": CandidateAssetClass.COMMODITY,
        "UUP": CandidateAssetClass.FX,
        "IBIT": CandidateAssetClass.CRYPTO,
        "VNQ": CandidateAssetClass.REAL_ESTATE,
        "DBMF": CandidateAssetClass.ALTERNATIVE,
        "WTPI": CandidateAssetClass.OPTION,
        "VIXY": CandidateAssetClass.VOLATILITY,
        "BTAL": CandidateAssetClass.ALTERNATIVE,
    }

    def resolve(self, candidate: CandidateDecisionRecord) -> DecisionPolicyProfile:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")

        if (
            candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY
            and candidate.instrument.replication_method
            == "direct-common-equity-exploratory"
        ):
            return self._apply_horizon(
                self._exploratory_equity_profile(),
                candidate.decision_horizon_days,
            )
        execution = self._profile_for(candidate.instrument.asset_class)
        exposure_class = self._economic_exposure_class(candidate)
        exposure = self._profile_for(exposure_class)
        if (
            candidate.instrument.asset_class is CandidateAssetClass.US_ETF
            and exposure_class is not CandidateAssetClass.US_ETF
        ):
            # The underlying exposure governs return, probability, downside and
            # persistence. The listed wrapper contributes the tighter position
            # ceiling, while liquidity and execution controls remain separate.
            profile = replace(
                exposure,
                identifier=(
                    f"economic-exposure[{exposure.identifier}]"
                    f"+wrapper-position[{execution.identifier}]"
                ),
                maximum_position_weight=min(
                    execution.maximum_position_weight,
                    exposure.maximum_position_weight,
                ),
            )
        else:
            profile = self._stricter(execution, exposure)
        if candidate.instrument.uses_derivatives:
            derivative = self._profile_for(CandidateAssetClass.OPTION)
            profile = replace(
                derivative,
                identifier=f"derivative-overlay[{derivative.identifier}+{profile.identifier}]",
                maximum_position_weight=min(
                    profile.maximum_position_weight,
                    derivative.maximum_position_weight,
                ),
            )
        return self._apply_horizon(profile, candidate.decision_horizon_days)

    @classmethod
    def _economic_exposure_class(
        cls,
        candidate: CandidateDecisionRecord,
    ) -> CandidateAssetClass:
        explicit = candidate.instrument.economic_exposure_class
        if explicit is not None and explicit is not candidate.instrument.asset_class:
            return explicit
        if (
            candidate.instrument.replication_method
            == "us-listed-economic-exposure-wrapper"
        ):
            return cls._CURRENT_WRAPPER_EXPOSURES.get(
                candidate.instrument.symbol,
                candidate.instrument.asset_class,
            )
        return explicit or candidate.instrument.asset_class

    @classmethod
    def _exploratory_equity_profile(cls) -> DecisionPolicyProfile:
        """Permit a risk-capped paper probe while reserving full standards for scale."""

        return replace(
            cls._STANDARD,
            identifier="direct-common-equity-exploratory",
            minimum_net_expected_return=0.04,
            minimum_opportunity_edge=0.0025,
            minimum_probability_of_success=0.52,
            maximum_expected_downside=-0.55,
            maximum_position_weight=0.01,
            minimum_robust_edge=0.001,
            maximum_probability_of_loss=0.48,
            minimum_worst_case_portfolio_return=-0.01,
            entry_persistence_cycles=1,
            increase_persistence_cycles=2,
            reduce_persistence_cycles=2,
            cooldown_days=3,
            forecast_durability_floor=0.45,
            annualization_cap=0.60,
        )

    @classmethod
    def _profile_for(
        cls,
        asset_class: CandidateAssetClass,
    ) -> DecisionPolicyProfile:
        if asset_class in {
            CandidateAssetClass.US_ETF,
            CandidateAssetClass.FIXED_INCOME,
            CandidateAssetClass.CASH_EQUIVALENT,
        }:
            return replace(
                cls._STANDARD,
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
        if asset_class in {
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.VOLATILITY,
            CandidateAssetClass.ALTERNATIVE,
        }:
            return replace(
                cls._STANDARD,
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
        if asset_class in {
            CandidateAssetClass.OPTION,
            CandidateAssetClass.FUTURE,
        }:
            return replace(
                cls._STANDARD,
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
        return cls._STANDARD

    @staticmethod
    def _stricter(
        left: DecisionPolicyProfile,
        right: DecisionPolicyProfile,
    ) -> DecisionPolicyProfile:
        if left == right:
            return left
        identifiers = tuple(dict.fromkeys((left.identifier, right.identifier)))
        return DecisionPolicyProfile(
            identifier="strictest[" + "+".join(identifiers) + "]",
            minimum_net_expected_return=max(
                left.minimum_net_expected_return,
                right.minimum_net_expected_return,
            ),
            minimum_opportunity_edge=max(
                left.minimum_opportunity_edge,
                right.minimum_opportunity_edge,
            ),
            minimum_probability_of_success=max(
                left.minimum_probability_of_success,
                right.minimum_probability_of_success,
            ),
            maximum_expected_downside=max(
                left.maximum_expected_downside,
                right.maximum_expected_downside,
            ),
            maximum_position_weight=min(
                left.maximum_position_weight,
                right.maximum_position_weight,
            ),
            minimum_robust_edge=max(
                left.minimum_robust_edge,
                right.minimum_robust_edge,
            ),
            maximum_probability_of_loss=min(
                left.maximum_probability_of_loss,
                right.maximum_probability_of_loss,
            ),
            minimum_worst_case_portfolio_return=max(
                left.minimum_worst_case_portfolio_return,
                right.minimum_worst_case_portfolio_return,
            ),
            entry_persistence_cycles=max(
                left.entry_persistence_cycles,
                right.entry_persistence_cycles,
            ),
            increase_persistence_cycles=max(
                left.increase_persistence_cycles,
                right.increase_persistence_cycles,
            ),
            reduce_persistence_cycles=max(
                left.reduce_persistence_cycles,
                right.reduce_persistence_cycles,
            ),
            cooldown_days=max(left.cooldown_days, right.cooldown_days),
            forecast_durability_floor=max(
                left.forecast_durability_floor,
                right.forecast_durability_floor,
            ),
            annualization_cap=min(left.annualization_cap, right.annualization_cap),
        )

    @staticmethod
    def _apply_horizon(
        profile: DecisionPolicyProfile,
        horizon: int,
    ) -> DecisionPolicyProfile:
        if horizon <= 30:
            return replace(
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
        if horizon > 365:
            return replace(
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
