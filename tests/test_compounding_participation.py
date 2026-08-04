from __future__ import annotations

from types import SimpleNamespace

from portfolio.compounding_allocation import (
    CandidateAllocationDirective,
    CompoundingParticipationPolicy,
    PortfolioSleeve,
)


def _candidate():
    return SimpleNamespace(
        identifier="candidate:ABC",
        maximum_position_weight=0.10,
        evidence_quality=SimpleNamespace(score=0.82, ceiling=0.78),
    )


def _specialists(*, evidence_vetoes=()):
    return SimpleNamespace(
        evidence_vetoes=evidence_vetoes,
        implementation_blocks=(),
        analyses=(),
        evidence_independence=SimpleNamespace(
            independent_opposition_count=lambda analyses, minimum_confidence: 1
        ),
        portfolio_recommendation=SimpleNamespace(
            recommended_position_weight=0.01,
            funding_source="cash above minimum reserve",
        ),
    )


def test_small_position_is_authorized_only_when_all_hard_controls_clear() -> None:
    candidate = _candidate()
    directive = CandidateAllocationDirective(
        candidate_identifier=candidate.identifier,
        sleeve=PortfolioSleeve.PRODUCTIVE_RISK,
        posture_alignment=0.80,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
        rationale="risk-on productive-risk sleeve",
    )
    robustness = SimpleNamespace(
        robust_edge=0.012,
        stressed_edge=0.004,
        probability_of_loss=0.40,
        probability_consistency_gap=0.08,
    )
    reconciliation = SimpleNamespace(
        probability_of_success=0.56,
        expected_return=0.09,
    )
    ensemble = SimpleNamespace(
        stage=SimpleNamespace(value="explore"),
        minimum_target_weight=0.0025,
        maximum_target_weight=0.01,
        target_multiplier=0.60,
    )
    policy = CompoundingParticipationPolicy()

    result = policy.assess(
        candidate=candidate,
        directive=directive,
        universe=SimpleNamespace(direct_recommendation_allowed=True),
        specialists=_specialists(),
        robustness=robustness,
        reconciliation=reconciliation,
        ensemble=ensemble,
        effective_alternative=0.04,
        material_opposition_threshold=0.75,
    )

    assert result.authorized is True
    assert result.target_weight == 0.006

    blocked = policy.assess(
        candidate=candidate,
        directive=directive,
        universe=SimpleNamespace(direct_recommendation_allowed=True),
        specialists=_specialists(
            evidence_vetoes=("missing required fundamentals",)
        ),
        robustness=robustness,
        reconciliation=reconciliation,
        ensemble=ensemble,
        effective_alternative=0.04,
        material_opposition_threshold=0.75,
    )

    assert blocked.authorized is False
    assert blocked.target_weight is None
    assert any("evidence integrity" in item for item in blocked.reasons)


def test_negative_stressed_edge_cannot_be_rescued_by_favorable_posture() -> None:
    candidate = _candidate()
    directive = CandidateAllocationDirective(
        candidate_identifier=candidate.identifier,
        sleeve=PortfolioSleeve.PRODUCTIVE_RISK,
        posture_alignment=0.95,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
        rationale="strongly preferred sleeve",
    )

    result = CompoundingParticipationPolicy().assess(
        candidate=candidate,
        directive=directive,
        universe=SimpleNamespace(direct_recommendation_allowed=True),
        specialists=_specialists(),
        robustness=SimpleNamespace(
            robust_edge=0.02,
            stressed_edge=-0.001,
            probability_of_loss=0.40,
            probability_consistency_gap=0.08,
        ),
        reconciliation=SimpleNamespace(
            probability_of_success=0.58,
            expected_return=0.10,
        ),
        ensemble=SimpleNamespace(
            stage=SimpleNamespace(value="explore"),
            minimum_target_weight=0.0025,
            maximum_target_weight=0.01,
            target_multiplier=0.75,
        ),
        effective_alternative=0.04,
        material_opposition_threshold=0.75,
    )

    assert result.authorized is False
    assert any("stressed edge" in item for item in result.reasons)
