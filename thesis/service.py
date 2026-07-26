"""Event-driven and scheduled thesis monitoring without portfolio authority."""

from __future__ import annotations

from dataclasses import dataclass

from cio import ThesisState
from thesis.models import (
    LivingThesis,
    ThesisEvidenceUpdate,
    ThesisReview,
    ThesisReviewProposal,
)


@dataclass(frozen=True, slots=True)
class ThesisMonitoringPolicy:
    """Versioned materiality and review-proposal thresholds."""

    version: str = "thesis-monitoring.v1"
    strengthening_return_change: float = 0.03
    weakening_return_change: float = -0.03
    strengthening_confidence_change: float = 0.10
    weakening_confidence_change: float = -0.10
    downside_deterioration: float = -0.10
    reduce_expected_return: float = 0.0
    exit_expected_return: float = -0.05
    replacement_edge: float = 0.03
    decisive_replacement_edge: float = 0.10

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if self.strengthening_return_change <= 0.0:
            raise ValueError("strengthening_return_change must be positive")
        if self.weakening_return_change >= 0.0:
            raise ValueError("weakening_return_change must be negative")
        if self.strengthening_confidence_change <= 0.0:
            raise ValueError("strengthening_confidence_change must be positive")
        if self.weakening_confidence_change >= 0.0:
            raise ValueError("weakening_confidence_change must be negative")
        if self.downside_deterioration >= 0.0:
            raise ValueError("downside_deterioration must be negative")
        if self.exit_expected_return >= self.reduce_expected_return:
            raise ValueError("exit_expected_return must be below reduce threshold")
        if self.replacement_edge <= 0.0:
            raise ValueError("replacement_edge must be positive")
        if self.decisive_replacement_edge <= self.replacement_edge:
            raise ValueError(
                "decisive_replacement_edge must exceed replacement_edge"
            )


class ThesisMonitor:
    """Challenge an active thesis and propose, but never issue, CIO actions."""

    _REVIEWABLE_STATES = {
        ThesisState.ACTIVE,
        ThesisState.STRENGTHENING,
        ThesisState.STABLE,
        ThesisState.WEAKENING,
        ThesisState.REDUCED,
    }

    def __init__(
        self,
        policy: ThesisMonitoringPolicy | None = None,
    ) -> None:
        self.policy = policy or ThesisMonitoringPolicy()

    def evaluate(
        self,
        thesis: LivingThesis,
        update: ThesisEvidenceUpdate,
    ) -> ThesisReview:
        if not isinstance(thesis, LivingThesis):
            raise TypeError("thesis must be a LivingThesis")
        if not isinstance(update, ThesisEvidenceUpdate):
            raise TypeError("update must be a ThesisEvidenceUpdate")
        if update.thesis_identifier != thesis.identifier:
            raise ValueError("update does not match thesis")
        if thesis.state not in self._REVIEWABLE_STATES:
            raise ValueError(
                f"thesis state {thesis.state.value} cannot receive another active review"
            )
        if update.as_of <= thesis.updated_at:
            raise ValueError("update must be later than the current thesis snapshot")

        return_change = round(update.expected_return - thesis.expected_return, 8)
        downside_change = round(
            update.expected_downside - thesis.expected_downside,
            8,
        )
        confidence_change = round(
            update.confidence - thesis.current_confidence,
            8,
        )
        replacement_edge = round(
            update.best_replacement_expected_return - update.expected_return,
            8,
        )
        new_state, proposal, rationale = self._classify(
            thesis,
            update,
            return_change=return_change,
            downside_change=downside_change,
            confidence_change=confidence_change,
            replacement_edge=replacement_edge,
        )
        return ThesisReview(
            identifier=f"thesis-review:{thesis.identifier}:{update.as_of.isoformat()}",
            thesis_identifier=thesis.identifier,
            reviewed_at=update.as_of,
            prior_state=thesis.state,
            new_state=new_state,
            proposal=proposal,
            rationale=rationale,
            evidence_identifiers=update.evidence_identifiers,
            current_expected_return=update.expected_return,
            expected_return_change=return_change,
            current_expected_downside=update.expected_downside,
            downside_change=downside_change,
            current_confidence=update.confidence,
            confidence_change=confidence_change,
            performance_since_approval=update.performance_since_approval,
            replacement_opportunity_edge=replacement_edge,
            triggered_invalidation_conditions=(
                update.triggered_invalidation_conditions
            ),
            required_cio_review=(
                proposal is not ThesisReviewProposal.CONTINUE_MONITORING
            ),
            next_review_at=update.next_review_at,
            policy_version=self.policy.version,
        )

    def _classify(
        self,
        thesis: LivingThesis,
        update: ThesisEvidenceUpdate,
        *,
        return_change: float,
        downside_change: float,
        confidence_change: float,
        replacement_edge: float,
    ) -> tuple[ThesisState, ThesisReviewProposal, str]:
        if update.triggered_invalidation_conditions:
            return (
                ThesisState.INVALIDATED,
                ThesisReviewProposal.INVALIDATE,
                "Explicit thesis invalidation conditions were observed: "
                + "; ".join(update.triggered_invalidation_conditions),
            )
        if not update.data_current:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_EVIDENCE,
                "Required thesis evidence is stale or incomplete; the CIO must review evidence sufficiency before relying on the position.",
            )
        if update.expected_return <= self.policy.exit_expected_return:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_EXIT,
                "The updated expected return is below the exit-review threshold.",
            )
        if replacement_edge >= self.policy.decisive_replacement_edge:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_EXIT,
                "A qualified replacement offers a decisively superior expected return.",
            )
        if update.expected_return < self.policy.reduce_expected_return:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_REDUCE,
                "The updated expected return is negative and requires a CIO reduction review.",
            )
        if replacement_edge >= self.policy.replacement_edge:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_REDUCE,
                "A qualified replacement offers a material expected-return advantage.",
            )

        weakening_reasons: list[str] = []
        if return_change <= self.policy.weakening_return_change:
            weakening_reasons.append("expected return deteriorated materially")
        if confidence_change <= self.policy.weakening_confidence_change:
            weakening_reasons.append("decision confidence deteriorated materially")
        if downside_change <= self.policy.downside_deterioration:
            weakening_reasons.append("expected downside increased materially")
        if update.weakened_indicators:
            weakening_reasons.append(
                "monitoring indicators weakened: "
                + "; ".join(update.weakened_indicators)
            )
        if weakening_reasons:
            return (
                ThesisState.WEAKENING,
                ThesisReviewProposal.REVIEW_REDUCE,
                "; ".join(weakening_reasons) + ".",
            )

        strengthening_reasons: list[str] = []
        if return_change >= self.policy.strengthening_return_change:
            strengthening_reasons.append("expected return improved materially")
        if confidence_change >= self.policy.strengthening_confidence_change:
            strengthening_reasons.append("decision confidence improved materially")
        if update.strengthened_indicators:
            strengthening_reasons.append(
                "monitoring indicators strengthened: "
                + "; ".join(update.strengthened_indicators)
            )
        if strengthening_reasons:
            return (
                ThesisState.STRENGTHENING,
                ThesisReviewProposal.REVIEW_INCREASE,
                "; ".join(strengthening_reasons) + ".",
            )

        return (
            ThesisState.STABLE,
            ThesisReviewProposal.CONTINUE_MONITORING,
            "No material thesis, expected-return, downside, confidence, or replacement-opportunity change was detected.",
        )


__all__ = [
    "ThesisMonitor",
    "ThesisMonitoringPolicy",
]