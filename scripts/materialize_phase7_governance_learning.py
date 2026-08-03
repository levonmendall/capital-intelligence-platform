from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    # Prior decisions carry explicit evidence-outage observability state.
    replace_once(
        "cio/models.py",
        """    last_material_change_at: datetime | None = None
    emergency_override: bool = False
""",
        """    last_material_change_at: datetime | None = None
    emergency_override: bool = False
    last_complete_evidence_at: datetime | None = None
    operational_outage_started_at: datetime | None = None
    independent_substitute_evidence_available: bool = False
    custody_settlement_observable: bool = True
    lifecycle_observable: bool = True
""",
    )
    replace_once(
        "cio/models.py",
        """        if not isinstance(self.emergency_override, bool):
            raise TypeError("emergency_override must be a bool")


class ThesisState(str, Enum):
""",
        """        if not isinstance(self.emergency_override, bool):
            raise TypeError("emergency_override must be a bool")
        for field_name in (
            "last_complete_evidence_at",
            "operational_outage_started_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _aware(value, field_name=field_name)
                if value > self.decided_at:
                    raise ValueError(
                        f"{field_name} cannot follow the prior decision timestamp"
                    )
        for field_name in (
            "independent_substitute_evidence_available",
            "custody_settlement_observable",
            "lifecycle_observable",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")


class ThesisState(str, Enum):
""",
    )

    # Screening and CIO must use one exact policy authority.
    replace_once(
        "opportunity/engine.py",
        """from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
        """from cio.policy_authority import CanonicalDecisionPolicyAuthority
from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
    )
    replace_once(
        "opportunity/engine.py",
        """        robustness_policy: RobustDecisionPolicy | None = None,
        policy_matrix: DecisionPolicyMatrix | None = None,
    ) -> None:
""",
        """        robustness_policy: RobustDecisionPolicy | None = None,
        policy_matrix: DecisionPolicyMatrix | None = None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
    ) -> None:
""",
    )
    replace_once(
        "opportunity/engine.py",
        """        self.robust_assessor = RobustCandidateAssessor(robustness_policy)
        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()
""",
        """        self.robust_assessor = RobustCandidateAssessor(robustness_policy)
        if policy_authority is not None and policy_matrix is not None:
            if policy_authority.matrix is not policy_matrix:
                raise ValueError(
                    "policy_matrix and policy_authority cannot identify different authorities"
                )
        self.policy_authority = policy_authority or CanonicalDecisionPolicyAuthority(
            matrix=policy_matrix or DecisionPolicyMatrix()
        )
        self.policy_matrix = self.policy_authority.matrix
""",
    )

    replace_once(
        "cio/service.py",
        """from cio.growth_ensemble import (
""",
        """from cio.evidence_outage import (
    EvidenceOutageAssessment,
    EvidenceOutageAuthority,
    EvidenceOutageDisposition,
)
from cio.growth_ensemble import (
""",
    )
    replace_once(
        "cio/service.py",
        """from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
        """from cio.policy_authority import CanonicalDecisionPolicyAuthority
from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
    )
    replace_once(
        "cio/service.py",
        """        policy_matrix: DecisionPolicyMatrix | None = None,
        growth_ensemble: AdaptiveRobustGrowthEnsemble | None = None,
    ) -> None:
""",
        """        policy_matrix: DecisionPolicyMatrix | None = None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
        growth_ensemble: AdaptiveRobustGrowthEnsemble | None = None,
        evidence_outage_authority: EvidenceOutageAuthority | None = None,
    ) -> None:
""",
    )
    replace_once(
        "cio/service.py",
        """        self.reconciler = SpecialistReturnReconciler(reconciliation_policy)
        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()
        self.growth_ensemble = growth_ensemble or AdaptiveRobustGrowthEnsemble()
""",
        """        self.reconciler = SpecialistReturnReconciler(reconciliation_policy)
        if policy_authority is not None and policy_matrix is not None:
            if policy_authority.matrix is not policy_matrix:
                raise ValueError(
                    "policy_matrix and policy_authority cannot identify different authorities"
                )
        self.policy_authority = policy_authority or CanonicalDecisionPolicyAuthority(
            matrix=policy_matrix or DecisionPolicyMatrix()
        )
        self.policy_matrix = self.policy_authority.matrix
        self.growth_ensemble = growth_ensemble or AdaptiveRobustGrowthEnsemble()
        self.evidence_outage_authority = (
            evidence_outage_authority or EvidenceOutageAuthority()
        )
""",
    )
    replace_once(
        "cio/service.py",
        """        profile = self.policy_matrix.resolve(candidate)
""",
        """        profile = self.policy_authority.resolve(candidate)
""",
    )
    replace_once(
        "cio/service.py",
        """        portfolio = specialists.portfolio_recommendation
        action, position_weight, reason = self._select_action(
""",
        """        portfolio = specialists.portfolio_recommendation
        outage_assessment = self.evidence_outage_authority.assess(
            candidate,
            prior_context,
            operational_only_veto=(
                specialists.has_operational_only_evidence_veto
            ),
        )
        action, position_weight, reason = self._select_action(
""",
    )
    replace_once(
        "cio/service.py",
        """            analysis_lane=analysis_lane,
            ensemble=ensemble,
        )
""",
        """            analysis_lane=analysis_lane,
            ensemble=ensemble,
            outage_assessment=outage_assessment,
        )
""",
    )
    replace_once(
        "cio/service.py",
        """        if historical_learning.status.value != "not_applicable":
            reason = f"{reason} {historical_learning.summary}"
        final_confidence = self._confidence(
""",
        """        if historical_learning.status.value != "not_applicable":
            reason = f"{reason} {historical_learning.summary}"
        if outage_assessment.disposition is not EvidenceOutageDisposition.NOT_APPLICABLE:
            reason = f"{reason} Evidence outage control: {outage_assessment.reason}"
        final_confidence = self._confidence(
""",
    )
    replace_once(
        "cio/service.py",
        """            reconciliation=reconciliation,
        )
        funding_source = (
""",
        """            reconciliation=reconciliation,
        )
        final_confidence = min(
            final_confidence,
            outage_assessment.confidence_ceiling,
        )
        funding_source = (
""",
    )
    replace_once(
        "cio/service.py",
        """                    + ("historical_learning_calibration",)
""",
        """                    + (
                        "historical_learning_calibration",
                        "canonical_policy_authority_fingerprint",
                        "evidence_outage_age",
                    )
""",
    )
    replace_once(
        "cio/service.py",
        """            policy_matrix_version=self.policy_matrix.version,
        )
""",
        """            policy_matrix_version=self.policy_matrix.version,
        )
""",
    )
    replace_once(
        "cio/service.py",
        """        analysis_lane: str,
        ensemble: GrowthEnsembleAssessment,
    ) -> tuple[CIOAction, float | None, str]:
""",
        """        analysis_lane: str,
        ensemble: GrowthEnsembleAssessment,
        outage_assessment: EvidenceOutageAssessment,
    ) -> tuple[CIOAction, float | None, str]:
""",
    )
    replace_once(
        "cio/service.py",
        """                if specialists.has_operational_only_evidence_veto:
                    return (
                        CIOAction.HOLD,
                        None,
                        "New or increased exposure is prohibited, but the existing holding is preserved while an operational evidence outage is repaired: "
                        + detail,
                    )
""",
        """                if specialists.has_operational_only_evidence_veto:
                    if outage_assessment.requires_reduction:
                        target = self._conservative_reduction_target(
                            current_weight=current_weight,
                            proposed_weight=portfolio.recommended_position_weight,
                        )
                        return (
                            CIOAction.REDUCE,
                            target,
                            "New or increased exposure is prohibited and the existing holding is reduced because the operational evidence outage exceeded its bounded observability window: "
                            + outage_assessment.reason
                            + "; "
                            + detail,
                        )
                    return (
                        CIOAction.HOLD,
                        None,
                        "New or increased exposure is prohibited, but the existing holding is preserved within the bounded operational outage window: "
                        + outage_assessment.reason
                        + "; "
                        + detail,
                    )
""",
    )

    # The canonical cycle constructs and exposes the exact shared authority.
    replace_once(
        "application/cio_cycle.py",
        """    PriorDecisionContext,
)
""",
        """    PriorDecisionContext,
)
from cio.policy_authority import CanonicalDecisionPolicyAuthority
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """    cycle_disposition: CIOCycleDisposition | None = None
""",
        """    policy_authority_identifier: str
    cycle_disposition: CIOCycleDisposition | None = None
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        if not isinstance(self.briefing, DailyCIOBriefing):
""",
        """        if not isinstance(self.policy_authority_identifier, str) or not self.policy_authority_identifier.strip():
            raise ValueError("policy_authority_identifier cannot be empty")
        if not isinstance(self.briefing, DailyCIOBriefing):
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        joint_candidate_engine: JointCandidateIntelligenceEngine | None = None,
    ) -> None:
        self.opportunity_engine = opportunity_engine or OpportunityEngine()
""",
        """        joint_candidate_engine: JointCandidateIntelligenceEngine | None = None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
    ) -> None:
        self.policy_authority = policy_authority or CanonicalDecisionPolicyAuthority()
        self.opportunity_engine = opportunity_engine or OpportunityEngine(
            policy_authority=self.policy_authority
        )
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        self.cio = cio or ChiefInvestmentOfficer()
""",
        """        self.cio = cio or ChiefInvestmentOfficer(
            policy_authority=self.policy_authority
        )
        self.policy_authority.assert_same_authority(
            self.opportunity_engine.policy_authority
        )
        self.policy_authority.assert_same_authority(
            self.cio.policy_authority
        )
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """            briefing=briefing,
            cycle_disposition=cycle_disposition,
""",
        """            briefing=briefing,
            policy_authority_identifier=self.policy_authority.identifier,
            cycle_disposition=cycle_disposition,
""",
    )

    # Public exports remain explicit and advisory.
    replace_once(
        "cio/__init__.py",
        """    "DecisionPolicyMatrix": ("cio.policy_matrix", "DecisionPolicyMatrix"),
""",
        """    "CanonicalDecisionPolicyAuthority": ("cio.policy_authority", "CanonicalDecisionPolicyAuthority"),
    "EvidenceOutageAssessment": ("cio.evidence_outage", "EvidenceOutageAssessment"),
    "EvidenceOutageAuthority": ("cio.evidence_outage", "EvidenceOutageAuthority"),
    "EvidenceOutageDisposition": ("cio.evidence_outage", "EvidenceOutageDisposition"),
    "EvidenceOutagePolicy": ("cio.evidence_outage", "EvidenceOutagePolicy"),
    "DecisionPolicyMatrix": ("cio.policy_matrix", "DecisionPolicyMatrix"),
""",
    )
    replace_once(
        "cio/__init__.py",
        """    "CapitalAlternativeComparison",
""",
        """    "CapitalAlternativeComparison",
    "CanonicalDecisionPolicyAuthority",
""",
    )
    replace_once(
        "cio/__init__.py",
        """    "EvidenceDependency",
""",
        """    "EvidenceDependency",
    "EvidenceOutageAssessment",
    "EvidenceOutageAuthority",
    "EvidenceOutageDisposition",
    "EvidenceOutagePolicy",
""",
    )

    replace_once(
        "evaluation/__init__.py",
        """from evaluation.decision_learning import (
""",
        """from evaluation.decision_value import (
    AdvisoryDecisionValueEvaluator,
    AdvisoryDecisionValueMetric,
    AdvisoryDecisionValueReport,
    CalibrationSegment,
    GateDecisionValueMetric,
)
from evaluation.decision_learning import (
""",
    )
    replace_once(
        "evaluation/__init__.py",
        """    "AlternativeRealizedReturn",
""",
        """    "AdvisoryDecisionValueEvaluator",
    "AdvisoryDecisionValueMetric",
    "AdvisoryDecisionValueReport",
    "AlternativeRealizedReturn",
""",
    )
    replace_once(
        "evaluation/__init__.py",
        """    "CalibrationMetric",
""",
        """    "CalibrationMetric",
    "CalibrationSegment",
""",
    )
    replace_once(
        "evaluation/__init__.py",
        """    "EvidenceReference",
""",
        """    "EvidenceReference",
    "GateDecisionValueMetric",
""",
    )


if __name__ == "__main__":
    main()
