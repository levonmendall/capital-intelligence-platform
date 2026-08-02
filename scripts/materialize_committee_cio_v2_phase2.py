from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "committee/specialists.py",
        "from company import CompanyAnalysis, CompanyFactor\n",
        """from committee.evidence_applicability import (
    ApplicableAnalysis,
    ApplicableEvidenceMatrix,
)
from company import CompanyAnalysis, CompanyFactor
""",
    )
    replace_once(
        "committee/specialists.py",
        '    version: str = "specialist-governance.v2"',
        '    version: str = "specialist-governance.v3-applicable-evidence"',
    )
    replace_once(
        "committee/specialists.py",
        """    def __init__(
        self,
        policy: SpecialistGovernancePolicy | None = None,
    ) -> None:
        self.policy = policy or SpecialistGovernancePolicy()
""",
        """    def __init__(
        self,
        policy: SpecialistGovernancePolicy | None = None,
        *,
        applicability_matrix: ApplicableEvidenceMatrix | None = None,
    ) -> None:
        self.policy = policy or SpecialistGovernancePolicy()
        self.applicability_matrix = (
            applicability_matrix or ApplicableEvidenceMatrix()
        )
""",
    )

    old_fundamental = """        equity_candidate = candidate.instrument.asset_class in {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.INTERNATIONAL_EQUITY,
        }
        if company is None and asset_valuation is not None:
            if asset_valuation.asset_class is not candidate.instrument.asset_class:
                raise ValueError("asset valuation class does not match candidate")
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=_position(asset_valuation.expected_return_impact),
                conclusion=(
                    "Independent asset-specific valuation and return-driver evidence was reviewed."
                ),
                expected_return_impact=asset_valuation.expected_return_impact,
                confidence=asset_valuation.confidence,
                supporting_evidence=asset_valuation.valuation_evidence,
                contradictory_evidence=asset_valuation.contradictory_evidence,
                critical_assumptions=asset_valuation.critical_assumptions,
                risks=asset_valuation.risks,
                limitations=asset_valuation.limitations,
                change_conditions=asset_valuation.change_conditions,
                evidence_origin_identifiers=asset_valuation.evidence_identifiers,
            )
        if company is None:
            requirement = (
                "point-in-time company quality and valuation analysis"
                if equity_candidate
                else "independent asset-specific valuation analysis"
            )
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=SpecialistPosition.ABSTAIN,
                conclusion=f"Required {requirement} is unavailable.",
                expected_return_impact=0.0,
                confidence=0.0,
                supporting_evidence=(
                    "The candidate record discloses the missing independent valuation packet",
                ),
                contradictory_evidence=(),
                critical_assumptions=(
                    "Independent valuation evidence is required before a recommendation",
                ),
                risks=(
                    "The candidate return estimate cannot be independently verified",
                ),
                limitations=(
                    "No independent company or asset-specific valuation packet was supplied",
                ),
                change_conditions=(
                    "Provide point-in-time independent valuation and return-driver evidence",
                ),
                evidence_origin_identifiers=candidate.evidence_identifiers,
            )
"""
    new_fundamental = """        applicability = self.applicability_matrix.assess(
            candidate,
            company_present=company is not None,
            asset_valuation_class=(
                None if asset_valuation is None else asset_valuation.asset_class
            ),
        )
        if not applicability.complete:
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=SpecialistPosition.ABSTAIN,
                conclusion=(
                    "Required applicable business, valuation, or return-driver "
                    "evidence is unavailable."
                ),
                expected_return_impact=0.0,
                confidence=0.0,
                supporting_evidence=(
                    f"Applicable evidence policy={applicability.policy_version}",
                    f"Required analysis={applicability.rule.required_analysis.value}",
                ),
                contradictory_evidence=applicability.reasons,
                critical_assumptions=(
                    "The applicable independent return-driver packet must be complete "
                    "before a positive portfolio action",
                ),
                risks=(
                    "The candidate return estimate cannot be independently verified",
                    *applicability.reasons,
                ),
                limitations=(
                    "Applicable analysis is incomplete and cannot be treated as an "
                    "ordinary neutral specialist view",
                ),
                change_conditions=(
                    "Provide point-in-time independent applicable business, valuation, "
                    "and return-driver evidence",
                ),
                evidence_origin_identifiers=candidate.evidence_identifiers,
            )
        if applicability.rule.required_analysis is ApplicableAnalysis.ASSET_VALUATION:
            if asset_valuation is None:
                raise AssertionError("complete asset-valuation assessment lacks packet")
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=_position(asset_valuation.expected_return_impact),
                conclusion=(
                    "Independent asset-specific valuation and return-driver evidence was reviewed."
                ),
                expected_return_impact=asset_valuation.expected_return_impact,
                confidence=asset_valuation.confidence,
                supporting_evidence=(
                    f"Applicable evidence policy={applicability.policy_version}",
                    *asset_valuation.valuation_evidence,
                ),
                contradictory_evidence=asset_valuation.contradictory_evidence,
                critical_assumptions=asset_valuation.critical_assumptions,
                risks=asset_valuation.risks,
                limitations=asset_valuation.limitations,
                change_conditions=asset_valuation.change_conditions,
                evidence_origin_identifiers=asset_valuation.evidence_identifiers,
            )
        if company is None:
            raise AssertionError("complete company-analysis assessment lacks packet")
"""
    replace_once("committee/specialists.py", old_fundamental, new_fundamental)

    old_evidence_gate = """        if (
            candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY
            and context.company is None
        ):
            add_veto(
                "point-in-time normalized company analysis is missing for a U.S. equity",
                EvidenceVetoCategory.OPERATIONAL_UNAVAILABLE,
            )
"""
    new_evidence_gate = """        applicability = self.applicability_matrix.assess(
            candidate,
            company_present=context.company is not None,
            asset_valuation_class=(
                None
                if context.asset_valuation is None
                else context.asset_valuation.asset_class
            ),
        )
        for reason in applicability.reasons:
            add_veto(
                reason,
                EvidenceVetoCategory.OPERATIONAL_UNAVAILABLE,
            )
"""
    replace_once("committee/specialists.py", old_evidence_gate, new_evidence_gate)
    replace_once(
        "committee/specialists.py",
        """        evidence = (
            f"reliability={quality.reliability:.3f}",
""",
        """        evidence = (
            f"applicable evidence policy={applicability.policy_version}",
            f"required analysis={applicability.rule.required_analysis.value}",
            f"reliability={quality.reliability:.3f}",
""",
    )

    replace_once(
        "committee/__init__.py",
        "from committee.consensus import CommitteeConsensus\n",
        """from committee.consensus import CommitteeConsensus
from committee.evidence_applicability import (
    ApplicableAnalysis,
    ApplicableEvidenceAssessment,
    ApplicableEvidenceMatrix,
    ApplicableEvidenceRule,
)
""",
    )
    replace_once(
        "committee/__init__.py",
        '    "CIOAction",\n',
        """    "ApplicableAnalysis",
    "ApplicableEvidenceAssessment",
    "ApplicableEvidenceMatrix",
    "ApplicableEvidenceRule",
    "CIOAction",
""",
    )

    Path("tests/test_applicable_evidence_matrix.py").write_text(
        '''from __future__ import annotations

from dataclasses import replace

from cio import CandidateAssetClass, SpecialistPosition, SpecialistRole
from committee.evidence_applicability import (
    ApplicableAnalysis,
    ApplicableEvidenceMatrix,
)
from committee.specialists import (
    AssetValuationSpecialistContext,
    IndependentSpecialistService,
)
from tests.test_cross_asset_forecast_specialist import (
    AS_OF,
    _candidate,
    _context,
)


def _as_asset_class(asset_class: CandidateAssetClass):
    candidate = _candidate()
    return replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            asset_class=asset_class,
        ),
    )


def test_equities_require_company_analysis() -> None:
    matrix = ApplicableEvidenceMatrix()
    for asset_class in (
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    ):
        assessment = matrix.assess(
            _as_asset_class(asset_class),
            company_present=False,
            asset_valuation_class=None,
        )
        assert not assessment.complete
        assert assessment.rule.required_analysis is ApplicableAnalysis.COMPANY
        assert "company" in assessment.reasons[0]


def test_non_equities_require_matching_asset_valuation() -> None:
    candidate = _as_asset_class(CandidateAssetClass.US_ETF)
    matrix = ApplicableEvidenceMatrix()

    missing = matrix.assess(
        candidate,
        company_present=False,
        asset_valuation_class=None,
    )
    mismatched = matrix.assess(
        candidate,
        company_present=False,
        asset_valuation_class=CandidateAssetClass.FIXED_INCOME,
    )
    complete = matrix.assess(
        candidate,
        company_present=False,
        asset_valuation_class=CandidateAssetClass.US_ETF,
    )

    assert not missing.complete
    assert not mismatched.complete
    assert complete.complete
    assert complete.rule.required_analysis is ApplicableAnalysis.ASSET_VALUATION


def test_missing_applicable_analysis_creates_evidence_veto() -> None:
    candidate = _candidate()
    packet = IndependentSpecialistService().analyze(candidate, _context(None))

    fundamental = packet.for_role(SpecialistRole.FUNDAMENTAL_VALUATION)
    evidence = packet.for_role(SpecialistRole.EVIDENCE_GOVERNANCE)

    assert fundamental.position is SpecialistPosition.ABSTAIN
    assert evidence.position is SpecialistPosition.OPPOSED
    assert any("asset-specific valuation" in item for item in evidence.veto_reasons)


def test_matching_asset_valuation_completes_applicable_packet() -> None:
    candidate = _candidate()
    valuation = AssetValuationSpecialistContext(
        as_of=AS_OF,
        asset_class=CandidateAssetClass.US_ETF,
        expected_return_impact=0.02,
        confidence=0.80,
        valuation_evidence=("Underlying earnings and valuation evidence is complete",),
        contradictory_evidence=("Foreign-currency translation remains uncertain",),
        critical_assumptions=("Underlying holdings remain representative",),
        risks=("Tracking and valuation relationships can change",),
        limitations=("The valuation is point-in-time",),
        change_conditions=("Reassess after material holdings or valuation changes",),
        evidence_identifiers=("valuation:acwi:point-in-time",),
    )
    context = replace(_context(None), asset_valuation=valuation)
    packet = IndependentSpecialistService().analyze(candidate, context)

    fundamental = packet.for_role(SpecialistRole.FUNDAMENTAL_VALUATION)
    evidence = packet.for_role(SpecialistRole.EVIDENCE_GOVERNANCE)

    assert fundamental.position is SpecialistPosition.SUPPORTIVE
    assert not any("asset-specific valuation" in item for item in evidence.veto_reasons)
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
