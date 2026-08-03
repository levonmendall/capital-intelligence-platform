"""Chief Investment Officer synthesis and final-action authority."""

from __future__ import annotations

from dataclasses import dataclass, replace

from cio.committee import EvidenceVetoCategory, IndependentSpecialistPacket
from cio.growth_ensemble import (
    AdaptiveRobustGrowthEnsemble,
    GrowthEnsembleAssessment,
    GrowthStage,
)
from cio.models import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    CapitalAlternativeComparison,
    PriorDecisionContext,
    ReturnReconciliation,
    SpecialistPosition,
)
from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
from cio.reconciliation import (
    SpecialistReconciliationPolicy,
    SpecialistReturnReconciler,
)
from cio.robustness import (
    RobustCandidateAssessment,
    RobustCandidateAssessor,
    RobustDecisionPolicy,
)
from cio.universe import UniverseAssessment


@dataclass(frozen=True, slots=True)
class CIOSynthesisPolicy:
    """Versioned materiality, evidence, and abstention rules."""

    version: str = "cio-synthesis.v9-independent-evidence"
    minimum_evidence_score: float = 0.70
    minimum_evidence_dimension: float = 0.50
    minimum_net_expected_return: float = 0.05
    minimum_opportunity_edge: float = 0.01
    minimum_probability_of_success: float = 0.55
    maximum_expected_downside: float = -0.35
    maximum_unresolved_dissent_confidence: float = 0.75
    material_weight_change: float = 0.005
    reduce_threshold: float = 0.0
    exit_threshold: float = -0.05
    holding_replacement_reduce_gap: float = 0.01
    holding_replacement_exit_gap: float = 0.05

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "minimum_evidence_score",
            "minimum_evidence_dimension",
            "minimum_probability_of_success",
            "maximum_unresolved_dissent_confidence",
            "material_weight_change",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if self.exit_threshold >= self.reduce_threshold:
            raise ValueError("exit_threshold must be below reduce_threshold")
        if self.maximum_expected_downside > 0.0:
            raise ValueError("maximum_expected_downside must be zero or negative")
        if self.minimum_net_expected_return <= -1.0:
            raise ValueError("minimum_net_expected_return must exceed -100%")
        if self.minimum_opportunity_edge < 0.0:
            raise ValueError("minimum_opportunity_edge cannot be negative")
        if self.holding_replacement_reduce_gap < 0.0:
            raise ValueError("holding_replacement_reduce_gap cannot be negative")
        if (
            self.holding_replacement_exit_gap
            <= self.holding_replacement_reduce_gap
        ):
            raise ValueError(
                "holding_replacement_exit_gap must exceed the reduce gap"
            )


class ChiefInvestmentOfficer:
    """Synthesize specialists and issue the sole user-facing investment action.

    The service does not expose a vote-to-action mapping.  Positive capital
    actions must clear evidence, opportunity, implementation, geometric-return,
    uncertainty, and adverse-probability stress controls.  Negative ownership
    actions remain available when a current holding has deteriorated.
    """

    def __init__(
        self,
        policy: CIOSynthesisPolicy | None = None,
        *,
        robustness_policy: RobustDecisionPolicy | None = None,
        reconciliation_policy: SpecialistReconciliationPolicy | None = None,
        policy_matrix: DecisionPolicyMatrix | None = None,
        growth_ensemble: AdaptiveRobustGrowthEnsemble | None = None,
    ) -> None:
        self.policy = policy or CIOSynthesisPolicy()
        self.robust_assessor = RobustCandidateAssessor(robustness_policy)
        self.reconciler = SpecialistReturnReconciler(reconciliation_policy)
        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()
        self.growth_ensemble = growth_ensemble or AdaptiveRobustGrowthEnsemble()

    def synthesize(
        self,
        candidate: CandidateDecisionRecord,
        universe: UniverseAssessment,
        specialists: IndependentSpecialistPacket,
        *,
        capital_comparison: CapitalAlternativeComparison | None = None,
        prior_context: PriorDecisionContext | None = None,
        analysis_lane: str = "acquisition",
    ) -> CIODecision:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(universe, UniverseAssessment):
            raise TypeError("universe must be an UniverseAssessment")
        if not isinstance(specialists, IndependentSpecialistPacket):
            raise TypeError(
                "specialists must be an IndependentSpecialistPacket"
            )
        if universe.instrument_id != candidate.instrument.instrument_id:
            raise ValueError("universe assessment does not match the candidate")
        specialists.validate_against(candidate)
        if capital_comparison is not None:
            if not isinstance(capital_comparison, CapitalAlternativeComparison):
                raise TypeError("capital_comparison must be CapitalAlternativeComparison")
            if capital_comparison.candidate_identifier != candidate.identifier:
                raise ValueError("capital comparison does not match candidate")
        if prior_context is not None:
            if not isinstance(prior_context, PriorDecisionContext):
                raise TypeError("prior_context must be PriorDecisionContext")
            if prior_context.candidate_identifier != candidate.identifier:
                raise ValueError("prior decision context does not match candidate")
        profile = self.policy_matrix.resolve(candidate)
        effective_alternative = (
            candidate.opportunity_cost_return
            if capital_comparison is None
            else capital_comparison.effective_opportunity_cost
        )
        best_alternative_identifier = (
            None
            if capital_comparison is None
            else capital_comparison.best_alternative_identifier
        )

        reconciliation = self.reconciler.reconcile(
            candidate,
            specialists,
            alternative_return=effective_alternative,
        )
        robustness_candidate = self._robustness_candidate(
            candidate,
            reconciliation,
        )
        portfolio_cap = specialists.portfolio_recommendation.recommended_position_weight
        assessment_cap = (
            min(
                portfolio_cap,
                candidate.maximum_position_weight,
                profile.maximum_position_weight,
            )
            if portfolio_cap is not None and portfolio_cap > 0.0
            else (
                candidate.current_portfolio_weight
                if candidate.current_portfolio_weight > 0.0
                else min(candidate.maximum_position_weight, profile.maximum_position_weight)
            )
        )
        historical_learning = specialists.historical_learning
        # Historical calibration is applied once to the final feasible cap.
        assessment_cap = round(assessment_cap, 8)
        progressive_lane = str(analysis_lane).lower() in {
            "participation",
            "exploration",
        }
        supported_weight = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=assessment_cap,
            policy_profile=profile,
            allow_soft_failures=False,
        )
        assessment_weight = (
            supported_weight
            if supported_weight > 0.0
            else min(
                self.robust_assessor.policy.minimum_reference_weight,
                assessment_cap,
            )
        )
        robustness = self.robust_assessor.assess(
            robustness_candidate,
            alternative_return=effective_alternative,
            position_weight=assessment_weight,
            policy_profile=profile,
        )
        ensemble = self.growth_ensemble.assess(
            candidate,
            specialists,
            robustness,
            profile,
            analysis_lane=analysis_lane,
        )
        dissent = specialists.strongest_dissent()
        evidence_vetoes = specialists.evidence_vetoes
        implementation_blocks = specialists.implementation_blocks
        portfolio = specialists.portfolio_recommendation
        action, position_weight, reason = self._select_action(
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
        )
        selected_action = action
        action, position_weight, reason, hysteresis_applied, persistence_cycles = (
            self._apply_hysteresis(
                candidate,
                action=action,
                position_weight=position_weight,
                reason=reason,
                prior_context=prior_context,
                profile=profile,
                progressive_lane=progressive_lane,
                emergency=(
                    specialists.has_emergency_evidence_veto
                    or reconciliation.expected_return <= self.policy.exit_threshold
                    or reconciliation.expected_downside < profile.maximum_expected_downside
                ),
            )
        )
        reason = (
            f"{reason} Growth ensemble: {ensemble.explanation} "
            f"Committee evidence resolves to {specialists.effective_directional_count:.2f} "
            f"effective independent directional views from "
            f"{len(specialists.directional_active)} active roles."
        )
        if historical_learning.status.value != "not_applicable":
            reason = f"{reason} {historical_learning.summary}"
        final_confidence = self._confidence(
            candidate,
            specialists=specialists,
            has_dissent=dissent is not None,
            reconciliation=reconciliation,
        )
        funding_source = (
            portfolio.funding_source
            if action in {CIOAction.BUY, CIOAction.INCREASE}
            else None
        )
        thesis = self._thesis(candidate, action)
        portfolio_impact = self._portfolio_impact(
            candidate,
            action=action,
            position_weight=position_weight,
        )
        opportunity_cost = (
            f"Original arithmetic net expected return is {candidate.net_expected_return:.2%}; "
            f"specialist-reconciled expected return is {reconciliation.expected_return:.2%}; "
            f"the governing best alternative "
            f"{best_alternative_identifier or 'recorded baseline'} returns "
            f"{effective_alternative:.2%} annualized; "
            f"the reconciled horizon-normalized arithmetic edge is "
            f"{reconciliation.expected_return - reconciliation.horizon_alternative_return:.2%}. "
            f"After geometric compounding, evidence shrinkage, uncertainty, and "
            f"adverse-probability stress, the robust edge is "
            f"{robustness.robust_edge:.2%} and the stressed edge is "
            f"{robustness.stressed_edge:.2%}."
        )
        opportunity_cost += (
            " Historical-learning control: " + historical_learning.summary
        )
        explanation = self._explanation(
            candidate,
            action=action,
            reason=reason,
            confidence=final_confidence,
            has_dissent=dissent is not None,
            robustness=robustness,
            reconciliation=reconciliation,
        )
        if historical_learning.status.value != "not_applicable":
            explanation += " Historical learning: " + historical_learning.summary
        return CIODecision(
            identifier=(
                f"cio-decision:{candidate.identifier}:{candidate.as_of.isoformat()}"
            ),
            candidate_identifier=candidate.identifier,
            as_of=candidate.as_of,
            schema_version="cio-decision.v3",
            action=action,
            final_confidence=final_confidence,
            expected_return=reconciliation.expected_return,
            decision_horizon_days=candidate.decision_horizon_days,
            recommended_position_weight=position_weight,
            funding_source=funding_source,
            thesis=thesis,
            rationale=reason,
            supporting_evidence=tuple(
                dict.fromkeys(
                    candidate.supporting_evidence
                    + (historical_learning.summary,)
                )
            ),
            contradictory_evidence=candidate.contradictory_evidence,
            key_assumptions=candidate.critical_assumptions,
            catalysts=candidate.primary_catalysts,
            risks=tuple(
                dict.fromkeys(candidate.key_risks + historical_learning.limitations)
            ),
            invalidation_conditions=candidate.invalidation_conditions,
            portfolio_impact=portfolio_impact,
            opportunity_cost=opportunity_cost,
            dissent=dissent,
            evidence_vetoes=evidence_vetoes,
            implementation_blocks=implementation_blocks,
            monitoring_indicators=tuple(
                dict.fromkeys(
                    candidate.monitoring_indicators
                    + ("historical_learning_calibration",)
                )
            ),
            review_at=candidate.review_at,
            explanation=explanation,
            policy_version=self.policy.version,
            return_reconciliation=reconciliation,
            best_alternative_identifier=best_alternative_identifier,
            effective_opportunity_cost=effective_alternative,
            prior_decision_identifier=(
                None if prior_context is None else prior_context.prior_decision_identifier
            ),
            persistence_cycles=persistence_cycles,
            hysteresis_applied=hysteresis_applied,
            deferred_action=(
                selected_action if hysteresis_applied else None
            ),
            resolved_policy_profile=profile.identifier,
            policy_matrix_version=self.policy_matrix.version,
        )

    def _select_action(
        self,
        candidate: CandidateDecisionRecord,
        *,
        universe: UniverseAssessment,
        specialists: IndependentSpecialistPacket,
        robustness: RobustCandidateAssessment,
        robustness_candidate: CandidateDecisionRecord,
        reconciliation: ReturnReconciliation,
        effective_alternative: float,
        profile: DecisionPolicyProfile,
        analysis_lane: str,
        ensemble: GrowthEnsembleAssessment,
    ) -> tuple[CIOAction, float | None, str]:
        current_weight = candidate.current_portfolio_weight
        portfolio = specialists.portfolio_recommendation
        evidence_deficient = bool(specialists.evidence_vetoes) or (
            candidate.evidence_quality.score < self.policy.minimum_evidence_score
            or candidate.evidence_quality.ceiling
            < self.policy.minimum_evidence_dimension
        )
        if evidence_deficient:
            detail = (
                "; ".join(specialists.evidence_vetoes)
                if specialists.evidence_vetoes
                else "evidence quality or one required evidence dimension is below policy threshold"
            )
            if current_weight > 0.0:
                if specialists.has_operational_only_evidence_veto:
                    return (
                        CIOAction.HOLD,
                        None,
                        "New or increased exposure is prohibited, but the existing holding is preserved while an operational evidence outage is repaired: "
                        + detail,
                    )
                target = self._conservative_reduction_target(
                    current_weight=current_weight,
                    proposed_weight=portfolio.recommended_position_weight,
                )
                categories = set(specialists.evidence_veto_categories)
                if categories.intersection(
                    {
                        EvidenceVetoCategory.THESIS_CONTRADICTION,
                        EvidenceVetoCategory.INTEGRITY_EMERGENCY,
                    }
                ):
                    classification = (
                        "a thesis contradiction or evidence-integrity emergency"
                    )
                else:
                    classification = "material evidence uncertainty"
                return (
                    CIOAction.REDUCE,
                    target,
                    "New or increased exposure is prohibited and the existing holding is reduced because "
                    + classification
                    + " no longer supports its full ownership case: "
                    + detail,
                )
            return CIOAction.INSUFFICIENT_EVIDENCE, None, detail

        expected_return = reconciliation.expected_return
        holding_risk_return = min(candidate.net_expected_return, expected_return)
        arithmetic_edge = round(
            expected_return - reconciliation.horizon_alternative_return, 8
        )
        opportunity_edge = robustness.robust_edge
        replacement_gap = round(
            max(-arithmetic_edge, -opportunity_edge),
            8,
        )

        if current_weight > 0.0 and (
            holding_risk_return <= self.policy.exit_threshold
            or replacement_gap >= self.policy.holding_replacement_exit_gap
        ):
            reason = (
                "The cost-adjusted expected return is materially negative."
                if holding_risk_return <= self.policy.exit_threshold
                else "A feasible alternative exceeds the holding by the full-replacement opportunity-cost threshold after horizon normalization."
            )
            return CIOAction.EXIT, 0.0, reason

        if current_weight > 0.0 and (
            holding_risk_return < self.policy.reduce_threshold
            or replacement_gap >= self.policy.holding_replacement_reduce_gap
            or robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
            or reconciliation.expected_downside < profile.maximum_expected_downside
        ):
            target = self._conservative_reduction_target(
                current_weight=current_weight,
                proposed_weight=portfolio.recommended_position_weight,
            )
            if replacement_gap >= self.policy.holding_replacement_reduce_gap:
                reason = (
                    "The holding remains positive in isolation, but a feasible alternative is materially superior after costs and horizon normalization."
                )
            elif (
                robustness.evidence_adjusted_return
                < profile.minimum_net_expected_return
            ):
                reason = "The holding no longer clears the absolute ownership-return hurdle."
            elif reconciliation.expected_downside < profile.maximum_expected_downside:
                reason = "The reconciled downside exceeds the ownership-risk limit."
            else:
                reason = "The cost-adjusted expected return is negative but does not meet the full-exit threshold."
            return CIOAction.REDUCE, target, reason

        if not universe.direct_recommendation_allowed:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The instrument remains under review, but policy prohibits new or increased direct exposure: "
                    + "; ".join(universe.reasons),
                )
            return (
                CIOAction.INSUFFICIENT_EVIDENCE,
                None,
                "The instrument is not eligible for new or increased exposure: "
                + "; ".join(universe.reasons),
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
        independent_opposition = specialists.independent_opposition_count(
            self.policy.maximum_unresolved_dissent_confidence
        )
        progressive_lane = str(analysis_lane).lower() in {
            "participation",
            "exploration",
        }
        if high_confidence_opposition and (
            (not progressive_lane and independent_opposition >= 1)
            or independent_opposition >= 2
        ):
            roles = ", ".join(item.role.value for item in high_confidence_opposition)
            return (
                CIOAction.WATCH,
                None,
                "Material specialist disagreement remains unresolved across: "
                + roles,
            )

        if (
            robustness.effective_probability_of_success
            < profile.minimum_probability_of_success
        ):
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The reconciled distribution does not support increasing the holding at the required success probability.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The reconciled probability of outperforming the best alternative is below policy.",
            )
        if (
            robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
        ):
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The holding remains owned, but its reconciled return does not clear the absolute hurdle for additional capital.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The specialist-reconciled return is below the horizon-normalized absolute return hurdle.",
            )
        if reconciliation.expected_downside < profile.maximum_expected_downside:
            if current_weight > 0.0:
                return CIOAction.HOLD, None, "Downside risk blocks any increase."
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The reconciled downside exceeds the acquisition limit.",
            )
        if opportunity_edge < profile.minimum_opportunity_edge:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The holding is not sufficiently superior to justify more capital, but the replacement gap is not large enough to force a reduction.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The candidate does not offer a material cost-adjusted advantage over the recorded alternative.",
            )

        if robustness.stressed_edge <= 0.0:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The holding is preserved, but adverse probability stress removes its positive edge and blocks additional capital.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The candidate does not retain a positive economic edge after adverse scenario-probability stress.",
            )

        if portfolio.recommended_position_weight is None:
            return (
                CIOAction.WATCH,
                None,
                "The opportunity is analytically qualified but lacks a feasible portfolio-size ceiling.",
            )
        if portfolio.funding_source is None and (
            current_weight == 0.0
            or portfolio.recommended_position_weight > current_weight
        ):
            return (
                CIOAction.WATCH,
                None,
                "A positive allocation is not authorized until its exact funding source is identified.",
            )

        feasible_cap = min(
            portfolio.recommended_position_weight,
            candidate.maximum_position_weight,
            profile.maximum_position_weight,
        )
        feasible_cap = round(
            feasible_cap
            * specialists.historical_learning.effective_position_multiplier,
            8,
        )
        if feasible_cap <= 0.0:
            return (
                CIOAction.WATCH,
                None,
                "The portfolio analysis did not identify a positive feasible allocation.",
            )
        if progressive_lane and ensemble.stage is GrowthStage.OBSERVE:
            return (
                CIOAction.WATCH,
                None,
                "Independent return engines do not yet support even an exploratory allocation.",
            )
        growth_cap = (
            min(feasible_cap, ensemble.maximum_target_weight or feasible_cap)
            if progressive_lane
            else feasible_cap
        )
        robust_cap = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=growth_cap,
            policy_profile=profile,
            allow_soft_failures=False,
        )
        if robust_cap <= 0.0:
            reason = (
                "Positive allocation is blocked by robust decision controls: "
                + "; ".join(robustness.reasons)
            )
            if current_weight > 0.0:
                target = min(current_weight, robust_cap)
                if target < current_weight - self.policy.material_weight_change:
                    return CIOAction.REDUCE, target, reason
                return CIOAction.HOLD, None, reason
            return CIOAction.NO_SUPERIOR_OPPORTUNITY, None, reason

        target = self._confidence_aware_target(
            robust_cap=robust_cap,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
            progressive_lane=progressive_lane,
        )
        if target <= 0.0:
            return (
                CIOAction.WATCH,
                None,
                "The reconciled uncertainty supports no positive allocation.",
            )
        if current_weight == 0.0:
            return (
                CIOAction.BUY,
                target,
                "The candidate clears evidence, absolute return, geometric compounding, uncertainty, downside, opportunity, funding, and implementation thresholds at the final target weight.",
            )
        difference = target - current_weight
        if difference >= self.policy.material_weight_change:
            return (
                CIOAction.INCREASE,
                target,
                "The holding remains a robust superior use of capital and the final reconciled target is materially above the current weight.",
            )
        if difference <= -self.policy.material_weight_change:
            return (
                CIOAction.REDUCE,
                target,
                "The thesis remains valid, but final reconciled robustness supports a materially smaller position.",
            )
        return (
            CIOAction.NO_MATERIAL_CHANGE,
            None,
            "The holding remains valid and the final reconciled allocation change is immaterial.",
        )

    def _apply_hysteresis(
        self,
        candidate: CandidateDecisionRecord,
        *,
        action: CIOAction,
        position_weight: float | None,
        reason: str,
        prior_context: PriorDecisionContext | None,
        profile: DecisionPolicyProfile,
        progressive_lane: bool,
        emergency: bool,
    ) -> tuple[CIOAction, float | None, str, bool, int]:
        """Require persistent evidence for non-urgent portfolio changes."""

        if emergency or (
            prior_context is not None and prior_context.emergency_override
        ):
            cycles = (
                1
                if prior_context is None
                else max(1, prior_context.consecutive_opposing_cycles + 1)
            )
            return action, position_weight, reason, False, cycles

        # The resolved policy profile is the sole persistence authority.  A first
        # valid observation counts as cycle one rather than bypassing the profile.
        required = 1
        observed = 1
        if action is CIOAction.BUY:
            required = (
                1
                if progressive_lane
                else max(1, profile.entry_persistence_cycles)
            )
            if prior_context is not None:
                observed = prior_context.consecutive_supportive_cycles + 1
        elif action is CIOAction.INCREASE:
            required = max(1, profile.increase_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_supportive_cycles + 1
        elif action in {CIOAction.REDUCE, CIOAction.EXIT}:
            required = max(1, profile.reduce_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_opposing_cycles + 1

        cooldown_active = False
        if (
            prior_context is not None
            and prior_context.last_material_change_at is not None
            and profile.cooldown_days > 0
        ):
            elapsed = (candidate.as_of - prior_context.last_material_change_at).days
            cooldown_active = elapsed < profile.cooldown_days
        if required <= 1 and not cooldown_active:
            return action, position_weight, reason, False, observed
        if observed >= required and not cooldown_active:
            return action, position_weight, reason, False, observed

        remaining = max(0, required - observed)
        detail = (
            f" Action is deferred by hysteresis: {observed}/{required} persistent "
            "cycles are confirmed"
        )
        if remaining:
            detail += f"; {remaining} additional cycle(s) are required"
        if cooldown_active:
            detail += f"; the {profile.cooldown_days}-day cooldown remains active"
        detail += "."
        if candidate.current_portfolio_weight > 0.0:
            deferred = (
                CIOAction.HOLD
                if action in {CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT}
                else CIOAction.NO_MATERIAL_CHANGE
            )
        else:
            deferred = CIOAction.WATCH
        return deferred, None, reason + detail, True, observed

    @staticmethod
    def _conservative_reduction_target(
        *,
        current_weight: float,
        proposed_weight: float | None,
    ) -> float:
        target = round(current_weight / 2.0, 8)
        if proposed_weight is not None and proposed_weight < current_weight:
            target = min(target, proposed_weight)
        return round(max(0.0, target), 8)

    def _confidence_aware_target(
        self,
        *,
        robust_cap: float,
        robustness: RobustCandidateAssessment,
        reconciliation: ReturnReconciliation,
        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
        progressive_lane: bool,
    ) -> float:
        # RobustCandidateAssessor already incorporates evidence shrinkage,
        # probability consistency, downside, edge and stress.  Do not charge the
        # same uncertainty again through three independent minimum scales.
        if not progressive_lane:
            return round(max(0.0, robust_cap), 8)
        target = robust_cap * max(0.20, min(1.0, ensemble.target_multiplier))
        if ensemble.stage is not GrowthStage.OBSERVE:
            target = max(
                target,
                min(robust_cap, ensemble.minimum_target_weight),
            )
        if progressive_lane and ensemble.maximum_target_weight > 0.0:
            target = min(target, ensemble.maximum_target_weight)
        return round(max(0.0, target), 8)

    def _confidence(
        self,
        candidate: CandidateDecisionRecord,
        *,
        specialists: IndependentSpecialistPacket,
        has_dissent: bool,
        reconciliation: ReturnReconciliation,
    ) -> float:
        directional = specialists.independent_directional_support_ratio
        independence = specialists.evidence_independence
        calculated = (
            candidate.evidence_quality.score * 0.35
            + specialists.evidence_confidence * 0.15
            + specialists.implementation_confidence * 0.10
            + specialists.independent_confidence * 0.15
            + directional * 0.15
            + specialists.coverage_ratio * 0.10
        )
        origin_factor = min(1.0, reconciliation.evidence_origin_count / 4.0)
        calculated *= (
            0.55
            + 0.20 * origin_factor
            + 0.15 * independence.independence_ratio
            + 0.10 * specialists.coverage_ratio
        )
        calculated = min(calculated, candidate.evidence_quality.ceiling)
        if has_dissent:
            calculated = min(calculated, 0.75)
        if specialists.evidence_vetoes:
            calculated = min(calculated, 0.25)
        if specialists.implementation_blocks:
            calculated = min(calculated, 0.50)
        calculated = min(
            calculated,
            specialists.historical_learning.confidence_ceiling,
        )
        return round(max(0.0, min(1.0, calculated)), 6)

    @staticmethod
    def _robustness_candidate(
        candidate: CandidateDecisionRecord,
        reconciliation: ReturnReconciliation,
    ) -> CandidateDecisionRecord:
        by_label = {item.label.lower(): item for item in reconciliation.outcomes}
        updates = {
            "payoff_distribution": reconciliation.outcomes,
            "probability_of_success": reconciliation.probability_of_success,
            "expected_downside": reconciliation.expected_downside,
        }
        if {"base", "bull", "bear"}.issubset(by_label):
            updates.update(
                base_case_return=by_label["base"].total_return,
                bull_case_return=by_label["bull"].total_return,
                bear_case_return=by_label["bear"].total_return,
                base_case_probability=by_label["base"].probability,
                bull_case_probability=by_label["bull"].probability,
                bear_case_probability=by_label["bear"].probability,
            )
        return replace(candidate, **updates)

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
        robustness: RobustCandidateAssessment,
        reconciliation: ReturnReconciliation,
    ) -> str:
        dissent_text = (
            " Material specialist dissent is preserved in the decision record."
            if has_dissent
            else " No material opposing specialist conclusion remains unresolved."
        )
        return (
            f"What changed: {candidate.primary_catalysts[0]} "
            f"Why it matters: original cost-adjusted expected return is "
            f"{candidate.net_expected_return:.2%}; specialist-reconciled expected return is "
            f"{reconciliation.expected_return:.2%}, reconciled downside is "
            f"{reconciliation.expected_downside:.2%}, reconciled success probability is "
            f"{reconciliation.probability_of_success:.0%}, robust edge is "
            f"{robustness.robust_edge:.2%}, and stressed edge is "
            f"{robustness.stressed_edge:.2%}. "
            f"CIO decision: {action.value.replace('_', ' ')}. {reason} "
            f"Decision confidence is {confidence:.0%}; this describes evidence "
            f"and process reliability, not a guarantee of return.{dissent_text}"
        )


__all__ = [
    "ChiefInvestmentOfficer",
    "CIOSynthesisPolicy",
]
