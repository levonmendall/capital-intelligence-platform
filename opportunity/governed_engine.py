"""Governed opportunity engine for broad research and strict paper ownership.

The production paper policy may classify an analytically strong instrument as
intelligence-only solely because its exact paper-allocation certification is absent.
Such an instrument should still reach the committee and CIO for research, while its
original strict universe assessment must remain attached so the CIO cannot authorize
new or increased exposure.
"""

from __future__ import annotations

from dataclasses import replace

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    UniverseAssessment,
    UniverseDisposition,
)
from opportunity.engine import (
    OpportunityEngine as StrictOpportunityEngine,
    OpportunityQualificationPolicy,
)
from opportunity.models import AnalysisLane


class _ResearchReviewUniversePolicy:
    version = "research-review-universe.v1"

    def evaluate(
        self,
        instrument: CandidateInstrument,
        *,
        as_of=None,
    ) -> UniverseAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be a CandidateInstrument")
        if instrument.asset_class is CandidateAssetClass.OTHER:
            return UniverseAssessment(
                instrument_id=instrument.instrument_id,
                disposition=UniverseDisposition.INELIGIBLE,
                policy_version=self.version,
                reasons=("unclassified instruments remain fail-closed",),
            )
        return UniverseAssessment(
            instrument_id=instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version=self.version,
            reasons=(
                "temporary research-review eligibility; direct portfolio authority is intentionally not granted",
            ),
        )


class OpportunityEngine(StrictOpportunityEngine):
    """Route capable research to review without turning research into authority."""

    def __init__(
        self,
        *,
        universe_policy=None,
        qualification_policy: OpportunityQualificationPolicy | None = None,
        robustness_policy=None,
        policy_matrix=None,
    ) -> None:
        super().__init__(
            universe_policy=universe_policy,
            qualification_policy=qualification_policy,
            robustness_policy=robustness_policy,
            policy_matrix=policy_matrix,
        )
        self._research_engine = StrictOpportunityEngine(
            universe_policy=_ResearchReviewUniversePolicy(),
            qualification_policy=self.policy,
            robustness_policy=self.robust_assessor.policy,
            policy_matrix=self.policy_matrix,
        )

    def _qualify_with_robustness(
        self,
        candidate: CandidateDecisionRecord,
        context,
    ):
        strict_qualification, strict_robustness = super()._qualify_with_robustness(
            candidate,
            context,
        )
        if strict_qualification.qualified:
            return strict_qualification, strict_robustness
        if strict_qualification.universe.direct_recommendation_allowed:
            return strict_qualification, strict_robustness
        if getattr(
            self.universe_policy,
            "market_participation_authority",
            None,
        ) is None:
            return strict_qualification, strict_robustness

        research_qualification, research_robustness = (
            self._research_engine._qualify_with_robustness(candidate, context)
        )
        if not research_qualification.qualified:
            return strict_qualification, strict_robustness

        return (
            replace(
                research_qualification,
                universe=strict_qualification.universe,
                analysis_lane=AnalysisLane.EXPLORATION,
                reasons=tuple(
                    dict.fromkeys(
                        (
                            "candidate merits research-only committee and CIO consideration; direct allocation remains prohibited until exact instrument capability certification is active",
                            *research_qualification.reasons,
                            *strict_qualification.universe.reasons,
                        )
                    )
                ),
            ),
            research_robustness,
        )


__all__ = ["OpportunityEngine"]
