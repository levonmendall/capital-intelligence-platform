from committee.cio import (
    CIOAction,
    CIODecision,
    CIOSynthesisPolicy,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    ChiefInvestmentOfficer,
    EvidenceQuality,
    IndependentSpecialistPacket,
    RecommendationUniversePolicy,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistRole,
    UniverseAssessment,
    UniverseDisposition,
)
from committee.consensus import CommitteeConsensus
from committee.decision_discipline import (
    DissentDisposition,
    DissentRegister,
    NoActionDecision,
    NoActionReason,
    StructuredDissent,
)
from committee.meeting import CommitteeMeeting, InvestmentCommittee
from committee.member import CommitteeMember
from committee.opinion import CommitteeOpinion
from committee.regime_governance import (
    RegimeCommitteeDecision,
    RegimeGovernanceOutcome,
    RegimeGovernancePolicy,
    RegimeGovernanceWorkflow,
    build_regime_recommendation,
)

# Install the governed specialist adapter before callers import
# ``committee.specialists.IndependentSpecialistService``. This preserves the
# canonical import surface while strengthening evidence coverage and handoff.
from committee import specialists as _specialists
from committee.review_integrity import (
    IndependentSpecialistService as _GovernedIndependentSpecialistService,
)

_specialists.IndependentSpecialistService = _GovernedIndependentSpecialistService


__all__ = [
    "CIOAction",
    "CIODecision",
    "CIOSynthesisPolicy",
    "CandidateAssetClass",
    "CandidateDecisionRecord",
    "CandidateInstrument",
    "ChiefInvestmentOfficer",
    "CommitteeConsensus",
    "CommitteeMeeting",
    "CommitteeMember",
    "CommitteeOpinion",
    "DissentDisposition",
    "DissentRegister",
    "EvidenceQuality",
    "IndependentSpecialistPacket",
    "InvestmentCommittee",
    "NoActionDecision",
    "NoActionReason",
    "RecommendationUniversePolicy",
    "RegimeCommitteeDecision",
    "RegimeGovernanceOutcome",
    "RegimeGovernancePolicy",
    "RegimeGovernanceWorkflow",
    "SpecialistAnalysis",
    "SpecialistPosition",
    "SpecialistRole",
    "StructuredDissent",
    "UniverseAssessment",
    "UniverseDisposition",
    "build_regime_recommendation",
]
