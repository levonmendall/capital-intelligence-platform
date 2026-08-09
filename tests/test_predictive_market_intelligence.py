from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import production_paper_evidence as paper_evidence
from committee.specialists import MarketSpecialistContext
from intelligence.forward import (
    ForwardIntelligenceBundle,
    ForwardScenario,
    ForwardSignal,
)
from intelligence.predictive_market import (
    CapitalFlowEngine,
    CapitalFlowState,
    MarketExpectationsEngine,
    build_predictive_market_intelligence,
)
from intelligence.predictive_scenario_merge import (
    reconcile_forward_intelligence,
)


NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)


def _rows(*, first: float, daily_return: float, volume_growth: float, count: int = 120):
    rows = []
    close = first
    volume = 1_000_000.0
    for index in range(count):
        close *= 1.0 + daily_return
        volume *= 1.0 + volume_growth
        rows.append(
            {
                "t": (NOW - timedelta(days=count - index)).isoformat(),
                "c": close,
                "v": volume,
            }
        )
    return tuple(rows)


def _candidate(*, base_return: float = 0.16, probability: float = 0.62):
    return SimpleNamespace(
        identifier="candidate:test:ABC",
        as_of=NOW,
        base_case_return=base_return,
        probability_of_success=probability,
        primary_catalysts=("earnings revisions improve",),
        evidence_identifiers=("candidate:evidence",),
        evidence_quality=SimpleNamespace(score=0.82),
    )


def _features(*, momentum: float, six_month: float, twelve_month: float, volatility: float):
    return SimpleNamespace(
        symbol="ABC",
        momentum=momentum,
        six_month_return=six_month,
        twelve_month_return=twelve_month,
        annualized_volatility=volatility,
        rolling_annual_median=0.10,
        evidence_identifiers=("bars:ABC", "quote:ABC"),
    )


def _market() -> MarketSpecialistContext:
    return MarketSpecialistContext(
        as_of=NOW,
        market_regime="positive_trend",
        expected_return_impact=0.02,
        confidence=0.62,
        trend=0.30,
        momentum=0.25,
        breadth=0.10,
        liquidity=0.70,
        positioning=0.0,
        evidence=("existing market evidence",),
        risks=("existing market risk",),
        entry_conditions=("quote remains current",),
        evidence_identifiers=("market:evidence",),
    )


def test_durable_price_volume_confirmation_is_accumulation() -> None:
    rows = _rows(first=100.0, daily_return=0.004, volume_growth=0.004)
    observation = CapitalFlowEngine.observe(
        symbol="ABC",
        as_of=NOW,
        rows=rows,
        evidence_identifiers=("bars:ABC",),
    )
    assessment = CapitalFlowEngine().analyze(observation)

    assert assessment.state in {
        CapitalFlowState.ACCUMULATION,
        CapitalFlowState.CROWDED_ADVANCE,
    }
    assert assessment.direction > 0.0
    assert assessment.expected_return_impact > 0.0
    assert assessment.signal.channels == ("market", "forecast")


def test_positive_bounce_after_medium_decline_retains_covering_risk() -> None:
    rows = list(_rows(first=120.0, daily_return=-0.003, volume_growth=0.0, count=100))
    close = float(rows[-1]["c"])
    volume = float(rows[-1]["v"])
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


def test_expectations_gap_rewards_unpriced_outlook_and_penalizes_fully_priced_move() -> None:
    flow_rows = _rows(first=100.0, daily_return=0.001, volume_growth=0.001)
    flow = CapitalFlowEngine().analyze(
        CapitalFlowEngine.observe(
            symbol="ABC",
            as_of=NOW,
            rows=flow_rows,
            evidence_identifiers=("bars:ABC",),
        )
    )
    underpriced = MarketExpectationsEngine.observe(
        candidate=_candidate(base_return=0.20, probability=0.65),
        features=_features(
            momentum=0.03,
            six_month=0.04,
            twelve_month=0.05,
            volatility=0.20,
        ),
        flow=flow,
    )
    fully_priced = MarketExpectationsEngine.observe(
        candidate=_candidate(base_return=0.08, probability=0.55),
        features=_features(
            momentum=0.45,
            six_month=0.55,
            twelve_month=0.70,
            volatility=0.30,
        ),
        flow=flow,
    )

    underpriced_assessment = MarketExpectationsEngine().analyze(underpriced)
    fully_priced_assessment = MarketExpectationsEngine().analyze(fully_priced)

    assert underpriced.expected_surprise > 0.0
    assert underpriced.priced_in_score < fully_priced.priced_in_score
    assert underpriced_assessment.expected_return_impact > fully_priced_assessment.expected_return_impact


def test_predictive_signals_enrich_existing_market_and_forward_contract() -> None:
    rows = _rows(first=100.0, daily_return=0.003, volume_growth=0.002)
    observation = CapitalFlowEngine.observe(
        symbol="ABC",
        as_of=NOW,
        rows=rows,
        evidence_identifiers=("bars:ABC",),
    )
    result = build_predictive_market_intelligence(
        candidate=_candidate(),
        features=_features(
            momentum=0.12,
            six_month=0.15,
            twelve_month=0.20,
            volatility=0.24,
        ),
        flow_observation=observation,
        market=_market(),
        existing_forward_intelligence=None,
    )

    assert result.market.positioning != 0.0
    assert "predictive-market" in result.forward_intelligence.identifier
    assert result.forward_intelligence.decision_context is None
    assert {signal.name for signal in result.forward_intelligence.signals} == {
        f"{result.flow.state.value.replace('_', ' ')} capital-flow proxy",
        "market expectations gap",
    }
    assert set(result.forward_intelligence.evidence_identifiers).issubset(
        set(result.evidence_identifiers)
    )
    assert any("priced-in" in item for item in result.market.risks)


def test_duplicate_forward_scenario_labels_are_reconciled_not_appended() -> None:
    signal = ForwardSignal(
        identifier="signal:test",
        as_of=NOW,
        name="test signal",
        channels=("forecast",),
        expected_return_impact=0.01,
        confidence=0.60,
        evidence=("test evidence",),
        contradictory_evidence=(),
        assumptions=("test assumption",),
        risks=("test risk",),
        change_conditions=("test change",),
        evidence_identifiers=("evidence:test",),
    )
    existing = ForwardIntelligenceBundle(
        identifier="forward:existing",
        candidate_identifier="candidate:test:ABC",
        as_of=NOW,
        signals=(signal,),
        scenarios=(
            ForwardScenario(
                label="bull",
                return_delta=0.05,
                probability_delta=0.01,
                path_drawdown_delta=0.0,
                rationale="existing bull case",
                evidence_identifiers=("evidence:existing",),
            ),
        ),
        diagnostics=(),
        model_versions=("existing.v1",),
    )
    predictive = ForwardIntelligenceBundle(
        identifier="forward:predictive",
        candidate_identifier="candidate:test:ABC",
        as_of=NOW,
        signals=(),
        scenarios=(
            ForwardScenario(
                label="bull",
                return_delta=0.04,
                probability_delta=0.02,
                path_drawdown_delta=0.0,
                rationale="predictive bull case",
                evidence_identifiers=("evidence:predictive",),
            ),
        ),
        diagnostics=(),
        model_versions=("predictive.v1",),
    )

    merged = reconcile_forward_intelligence(existing, predictive)

    assert len(merged.scenarios) == 1
    assert merged.scenarios[0].label == "bull"
    assert merged.scenarios[0].return_delta == 0.09
    assert merged.scenarios[0].probability_delta == 0.03
    assert set(merged.scenarios[0].evidence_identifiers) == {
        "evidence:existing",
        "evidence:predictive",
    }


def test_direct_helper_compatibility_flow_is_explicitly_neutral_and_nonproduction() -> None:
    features = _features(
        momentum=0.0,
        six_month=0.0,
        twelve_month=0.0,
        volatility=0.24,
    )
    observation = paper_evidence._compatibility_flow_observation(features, NOW)

    assert "compatibility-only" in observation.identifier
    assert observation.signed_dollar_flow == 0.0
    assert observation.accumulation_distribution == 0.0
    assert observation.persistence == 0.50
    assert observation.volatility == 0.24
    assert observation.identifier in observation.evidence_identifiers


def test_production_build_flag_is_distinct_from_direct_helper_compatibility() -> None:
    paper_evidence._FLOW_STATE.production_build = True
    try:
        assert paper_evidence._production_build_active() is True
    finally:
        paper_evidence._FLOW_STATE.production_build = False
    assert paper_evidence._production_build_active() is False
