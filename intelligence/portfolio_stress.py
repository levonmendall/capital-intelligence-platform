"""Research-only factor decomposition and deterministic portfolio stress testing."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class FactorExposure:
    symbol: str
    weight: float
    loadings: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if not isfinite(float(self.weight)):
            raise ValueError("weight must be finite")
        names = tuple(name for name, _value in self.loadings)
        if len(names) != len(set(names)):
            raise ValueError("factor loading names must be unique")
        if any(not isfinite(float(value)) for _name, value in self.loadings):
            raise ValueError("factor loadings must be finite")


@dataclass(frozen=True, slots=True)
class StressScenario:
    identifier: str
    shocks: tuple[tuple[str, float], ...]
    description: str

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.description.strip():
            raise ValueError("stress scenario identity/description cannot be empty")
        names = tuple(name for name, _value in self.shocks)
        if len(names) != len(set(names)):
            raise ValueError("stress factor names must be unique")


@dataclass(frozen=True, slots=True)
class StressResult:
    scenario_identifier: str
    estimated_portfolio_return: float
    contributions: tuple[tuple[str, float], ...]
    missing_factors: tuple[str, ...]
    investment_authority: bool = False
    execution_authority: bool = False


class PortfolioStressEngine:
    version = "portfolio-factor-stress.v1"

    def run(
        self,
        exposures: tuple[FactorExposure, ...],
        scenario: StressScenario,
    ) -> StressResult:
        shock_map = dict(scenario.shocks)
        contributions: list[tuple[str, float]] = []
        observed_factors: set[str] = set()
        total = 0.0
        for exposure in exposures:
            contribution = 0.0
            for factor, loading in exposure.loadings:
                observed_factors.add(factor)
                contribution += float(loading) * float(shock_map.get(factor, 0.0))
            weighted = float(exposure.weight) * contribution
            contributions.append((exposure.symbol, round(weighted, 8)))
            total += weighted
        missing = tuple(sorted(set(shock_map) - observed_factors))
        return StressResult(
            scenario_identifier=scenario.identifier,
            estimated_portfolio_return=round(total, 8),
            contributions=tuple(contributions),
            missing_factors=missing,
        )


DEFAULT_STRESS_SCENARIOS = (
    StressScenario(
        "rates-plus-200bp",
        (("duration", -0.02), ("rate_sensitive", -0.15), ("usd", 0.05)),
        "Parallel rate shock with tighter financial conditions.",
    ),
    StressScenario(
        "global-recession",
        (("equity_beta", -0.30), ("credit", -0.15), ("duration", 0.10), ("commodity", -0.20)),
        "Global recession with risk-asset drawdown and duration support.",
    ),
    StressScenario(
        "inflation-resurgence",
        (("duration", -0.15), ("inflation", 0.20), ("commodity", 0.25), ("growth", -0.10)),
        "Inflation resurgence, higher yields, and weaker real growth.",
    ),
    StressScenario(
        "dollar-plus-15pct",
        (("usd", 0.15), ("international_equity", -0.10), ("commodity", -0.10), ("crypto", -0.15)),
        "Broad U.S.-dollar appreciation shock.",
    ),
    StressScenario(
        "crypto-minus-60pct",
        (("crypto", -0.60), ("high_beta", -0.20), ("liquidity", -0.10)),
        "Large crypto drawdown with correlated liquidity stress.",
    ),
)


__all__ = [
    "DEFAULT_STRESS_SCENARIOS",
    "FactorExposure",
    "PortfolioStressEngine",
    "StressResult",
    "StressScenario",
]
