"""Portfolio-posture-aware CIO authority for bounded staged participation.

The class in this module remains the CIO.  It does not create candidates, waive
capability or evidence controls, construct a portfolio, or execute an order.  It
changes only one behavior: when the ordinary acquisition path abstains despite a
positive robust and stressed edge, a posture-consistent candidate may receive a
small staged target instead of being eliminated solely by ordinary uncertainty or
one bounded independent disagreement.
"""

from __future__ import annotations

from cio.decision_integrity import ChiefInvestmentOfficer
from cio.models import CIOAction
from portfolio.compounding_allocation import (
    CandidateAllocationDirective,
    CompoundingParticipationPolicy,
    PortfolioPosture,
)
from portfolio.compounding_participation_authority import (
    AuthoritativeCompoundingParticipationPolicy,
)


_NON_OWNERSHIP_ABSTENTIONS = {
    CIOAction.WATCH,
    CIOAction.NO_SUPERIOR_OPPORTUNITY,
    CIOAction.NO_MATERIAL_CHANGE,
}


class CompoundingChiefInvestmentOfficer(ChiefInvestmentOfficer):
    """Canonical CIO with a bounded portfolio-posture participation lane."""

    def __init__(
        self,
        *args,
        participation_policy: CompoundingParticipationPolicy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.participation_policy = (
            participation_policy
            or AuthoritativeCompoundingParticipationPolicy()
        )
        self._portfolio_posture: PortfolioPosture | None = None
        self._allocation_directives: dict[str, CandidateAllocationDirective] = {}

    @property
    def portfolio_posture(self) -> PortfolioPosture | None:
        return self._portfolio_posture

    def set_compounding_context(
        self,
        posture: PortfolioPosture,
        directives: tuple[CandidateAllocationDirective, ...],
    ) -> None:
        if not isinstance(posture, PortfolioPosture):
            raise TypeError("posture must be PortfolioPosture")
        if not isinstance(directives, tuple) or not all(
            isinstance(item, CandidateAllocationDirective) for item in directives
        ):
            raise TypeError(
                "directives must contain CandidateAllocationDirective values"
            )
        values = {item.candidate_identifier: item for item in directives}
        if len(values) != len(directives):
            raise ValueError("allocation directives must be unique by candidate")
        self._portfolio_posture = posture
        self._allocation_directives = values

    def clear_compounding_context(self) -> None:
        self._portfolio_posture = None
        self._allocation_directives = {}

    def _select_action(
        self,
        candidate,
        *,
        universe,
        specialists,
        robustness,
        robustness_candidate,
        reconciliation,
        effective_alternative,
        profile,
        analysis_lane,
        ensemble,
        outage_assessment,
    ):
        action, position_weight, reason = super()._select_action(
            candidate,
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            robustness_candidate=robustness_candidate,
            reconciliation=reconciliation,
            effective_alternative=effective_alternative,
            profile=profile,
            analysis_lane=analysis_lane,
            ensemble=ensemble,
            outage_assessment=outage_assessment,
        )
        if float(candidate.current_portfolio_weight) > 0.0:
            return action, position_weight, reason
        if action not in _NON_OWNERSHIP_ABSTENTIONS:
            return action, position_weight, reason
        if self._portfolio_posture is None:
            return action, position_weight, reason

        directive = self._allocation_directives.get(candidate.identifier)
        staged = self.participation_policy.assess(
            candidate=candidate,
            directive=directive,
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            reconciliation=reconciliation,
            ensemble=ensemble,
            effective_alternative=effective_alternative,
            material_opposition_threshold=(
                self.policy.maximum_unresolved_dissent_confidence
            ),
        )
        if not staged.authorized:
            return action, position_weight, reason
        return (
            CIOAction.BUY,
            staged.target_weight,
            reason
            + " Portfolio-posture staged participation applies: "
            + staged.reasons[0]
            + f". Regime={self._portfolio_posture.regime.value}; "
            + f"posture confidence={self._portfolio_posture.confidence:.0%}; "
            + f"sleeve={directive.sleeve.value if directive is not None else 'unknown'}; "
            + f"target={staged.target_weight:.2%}. The target remains subject to "
            + "independent portfolio construction and paper-execution controls.",
        )


__all__ = ["CompoundingChiefInvestmentOfficer"]
