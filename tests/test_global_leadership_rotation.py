from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio.global_rotation_authority import GlobalRotationChiefInvestmentOfficer
from cio.models import (
    CIOAction,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal, TrendStage
from intelligence.global_leadership import (
    GlobalLeadershipState,
    assess_global_leadership_economics,
    enrich_bundle_with_global_leadership_economics,
)
from intelligence.mispriced_change import MispricedChangeState
from portfolio.global_rotation import (
    CashCompetitionState,
    ConvictionStage,
    GlobalConvictionDecision,
    GlobalConvictionPolicy,
    GlobalOpportunityDomain,
    GlobalOpportunitySignal,
    GlobalRotationContext,
    build_global_rotation_context,
    opportunity_domain,
)

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def _signal(identifier: str, impact: float, confidence: float = 0.8) -> ForwardSignal:
    return ForwardSignal(
        identifier=identifier,
        as_of=NOW,
        name=identifier,
        channels=("forecast",),
        expected_return_impact=impact,
        confidence=confidence,
        evidence=("governed evidence",),
        contradictory_evidence=(),
        assumptions=("assumption",),
        risks=("risk",),
        change_conditions=("change",),
        evidence_identifiers=(f"evidence:{identifier}",),
    )


def _bundle() -> ForwardIntelligenceBundle:
    radar = _signal("signal:global-opportunity-radar:candidate:AAA", 0.0, 0.81)
    forward = _signal("signal:forward-business:candidate:AAA", 0.04, 0.8)
    return ForwardIntelligenceBundle(
        identifier="forward:test",
        candidate_identifier="candidate:AAA",
        as_of=NOW,
        signals=(radar, forward),
        scenarios=(),
        diagnostics=(),
        model_versions=("test.v1",),
        trend_stage=TrendStage.EARLY,
    )


def _candidate(asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY):
    instrument = CandidateInstrument(
        instrument_id="instrument:AAA",
        symbol="AAA",
        name="AAA asset",
        asset_class=asset_class,
        economic_exposure_class=asset_class,
        venue="NYSE",
        country_code="US",
        average_daily_dollar_volume=100_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:test",
        security_master_record_identifiers=("security:AAA",),
    )
    return CandidateDecisionRecord(
        identifier="candidate:AAA",
        as_of=NOW,
        schema_version="candidate.test.v1",
        instrument=instrument,
        current_price=100.0,
        decision_horizon_days=90,
        base_case_return=0.08,
        bull_case_return=0.18,
        bear_case_return=-0.10,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=110.0,
        expected_upside=0.18,
        expected_downside=-0.10,
        probability_of_success=0.56,
        primary_catalysts=("forward demand",),
        key_risks=("demand reversal",),
        critical_assumptions=("demand persists",),
        invalidation_conditions=("demand breaks",),
        supporting_evidence=("evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.03,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("monitor",),
        review_at=NOW + timedelta(days=30),
        evidence_identifiers=("evidence:AAA",),
        model_versions=("model:test",),
    )


def test_leadership_needs_forward_mispricing_corroboration(monkeypatch):
    import intelligence.global_leadership as module

    monkeypatch.setattr(
        module,
        "assess_mispriced_change",
        lambda _bundle: SimpleNamespace(
            state=MispricedChangeState.CONSTRUCTIVE,
            score=0.55,
            confidence=0.8,
            evidence_identifiers=("evidence:mispricing",),
        ),
    )
    assessment = assess_global_leadership_economics(_bundle())
    assert assessment.state is GlobalLeadershipState.EMERGING
    assert 0.0 < assessment.interaction_return_adjustment <= 0.01
    enriched = enrich_bundle_with_global_leadership_economics(_bundle())
    added = [
        item
        for item in enriched.signals
        if item.identifier.startswith("signal:global-leadership-economics:")
    ]
    assert len(added) == 1
    assert added[0].expected_return_impact <= 0.01


def test_momentum_without_forward_economics_is_not_promoted(monkeypatch):
    import intelligence.global_leadership as module

    monkeypatch.setattr(
        module,
        "assess_mispriced_change",
        lambda _bundle: SimpleNamespace(
            state=MispricedChangeState.MOMENTUM_ONLY,
            score=0.20,
            confidence=0.7,
            evidence_identifiers=("evidence:momentum",),
        ),
    )
    assessment = assess_global_leadership_economics(_bundle())
    assert assessment.state is GlobalLeadershipState.UNCONFIRMED
    assert assessment.interaction_return_adjustment == 0.0


def _policy_inputs(
    *,
    evidence_vetoes=(),
    implementation_blocks=(),
    stressed_edge=-0.002,
    funding_source="cash",
    opposition_count=0,
    ensemble_stage="participate",
    preferred=True,
    discouraged=False,
):
    return dict(
        candidate=_candidate(),
        signal=GlobalOpportunitySignal(
            candidate_identifier="candidate:AAA",
            domain=GlobalOpportunityDomain.EQUITY,
            rank=1,
            score=0.66,
            leadership_state="emerging",
            leadership_score=0.75,
            mispriced_change_state="constructive_mispriced_change",
            mispriced_change_score=0.55,
            forward_impulse=0.04,
            expected_return_edge=0.05,
            evidence_score=0.9,
            evidence_identifiers=("evidence:AAA",),
        ),
        universe=SimpleNamespace(direct_recommendation_allowed=True),
        specialists=SimpleNamespace(
            evidence_vetoes=evidence_vetoes,
            implementation_blocks=implementation_blocks,
            portfolio_recommendation=SimpleNamespace(
                recommended_position_weight=0.08,
                funding_source=funding_source,
            ),
            historical_learning=SimpleNamespace(effective_position_multiplier=1.0),
            independent_opposition_count=lambda _threshold: opposition_count,
        ),
        robustness=SimpleNamespace(
            effective_probability_of_success=0.50,
            probability_of_loss=0.50,
            robust_edge=0.01,
            stressed_edge=stressed_edge,
            evidence_adjusted_return=0.045,
            reasons=(
                "evidence-adjusted geometric return does not clear the best alternative by the required margin",
            ),
        ),
        reconciliation=SimpleNamespace(
            expected_return=0.06,
            horizon_alternative_return=0.01,
            expected_downside=-0.20,
        ),
        profile=SimpleNamespace(
            maximum_expected_downside=-0.45,
            minimum_probability_of_success=0.52,
            minimum_net_expected_return=0.05,
            minimum_opportunity_edge=0.005,
            maximum_position_weight=0.10,
        ),
        ensemble=SimpleNamespace(stage=SimpleNamespace(value=ensemble_stage)),
        directive=SimpleNamespace(preferred=preferred, discouraged=discouraged),
        material_opposition_threshold=0.75,
    )


def test_soft_uncertainty_becomes_provisional_position_not_cash():
    decision = GlobalConvictionPolicy().assess(**_policy_inputs())
    assert decision.stage is ConvictionStage.PROVISIONAL
    assert decision.authorized is True
    assert 0.0 < decision.target_weight <= 0.03


def test_hard_evidence_veto_remains_zero_capital():
    decision = GlobalConvictionPolicy().assess(
        **_policy_inputs(evidence_vetoes=("source integrity failure",))
    )
    assert decision.stage is ConvictionStage.BLOCKED
    assert decision.target_weight is None


def test_hard_implementation_block_remains_zero_capital():
    decision = GlobalConvictionPolicy().assess(
        **_policy_inputs(implementation_blocks=("cannot implement safely",))
    )
    assert decision.stage is ConvictionStage.BLOCKED
    assert decision.target_weight is None


def test_missing_exact_funding_source_remains_zero_capital():
    decision = GlobalConvictionPolicy().assess(**_policy_inputs(funding_source=""))
    assert decision.stage is ConvictionStage.BLOCKED
    assert decision.target_weight is None


def test_ordinary_specialist_opposition_reduces_size_instead_of_forcing_cash():
    inputs = _policy_inputs(opposition_count=1, stressed_edge=0.01)
    inputs["robustness"] = SimpleNamespace(
        effective_probability_of_success=0.61,
        probability_of_loss=0.35,
        robust_edge=0.02,
        stressed_edge=0.01,
        evidence_adjusted_return=0.07,
        reasons=(),
    )
    decision = GlobalConvictionPolicy().assess(**inputs)
    assert decision.stage is ConvictionStage.PROVISIONAL
    assert decision.authorized is True
    assert decision.target_weight <= 0.03


def test_observe_ensemble_reduces_viable_opportunity_to_exploratory_not_zero():
    decision = GlobalConvictionPolicy().assess(
        **_policy_inputs(ensemble_stage="observe")
    )
    assert decision.stage is ConvictionStage.EXPLORATORY
    assert decision.authorized is True
    assert decision.target_weight <= 0.01


def test_fx_is_first_class_currency_domain_and_excess_cash_is_competed():
    fx = _candidate(CandidateAssetClass.FX)
    assert opportunity_domain(fx) is GlobalOpportunityDomain.CURRENCY
    portfolio = SimpleNamespace(
        as_of=NOW,
        cash_weight=0.60,
        cash_expected_return=0.04,
    )
    context = build_global_rotation_context(
        candidates=(fx,),
        specialist_contexts=(),
        portfolio=portfolio,
        minimum_cash_weight=0.05,
    )
    assert context.by_candidate[fx.identifier].domain is GlobalOpportunityDomain.CURRENCY
    assert context.excess_cash_weight == 0.55
    assert context.cash_competition_state in {
        CashCompetitionState.DEPLOYMENT_OPPORTUNITY,
        CashCompetitionState.CASH_LEADING_ESTIMATE,
    }


def test_confirmed_deterioration_derisks_and_names_cross_asset_replacement():
    cio = GlobalRotationChiefInvestmentOfficer()
    held = SimpleNamespace(identifier="held", current_portfolio_weight=0.08)
    held_signal = GlobalOpportunitySignal(
        "held",
        GlobalOpportunityDomain.EQUITY,
        2,
        0.35,
        "deteriorating",
        0.60,
        "deteriorating",
        -0.50,
        -0.04,
        -0.02,
        0.90,
        ("evidence:held",),
    )
    replacement = GlobalOpportunitySignal(
        "usd",
        GlobalOpportunityDomain.CURRENCY,
        1,
        0.80,
        "leading",
        0.80,
        "constructive_mispriced_change",
        0.50,
        0.05,
        0.04,
        0.90,
        ("evidence:usd",),
    )
    cio.set_global_rotation_context(
        GlobalRotationContext(
            as_of=NOW,
            signals=(replacement, held_signal),
            cash_expected_return=0.04,
            minimum_cash_weight=0.05,
            current_cash_weight=0.40,
            excess_cash_weight=0.35,
            cash_competition_state=CashCompetitionState.DEPLOYMENT_OPPORTUNITY,
        )
    )
    action, target, reason = cio._apply_confirmed_deterioration(
        held,
        action=CIOAction.HOLD,
        position_weight=None,
        reason="holding review.",
        conviction=GlobalConvictionDecision(
            ConvictionStage.QUALIFIED,
            0.07,
            (),
            (),
            ("ok",),
        ),
    )
    assert action is CIOAction.REDUCE
    assert target == 0.04
    assert "usd" in reason
    assert "currency" in reason
