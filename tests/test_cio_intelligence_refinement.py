from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from application.joint_portfolio_preview import build_joint_portfolio_preview
from cio import ChiefInvestmentOfficer
from cio.intelligence_refinement import (
    PathAwareRobustCandidateAssessor,
    cap_historical_confidence,
    refine_decision_context_payload,
)
from cio.joint_preview import JointPortfolioPreview
from cio.models import (
    CIOAction,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)


def _candidate(symbol: str = "AAA") -> CandidateDecisionRecord:
    as_of = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)
    instrument = CandidateInstrument(
        instrument_id=f"instrument:{symbol}",
        symbol=symbol,
        name=f"{symbol} asset",
        asset_class=CandidateAssetClass.US_EQUITY,
        venue="NYSE",
        country_code="US",
        average_daily_dollar_volume=250_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:test",
        security_master_record_identifiers=(f"security:{symbol}",),
    )
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol}",
        as_of=as_of,
        schema_version="candidate-decision.test.v1",
        instrument=instrument,
        current_price=100.0,
        decision_horizon_days=90,
        base_case_return=0.10,
        bull_case_return=0.25,
        bear_case_return=-0.15,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=110.0,
        expected_upside=0.25,
        expected_downside=-0.15,
        probability_of_success=0.60,
        primary_catalysts=("earnings improvement",),
        key_risks=("demand deterioration",),
        critical_assumptions=("margins remain durable",),
        invalidation_conditions=("margin thesis fails",),
        supporting_evidence=("point-in-time evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(
            reliability=0.90,
            freshness=0.90,
            relevance=0.90,
            independence=0.90,
            completeness=0.90,
            point_in_time_integrity=0.90,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.02,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("monitor:test",),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=(f"evidence:{symbol}",),
        model_versions=("model:test",),
    )


def test_canonical_export_uses_intelligence_refined_cio() -> None:
    assert ChiefInvestmentOfficer.__module__ == "cio.intelligence_refinement"


def test_historical_learning_ceiling_is_restored() -> None:
    specialists = SimpleNamespace(
        historical_learning=SimpleNamespace(confidence_ceiling=0.42)
    )
    assert cap_historical_confidence(0.81, specialists) == 0.42


def test_reconciled_path_drawdown_becomes_robustness_authoritative() -> None:
    candidate = _candidate()
    assessor = PathAwareRobustCandidateAssessor()
    baseline = assessor.assess(
        candidate,
        alternative_return=0.02,
        position_weight=0.10,
    )
    with assessor.bind_path_drawdowns(
        candidate.identifier,
        (("bear", -0.90),),
    ):
        path_aware = assessor.assess(
            candidate,
            alternative_return=0.02,
            position_weight=0.10,
        )
    assert path_aware.worst_case_portfolio_return < baseline.worst_case_portfolio_return
    assert path_aware.worst_case_portfolio_return < -0.06
    assert any("path drawdown" in reason for reason in path_aware.reasons)


def test_context_uses_horizon_consistent_edge_and_structured_stage() -> None:
    candidate = _candidate()
    decision = SimpleNamespace(
        action=CIOAction.BUY,
        rationale=(
            "Ordinary acquisition abstained. Portfolio-posture staged participation "
            "applies: bounded exploration."
        ),
        expected_return=0.06,
        return_reconciliation=SimpleNamespace(
            horizon_alternative_return=0.015,
            path_drawdown_by_scenario=(("bear", -0.20),),
        ),
    )
    preview = JointPortfolioPreview(
        identifier="joint-preview:test",
        status="partial",
        policy_version="portfolio-construction.test",
        requested_targets=((candidate.identifier, 0.10),),
        joint_targets=((candidate.identifier, 0.04),),
        target_cash_weight=0.30,
        expected_return_improvement=0.01,
        blocks=("competing candidate used remaining capacity",),
    )
    payload = {
        "action_ladder": {
            "reduce": {"triggers": ["expected return below threshold"]},
            "exit": {
                "triggers": [
                    "expected return below full-exit threshold",
                    "complete thesis invalidation or integrity emergency",
                ]
            },
        }
    }
    refined = refine_decision_context_payload(
        payload,
        decision=decision,
        candidate=candidate,
        joint_preview=preview,
    )
    assert refined["horizon_alternative_return"] == 0.015
    assert refined["best_alternative_relative_edge"] == 0.045
    assert refined["cash_relative_edge"] == 0.045
    assert refined["decision_stage"] == "exploratory"
    assert refined["participation_mode"] == "portfolio_posture_staged"
    assert refined["joint_portfolio_preview"]["positive_cap"] == 0.04
    assert "complete thesis invalidation or integrity emergency" not in refined[
        "action_ladder"
    ]["exit"]["triggers"]
    assert any(
        "integrity emergency" in item
        for item in refined["action_ladder"]["reduce"]["triggers"]
    )


def test_zero_joint_target_is_not_hidden_cio_veto() -> None:
    candidate = _candidate()
    preview = JointPortfolioPreview(
        identifier="joint-preview:zero",
        status="partial",
        policy_version="portfolio-construction.test",
        requested_targets=((candidate.identifier, 0.10),),
        joint_targets=((candidate.identifier, 0.0),),
        target_cash_weight=1.0,
        expected_return_improvement=0.0,
    )
    assert preview.positive_cap_for(
        candidate.identifier,
        current_weight=0.0,
    ) is None


def test_joint_preview_constructs_review_candidates_simultaneously() -> None:
    first = _candidate("AAA")
    second = _candidate("BBB")

    class Portfolio:
        cash_weight = 1.0

        def current_weight(self, symbol):
            return 0.0

        def profile(self, candidate_identifier):
            return SimpleNamespace(
                sector="test",
                factor_loadings=(),
                correlation_bucket="test",
                derivative_lifecycle=None,
            )

        def request(self, *, identifier, intents):
            return SimpleNamespace(identifier=identifier, intents=intents)

    class Engine:
        policy = SimpleNamespace(version="portfolio-construction.test")

        def __init__(self):
            self.intent_count = 0

        def construct(self, request):
            self.intent_count = len(request.intents)
            return SimpleNamespace(
                request_identifier=request.identifier,
                status=SimpleNamespace(value="partial"),
                policy_version="portfolio-construction.test",
                target_weights=(("AAA", 0.06), ("BBB", 0.03)),
                target_cash_weight=0.91,
                expected_return_improvement=0.02,
                blocks=(),
            )

    engine = Engine()
    preview = build_joint_portfolio_preview(
        cycle_identifier="cycle:test",
        candidates=(first, second),
        portfolio=Portfolio(),
        construction_engine=engine,
    )
    assert engine.intent_count == 2
    assert preview.target_for(first.identifier) == 0.06
    assert preview.target_for(second.identifier) == 0.03
