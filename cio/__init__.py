"""Canonical Capital Intelligence CIO decision domain.

The core models and specialist packet are imported eagerly.  Services that
cross the governance boundary are loaded lazily so importing ``governance`` and
``cio`` in either order cannot create a partially initialized circular import.
"""

from __future__ import annotations

from typing import Any

from cio.committee import IndependentSpecialistPacket, SpecialistAnalysis
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
    "ChiefInvestmentOfficer": ("cio.service", "ChiefInvestmentOfficer"),
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
    "DecisionPolicyMatrix": ("cio.policy_matrix", "DecisionPolicyMatrix"),
    "DecisionPolicyProfile": ("cio.policy_matrix", "DecisionPolicyProfile"),
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
    "CIOAction",
    "CIODecision",
    "CIOSynthesisPolicy",
    "CapitalAlternativeComparison",
    "CandidateAssetClass",
    "CandidateDecisionRecord",
    "CandidateInstrument",
    "ChiefInvestmentOfficer",
    "EvidenceDependency",
    "EvidenceQuality",
    "IndependentSpecialistPacket",
    "MaterialDissent",
    "PayoffDistributionPoint",
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
