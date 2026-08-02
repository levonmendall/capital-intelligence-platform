from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact_count(
    path: str,
    old: str,
    new: str,
    *,
    expected: int,
) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} matches, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    service = Path("cio/service.py").read_text(encoding="utf-8")
    if 'version: str = "cio-synthesis.v8-economic-consistency"' in service:
        raise SystemExit("Phase 1 economic-consistency source is already materialized")

    replace_once(
        "cio/service.py",
        'version: str = "cio-synthesis.v7-growth"',
        'version: str = "cio-synthesis.v8-economic-consistency"',
    )
    replace_exact_count(
        "cio/service.py",
        "allow_soft_failures=progressive_lane,",
        "allow_soft_failures=False,",
        expected=2,
    )
    replace_once(
        "cio/service.py",
        """        if (
            not progressive_lane
            and robustness.effective_probability_of_success
            < profile.minimum_probability_of_success
        ):""",
        """        if (
            robustness.effective_probability_of_success
            < profile.minimum_probability_of_success
        ):""",
    )
    replace_once(
        "cio/service.py",
        """        if (
            not progressive_lane
            and robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
        ):""",
        """        if (
            robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
        ):""",
    )
    replace_once(
        "cio/service.py",
        "        if not progressive_lane and opportunity_edge < profile.minimum_opportunity_edge:",
        "        if opportunity_edge < profile.minimum_opportunity_edge:",
    )
    replace_once(
        "cio/service.py",
        "\n        if portfolio.recommended_position_weight is None:\n",
        """
        if robustness.stressed_edge <= 0.0:
            if current_weight > 0.0:
                return (
                    CIOAction.HOLD,
                    None,
                    "The holding is preserved, but adverse probability stress removes its positive edge and blocks additional capital.",
                )
            return (
                CIOAction.NO_SUPERIOR_OPPORTUNITY,
                None,
                "The candidate does not retain a positive economic edge after adverse scenario-probability stress.",
            )

        if portfolio.recommended_position_weight is None:
""",
    )

    replace_once(
        "cio/robustness.py",
        'version: str = "robust-decision.v3"',
        'version: str = "robust-decision.v4-economic-consistency"',
    )
    replace_once(
        "cio/robustness.py",
        """        stressed_floor = self.policy.minimum_stressed_edge
        if policy_profile is not None:
            stressed_floor = min(stressed_floor, -0.001)
""",
        """        stressed_floor = self.policy.minimum_stressed_edge
""",
    )
    replace_once(
        "cio/robustness.py",
        """        Full acquisitions require every robustness control. Participation and
        exploration may treat edge, stress, uncertainty, and probability-of-loss
        shortfalls as sizing inputs. Scenario integrity and worst-case portfolio
        loss remain hard portfolio-survival constraints.
""",
        """        Canonical positive allocations require every robustness control. The
        allow_soft_failures parameter remains only for backward-compatible research
        diagnostics and must not be enabled by CIO allocation paths.
""",
    )

    replace_once(
        "opportunity/engine.py",
        'version: str = "opportunity-qualification.v6-growth"',
        'version: str = "opportunity-qualification.v7-economic-consistency"',
    )
    replace_once(
        "opportunity/engine.py",
        """                        f"{lane.value} lane: hard evidence, liquidity, downside, cost, and integrity controls passed",
""",
        """                        f"{lane.value} research lane: hard evidence, liquidity, downside, cost, and integrity controls passed; this lane is non-authoritative and cannot receive positive canonical capital until all economic qualification and robustness controls clear",
""",
    )

    replace_once(
        "tests/test_adaptive_robust_growth_ensemble.py",
        """def test_cio_uses_ensemble_and_progressive_lanes() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")
    assert "AdaptiveRobustGrowthEnsemble" in source
    assert 'progressive_lane = str(analysis_lane).lower()' in source
    assert "ensemble.minimum_target_weight" in source
    assert "effective_position_multiplier" in source
    assert "if not progressive_lane:" in source
    assert "growth_cap = (" in source
    assert "if progressive_lane" in source
""",
        """def test_cio_keeps_progressive_lanes_research_only_below_economic_hurdles() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")
    assert "AdaptiveRobustGrowthEnsemble" in source
    assert 'progressive_lane = str(analysis_lane).lower()' in source
    assert "ensemble.minimum_target_weight" in source
    assert "effective_position_multiplier" in source
    assert source.count("allow_soft_failures=False") == 2
    assert "robustness.stressed_edge <= 0.0" in source
    assert "growth_cap = (" in source
    assert "if progressive_lane" in source
""",
    )
    replace_once(
        "tests/test_opportunity_engine.py",
        """    assert qualification.analysis_lane in {
        AnalysisLane.PARTICIPATION,
        AnalysisLane.EXPLORATION,
    }
    assert any(reason_fragment in reason for reason in qualification.reasons)
""",
        """    assert qualification.analysis_lane in {
        AnalysisLane.PARTICIPATION,
        AnalysisLane.EXPLORATION,
    }
    assert any("research lane" in reason for reason in qualification.reasons)
    assert any(reason_fragment in reason for reason in qualification.reasons)
""",
    )

    Path("tests/test_progressive_lane_economic_authority.py").write_text(
        """from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from cio import CIOAction, CandidateAssetClass, ChiefInvestmentOfficer
from opportunity import AnalysisLane, OpportunityEngine
from tests.test_decision_quality_reconciliation import _candidate, _context, _packet


def test_progressive_lane_cannot_authorize_capital_below_canonical_hurdles() -> None:
    candidate = _candidate(
        "RESEARCHPROBE",
        base=0.05,
        bull=0.10,
        bear=-0.02,
    )
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            replication_method="us-listed-economic-exposure-wrapper",
            instrument_type="etf",
        ),
    )
    qualification = OpportunityEngine().qualify(candidate, _context())

    assert qualification.qualified
    assert qualification.analysis_lane in {
        AnalysisLane.PARTICIPATION,
        AnalysisLane.EXPLORATION,
    }

    packet = _packet(candidate, duplicate_origins=False)
    packet = replace(
        packet,
        analyses=tuple(
            replace(analysis, expected_return_impact=0.0, scenario_adjustments=())
            for analysis in packet.analyses
        ),
    )
    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        packet,
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
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
