"""Chief Investment Officer synthesis and final-action authority."""

from __future__ import annotations

from dataclasses import dataclass

from cio.committee import IndependentSpecialistPacket
from cio.models import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    SpecialistPosition,
)
from cio.universe import UniverseAssessment


@dataclass(frozen=True, slots=True)
class CIOSynthesisPolicy:
    """Versioned materiality, evidence, and abstention rules."""

    version: str = "cio-synthesis.v1"
    minimum_evidence_score: float = 0.70
    minimum_evidence_dimension: float = 0.50
    minimum_net_expected_return: float = 0.05
    minimum_opportunity_edge: float = 0.01
    maximum_unresolved_dissent_confidence: float = 0.75
    material_weight_change: float = 0.005
    reduce_threshold: float = 0.0
    exit_threshold: float = -0.05

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "minimum_evidence_score",
            "minimum_evidence_dimension",
            "maximum_unresolved_dissent_confidence",
            "material_weight_change",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if self.exit_threshold >= self.reduce_threshold:
            raise ValueError("exit_threshold must be below reduce_threshold")


class ChiefInvestmentOfficer:
    """Synthesize specialists and issue the sole user-facing investment action.

    This service deliberately does not expose a vote-to-action mapping. Vote and
    confidence statistics inform reliability, while the action follows the
    disclosed evidence, opportunity, dissent, veto, cost, and implementation
    rules below.
    """

    def __init__(
        self,
        policy: CIOSynthesisPolicy | None = None,
    ) -> None:
        self.policy = policy or CIOSynthesisPolicy()

    def synthesize(
        self,
        candidate: CandidateDecisionRecord,
        universe: UniverseAssessment,
        specialists: IndependentSpecialistPacket,
    ) -> CIODecision:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(universe, UniverseAssessment):
            raise TypeError("universe must be a UniverseAssessment")
        if not isinstance(specialists, IndependentSpecialistPacket):
            raise TypeError(
                "specialists must be an IndependentSpecialistPacket"
            )
        if universe.instrument_id != candidate.instrument.instrument_id:
            raise ValueError("universe assessment does not match the candidate")
        specialists.validate_against(candidate)

        dissent = specialists.strongest_dissent()
        evidence_vetoes = specialists.evidence_vetoes
        implementation_blocks = specialists.implementation_blocks
        portfolio = specialists.portfolio_recommendation
        action, position_weight, reason = self._select_action(
            candidate,
            universe=universe,
            specialists=specialists,
        )
        final_confidence = self._confidence(
            candidate,
            specialists=specialists,
            has_dissent=dissent is not None,
        )
        funding_source = (
            portfolio.funding_source
            if action in {
                CIOAction.BUY,
                CIOAction.INCREASE,
                CIOAction.REDUCE,
            }
            else None
        )
        thesis = self._thesis(candidate, action)
        portfolio_impact = self._portfolio_impact(
            candidate,
            action=action,
            position_weight=position_weight,
        )
        opportunity_cost = (
            f"Net expected return is {candidate.net_expected_return:.2%}; "
            f"the best recorded alternative is "
            f"{candidate.opportunity_cost_return:.2%}; "
            f"the cost-adjusted opportunity edge is "
            f"{candidate.opportunity_edge:.2%}."
        )
        explanation = self._explanation(
            candidate,
            action=action,
            reason=reason,
            confidence=final_confidence,
            has_dissent=dissent is not None,
        )
        return CIODecision(
            identifier=(
                f"cio-decision:{candidate.identifier}:{candidate.as_of.isoformat()}"
            ),
            candidate_identifier=candidate.identifier,
            as_of=candidate.as_of,
            schema_version="cio-decision.v1",
            action=action,
            final_confidence=final_confidence,
            expected_return=candidate.net_expected_return,
            decision_horizon_days=candidate.decision_horizon_days,
            recommended_position_weight=position_weight,
            funding_source=funding_source,
            thesis=thesis,
            rationale=reason,
            supporting_evidence=candidate.supporting_evidence,
            contradictory_evidence=candidate.contradictory_evidence,
            key_assumptions=candidate.critical_assumptions,
            catalysts=candidate.primary_catalysts,
            risks=candidate.key_risks,
            invalidation_conditions=candidate.invalidation_conditions,
            portfolio_impact=portfolio_impact,
            opportunity_cost=opportunity_cost,
            dissent=dissent,
            evidence_vetoes=evidence_vetoes,
            implementation_blocks=implementation_blocks,
            monitoring_indicators=candidate.monitoring_indicators,
            review_at=candidate.review_at,
            explanation=explanation,
            policy_version=self.policy.version,
        )

    def _select_action(
        self,
        candidate: CandidateDecisionRecord,
        *,
        universe: UniverseAssessment,
        specialists: IndependentSpecialistPacket,
    ) -> tuple[CIOAction, float | None, str]:
        if not universe.direct_recommendation_allowed:
            return (
                CIOAction.INSUFFICIENT_EVIDENCE,
                None,
                "The instrument is not eligible for a Version 1 direct recommendation: "
                + "; ".join(universe.reasons),
            )
        if specialists.evidence_vetoes:
            return (
                CIOAction.INSUFFICIENT_EVIDENCE,
                None,
                "The Evidence & Governance Officer vetoed the decision: "
                + "; ".join(specialists.evidence_vetoes),
            )
        if (
            candidate.evidence_quality.score
            < self.policy.minimum_evidence_score
            or candidate.evidence_quality.ceiling
            < self.policy.minimum_evidence_dimension
        ):
            return (
                CIOAction.INSUFFICIENT_EVIDENCE,
                None,
                "Evidence quality or one required evidence dimension is below policy threshold.",
            )
        if specialists.implementation_blocks:
            return (
                CIOAction.WATCH,
                None,
                "No valid implementation currently satisfies portfolio constraints: "
                + "; ".join(specialists.implementation_blocks),
            )
        high_confidence_opposition = tuple(
            analysis
            for analysis in specialists.opposing
            if analysis.confidence
            >= self.policy.maximum_unresolved_dissent_confidence
        )
        if high_confidence_opposition:
            roles = ", ".join(item.role.value for item in high_confidence_opposition)
            return (
                CIOAction.WATCH,
                None,
                "Material specialist disagreement remains unresolved across: "
                + roles,
            )

        expected_return = candidate.net_expected_return
        current_weight = candidate.current_portfolio_weight
        portfolio = specialists.portfolio_recommendation

        if current_weight > 0.0 and expected_return <= self.policy.exit_threshold:
            return (
                CIOAction.EXIT,
                0.0,
                "The cost-adjusted expected return is materially negative and no evidence veto prevents action.",
            )
        if current_weight > 0.0 and expected_return < self.policy.reduce_threshold:
            target = portfolio.recommended_position_weight
            if target is None or target >= current_weight:
                target = round(current_weight / 2.0, 8)
            return (
                CIOAction.REDUCE,
                target,
                "The cost-adjusted expected return is negative but does not meet the full-exit threshold.",
            )
        if expected_return < self.policy.minimum_net_expected_return:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "Expected return does not justify increasing the holding, but the evidence does not support a reduction.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The candidate does not satisfy the minimum cost-adjusted expected-return threshold.",
            )
        if candidate.opportunity_edge < self.policy.minimum_opportunity_edge:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The candidate does not improve materially on the recorded alternative use of capital.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The candidate does not offer a material cost-adjusted advantage over the recorded alternative.",
            )
        if portfolio.recommended_position_weight is None:
            return (
                CIOAction.WATCH,
                None,
                "The opportunity is analytically qualified but lacks a feasible portfolio-size proposal.",
            )
        target = min(
            portfolio.recommended_position_weight,
            candidate.maximum_position_weight,
        )
        if target <= 0.0:
            return (
                CIOAction.WATCH,
                None,
                "The portfolio analysis did not identify a positive feasible allocation.",
            )
        if current_weight == 0.0:
            return (
                CIOAction.BUY,
                target,
                "The candidate clears evidence, return, cost, opportunity, and implementation thresholds.",
            )
        difference = target - current_weight
        if difference >= self.policy.material_weight_change:
            return (
                CIOAction.INCREASE,
                target,
                "The candidate remains a superior use of capital and the feasible target is materially above the current weight.",
            )
        if difference <= -self.policy.material_weight_change:
            return (
                CIOAction.REDUCE,
                target,
                "The thesis remains valid, but the feasible target is materially below the current weight.",
            )
        return (
            CIOAction.NO_MATERIAL_CHANGE,
            None,
            "The candidate remains valid but the feasible allocation change is immaterial.",
        )

    def _confidence(
        self,
        candidate: CandidateDecisionRecord,
        *,
        specialists: IndependentSpecialistPacket,
        has_dissent: bool,
    ) -> float:
        # Confidence is a disclosed reliability diagnostic. It does not decide the
        # action and is capped by the weakest evidence dimension.
        calculated = (
            candidate.evidence_quality.score * 0.55
            + specialists.median_confidence * 0.25
            + specialists.support_ratio * 0.20
        )
        calculated = min(calculated, candidate.evidence_quality.ceiling)
        if has_dissent:
            calculated = min(calculated, 0.75)
        if specialists.evidence_vetoes:
            calculated = min(calculated, 0.25)
        if specialists.implementation_blocks:
            calculated = min(calculated, 0.50)
        return round(max(0.0, min(1.0, calculated)), 6)

    @staticmethod
    def _thesis(candidate: CandidateDecisionRecord, action: CIOAction) -> str:
        catalyst = candidate.primary_catalysts[0]
        assumption = candidate.critical_assumptions[0]
        return (
            f"{action.value.replace('_', ' ').title()} {candidate.instrument.symbol}: "
            f"{catalyst}; the decision depends on {assumption}."
        )

    @staticmethod
    def _portfolio_impact(
        candidate: CandidateDecisionRecord,
        *,
        action: CIOAction,
        position_weight: float | None,
    ) -> str:
        if position_weight is None:
            return (
                f"{action.value.replace('_', ' ').title()} without a portfolio "
                "weight change at this decision boundary."
            )
        return (
            f"{action.value.replace('_', ' ').title()} toward a "
            f"{position_weight:.2%} portfolio weight, subject to final execution controls."
        )

    @staticmethod
    def _explanation(
        candidate: CandidateDecisionRecord,
        *,
        action: CIOAction,
        reason: str,
        confidence: float,
        has_dissent: bool,
    ) -> str:
        dissent_text = (
            " Material specialist dissent is preserved in the decision record."
            if has_dissent
            else " No material opposing specialist conclusion remains unresolved."
        )
        return (
            f"What changed: {candidate.primary_catalysts[0]} "
            f"Why it matters: cost-adjusted expected return is "
            f"{candidate.net_expected_return:.2%}, with expected downside of "
            f"{candidate.expected_downside:.2%}. "
            f"CIO decision: {action.value.replace('_', ' ')}. {reason} "
            f"Decision confidence is {confidence:.0%}; this describes evidence "
            f"and process reliability, not a guarantee of return.{dissent_text}"
        )


__all__ = [
    "ChiefInvestmentOfficer",
    "CIOSynthesisPolicy",
]