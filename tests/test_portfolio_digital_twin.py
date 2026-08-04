from dataclasses import replace
from datetime import UTC, datetime

import pytest

from portfolio.digital_twin import (
    DigitalTwinAlternative,
    DigitalTwinPosition,
    PortfolioDigitalTwin,
    PortfolioPathScenario,
    ScenarioConfidence,
)


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def _scenario(identifier: str, probability: float, shock: float) -> PortfolioPathScenario:
    return PortfolioPathScenario(
        identifier=identifier,
        probability=probability,
        growth=shock,
        inflation=0.0,
        policy_rates=0.0,
        real_yields=0.0,
        credit_spreads=-shock,
        liquidity=shock,
        currency=0.0,
        commodities=0.0,
        volatility=abs(shock),
        correlation=abs(shock),
        earnings=shock,
        funding_stress=max(0.0, -shock),
        transaction_cost_multiplier=1.0 + abs(shock),
        market_liquidity_multiplier=max(0.5, 1.0 + shock),
        execution_delay_days=max(0.0, -shock * 10),
        instrument_return_shocks=(("asset:a", shock),),
    )


def test_digital_twin_preserves_cio_ceiling_and_reports_paths():
    position = DigitalTwinPosition(
        instrument_identifier="asset:a",
        current_weight=0.0,
        cio_approved_weight=0.20,
        constructed_weight=0.15,
        expected_return=0.08,
        volatility=0.20,
        liquidity_days=2.0,
        transaction_cost=0.002,
    )
    alternative = DigitalTwinAlternative("cio-selected", (position,), 0.85, 0.04)
    scenarios = (
        _scenario("bull", 0.3, 0.15),
        _scenario("base", 0.5, 0.0),
        _scenario("bear", 0.2, -0.20),
    )
    result = PortfolioDigitalTwin().simulate(alternative, scenarios, as_of=AS_OF)
    assert len(result.scenario_outcomes) == 3
    assert result.confidence is ScenarioConfidence.LIMITED
    assert result.probability_outperforming_cash >= 0.0
    assert result.to_dict()["can_increase_cio_sizing"] is False


def test_digital_twin_rejects_size_increase_and_unapproved_shock():
    with pytest.raises(ValueError, match="cannot increase"):
        DigitalTwinPosition("asset:a", 0.0, 0.10, 0.20, 0.08, 0.2, 1.0, 0.001)
    position = DigitalTwinPosition(
        "asset:a", 0.0, 0.20, 0.10, 0.08, 0.2, 1.0, 0.001
    )
    alternative = DigitalTwinAlternative("selected", (position,), 0.90, 0.04)
    bad = _scenario("bad", 1.0, 0.0)
    bad = replace(bad, instrument_return_shocks=(("asset:unapproved", 0.1),))
    with pytest.raises(ValueError, match="unapproved"):
        PortfolioDigitalTwin().simulate(alternative, (bad,), as_of=AS_OF)
