from __future__ import annotations

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
