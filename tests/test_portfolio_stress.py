from intelligence.portfolio_stress import (
    FactorExposure,
    PortfolioStressEngine,
    StressScenario,
)


def test_stress_engine_attributes_portfolio_factor_shock_without_authority() -> None:
    result = PortfolioStressEngine().run(
        (
            FactorExposure("EQ", 0.60, (("equity_beta", 1.0),)),
            FactorExposure("BOND", 0.40, (("duration", 0.8),)),
        ),
        StressScenario(
            "recession",
            (("equity_beta", -0.30), ("duration", 0.10)),
            "recession test",
        ),
    )
    assert result.estimated_portfolio_return == -0.148
    assert result.investment_authority is False
    assert result.execution_authority is False
