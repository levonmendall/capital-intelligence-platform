"""Canonical Capital Intelligence CIO decision domain.

The core models and specialist packet are imported eagerly.  Services that
cross the governance boundary are loaded lazily so importing ``governance`` and
``cio`` in either order cannot create a partially initialized circular import.
"""

from __future__ import annotations

from typing import Any

from cio.historical_learning import (
    HistoricalLearningContext,
    HistoricalLearningStatus,
)
from cio.governed_historical_learning import HistoricalLearningResolver
from cio.committee import (
    EvidenceVetoCategory,
    IndependentSpecialistPacket,
    SpecialistAnalysis,
)
from cio.models import (
    CIOAction,
    CIODecision,
    CapitalAlternativeComparison,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceDependency,
    EvidenceQuality,
    MaterialDissent,
    PayoffDistributionPoint,
    PriorDecisionContext,
    ReturnReconciliation,
    ScenarioAdjustment,
    SpecialistReturnAdjustment,
    SpecialistPosition,
    SpecialistRole,
    ThesisState,
)

_LAZY_EXPORTS = {
    "CIOSynthesisPolicy": ("cio.service", "CIOSynthesisPolicy"),
    "ChiefInvestmentOfficer": ("cio.committee_advisory_cio", "ChiefInvestmentOfficer"),
    "RecommendationUniversePolicy": (
        "cio.universe",
        "RecommendationUniversePolicy",
    ),
    "RobustCandidateAssessment": (
        "cio.robustness",
        "RobustCandidateAssessment",
    ),
    "RobustCandidateAssessor": ("cio.robustness", "RobustCandidateAssessor"),
    "RobustDecisionPolicy": ("cio.robustness", "RobustDecisionPolicy"),
    "SpecialistReconciliationPolicy": (
        "cio.reconciliation",
        "SpecialistReconciliationPolicy",
    ),
    "SpecialistReturnReconciler": (
        "cio.reconciliation",
        "SpecialistReturnReconciler",
    ),
    "UniverseAssessment": ("cio.universe", "UniverseAssessment"),
    "UniverseDisposition": ("cio.universe", "UniverseDisposition"),
    "CanonicalDecisionPolicyAuthority": ("cio.policy_authority", "CanonicalDecisionPolicyAuthority"),
    "EvidenceOutageAssessment": ("cio.evidence_outage", "EvidenceOutageAssessment"),
    "EvidenceOutageAuthority": ("cio.evidence_outage", "EvidenceOutageAuthority"),
    "EvidenceOutageDisposition": ("cio.evidence_outage", "EvidenceOutageDisposition"),
    "EvidenceOutagePolicy": ("cio.evidence_outage", "EvidenceOutagePolicy"),
    "DecisionPolicyMatrix": ("cio.policy_matrix", "DecisionPolicyMatrix"),
    "DecisionPolicyProfile": ("cio.policy_matrix", "DecisionPolicyProfile"),
    "AdaptiveRobustGrowthEnsemble": ("cio.growth_ensemble", "AdaptiveRobustGrowthEnsemble"),
    "GrowthEnsembleAssessment": ("cio.growth_ensemble", "GrowthEnsembleAssessment"),
    "GrowthEnsemblePolicy": ("cio.growth_ensemble", "GrowthEnsemblePolicy"),
    "GrowthStage": ("cio.growth_ensemble", "GrowthStage"),
    "ChampionChallengerRegistry": ("cio.policy_governance", "ChampionChallengerRegistry"),
    "PolicyPerformanceEvidence": ("cio.policy_governance", "PolicyPerformanceEvidence"),
    "PolicyPromotionDecision": ("cio.policy_governance", "PolicyPromotionDecision"),
    "PolicyPromotionPolicy": ("cio.policy_governance", "PolicyPromotionPolicy"),
    "PolicyVersionCandidate": ("cio.policy_governance", "PolicyVersionCandidate"),
    "PolicyVersionStatus": ("cio.policy_governance", "PolicyVersionStatus"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'cio' has no attribute {name!r}")
    module_name, attribute_name = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "AdaptiveRobustGrowthEnsemble",
    "CIOAction",
    "ChampionChallengerRegistry",
    "CIODecision",
    "CIOSynthesisPolicy",
    "CapitalAlternativeComparison",
    "CanonicalDecisionPolicyAuthority",
    "CandidateAssetClass",
    "CandidateDecisionRecord",
    "CandidateInstrument",
    "ChiefInvestmentOfficer",
    "EvidenceDependency",
    "EvidenceOutageAssessment",
    "EvidenceOutageAuthority",
    "EvidenceOutageDisposition",
    "EvidenceOutagePolicy",
    "EvidenceQuality",
    "EvidenceVetoCategory",
    "HistoricalLearningContext",
    "HistoricalLearningResolver",
    "HistoricalLearningStatus",
    "GrowthEnsembleAssessment",
    "GrowthEnsemblePolicy",
    "GrowthStage",
    "IndependentSpecialistPacket",
    "MaterialDissent",
    "PayoffDistributionPoint",
    "PolicyPerformanceEvidence",
    "PolicyPromotionDecision",
    "PolicyPromotionPolicy",
    "PolicyVersionCandidate",
    "PolicyVersionStatus",
    "PriorDecisionContext",
    "RecommendationUniversePolicy",
    "ReturnReconciliation",
    "ScenarioAdjustment",
    "RobustCandidateAssessment",
    "RobustCandidateAssessor",
    "RobustDecisionPolicy",
    "SpecialistAnalysis",
    "SpecialistReconciliationPolicy",
    "SpecialistReturnAdjustment",
    "SpecialistReturnReconciler",
    "SpecialistPosition",
    "SpecialistRole",
    "ThesisState",
    "UniverseAssessment",
    "UniverseDisposition",
    "DecisionPolicyMatrix",
    "DecisionPolicyProfile",
]
