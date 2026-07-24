"""Mandate-aware gate between committee approval and portfolio action."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from committee.regime_governance import (
    RegimeCommitteeDecision,
    RegimeGovernanceOutcome,
)
from intelligence.recommendation import RecommendationAction
from portfolio.models import (
    PortfolioMandate,
    PortfolioProposal,
    PortfolioSnapshot,
)


class PortfolioFitOutcome(str, Enum):
    """Simple terminal result shown to the accountable investor."""

    FIT = "fit"
    FIT_SMALLER = "fit_smaller"
    REPLACE_OVERLAP = "replace_overlap"
    POLICY_BLOCKED = "policy_blocked"
    NO_RISK_BUDGET = "no_risk_budget"
    NO_ACTION = "no_action"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _bounded_ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(
            f"{field_name} must be between 0.0 and 1.0"
        )
    return round(normalized, 6)


@dataclass(frozen=True, slots=True)
class PortfolioFitPolicy:
    """Versioned rules shared across mandate-specific limits."""

    version: str = "portfolio-fit.v1"
    minimum_meaningful_weight_delta: float = 0.005
    overlap_weight_threshold: float = 0.20

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "minimum_meaningful_weight_delta",
            "overlap_weight_threshold",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_ratio(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if self.minimum_meaningful_weight_delta == 0.0:
            raise ValueError(
                "minimum_meaningful_weight_delta must be positive"
            )


@dataclass(frozen=True, slots=True)
class PortfolioFitDecision:
    """Immutable decision about whether one proposal fits a portfolio."""

    identifier: str
    source_decision_identifier: str
    proposal_identifier: str
    portfolio_identifier: str
    portfolio_as_of: datetime
    mandate_identifier: str
    assessed_at: datetime
    mandate_version: str
    policy_version: str
    outcome: PortfolioFitOutcome
    headline: str
    explanation: str
    binding_constraints: tuple[str, ...] = ()
    overlapping_positions: tuple[str, ...] = ()
    permitted_weight_delta: float | None = None
    permitted_risk_budget_delta: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "source_decision_identifier",
            "proposal_identifier",
            "portfolio_identifier",
            "mandate_identifier",
            "mandate_version",
            "policy_version",
            "headline",
            "explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        _aware_datetime(
            self.portfolio_as_of,
            field_name="portfolio_as_of",
        )
        _aware_datetime(self.assessed_at, field_name="assessed_at")
        if self.portfolio_as_of > self.assessed_at:
            raise ValueError(
                "portfolio_as_of cannot be later than assessed_at"
            )
        if not isinstance(self.outcome, PortfolioFitOutcome):
            raise TypeError(
                "outcome must be a PortfolioFitOutcome"
            )
        for field_name in (
            "binding_constraints",
            "overlapping_positions",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise TypeError(f"{field_name} must be a tuple")
            normalized = tuple(
                _required_text(item, field_name=field_name)
                for item in values
            )
            if len(normalized) != len(set(normalized)):
                raise ValueError(
                    f"{field_name} cannot contain duplicates"
                )
            object.__setattr__(self, field_name, normalized)
        for field_name in (
            "permitted_weight_delta",
            "permitted_risk_budget_delta",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"{field_name} must be numeric or None")
            normalized = float(value)
            if not isfinite(normalized) or not -1.0 <= normalized <= 1.0:
                raise ValueError(
                    f"{field_name} must be between -1.0 and 1.0"
                )
            object.__setattr__(
                self,
                field_name,
                round(normalized, 6),
            )
        if self.outcome in {
            PortfolioFitOutcome.FIT,
            PortfolioFitOutcome.FIT_SMALLER,
        }:
            if self.permitted_weight_delta is None:
                raise ValueError(
                    "fit outcomes require permitted_weight_delta"
                )
            if self.permitted_risk_budget_delta is None:
                raise ValueError(
                    "fit outcomes require "
                    "permitted_risk_budget_delta"
                )
            if self.permitted_weight_delta == 0.0:
                raise ValueError(
                    "fit outcomes require a non-zero weight delta"
                )
            if (
                self.permitted_weight_delta
                * self.permitted_risk_budget_delta
                < 0
            ):
                raise ValueError(
                    "permitted weight and risk deltas cannot "
                    "have opposite signs"
                )
        elif (
            self.permitted_weight_delta is not None
            or self.permitted_risk_budget_delta is not None
        ):
            raise ValueError(
                "non-fit outcomes cannot permit a proposal"
            )
        if (
            self.outcome is PortfolioFitOutcome.REPLACE_OVERLAP
            and not self.overlapping_positions
        ):
            raise ValueError(
                "replace_overlap requires overlapping_positions"
            )

    @property
    def permits_expression(self) -> bool:
        """Whether this exact decision permits a portfolio proposal."""

        return self.outcome in {
            PortfolioFitOutcome.FIT,
            PortfolioFitOutcome.FIT_SMALLER,
        }


class PortfolioFitGate:
    """Apply committee, direction, mandate, risk, and overlap controls."""

    def __init__(
        self,
        policy: PortfolioFitPolicy | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy or PortfolioFitPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate(
        self,
        decision: RegimeCommitteeDecision,
        proposal: PortfolioProposal,
        portfolio: PortfolioSnapshot,
        mandate: PortfolioMandate,
    ) -> PortfolioFitDecision:
        """Return a non-executing fit decision for one proposal."""

        self._validate_inputs(
            decision,
            proposal,
            portfolio,
            mandate,
        )
        assessed_at = _aware_datetime(
            self._clock(),
            field_name="clock",
        )
        if decision.decided_at > assessed_at:
            raise ValueError(
                "decision cannot be later than the fit assessment"
            )
        if portfolio.as_of > assessed_at:
            raise ValueError(
                "portfolio snapshot cannot be later than assessment"
            )
        base = {
            "identifier": (
                f"portfolio-fit:{portfolio.identifier}:"
                f"{proposal.identifier}"
            ),
            "source_decision_identifier": (
                decision.decision_identifier
            ),
            "proposal_identifier": proposal.identifier,
            "portfolio_identifier": portfolio.identifier,
            "portfolio_as_of": portfolio.as_of,
            "mandate_identifier": mandate.identifier,
            "assessed_at": assessed_at,
            "mandate_version": mandate.version,
            "policy_version": self.policy.version,
        }

        if decision.outcome is not RegimeGovernanceOutcome.APPROVE:
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.NO_ACTION,
                headline="Keep the portfolio unchanged",
                explanation=(
                    "The committee has not approved this portfolio "
                    "change."
                ),
                binding_constraints=("committee_approval",),
            )

        direction_error = self._direction_error(decision, proposal)
        if direction_error is not None:
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.POLICY_BLOCKED,
                headline="Proposal conflicts with the decision",
                explanation=direction_error,
                binding_constraints=("recommendation_direction",),
            )

        if proposal.requested_weight_delta < 0:
            return self._evaluate_reduction(
                proposal,
                portfolio,
                base,
            )

        policy_block = self._policy_block(
            proposal,
            mandate,
        )
        if policy_block is not None:
            constraint, explanation = policy_block
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.POLICY_BLOCKED,
                headline="Portfolio policy blocks this change",
                explanation=explanation,
                binding_constraints=(constraint,),
            )

        scale, constraints = self._capacity_scale(
            proposal,
            portfolio,
            mandate,
        )
        overlaps = tuple(
            position.identifier
            for position in portfolio.overlapping_positions(
                proposal.exposure_tags
            )
            if position.identifier != proposal.target_identifier
        )
        overlap_weight = sum(
            portfolio.position_weight(identifier)
            for identifier in overlaps
        )
        if (
            overlaps
            and overlap_weight
            >= self.policy.overlap_weight_threshold
        ):
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.REPLACE_OVERLAP,
                headline="Replace overlapping exposure first",
                explanation=(
                    "The portfolio already carries similar risk. "
                    "Review replacing an existing exposure instead "
                    "of adding more."
                ),
                binding_constraints=constraints,
                overlapping_positions=overlaps,
            )

        permitted_weight = (
            proposal.requested_weight_delta * scale
        )
        if (
            permitted_weight
            < self.policy.minimum_meaningful_weight_delta
        ):
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.NO_RISK_BUDGET,
                headline="No room for more portfolio risk",
                explanation=(
                    "Current portfolio limits leave no meaningful "
                    "room for this addition."
                ),
                binding_constraints=constraints or (
                    "portfolio_capacity",
                ),
            )

        permitted_risk = (
            proposal.estimated_risk_budget_delta * scale
        )
        if scale < 1.0:
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.FIT_SMALLER,
                headline="Use a smaller portfolio change",
                explanation=(
                    "The idea fits, but the requested size exceeds "
                    "one or more portfolio limits."
                ),
                binding_constraints=constraints,
                permitted_weight_delta=permitted_weight,
                permitted_risk_budget_delta=permitted_risk,
            )

        return PortfolioFitDecision(
            **base,
            outcome=PortfolioFitOutcome.FIT,
            headline="The proposal fits the portfolio",
            explanation=(
                "The proposed change stays within the current "
                "mandate and risk limits."
            ),
            permitted_weight_delta=proposal.requested_weight_delta,
            permitted_risk_budget_delta=(
                proposal.estimated_risk_budget_delta
            ),
        )

    @staticmethod
    def _validate_inputs(
        decision: RegimeCommitteeDecision,
        proposal: PortfolioProposal,
        portfolio: PortfolioSnapshot,
        mandate: PortfolioMandate,
    ) -> None:
        if not isinstance(decision, RegimeCommitteeDecision):
            raise TypeError(
                "decision must be a RegimeCommitteeDecision"
            )
        if not isinstance(proposal, PortfolioProposal):
            raise TypeError(
                "proposal must be a PortfolioProposal"
            )
        if not isinstance(portfolio, PortfolioSnapshot):
            raise TypeError(
                "portfolio must be a PortfolioSnapshot"
            )
        if not isinstance(mandate, PortfolioMandate):
            raise TypeError(
                "mandate must be a PortfolioMandate"
            )
        if (
            proposal.source_decision_identifier
            != decision.decision_identifier
        ):
            raise ValueError(
                "proposal must reference the committee decision"
            )

    @staticmethod
    def _direction_error(
        decision: RegimeCommitteeDecision,
        proposal: PortfolioProposal,
    ) -> str | None:
        action = decision.recommendation.action
        positive = {
            RecommendationAction.OVERWEIGHT,
            RecommendationAction.ACCUMULATE,
        }
        negative = {
            RecommendationAction.UNDERWEIGHT,
            RecommendationAction.REDUCE,
            RecommendationAction.AVOID,
        }
        if action in positive and proposal.requested_weight_delta < 0:
            return (
                "The committee approved adding exposure, but the "
                "proposal reduces it."
            )
        if action in negative and proposal.requested_weight_delta > 0:
            return (
                "The committee approved reducing exposure, but the "
                "proposal adds it."
            )
        if action is RecommendationAction.NEUTRAL:
            return (
                "A neutral recommendation does not authorize a "
                "portfolio weight change."
            )
        return None

    @staticmethod
    def _policy_block(
        proposal: PortfolioProposal,
        mandate: PortfolioMandate,
    ) -> tuple[str, str] | None:
        if proposal.target_identifier in mandate.prohibited_identifiers:
            return (
                "prohibited_identifier",
                "The mandate does not allow this investment.",
            )
        blocked_tags = set(proposal.exposure_tags).intersection(
            mandate.prohibited_exposure_tags
        )
        if blocked_tags:
            return (
                "prohibited_exposure",
                "The mandate does not allow this type of exposure.",
            )
        if (
            proposal.liquidity_score
            < mandate.minimum_liquidity_score
        ):
            return (
                "liquidity",
                "The investment is not liquid enough for this mandate.",
            )
        return None

    @staticmethod
    def _capacity_scale(
        proposal: PortfolioProposal,
        portfolio: PortfolioSnapshot,
        mandate: PortfolioMandate,
    ) -> tuple[float, tuple[str, ...]]:
        requested = proposal.requested_weight_delta
        capacities = {
            "position_limit": max(
                0.0,
                mandate.maximum_position_weight
                - portfolio.position_weight(
                    proposal.target_identifier
                ),
            ),
            "bucket_limit": max(
                0.0,
                mandate.maximum_bucket_weight(proposal.bucket)
                - portfolio.bucket_weight(proposal.bucket),
            ),
            "cash_reserve": max(
                0.0,
                portfolio.cash_weight
                - mandate.minimum_cash_weight,
            ),
        }
        scales = {
            name: min(1.0, capacity / requested)
            for name, capacity in capacities.items()
        }
        if proposal.estimated_risk_budget_delta > 0:
            risk_capacity = max(
                0.0,
                mandate.maximum_risk_budget
                - portfolio.risk_budget_used,
            )
            scales["risk_budget"] = min(
                1.0,
                risk_capacity
                / proposal.estimated_risk_budget_delta,
            )
        scale = min(scales.values(), default=1.0)
        constraints = tuple(
            name
            for name, value in scales.items()
            if value == scale and value < 1.0
        )
        return round(scale, 6), constraints

    def _evaluate_reduction(
        self,
        proposal: PortfolioProposal,
        portfolio: PortfolioSnapshot,
        base: dict[str, object],
    ) -> PortfolioFitDecision:
        current_weight = portfolio.position_weight(
            proposal.target_identifier
        )
        if current_weight < self.policy.minimum_meaningful_weight_delta:
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.NO_ACTION,
                headline="No portfolio change needed",
                explanation=(
                    "The portfolio does not hold enough of this "
                    "exposure to reduce it."
                ),
                binding_constraints=("current_position",),
            )
        requested_reduction = abs(
            proposal.requested_weight_delta
        )
        permitted_reduction = min(
            requested_reduction,
            current_weight,
        )
        scale = permitted_reduction / requested_reduction
        permitted_risk = (
            proposal.estimated_risk_budget_delta * scale
        )
        if scale < 1.0:
            return PortfolioFitDecision(
                **base,
                outcome=PortfolioFitOutcome.FIT_SMALLER,
                headline="Reduce only the current position",
                explanation=(
                    "The requested reduction is larger than the "
                    "portfolio's current exposure."
                ),
                binding_constraints=("current_position",),
                permitted_weight_delta=-permitted_reduction,
                permitted_risk_budget_delta=permitted_risk,
            )
        return PortfolioFitDecision(
            **base,
            outcome=PortfolioFitOutcome.FIT,
            headline="The reduction fits the portfolio",
            explanation=(
                "Reducing this exposure lowers portfolio concentration "
                "and risk."
            ),
            permitted_weight_delta=proposal.requested_weight_delta,
            permitted_risk_budget_delta=(
                proposal.estimated_risk_budget_delta
            ),
        )


__all__ = [
    "PortfolioFitDecision",
    "PortfolioFitGate",
    "PortfolioFitOutcome",
    "PortfolioFitPolicy",
]
