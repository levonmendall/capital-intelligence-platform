"""Final semantic normalization and complete committee handoff for CIO decisions."""

from __future__ import annotations

import json
from dataclasses import replace

from cio.committee import IndependentSpecialistPacket
from cio.models import CIOAction, CIODecision, SpecialistPosition
from cio.service import ChiefInvestmentOfficer as _ChiefInvestmentOfficer


_ZERO_WEIGHT_TOLERANCE = 0.00000001
_DECISION_CONTEXT_PREFIX = "decision-context.v1:"


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for group in groups
            for item in group
            if isinstance(item, str) and item.strip()
        )
    )


def _decision_context_record(
    *,
    decision: CIODecision,
    candidate,
    specialists: IndependentSpecialistPacket,
    policy,
    policy_profile,
) -> str:
    """Encode the complete machine-readable CIO handoff inside the decision record."""

    independence = specialists.evidence_independence
    analyses = tuple(
        {
            "role": item.role.value,
            "position": item.position.value,
            "confidence": item.confidence,
            "dependency_weight": independence.weight_for(item.role),
            "conclusion": item.conclusion,
            "expected_return_impact": item.expected_return_impact,
            "supporting_evidence": list(item.supporting_evidence),
            "contradictory_evidence": list(item.contradictory_evidence),
            "assumptions": list(item.critical_assumptions),
            "risks": list(item.risks),
            "limitations": list(item.limitations),
            "change_conditions": list(item.change_conditions),
            "veto_reasons": list(item.veto_reasons),
            "implementation_blocks": list(item.implementation_blocks),
            "recommended_position_weight": item.recommended_position_weight,
            "funding_source": item.funding_source,
            "evidence_origin_identifiers": list(item.evidence_origin_identifiers),
        }
        for item in specialists.analyses
    )
    opposed = tuple(item for item in analyses if item["position"] == "opposed")
    abstained = tuple(item for item in analyses if item["position"] == "abstain")
    portfolio = specialists.portfolio_recommendation
    profile_maximum_downside = getattr(
        policy_profile,
        "maximum_expected_downside",
        policy.maximum_expected_downside,
    )
    profile_minimum_return = getattr(
        policy_profile,
        "minimum_net_expected_return",
        policy.minimum_net_expected_return,
    )
    profile_minimum_edge = getattr(
        policy_profile,
        "minimum_opportunity_edge",
        policy.minimum_opportunity_edge,
    )
    profile_minimum_probability = getattr(
        policy_profile,
        "minimum_probability_of_success",
        policy.minimum_probability_of_success,
    )
    payload = {
        "schema_version": "cio-self-contained-context.v1",
        "candidate_identifier": decision.candidate_identifier,
        "decision_identifier": decision.identifier,
        "action": decision.action.value,
        "current_portfolio_weight": candidate.current_portfolio_weight,
        "recommended_position_weight": decision.recommended_position_weight,
        "maximum_candidate_weight": candidate.maximum_position_weight,
        "portfolio_feasible_ceiling": portfolio.recommended_position_weight,
        "funding_source": decision.funding_source or portfolio.funding_source,
        "best_alternative_identifier": decision.best_alternative_identifier,
        "effective_opportunity_cost": decision.effective_opportunity_cost,
        "cash_relative_edge": (
            None
            if decision.effective_opportunity_cost is None
            else decision.expected_return - decision.effective_opportunity_cost
        ),
        "benchmark_relative_attractiveness": {
            "status": "unavailable_without_approved_point_in_time_benchmark_return",
            "value": None,
        },
        "portfolio_context": {
            "expected_portfolio_contribution": portfolio.expected_return_impact,
            "implementation_blocks": list(portfolio.implementation_blocks),
            "review_conditions": list(portfolio.change_conditions),
        },
        "committee": {
            "roles": list(analyses),
            "all_opposition": list(opposed),
            "all_abstentions": list(abstained),
            "evidence_vetoes": list(specialists.evidence_vetoes),
            "implementation_blocks": list(specialists.implementation_blocks),
            "dependency_adjusted_support_ratio": (
                specialists.independent_directional_support_ratio
            ),
            "dependency_adjusted_confidence": specialists.independent_confidence,
            "effective_directional_count": specialists.effective_directional_count,
            "evidence_independence_ratio": specialists.evidence_independence_ratio,
        },
        "action_ladder": {
            "buy_or_increase": {
                "requirements": [
                    f"evidence score >= {policy.minimum_evidence_score:.8f}",
                    f"weakest evidence dimension >= {policy.minimum_evidence_dimension:.8f}",
                    f"evidence-adjusted return >= {profile_minimum_return:.8f}",
                    f"probability of success >= {profile_minimum_probability:.8f}",
                    f"opportunity edge >= {profile_minimum_edge:.8f}",
                    f"expected downside >= {profile_maximum_downside:.8f}",
                    "positive stressed edge",
                    "no evidence veto",
                    "no implementation block",
                    "identified funding source",
                    "positive robust supported weight",
                ],
            },
            "hold_or_no_material_change": {
                "requirements": [
                    "ownership thesis remains valid",
                    "no superior replacement clears the reduction threshold",
                    "no emergency evidence or downside condition requires action",
                    f"target change remains below {policy.material_weight_change:.8f}",
                ],
            },
            "reduce": {
                "triggers": [
                    f"expected return below {policy.reduce_threshold:.8f}",
                    f"superior replacement gap >= {policy.holding_replacement_reduce_gap:.8f}",
                    f"evidence-adjusted ownership return below {profile_minimum_return:.8f}",
                    f"expected downside below {profile_maximum_downside:.8f}",
                    "material evidence uncertainty no longer supports full ownership",
                ],
            },
            "exit": {
                "triggers": [
                    f"expected return <= {policy.exit_threshold:.8f}",
                    f"superior replacement gap >= {policy.holding_replacement_exit_gap:.8f}",
                    "complete thesis invalidation or integrity emergency",
                ],
            },
        },
    }
    return _DECISION_CONTEXT_PREFIX + json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def normalize_final_decision(decision: CIODecision) -> CIODecision:
    """Represent a complete liquidation as EXIT rather than REDUCE-to-zero."""

    if not isinstance(decision, CIODecision):
        raise TypeError("decision must be a CIODecision")
    target = decision.recommended_position_weight
    if (
        decision.action is CIOAction.REDUCE
        and target is not None
        and target <= _ZERO_WEIGHT_TOLERANCE
    ):
        return replace(
            decision,
            action=CIOAction.EXIT,
            recommended_position_weight=0.0,
            thesis=decision.thesis.replace("Reduce ", "Exit ", 1),
            rationale=(
                decision.rationale
                + " The final governed target is zero, so the action is normalized "
                "to a complete exit."
            ),
            portfolio_impact=(
                "Exit toward a 0.00% portfolio weight, subject to final execution controls."
            ),
            explanation=decision.explanation.replace(
                "CIO decision: reduce.",
                "CIO decision: exit.",
            ),
        )
    return decision


def enrich_committee_handoff(
    decision: CIODecision,
    specialists: IndependentSpecialistPacket,
    *,
    material_opposition_threshold: float,
    candidate=None,
    policy=None,
    policy_profile=None,
) -> CIODecision:
    """Make the final CIO record self-contained without changing its action."""

    if not isinstance(decision, CIODecision):
        raise TypeError("decision must be a CIODecision")
    if not isinstance(specialists, IndependentSpecialistPacket):
        raise TypeError("specialists must be an IndependentSpecialistPacket")
    if specialists.candidate_identifier != decision.candidate_identifier:
        raise ValueError("specialist packet does not match the CIO decision")

    analyses = specialists.analyses
    role_summaries = tuple(
        (
            f"{item.role.value}: position={item.position.value}; "
            f"confidence={item.confidence:.2%}; conclusion={item.conclusion}"
        )
        for item in analyses
    )
    all_disagreements = tuple(
        (
            f"Committee disagreement from {item.role.value} "
            f"(position {item.position.value}, confidence {item.confidence:.2%}): "
            f"{item.conclusion}; resolution evidence: {'; '.join(item.change_conditions)}"
        )
        for item in analyses
        if item.position in {SpecialistPosition.OPPOSED, SpecialistPosition.ABSTAIN}
    )
    material_opposition = tuple(
        (
            f"Material opposition from {item.role.value} "
            f"(confidence {item.confidence:.2%}): {item.conclusion}; "
            f"resolution evidence: {'; '.join(item.change_conditions)}"
        )
        for item in analyses
        if item.position is SpecialistPosition.OPPOSED
        and item.confidence >= material_opposition_threshold
    )
    context_record = None
    if candidate is not None and policy is not None and policy_profile is not None:
        context_record = _decision_context_record(
            decision=decision,
            candidate=candidate,
            specialists=specialists,
            policy=policy,
            policy_profile=policy_profile,
        )
    committee_explanation = " Committee record: " + " | ".join(role_summaries)
    if material_opposition:
        committee_explanation += (
            " | Preserved material opposition: "
            + " | ".join(material_opposition)
        )

    return replace(
        decision,
        supporting_evidence=_unique(
            decision.supporting_evidence,
            tuple(
                evidence
                for item in analyses
                for evidence in item.supporting_evidence
            ),
            role_summaries,
        ),
        contradictory_evidence=_unique(
            decision.contradictory_evidence,
            tuple(
                evidence
                for item in analyses
                for evidence in item.contradictory_evidence
            ),
            all_disagreements,
            material_opposition,
        ),
        key_assumptions=_unique(
            decision.key_assumptions,
            tuple(
                assumption
                for item in analyses
                for assumption in item.critical_assumptions
            ),
        ),
        risks=_unique(
            decision.risks,
            tuple(risk for item in analyses for risk in item.risks),
            tuple(
                limitation
                for item in analyses
                for limitation in item.limitations
            ),
        ),
        invalidation_conditions=_unique(
            decision.invalidation_conditions,
            tuple(
                condition
                for item in analyses
                for condition in item.change_conditions
            ),
        ),
        monitoring_indicators=_unique(
            decision.monitoring_indicators,
            tuple(
                f"committee:{item.role.value}:{item.position.value}"
                for item in analyses
            ),
            (() if context_record is None else (context_record,)),
        ),
        explanation=decision.explanation + committee_explanation,
    )


class ChiefInvestmentOfficer(_ChiefInvestmentOfficer):
    """Canonical CIO service with complete dependency-aware record preservation."""

    def _confidence(
        self,
        candidate,
        *,
        specialists: IndependentSpecialistPacket,
        has_dissent: bool,
        reconciliation,
    ) -> float:
        """Calculate confidence after discounting shared evidence in every role metric."""

        independence = specialists.evidence_independence
        active = tuple(
            item
            for item in specialists.analyses
            if item.position is not SpecialistPosition.ABSTAIN
        )
        effective_coverage = min(
            1.0,
            sum(independence.weight_for(item.role) for item in active)
            / len(specialists.analyses),
        )
        directional = specialists.independent_directional_support_ratio
        calculated = (
            candidate.evidence_quality.score * 0.35
            + specialists.evidence_confidence * 0.15
            + specialists.implementation_confidence * 0.10
            + specialists.independent_confidence * 0.15
            + directional * 0.15
            + effective_coverage * 0.10
        )
        origin_factor = min(1.0, reconciliation.evidence_origin_count / 4.0)
        calculated *= (
            0.55
            + 0.20 * origin_factor
            + 0.15 * independence.independence_ratio
            + 0.10 * effective_coverage
        )
        calculated = min(calculated, candidate.evidence_quality.ceiling)
        if has_dissent:
            calculated = min(calculated, 0.75)
        if specialists.evidence_vetoes:
            calculated = min(calculated, 0.25)
        if specialists.implementation_blocks:
            calculated = min(calculated, 0.50)
        return round(max(0.0, min(1.0, calculated)), 8)

    def synthesize(
        self,
        candidate,
        universe,
        specialists,
        *,
        capital_comparison=None,
        prior_context=None,
        analysis_lane: str = "acquisition",
    ) -> CIODecision:
        decision = super().synthesize(
            candidate,
            universe,
            specialists,
            capital_comparison=capital_comparison,
            prior_context=prior_context,
            analysis_lane=analysis_lane,
        )
        enriched = enrich_committee_handoff(
            decision,
            specialists,
            material_opposition_threshold=(
                self.policy.maximum_unresolved_dissent_confidence
            ),
            candidate=candidate,
            policy=self.policy,
            policy_profile=self.policy_authority.resolve(candidate),
        )
        return normalize_final_decision(enriched)


__all__ = [
    "ChiefInvestmentOfficer",
    "enrich_committee_handoff",
    "normalize_final_decision",
]
