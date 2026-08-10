"""Portfolio-posture-aware CIO authority for bounded staged participation.

The class in this module remains the CIO. It does not create candidates, waive
capability or evidence controls, construct a portfolio, or execute an order. When
the ordinary acquisition path abstains despite a positive robust and stressed edge,
a posture-consistent candidate may receive a small staged target. A simultaneous
construction preview may also reduce an otherwise-positive target to a smaller
still-positive jointly feasible target, but it can never create a buy or act as a
hidden zero-target veto.
"""

from __future__ import annotations

from cio.intelligence_refinement import ChiefInvestmentOfficer
from cio.joint_preview import JointPortfolioPreview
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
    """Canonical CIO with bounded staged participation and joint sizing context."""

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
        self._joint_portfolio_preview: JointPortfolioPreview | None = None

    @property
    def portfolio_posture(self) -> PortfolioPosture | None:
        return self._portfolio_posture

    @property
    def joint_portfolio_preview(self) -> JointPortfolioPreview | None:
        return self._joint_portfolio_preview

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

    def set_joint_preview_context(self, preview: JointPortfolioPreview) -> None:
        if not isinstance(preview, JointPortfolioPreview):
            raise TypeError("preview must be JointPortfolioPreview")
        self._joint_portfolio_preview = preview

    def clear_joint_preview_context(self) -> None:
        self._joint_portfolio_preview = None

    def _apply_joint_preview_cap(
        self,
        candidate,
        *,
        action: CIOAction,
        position_weight: float | None,
        reason: str,
    ) -> tuple[CIOAction, float | None, str]:
        preview = self._joint_portfolio_preview
        if (
            preview is None
            or action not in {CIOAction.BUY, CIOAction.INCREASE}
            or position_weight is None
        ):
            return action, position_weight, reason
        cap = preview.positive_cap_for(
            candidate.identifier,
            current_weight=float(candidate.current_portfolio_weight),
        )
        if cap is None or cap >= float(position_weight) - 0.00000001:
            return action, position_weight, reason
        return (
            action,
            round(cap, 8),
            reason
            + " Joint portfolio preview reduced the positive CIO target to a smaller "
            + f"simultaneously feasible weight of {cap:.2%} under "
            + f"{preview.identifier}; final construction remains authoritative.",
        )

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
        if (
            float(candidate.current_portfolio_weight) <= 0.0
            and action in _NON_OWNERSHIP_ABSTENTIONS
            and self._portfolio_posture is not None
        ):
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
            if staged.authorized:
                action = CIOAction.BUY
                position_weight = staged.target_weight
                reason = (
                    reason
                    + " Portfolio-posture staged participation applies: "
                    + staged.reasons[0]
                    + f". Regime={self._portfolio_posture.regime.value}; "
                    + f"posture confidence={self._portfolio_posture.confidence:.0%}; "
                    + f"sleeve={directive.sleeve.value if directive is not None else 'unknown'}; "
                    + f"target={staged.target_weight:.2%}. The target remains subject to "
                    + "independent portfolio construction and paper-execution controls."
                )
        return self._apply_joint_preview_cap(
            candidate,
            action=action,
            position_weight=position_weight,
            reason=reason,
        )


__all__ = ["CompoundingChiefInvestmentOfficer"]
