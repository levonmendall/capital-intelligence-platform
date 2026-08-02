from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from cio import CIOAction, ChiefInvestmentOfficer
from cio.policy_matrix import DecisionPolicyMatrix
from opportunity import (
    AnalysisLane,
    OpportunityEngine,
    OpportunityQualificationPolicy,
)
from tests.test_decision_quality_reconciliation import _candidate, _context, _packet


class _StrictResearchPolicyMatrix(DecisionPolicyMatrix):
    def resolve(self, candidate):
        return replace(
            super().resolve(candidate),
            minimum_net_expected_return=0.50,
            minimum_opportunity_edge=0.20,
            minimum_probability_of_success=0.99,
        )


def test_progressive_lane_cannot_authorize_capital_below_canonical_hurdles() -> None:
    candidate = _candidate("RESEARCHPROBE")
    qualification = OpportunityEngine(
        qualification_policy=OpportunityQualificationPolicy(
            minimum_net_expected_return=0.50,
        )
    ).qualify(candidate, _context())

    assert qualification.qualified
    assert qualification.analysis_lane in {
        AnalysisLane.PARTICIPATION,
        AnalysisLane.EXPLORATION,
    }

    decision = ChiefInvestmentOfficer(
        policy_matrix=_StrictResearchPolicyMatrix(),
    ).synthesize(
        candidate,
        qualification.universe,
        _packet(candidate, duplicate_origins=False),
        capital_comparison=qualification.capital_comparison,
        analysis_lane=qualification.analysis_lane.value,
    )

    assert decision.action in {
        CIOAction.NO_SUPERIOR_OPPORTUNITY,
        CIOAction.WATCH,
    }
    assert decision.recommended_position_weight is None
    assert decision.action not in {CIOAction.BUY, CIOAction.INCREASE}


def test_cio_source_has_no_progressive_soft_failure_allocation_path() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")
    assert "allow_soft_failures=progressive_lane" not in source
    assert source.count("allow_soft_failures=False") == 2
    assert "not progressive_lane and opportunity_edge" not in source
    assert "robustness.stressed_edge <= 0.0" in source
