from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import intelligence.predictive_market as predictive_market
from cio.compounding_authority import CompoundingChiefInvestmentOfficer
from intelligence.predictive_market import CapitalFlowEngine, CapitalFlowState
from intelligence.predictive_scenario_merge import reconcile_forward_intelligence
from portfolio.compounding_participation_authority import (
    AuthoritativeCompoundingParticipationPolicy,
)


NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)


def test_production_uses_governed_scenario_reconciliation() -> None:
    import production_paper_evidence  # noqa: F401

    assert (
        predictive_market.merge_forward_intelligence
        is reconcile_forward_intelligence
    )


def test_compounding_cio_uses_authoritative_participation_policy() -> None:
    cio = CompoundingChiefInvestmentOfficer()

    assert isinstance(
        cio.participation_policy,
        AuthoritativeCompoundingParticipationPolicy,
    )


def test_rebound_retains_covering_risk_even_when_classified_as_accumulation() -> None:
    rows: list[dict[str, object]] = []
    close = 120.0
    volume = 1_000_000.0
    for index in range(100):
        close *= 0.997
        rows.append(
            {
                "t": (NOW - timedelta(days=120 - index)).isoformat(),
                "c": close,
                "v": volume,
            }
        )
    for index in range(20):
        close *= 1.012
        volume *= 1.02
        rows.append(
            {
                "t": (NOW - timedelta(days=19 - index)).isoformat(),
                "c": close,
                "v": volume,
            }
        )

    observation = CapitalFlowEngine.observe(
        symbol="ABC",
        as_of=NOW,
        rows=tuple(rows),
        evidence_identifiers=("bars:ABC",),
    )
    assessment = CapitalFlowEngine().analyze(observation)

    assert observation.short_covering_likelihood >= 0.30
    assert observation.medium_trend < observation.short_trend
    assert assessment.state in {
        CapitalFlowState.ACCUMULATION,
        CapitalFlowState.SHORT_COVERING,
        CapitalFlowState.CROWDED_ADVANCE,
        CapitalFlowState.ROTATION,
    }
    assert assessment.expected_return_impact < 0.08
    assert assessment.reversal_risk > 0.0


def test_authoritative_policy_ignores_absent_optional_gap_but_not_assessor_reason() -> None:
    policy = AuthoritativeCompoundingParticipationPolicy()
    candidate = SimpleNamespace(
        identifier="candidate:ABC",
        maximum_position_weight=0.10,
        evidence_quality=SimpleNamespace(score=0.82, ceiling=0.78),
    )
    directive = SimpleNamespace(
        candidate_identifier=candidate.identifier,
        sleeve=SimpleNamespace(value="productive_risk"),
        posture_alignment=0.80,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
    )
    specialists = SimpleNamespace(
        evidence_vetoes=(),
        implementation_blocks=(),
        analyses=(),
        evidence_independence=SimpleNamespace(
            independent_opposition_count=lambda analyses, minimum_confidence: 0
        ),
        portfolio_recommendation=SimpleNamespace(
            recommended_position_weight=0.01,
            funding_source="cash above reserve",
        ),
    )
    ensemble = SimpleNamespace(
        stage=SimpleNamespace(value="explore"),
        minimum_target_weight=0.0025,
        maximum_target_weight=0.01,
        target_multiplier=0.60,
    )
    common = dict(
        candidate=candidate,
        directive=directive,
        universe=SimpleNamespace(direct_recommendation_allowed=True),
        specialists=specialists,
        reconciliation=SimpleNamespace(
            probability_of_success=0.56,
            expected_return=0.09,
        ),
        ensemble=ensemble,
        effective_alternative=0.04,
        material_opposition_threshold=0.75,
    )

    allowed = policy.assess(
        robustness=SimpleNamespace(
            robust_edge=0.012,
            stressed_edge=0.004,
            probability_of_loss=0.40,
            reasons=(),
        ),
        **common,
    )
    blocked = policy.assess(
        robustness=SimpleNamespace(
            robust_edge=0.012,
            stressed_edge=0.004,
            probability_of_loss=0.40,
            reasons=(
                "stated probability of success is inconsistent with the disclosed scenarios",
            ),
        ),
        **common,
    )

    assert allowed.authorized is True
    assert blocked.authorized is False
    assert any("scenario-implied" in reason for reason in blocked.reasons)
