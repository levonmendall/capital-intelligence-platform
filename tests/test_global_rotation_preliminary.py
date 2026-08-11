from __future__ import annotations

from types import SimpleNamespace

from application.global_rotation_preliminary import (
    MemoizedCandidateRiskIntelligenceEngine,
    MemoizedJointCandidateIntelligenceEngine,
    PrecomputedSpecialistService,
    assess_preliminary_global_conviction,
)
from portfolio.global_rotation import ConvictionStage, GlobalConvictionDecision


class _FakeRobustAssessor:
    policy = SimpleNamespace(minimum_reference_weight=0.01)

    def __init__(self):
        self.maximum_alternative = None
        self.assess_weight = None

    def maximum_supported_weight(
        self,
        _candidate,
        *,
        alternative_return,
        maximum_weight,
        policy_profile,
        allow_soft_failures,
    ):
        self.maximum_alternative = alternative_return
        assert maximum_weight == 0.08
        assert policy_profile.maximum_position_weight == 0.10
        assert allow_soft_failures is False
        return 0.02

    def assess(
        self,
        _candidate,
        *,
        alternative_return,
        position_weight,
        policy_profile,
    ):
        assert alternative_return == 0.06
        assert policy_profile.maximum_position_weight == 0.10
        self.assess_weight = position_weight
        return SimpleNamespace(
            effective_probability_of_success=0.55,
            probability_of_loss=0.40,
            robust_edge=0.02,
            stressed_edge=0.01,
            evidence_adjusted_return=0.07,
            reasons=(),
        )


def test_precomputed_specialist_service_reuses_packet_only_inside_bound_context():
    learning = object()
    candidate = SimpleNamespace(identifier="candidate:AAA")
    context = SimpleNamespace(historical_learning=learning)
    packet = SimpleNamespace(
        historical_learning=learning,
        validate_against=lambda value: None
        if value is candidate
        else (_ for _ in ()).throw(AssertionError("candidate changed")),
    )

    class Delegate:
        def __init__(self):
            self.calls = 0

        def analyze(self, _candidate, _context):
            self.calls += 1
            return "delegated"

    delegate = Delegate()
    service = PrecomputedSpecialistService(delegate)
    assert service.analyze(candidate, context) == "delegated"
    with service.bind_packets({candidate.identifier: packet}):
        assert service.analyze(candidate, context) is packet
    assert service.analyze(candidate, context) == "delegated"
    assert delegate.calls == 2


def test_candidate_risk_is_computed_once_across_preliminary_and_final_passes():
    candidate = SimpleNamespace(identifier="candidate:AAA")

    class Delegate:
        policy = SimpleNamespace(version="risk.test")

        def __init__(self):
            self.calls = 0

        def assess(self, candidate, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                candidate_identifier=candidate.identifier,
                proposed_weight=kwargs["proposed_weight"],
                probability_of_loss=0.30,
                expected_shortfall=-0.10,
                stressed_execution_cost_return=0.002,
                fragility_score=0.25,
                hard_blocks=(),
            )

    delegate = Delegate()
    engine = MemoizedCandidateRiskIntelligenceEngine(delegate)
    token = engine.begin_cycle_cache()
    try:
        first = engine.assess(
            candidate,
            portfolio_value=250_000.0,
            proposed_weight=0.05,
            alternative_return=0.04,
            invalidation_clarity=0.75,
        )
        second = engine.assess(
            candidate,
            portfolio_value=250_000.0,
            proposed_weight=0.05,
            alternative_return=0.04,
            invalidation_clarity=0.75,
        )
        assert first is second
        assert delegate.calls == 1
    finally:
        engine.end_cycle_cache(token)
    engine.assess(
        candidate,
        portfolio_value=250_000.0,
        proposed_weight=0.05,
        alternative_return=0.04,
        invalidation_clarity=0.75,
    )
    assert delegate.calls == 2


def test_joint_candidate_work_is_computed_once_inside_cycle_cache():
    candidates = (
        SimpleNamespace(identifier="candidate:AAA"),
        SimpleNamespace(identifier="candidate:BBB"),
    )
    risks = tuple(
        SimpleNamespace(
            candidate_identifier=item.identifier,
            proposed_weight=0.03,
            probability_of_loss=0.30,
            expected_shortfall=-0.10,
            stressed_execution_cost_return=0.002,
            fragility_score=0.25,
            hard_blocks=(),
        )
        for item in candidates
    )
    profiles = tuple(
        SimpleNamespace(
            candidate_identifier=item.identifier,
            factor_loadings=(("trend", 0.5),),
            correlation_bucket="growth",
        )
        for item in candidates
    )

    class Delegate:
        def __init__(self):
            self.calls = 0

        def assess(self, _candidates, _risks, _profiles):
            self.calls += 1
            return ("joint-result",)

    delegate = Delegate()
    engine = MemoizedJointCandidateIntelligenceEngine(delegate)
    token = engine.begin_cycle_cache()
    try:
        first = engine.assess(candidates, risks, profiles)
        second = engine.assess(candidates, risks, profiles)
        assert first is second
        assert delegate.calls == 1
    finally:
        engine.end_cycle_cache(token)
    engine.assess(candidates, risks, profiles)
    assert delegate.calls == 2


def test_preliminary_conviction_uses_authoritative_alternative_and_six_specialist_packet():
    candidate = SimpleNamespace(
        identifier="candidate:AAA",
        maximum_position_weight=0.10,
        current_portfolio_weight=0.0,
    )
    specialists = SimpleNamespace(
        portfolio_recommendation=SimpleNamespace(
            recommended_position_weight=0.08,
            funding_source="cash above minimum reserve",
        )
    )
    ranked = SimpleNamespace(
        qualification=SimpleNamespace(
            effective_opportunity_cost=0.06,
            analysis_lane=SimpleNamespace(value="exploration"),
            universe=SimpleNamespace(direct_recommendation_allowed=True),
        )
    )
    assessor = _FakeRobustAssessor()
    captured = {}

    class Policy:
        def assess(self, **kwargs):
            captured.update(kwargs)
            return GlobalConvictionDecision(
                stage=ConvictionStage.PROVISIONAL,
                target_weight=0.02,
                hard_blockers=(),
                soft_constraints=("bounded uncertainty",),
                reasons=("preliminary",),
            )

    cio = SimpleNamespace(
        global_rotation_context=SimpleNamespace(
            by_candidate={candidate.identifier: SimpleNamespace(score=0.70)}
        ),
        global_conviction_policy=Policy(),
        policy_authority=SimpleNamespace(
            resolve=lambda _candidate: SimpleNamespace(maximum_position_weight=0.10)
        ),
        reconciler=SimpleNamespace(
            reconcile=lambda _candidate, _specialists, alternative_return: SimpleNamespace(
                path_drawdown_by_scenario=(),
                alternative_return=alternative_return,
            )
        ),
        _robustness_candidate=lambda value, _reconciliation: value,
        robust_assessor=assessor,
        growth_ensemble=SimpleNamespace(
            assess=lambda *_args, **_kwargs: SimpleNamespace(stage="participate")
        ),
        policy=SimpleNamespace(maximum_unresolved_dissent_confidence=0.75),
    )
    directive = SimpleNamespace(preferred=True, discouraged=False)

    result = assess_preliminary_global_conviction(
        cio,
        candidate=candidate,
        ranked=ranked,
        specialists=specialists,
        directive=directive,
    )

    assert result is not None
    assert result.stage is ConvictionStage.PROVISIONAL
    assert result.target_weight == 0.02
    assert assessor.maximum_alternative == 0.06
    assert assessor.assess_weight == 0.02
    assert captured["candidate"] is candidate
    assert captured["specialists"] is specialists
    assert captured["directive"] is directive
    assert captured["material_opposition_threshold"] == 0.75
