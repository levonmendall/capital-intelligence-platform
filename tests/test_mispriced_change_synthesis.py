from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cio import CandidateAssetClass
from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal, TrendStage
from intelligence.forward_decision import (
    CatalystEvent,
    EvidenceAvailability,
    EventScenario,
    ForwardDecisionDimension,
    ForwardDimensionAssessment,
    ReturnDistribution,
    build_forward_decision_context,
)
from intelligence.mispriced_change import (
    MispricedChangeState,
    assess_mispriced_change,
    enrich_bundle_with_mispriced_change,
)
from application.mispriced_change_cycle import enrich_mispriced_change_contexts


AS_OF = datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
CANDIDATE = "candidate:mispriced-change:test"


def _signal(
    identifier: str,
    name: str,
    channel: str,
    impact: float,
    *,
    confidence: float = 0.85,
    evidence_id: str | None = None,
    priced_in: float | None = None,
) -> ForwardSignal:
    contradictory = ()
    if priced_in is not None:
        contradictory = (f"Estimated benefit already priced={priced_in:.0%}",)
    return ForwardSignal(
        identifier=identifier,
        as_of=AS_OF,
        name=name,
        channels=(channel,),
        expected_return_impact=impact,
        confidence=confidence,
        evidence=(f"governed evidence for {name}",),
        contradictory_evidence=contradictory,
        assumptions=("evidence remains representative",),
        risks=("evidence can change",),
        change_conditions=("reassess on material change",),
        evidence_identifiers=(evidence_id or f"evidence:{identifier}",),
    )


def _decision_context(*, shared_evidence_id: str | None = None):
    expectation_id = shared_evidence_id or "evidence:expectations"
    catalyst_id = shared_evidence_id or "evidence:catalyst"
    distribution_id = shared_evidence_id or "evidence:distribution"
    expectations = ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.EXPECTATIONS,
        availability=EvidenceAvailability.AVAILABLE,
        summary=(
            "Certified expectations evidence indicates expected surprise +8.00%; "
            "priced-in score 30%."
        ),
        confidence=0.82,
        evidence=("consensus revisions are improving",),
        evidence_identifiers=(expectation_id,),
        market_expectation="certified consensus",
        internal_expectation="evidence-backed upside surprise",
    )
    catalyst = CatalystEvent(
        identifier="catalyst:test",
        event_type="earnings",
        scheduled_at=AS_OF + timedelta(days=14),
        expected_outcome="fundamental acceleration becomes visible",
        market_expectation="only partial acceleration",
        scenarios=(
            EventScenario(
                label="upside",
                probability=0.70,
                return_impact=0.12,
                rationale="acceleration exceeds expectations",
            ),
            EventScenario(
                label="downside",
                probability=0.30,
                return_impact=-0.04,
                rationale="acceleration fails to appear",
            ),
        ),
        evidence_identifiers=(catalyst_id,),
    )
    distribution = ReturnDistribution(
        horizon_days=180,
        expected_return=0.18,
        geometric_expected_return=0.16,
        probability_positive=0.76,
        probability_beat_cash=0.78,
        probability_beat_best_alternative=0.66,
        expected_max_drawdown=-0.12,
        tail_loss=-0.20,
        percentiles=((5, -0.20), (50, 0.14), (95, 0.42)),
        evidence_identifiers=(distribution_id,),
    )
    return build_forward_decision_context(
        identifier="forward-decision:test",
        candidate_identifier=CANDIDATE,
        as_of=AS_OF,
        asset_class=CandidateAssetClass.US_EQUITY,
        assessments=(expectations,),
        catalysts=(catalyst,),
        return_distribution=distribution,
    )


def _strong_bundle(*, shared_evidence_id: str | None = None) -> ForwardIntelligenceBundle:
    business_id = shared_evidence_id or "evidence:business"
    trend_id = shared_evidence_id or "evidence:trend"
    regime_id = shared_evidence_id or "evidence:regime"
    return ForwardIntelligenceBundle(
        identifier="forward-bundle:test",
        candidate_identifier=CANDIDATE,
        as_of=AS_OF,
        signals=(
            _signal(
                "signal:business:test",
                "strategic business economics",
                "fundamental",
                0.12,
                evidence_id=business_id,
                priced_in=0.20,
            ),
            _signal(
                "signal:trend:test",
                "confirmed market trend",
                "market",
                0.10,
                evidence_id=trend_id,
            ),
            _signal(
                "signal:monetary:test",
                "rate cutting policy transmission",
                "forecast",
                0.06,
                evidence_id=regime_id,
            ),
        ),
        scenarios=(),
        diagnostics=(),
        model_versions=("fixture.v1",),
        trend_stage=TrendStage.CONFIRMED,
        decision_context=_decision_context(shared_evidence_id=shared_evidence_id),
    )


def test_strong_mispriced_change_requires_multi_domain_alignment() -> None:
    assessment = assess_mispriced_change(_strong_bundle())

    assert assessment.state is MispricedChangeState.STRONG
    assert assessment.score > 0.35
    assert assessment.coverage == 1.0
    assert 0.0 < assessment.interaction_return_adjustment <= 0.03
    assert assessment.advisory_only is True
    assert assessment.authorizes_capital is False
    assert assessment.real_money_authorized is False


def test_future_state_valuation_does_not_reward_a_value_trap() -> None:
    bundle = ForwardIntelligenceBundle(
        identifier="forward-bundle:value-trap",
        candidate_identifier=CANDIDATE,
        as_of=AS_OF,
        signals=(
            _signal(
                "signal:business:value-trap",
                "strategic business economics",
                "fundamental",
                -0.09,
                priced_in=0.15,
            ),
            _signal(
                "signal:trend:value-trap",
                "deteriorating market trend",
                "market",
                -0.08,
            ),
        ),
        scenarios=(),
        diagnostics=(),
        model_versions=("fixture.v1",),
        trend_stage=TrendStage.DETERIORATING,
    )

    assessment = assess_mispriced_change(bundle)

    assert assessment.state is MispricedChangeState.VALUE_TRAP_RISK
    assert assessment.interaction_return_adjustment < 0.0
    assert next(
        item for item in assessment.components if item.name == "future_state_valuation"
    ).score > 0.0


def test_strong_trend_without_future_state_value_is_not_promoted() -> None:
    bundle = ForwardIntelligenceBundle(
        identifier="forward-bundle:momentum-only",
        candidate_identifier=CANDIDATE,
        as_of=AS_OF,
        signals=(
            _signal(
                "signal:business:momentum-only",
                "strategic business economics",
                "fundamental",
                0.01,
                priced_in=0.80,
            ),
            _signal(
                "signal:trend:momentum-only",
                "broadening market trend",
                "market",
                0.12,
            ),
        ),
        scenarios=(),
        diagnostics=(),
        model_versions=("fixture.v1",),
        trend_stage=TrendStage.BROADENING,
    )

    assessment = assess_mispriced_change(bundle)

    assert assessment.state is MispricedChangeState.MOMENTUM_ONLY
    assert assessment.interaction_return_adjustment < 0.0


def test_duplicate_evidence_origins_are_discounted() -> None:
    assessment = assess_mispriced_change(
        _strong_bundle(shared_evidence_id="evidence:shared")
    )

    assert assessment.evidence_independence < 0.30
    assert assessment.state is not MispricedChangeState.STRONG


def test_bundle_enrichment_is_idempotent_and_only_adds_interaction_residual() -> None:
    first = enrich_bundle_with_mispriced_change(_strong_bundle())
    second = enrich_bundle_with_mispriced_change(first)
    synthesis = tuple(
        item for item in second.signals if item.identifier.startswith("signal:mispriced-change:")
    )

    assert len(synthesis) == 1
    assert synthesis[0].channels == ("forecast",)
    assert abs(synthesis[0].expected_return_impact) <= 0.03
    assert sum(item.startswith("Mispriced change:") for item in second.diagnostics) == 1
    assert second.model_versions.count("mispriced-change-synthesis.v1") == 1


@dataclass(frozen=True)
class _Context:
    candidate_identifier: str
    forward_intelligence: ForwardIntelligenceBundle | None


def test_cycle_context_enrichment_preserves_candidate_identity_and_missing_bundles() -> None:
    original = _Context(CANDIDATE, _strong_bundle())
    empty = _Context("candidate:no-forward", None)

    enriched = enrich_mispriced_change_contexts((original, empty))

    assert tuple(item.candidate_identifier for item in enriched) == (
        CANDIDATE,
        "candidate:no-forward",
    )
    assert enriched[0].forward_intelligence is not original.forward_intelligence
    assert enriched[1] is empty
