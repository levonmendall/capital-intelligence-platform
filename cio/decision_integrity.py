"""Final semantic normalization and complete committee handoff for CIO decisions."""

from __future__ import annotations

from dataclasses import replace

from cio.committee import IndependentSpecialistPacket
from cio.models import CIOAction, CIODecision, SpecialistPosition
from cio.service import ChiefInvestmentOfficer as _ChiefInvestmentOfficer


_ZERO_WEIGHT_TOLERANCE = 0.00000001


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for group in groups
            for item in group
            if isinstance(item, str) and item.strip()
        )
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
        ),
        explanation=decision.explanation + committee_explanation,
    )


class ChiefInvestmentOfficer(_ChiefInvestmentOfficer):
    """Canonical CIO service with complete committee-record preservation."""

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
        )
        return normalize_final_decision(enriched)


__all__ = [
    "ChiefInvestmentOfficer",
    "enrich_committee_handoff",
    "normalize_final_decision",
]
