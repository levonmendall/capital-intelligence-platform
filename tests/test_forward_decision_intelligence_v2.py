from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cio.committee import SpecialistAnalysis
from cio.models import CandidateAssetClass, SpecialistPosition, SpecialistRole
from intelligence.forward import ForwardIntelligenceBundle
from intelligence.forward_decision import (
    CatalystEvent,
    DecisionTiming,
    DecisionTimingPosture,
    EvidenceAvailability,
    EventScenario,
    ForwardDecisionDimension,
    ForwardDimensionAssessment,
    ReturnDistribution,
    ThesisMonitor,
    applicable_dimensions,
    build_forward_decision_context,
)

AS_OF = datetime(2026, 8, 9, 16, 0, tzinfo=timezone.utc)


def _available(dimension: ForwardDecisionDimension, suffix: str | None = None) -> ForwardDimensionAssessment:
    suffix = suffix or dimension.value
    return ForwardDimensionAssessment(
        dimension=dimension,
        availability=EvidenceAvailability.AVAILABLE,
        summary=f"Governed {dimension.value} evidence is available",
        confidence=0.8,
        evidence=(f"{dimension.value} supports the candidate-specific forward assessment",),
        contradictory_evidence=(f"{dimension.value} remains probabilistic",),
        assumptions=(f"{dimension.value} evidence remains representative",),
        risks=(f"{dimension.value} can change before implementation",),
        change_conditions=(f"Reassess when {dimension.value} changes materially",),
        evidence_identifiers=(f"evidence:v2:{suffix}",),
        market_expectation="market baseline",
        internal_expectation="governed internal distribution",
    )


def _event(identifier: str, hours: int) -> CatalystEvent:
    return CatalystEvent(
        identifier=identifier,
        event_type="earnings" if "earnings" in identifier else "macro_release",
        scheduled_at=AS_OF + timedelta(hours=hours),
        expected_outcome="central governed expectation",
        market_expectation="consensus-implied expectation",
        scenarios=(
            EventScenario("bull", 0.25, 0.08, "positive surprise"),
            EventScenario("base", 0.50, 0.01, "near expectations"),
            EventScenario("bear", 0.25, -0.09, "negative surprise"),
        ),
        evidence_identifiers=(f"evidence:{identifier}",),
    )


def _context():
    assessments = (
        _available(ForwardDecisionDimension.REGIME),
        _available(ForwardDecisionDimension.FUNDAMENTALS),
        _available(ForwardDecisionDimension.EXPECTATIONS),
        _available(ForwardDecisionDimension.CATALYSTS),
        _available(ForwardDecisionDimension.EARNINGS),
        _available(ForwardDecisionDimension.DERIVATIVES),
        _available(ForwardDecisionDimension.POSITIONING),
        _available(ForwardDecisionDimension.CROSS_ASSET),
        _available(ForwardDecisionDimension.MICROSTRUCTURE),
        _available(ForwardDecisionDimension.REFLEXIVITY),
        _available(ForwardDecisionDimension.STRUCTURAL),
        _available(ForwardDecisionDimension.CORPORATE_ACTIONS),
        _available(ForwardDecisionDimension.ALTERNATIVE_DATA),
        _available(ForwardDecisionDimension.PATH_RISK),
        _available(ForwardDecisionDimension.PORTFOLIO_CONTEXT),
        _available(ForwardDecisionDimension.CALIBRATION),
    )
    return build_forward_decision_context(
        identifier="forward-decision:CAND",
        candidate_identifier="CAND",
        as_of=AS_OF,
        asset_class=CandidateAssetClass.US_EQUITY,
        assessments=assessments,
        catalysts=(_event("earnings:CAND", 24), _event("cpi", 48)),
        return_distribution=ReturnDistribution(
            horizon_days=365,
            expected_return=0.16,
            geometric_expected_return=0.13,
            probability_positive=0.72,
            probability_beat_cash=0.68,
            probability_beat_best_alternative=0.61,
            expected_max_drawdown=-0.12,
            tail_loss=-0.28,
            percentiles=((10, -0.22), (25, -0.06), (50, 0.11), (75, 0.24), (90, 0.38)),
            evidence_identifiers=("evidence:distribution:CAND",),
        ),
        timing=DecisionTiming(
            posture=DecisionTimingPosture.REASSESS,
            rationale="Two material catalysts overlap inside the event-cluster window",
            next_reassessment_at=AS_OF + timedelta(days=3),
        ),
        thesis_monitor=ThesisMonitor(
            thesis="Fundamental trajectory exceeds what is priced into expectations",
            must_remain_true=("earnings revisions remain positive",),
            invalidation_conditions=("earnings revisions turn materially negative",),
            monitor_evidence=("revisions", "guidance", "positioning"),
        ),
    )


def _analysis(role: SpecialistRole) -> SpecialistAnalysis:
    return SpecialistAnalysis(
        candidate_identifier="CAND",
        role=role,
        completed_at=AS_OF,
        independent_first_pass=True,
        position=SpecialistPosition.NEUTRAL,
        conclusion="Independent specialist conclusion.",
        expected_return_impact=0.02,
        confidence=0.70,
        supporting_evidence=("base evidence",),
        contradictory_evidence=(),
        critical_assumptions=("base assumption",),
        risks=("base risk",),
        limitations=(),
        change_conditions=("base change condition",),
        evidence_origin_identifiers=("evidence:base",),
    )


def test_context_classifies_every_applicable_dimension_and_clusters_events() -> None:
    context = _context()

    assert len(context.dimensions) == len(ForwardDecisionDimension)
    assert context.evidence_completeness == 1.0
    assert context.missing_applicable_dimensions == ()
    assert context.event_clusters == (("earnings:CAND", "cpi"),)
    assert ForwardDecisionDimension.EARNINGS in applicable_dimensions(CandidateAssetClass.US_EQUITY)
    assert context.advisory_only is True


def test_builder_truthfully_marks_missing_evidence_without_fabricating_it() -> None:
    context = build_forward_decision_context(
        identifier="forward-decision:FX",
        candidate_identifier="FX",
        as_of=AS_OF,
        asset_class=CandidateAssetClass.FX,
        assessments=(_available(ForwardDecisionDimension.REGIME, "fx-regime"),),
    )

    by_dimension = {item.dimension: item for item in context.dimensions}
    assert by_dimension[ForwardDecisionDimension.REGIME].availability is EvidenceAvailability.AVAILABLE
    assert by_dimension[ForwardDecisionDimension.EARNINGS].availability is EvidenceAvailability.NOT_APPLICABLE
    assert by_dimension[ForwardDecisionDimension.DERIVATIVES].availability is EvidenceAvailability.UNAVAILABLE
    assert "evidence:v2:fx-regime" in context.evidence_identifiers
    assert context.evidence_completeness < 0.20


def test_forward_bundle_round_trip_preserves_v2_context_and_lineage() -> None:
    context = _context()
    bundle = ForwardIntelligenceBundle(
        identifier="forward:CAND",
        candidate_identifier="CAND",
        as_of=AS_OF,
        signals=(),
        scenarios=(),
        diagnostics=(),
        model_versions=("forward-decision-intelligence.v2",),
        decision_context=context,
    )

    restored = ForwardIntelligenceBundle.from_dict(bundle.to_dict())

    assert restored.decision_context == context
    assert "evidence:v2:expectations_gap" in restored.evidence_identifiers
    assert restored.to_dict()["decision_context"]["event_clusters"] == [["earnings:CAND", "cpi"]]


@pytest.mark.parametrize("role", tuple(SpecialistRole))
def test_v2_context_reaches_all_six_specialists_without_becoming_trade_authority(role: SpecialistRole) -> None:
    bundle = ForwardIntelligenceBundle(
        identifier="forward:CAND",
        candidate_identifier="CAND",
        as_of=AS_OF,
        signals=(),
        scenarios=(),
        diagnostics=(),
        model_versions=("forward-decision-intelligence.v2",),
        decision_context=_context(),
    )
    base = _analysis(role)

    enriched = bundle.enrich_analysis(base)

    assert enriched.expected_return_impact == base.expected_return_impact
    assert enriched.position is base.position
    assert enriched.confidence == base.confidence
    assert any("advisory evidence only" in item for item in enriched.limitations)
    assert "Forward Decision Intelligence v2" in enriched.conclusion or role is SpecialistRole.EVIDENCE_GOVERNANCE


def test_v2_context_rejects_candidate_mismatch() -> None:
    with pytest.raises(ValueError, match="decision context does not match candidate"):
        ForwardIntelligenceBundle(
            identifier="forward:OTHER",
            candidate_identifier="OTHER",
            as_of=AS_OF,
            signals=(),
            scenarios=(),
            diagnostics=(),
            model_versions=("forward-decision-intelligence.v2",),
            decision_context=_context(),
        )
