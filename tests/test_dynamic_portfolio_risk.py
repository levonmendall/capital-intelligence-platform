from intelligence.dynamic_portfolio_risk import (
    AssetReturnSeries,
    DynamicPortfolioRiskEngine,
)


def test_dynamic_risk_stress_increases_portfolio_volatility() -> None:
    left = tuple(0.01 if index % 2 == 0 else -0.008 for index in range(300))
    right = tuple(0.006 if index % 3 else -0.007 for index in range(300))
    engine = DynamicPortfolioRiskEngine()
    covariance = engine.estimate_covariance(
        (AssetReturnSeries("EQ", left), AssetReturnSeries("BOND", right))
    )
    risk = engine.portfolio_risk(covariance, (("EQ", 0.6), ("BOND", 0.4)))
    assert risk.annualized_volatility > 0.0
    assert risk.stressed_annualized_volatility >= risk.annualized_volatility
    assert risk.investment_authority is False
