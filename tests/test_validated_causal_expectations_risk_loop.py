from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from application.cio_cycle import CyclePortfolioState
from evaluation.causal_intelligence_graph import (
    CausalTransmissionOutcome,
    SQLiteCausalIntelligenceGraphStore,
    build_causal_calibration_report,
    build_causal_investment_graph,
)
from evaluation.causal_intelligence_runtime import persist_governed_event_forward_result
from evaluation.expectations_resolution import (
    ExpectationsForecastRecord,
    ExpectationsOutcomeObservation,
    SQLiteExpectationsResolutionStore,
    build_expectations_calibration_report,
)
from intelligence.event_market_forward import (
    CausalDriver,
    EventCausalState,
    EventMarketAssessment,
    MarketTransmission,
    RuleTransmission,
    TransmissionDirection,
)
from intelligence.portfolio_risk_synthesis import build_portfolio_risk_synthesis
from portfolio.construction_api import PortfolioAsset
from providers.event_forward import GovernedEventForwardResult


NOW = datetime(2026, 8, 10, 5, 30, tzinfo=timezone.utc)


def _assessment() -> EventMarketAssessment:
    driver = CausalDriver(
        rule_identifier="geopolitical-deescalation",
        name="geopolitical de-escalation",
        confidence=0.80,
        causal_chain=(
            "disruption probability falls",
            "risk premium compresses",
        ),
        transmissions=(
            RuleTransmission(
                target_identifier="affected_commodity",
                direction=TransmissionDirection.NEGATIVE,
                magnitude=0.50,
                mechanism="lower disruption premium",
                horizon="near_term",
            ),
        ),
        alternatives=("demand deterioration",),
    )
    transmission = MarketTransmission(
        target_identifier="broad_equities",
        direction=TransmissionDirection.POSITIVE,
        magnitude=0.40,
        confidence=0.75,
        mechanism="lower risk premium supports risk appetite",
        horizon="near_to_medium_term",
        contributing_driver_identifiers=("geopolitical-deescalation",),
        evidence_identifiers=("market:1", "event:1"),
    )
    return EventMarketAssessment(
        identifier="assessment:1",
        information_identifier="information:1",
        event_cluster_identifier="cluster:1",
        assessed_at=NOW,
        state=EventCausalState.MAPPED,
        drivers=(driver,),
        causal_chain=driver.causal_chain,
        transmissions=(transmission,),
        market_confirmation=0.70,
        confirmation_coverage=1.0,
        confidence=0.75,
        major_event=True,
        requires_causal_review=False,
        contradictory_evidence=("demand may also be weakening",),
        alternative_explanations=("growth expectations changed",),
        unresolved_questions=(),
        evidence_identifiers=("event:1", "market:1"),
        eligible_for_analysis=True,
        eligible_for_cio_context=True,
        policy_version="event-market-forward.v1",
    )


def test_causal_graph_preserves_event_to_driver_to_exposure_to_candidate(tmp_path):
    assessment = _assessment()
    graph = build_causal_investment_graph(
        assessment,
        candidate_exposure_links=(("broad_equities", "candidate:abc"),),
    )
    relationships = {item.relationship for item in graph.edges}
    assert {"explained_by", "transmits_to", "exposed_to"}.issubset(relationships)
    assert graph.investment_authority is False
    candidate_nodes = [item for item in graph.nodes if item.kind.value == "candidate"]
    assert len(candidate_nodes) == 1
    assert candidate_nodes[0].label == "candidate:abc"

    store = SQLiteCausalIntelligenceGraphStore(tmp_path / "causal.db")
    store.append_graph(graph)
    transmission_edge = next(
        item for item in graph.edges if item.relationship == "transmits_to"
    )
    store.append_outcome(
        CausalTransmissionOutcome(
            edge_identifier=transmission_edge.identifier,
            observed_at=NOW + timedelta(days=30),
            realized_direction="positive",
            realized_magnitude=0.42,
            evidence_identifiers=("outcome:1",),
        )
    )
    report = build_causal_calibration_report(
        store.resolved_edges(),
        as_of=NOW + timedelta(days=30),
    )
    assert report.directional_accuracy == 1.0
    assert report.magnitude_mean_absolute_error == pytest.approx(0.02)
    assert report.suggested_confidence_ceiling <= report.mean_confidence
    assert report.policy_change_authorized is False


def test_event_forward_result_persists_exact_retained_assessment(tmp_path):
    assessment = _assessment()
    result = GovernedEventForwardResult(
        bundles=(),
        assessment_identifiers=(assessment.identifier,),
        hypothesis_identifiers=(),
        diagnostics=("test",),
        assessments=(assessment,),
        candidate_exposure_links=(
            (assessment.identifier, "broad_equities", "candidate:abc"),
        ),
    )
    hashes = persist_governed_event_forward_result(
        result,
        path=tmp_path / "causal-runtime.db",
    )
    assert len(hashes) == 1
    assert result.authorizes_capital is False


def test_expectations_resolution_is_point_in_time_and_advisory(tmp_path):
    store = SQLiteExpectationsResolutionStore(tmp_path / "expectations.db")
    forecast = ExpectationsForecastRecord(
        identifier="expectations:1",
        packet_identifier="packet:1",
        candidate_identifier="candidate:abc",
        symbol="ABC",
        as_of=NOW,
        market_expectation="2.8%",
        internal_expectation="2.6%",
        expected_surprise=-0.20,
        priced_in_score=0.70,
        evidence_identifiers=("consensus:1",),
    )
    store.append_forecast(forecast)
    with pytest.raises(ValueError, match="after the forecast"):
        store.append_outcome(
            ExpectationsOutcomeObservation(
                forecast_identifier=forecast.identifier,
                observed_at=NOW,
                realized_surprise=-0.15,
                market_reaction=0.01,
                abnormal_market_reaction=0.005,
                evidence_identifiers=("release:1",),
            )
        )
    store.append_outcome(
        ExpectationsOutcomeObservation(
            forecast_identifier=forecast.identifier,
            observed_at=NOW + timedelta(hours=1),
            realized_surprise=-0.15,
            market_reaction=0.01,
            abnormal_market_reaction=0.005,
            evidence_identifiers=("release:1",),
        )
    )
    report = build_expectations_calibration_report(
        store.resolved_pairs(),
        as_of=NOW + timedelta(hours=1),
    )
    assert report.surprise_direction_accuracy == 1.0
    assert report.surprise_mean_absolute_error == pytest.approx(0.05)
    assert report.suggested_confidence_ceiling <= 1.0
    assert report.policy_change_authorized is False
    assert report.performance_claim_authorized is False


def _asset(symbol: str, weight: float, factor: str) -> PortfolioAsset:
    return PortfolioAsset(
        symbol=symbol,
        current_weight=weight,
        expected_return=0.07,
        sector="test",
        factor_loadings=((factor, 1.0),),
        correlation_bucket=factor,
        average_daily_dollar_volume=100_000_000.0,
        transaction_cost_bps=1.0,
        slippage_bps=1.0,
    )


def test_whole_portfolio_risk_compares_constructed_stress_without_fake_covariance():
    portfolio = CyclePortfolioState(
        identifier="portfolio:1",
        as_of=NOW,
        portfolio_value=250_000.0,
        cash_weight=0.20,
        cash_expected_return=0.04,
        positions=(
            _asset("EQ", 0.40, "equity_beta"),
            _asset("BOND", 0.40, "duration"),
        ),
        exposure_profiles=(),
    )
    construction = SimpleNamespace(
        target_weights=(("EQ", 0.50), ("BOND", 0.30)),
    )
    report = build_portfolio_risk_synthesis(
        portfolio=portfolio,
        construction=construction,
    )
    assert dict(report.current_factor_exposures)["equity_beta"] == pytest.approx(0.40)
    assert dict(report.proposed_factor_exposures)["equity_beta"] == pytest.approx(0.50)
    assert set(report.missing_dynamic_return_series) == {"EQ", "BOND"}
    assert report.dynamic_current is None
    assert report.dynamic_proposed is None
    assert any("unavailable" in item for item in report.risk_change_summary)
    assert report.investment_authority is False
    assert report.construction_authority is False


def test_dynamic_portfolio_risk_activates_only_with_complete_history():
    portfolio = CyclePortfolioState(
        identifier="portfolio:2",
        as_of=NOW,
        portfolio_value=250_000.0,
        cash_weight=0.20,
        cash_expected_return=0.04,
        positions=(
            _asset("EQ", 0.40, "equity_beta"),
            _asset("BOND", 0.40, "duration"),
        ),
        exposure_profiles=(),
    )
    construction = SimpleNamespace(
        target_weights=(("EQ", 0.50), ("BOND", 0.30)),
    )
    eq_returns = tuple(0.001 * ((index % 5) - 2) for index in range(80))
    bond_returns = tuple(0.0005 * ((index % 7) - 3) for index in range(80))
    report = build_portfolio_risk_synthesis(
        portfolio=portfolio,
        construction=construction,
        return_series_by_symbol={"EQ": eq_returns, "BOND": bond_returns},
    )
    assert report.missing_dynamic_return_series == ()
    assert report.dynamic_current is not None
    assert report.dynamic_proposed is not None
