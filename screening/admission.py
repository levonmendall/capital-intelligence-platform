"""Layered admission rules for mature all-market screening.

Screening admission is deliberately broader than direct-recommendation authority.
A classified instrument with a valid point-in-time identity, active primary listing,
and market metrics may enter preliminary screening even when the strict investment
universe would classify it as intelligence-only or ineligible for allocation.

This module never grants portfolio authority. The strict recommendation policy is
re-applied by the opportunity engine, preserved in the qualification record, and
ultimately enforced by the CIO and construction layers.
"""

from __future__ import annotations

from dataclasses import replace

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    RecommendationUniversePolicy,
    UniverseAssessment,
    UniverseDisposition,
)
from opportunity import AnalysisLane, CandidateQualification
from opportunity.engine import OpportunityEngine as StrictOpportunityEngine


class ScreeningAdmissionPolicy:
    """Admit classified instruments for research without authorizing investment."""

    version = "screening-admission.v1"

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
                reasons=(
                    "unclassified instruments cannot enter governed screening",
                ),
            )
        return UniverseAssessment(
            instrument_id=instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version=self.version,
            reasons=(
                "instrument is admitted for preliminary screening only; this admission grants no committee, CIO, construction, or allocation authority",
            ),
        )


class _ResearchReviewUniversePolicy:
    """Temporary qualification view used only to test research-review merit."""

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


class ResearchReviewOpportunityEngine(StrictOpportunityEngine):
    """Route meritorious non-authorized markets to research-only CIO review.

    The strict universe assessment is always calculated first. When that assessment
    blocks direct recommendation solely at the market-authority boundary, the
    candidate is evaluated a second time for analytical merit. A candidate that
    clears every non-authority qualification control enters the exploration lane,
    while its original strict universe assessment remains attached to the record.
    The CIO therefore receives the research but cannot authorize a new allocation.
    """

    def __init__(
        self,
        *,
        universe_policy: RecommendationUniversePolicy | None = None,
        qualification_policy=None,
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

        research_qualification, research_robustness = (
            self._research_engine._qualify_with_robustness(candidate, context)
        )
        if not research_qualification.qualified:
            return strict_qualification, strict_robustness

        reasons = tuple(
            dict.fromkeys(
                (
                    "candidate merits research-only committee and CIO consideration; direct allocation remains prohibited until strict market capability approval is complete",
                    *research_qualification.reasons,
                    *strict_qualification.universe.reasons,
                )
            )
        )
        return (
            replace(
                research_qualification,
                universe=strict_qualification.universe,
                analysis_lane=AnalysisLane.EXPLORATION,
                reasons=reasons,
            ),
            research_robustness,
        )


__all__ = [
    "ResearchReviewOpportunityEngine",
    "ScreeningAdmissionPolicy",
]
