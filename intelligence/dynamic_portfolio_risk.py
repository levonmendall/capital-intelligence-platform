"""Dynamic covariance and stressed-correlation research for portfolio construction."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import fmean


@dataclass(frozen=True, slots=True)
class AssetReturnSeries:
    symbol: str
    returns: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if len(self.returns) < 20:
            raise ValueError("return series requires at least 20 observations")
        if any(not isfinite(float(item)) for item in self.returns):
            raise ValueError("returns must be finite")


@dataclass(frozen=True, slots=True)
class DynamicCovarianceEstimate:
    symbols: tuple[str, ...]
    covariance: tuple[tuple[float, ...], ...]
    stressed_covariance: tuple[tuple[float, ...], ...]
    long_window: int
    recent_window: int
    recent_weight: float
    schema_version: str = "dynamic-covariance.v1"


@dataclass(frozen=True, slots=True)
class PortfolioRiskEstimate:
    annualized_volatility: float
    stressed_annualized_volatility: float
    marginal_variance_contributions: tuple[tuple[str, float], ...]
    investment_authority: bool = False
    execution_authority: bool = False


def _covariance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    n = min(len(a), len(b))
    left, right = a[-n:], b[-n:]
    mean_a, mean_b = fmean(left), fmean(right)
    return sum((x - mean_a) * (y - mean_b) for x, y in zip(left, right)) / max(1, n - 1)


class DynamicPortfolioRiskEngine:
    version = "dynamic-covariance-risk.v1"

    def estimate_covariance(
        self,
        series: tuple[AssetReturnSeries, ...],
        *,
        long_window: int = 252,
        recent_window: int = 63,
        recent_weight: float = 0.60,
        stress_vol_multiplier: float = 1.35,
        stress_correlation_pull: float = 0.20,
    ) -> DynamicCovarianceEstimate:
        if not series:
            raise ValueError("at least one return series is required")
        if len({item.symbol for item in series}) != len(series):
            raise ValueError("return-series symbols must be unique")
        if recent_window < 20 or long_window < recent_window:
            raise ValueError("risk windows are invalid")
        if not 0.0 <= recent_weight <= 1.0:
            raise ValueError("recent_weight must be between zero and one")
        if stress_vol_multiplier < 1.0:
            raise ValueError("stress_vol_multiplier must be at least one")
        if not 0.0 <= stress_correlation_pull <= 1.0:
            raise ValueError("stress_correlation_pull must be between zero and one")
        values = []
        for left in series:
            row = []
            for right in series:
                long_cov = _covariance(
                    left.returns[-min(long_window, len(left.returns)):],
                    right.returns[-min(long_window, len(right.returns)):],
                )
                recent_cov = _covariance(
                    left.returns[-min(recent_window, len(left.returns)):],
                    right.returns[-min(recent_window, len(right.returns)):],
                )
                row.append(recent_weight * recent_cov + (1.0 - recent_weight) * long_cov)
            values.append(row)
        variances = [max(0.0, values[index][index]) for index in range(len(series))]
        stressed = []
        for i in range(len(series)):
            row = []
            for j in range(len(series)):
                if i == j:
                    row.append(variances[i] * stress_vol_multiplier**2)
                    continue
                denom = sqrt(max(variances[i] * variances[j], 1e-18))
                corr = max(-1.0, min(1.0, values[i][j] / denom))
                stressed_corr = corr + stress_correlation_pull * (1.0 - corr)
                row.append(
                    stressed_corr
                    * sqrt(variances[i] * variances[j])
                    * stress_vol_multiplier**2
                )
            stressed.append(row)
        return DynamicCovarianceEstimate(
            symbols=tuple(item.symbol for item in series),
            covariance=tuple(tuple(round(item, 12) for item in row) for row in values),
            stressed_covariance=tuple(
                tuple(round(item, 12) for item in row) for row in stressed
            ),
            long_window=long_window,
            recent_window=recent_window,
            recent_weight=recent_weight,
        )

    def portfolio_risk(
        self,
        estimate: DynamicCovarianceEstimate,
        weights: tuple[tuple[str, float], ...],
    ) -> PortfolioRiskEstimate:
        weight_map = dict(weights)
        if any(symbol not in weight_map for symbol in estimate.symbols):
            raise ValueError("weights must cover every covariance symbol")
        vector = [float(weight_map[symbol]) for symbol in estimate.symbols]

        def variance(matrix: tuple[tuple[float, ...], ...]) -> float:
            return sum(
                vector[i] * vector[j] * matrix[i][j]
                for i in range(len(vector))
                for j in range(len(vector))
            )

        base_variance = max(0.0, variance(estimate.covariance))
        stress_variance = max(0.0, variance(estimate.stressed_covariance))
        marginal = []
        for i, symbol in enumerate(estimate.symbols):
            contribution = vector[i] * sum(
                estimate.covariance[i][j] * vector[j]
                for j in range(len(vector))
            )
            marginal.append((symbol, round(contribution, 12)))
        return PortfolioRiskEstimate(
            annualized_volatility=round(sqrt(base_variance * 252.0), 8),
            stressed_annualized_volatility=round(sqrt(stress_variance * 252.0), 8),
            marginal_variance_contributions=tuple(marginal),
        )


__all__ = [
    "AssetReturnSeries",
    "DynamicCovarianceEstimate",
    "DynamicPortfolioRiskEngine",
    "PortfolioRiskEstimate",
]
