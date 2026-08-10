"""Read-only whole-portfolio factor, stress, and dynamic-risk synthesis.

This module reuses the existing ``PortfolioStressEngine`` and
``DynamicPortfolioRiskEngine``. It compares the current portfolio with the constructed
portfolio and explicitly reports missing return histories rather than manufacturing a
covariance estimate. It cannot change construction limits or authorize capital; any
future influence must pass ``governance.analytical_promotion``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from intelligence.dynamic_portfolio_risk import (
    AssetReturnSeries,
    DynamicPortfolioRiskEngine,
    PortfolioRiskEstimate,
)
from intelligence.portfolio_stress import (
    DEFAULT_STRESS_SCENARIOS,
    FactorExposure,
    PortfolioStressEngine,
    StressResult,
)


def _weight_map(values: object) -> dict[str, float]:
    try:
        raw = dict(values or ())
    except (TypeError, ValueError):
        return {}
    return {str(symbol).upper(): float(weight) for symbol, weight in raw.items()}


def _aggregate_factor_exposures(exposures: tuple[FactorExposure, ...]) -> tuple[tuple[str, float], ...]:
    totals: dict[str, float] = {}
    for exposure in exposures:
        for factor, loading in exposure.loadings:
            totals[factor] = totals.get(factor, 0.0) + float(exposure.weight) * float(loading)
    return tuple(sorted((factor, round(value, 8)) for factor, value in totals.items()))


@dataclass(frozen=True, slots=True)
class PortfolioRiskSynthesis:
    identifier: str
    as_of: datetime
    current_factor_exposures: tuple[tuple[str, float], ...]
    proposed_factor_exposures: tuple[tuple[str, float], ...]
    current_stress_results: tuple[StressResult, ...]
    proposed_stress_results: tuple[StressResult, ...]
    worst_current_stress: tuple[str, float] | None
    worst_proposed_stress: tuple[str, float] | None
    dynamic_current: PortfolioRiskEstimate | None
    dynamic_proposed: PortfolioRiskEstimate | None
    missing_dynamic_return_series: tuple[str, ...]
    risk_change_summary: tuple[str, ...]
    investment_authority: bool = False
    construction_authority: bool = False
    schema_version: str = "portfolio-risk-synthesis.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("portfolio risk synthesis identifier cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("portfolio risk synthesis as_of must be timezone-aware")
        if self.investment_authority or self.construction_authority:
            raise ValueError("portfolio risk synthesis is read-only")

    def to_dict(self) -> dict[str, Any]:
        def stress(item: StressResult) -> dict[str, Any]:
            return {
                "scenario_identifier": item.scenario_identifier,
                "estimated_portfolio_return": item.estimated_portfolio_return,
                "contributions": [list(value) for value in item.contributions],
                "missing_factors": list(item.missing_factors),
            }

        def dynamic(item: PortfolioRiskEstimate | None) -> dict[str, Any] | None:
            if item is None:
                return None
            return {
                "annualized_volatility": item.annualized_volatility,
                "stressed_annualized_volatility": item.stressed_annualized_volatility,
                "marginal_variance_contributions": [list(value) for value in item.marginal_variance_contributions],
            }

        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "current_factor_exposures": [list(value) for value in self.current_factor_exposures],
            "proposed_factor_exposures": [list(value) for value in self.proposed_factor_exposures],
            "current_stress_results": [stress(item) for item in self.current_stress_results],
            "proposed_stress_results": [stress(item) for item in self.proposed_stress_results],
            "worst_current_stress": None if self.worst_current_stress is None else list(self.worst_current_stress),
            "worst_proposed_stress": None if self.worst_proposed_stress is None else list(self.worst_proposed_stress),
            "dynamic_current": dynamic(self.dynamic_current),
            "dynamic_proposed": dynamic(self.dynamic_proposed),
            "missing_dynamic_return_series": list(self.missing_dynamic_return_series),
            "risk_change_summary": list(self.risk_change_summary),
            "investment_authority": False,
            "construction_authority": False,
            "schema_version": self.schema_version,
        }


def _candidate_metadata(portfolio: object, candidates: tuple[object, ...]) -> dict[str, tuple[str, tuple[tuple[str, float], ...]]]:
    values: dict[str, tuple[str, tuple[tuple[str, float], ...]]] = {}
    for candidate in candidates:
        identifier = str(getattr(candidate, "identifier", "")).strip()
        if not identifier:
            continue
        try:
            profile = portfolio.profile(identifier)
        except KeyError:
            continue
        symbol = str(candidate.instrument.symbol).upper()
        values[symbol] = (identifier, tuple(profile.factor_loadings))
    return values


def build_portfolio_risk_synthesis(
    *,
    portfolio: object,
    construction: object | None,
    candidates: tuple[object, ...] = (),
    return_series_by_symbol: Mapping[str, tuple[float, ...]] | None = None,
) -> PortfolioRiskSynthesis:
    """Compare current and constructed portfolio risk using canonical exposures."""

    as_of = getattr(portfolio, "as_of")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("portfolio as_of must be timezone-aware")
    current_positions = tuple(getattr(portfolio, "positions", ()) or ())
    target_weights = _weight_map(
        () if construction is None else getattr(construction, "target_weights", ())
    )
    candidate_meta = _candidate_metadata(portfolio, candidates)

    current_exposures = tuple(
        FactorExposure(
            symbol=position.symbol,
            weight=float(position.current_weight),
            loadings=tuple(position.factor_loadings),
        )
        for position in current_positions
        if float(position.current_weight) > 0.0
    )
    proposed_rows: dict[str, FactorExposure] = {}
    for position in current_positions:
        weight = target_weights.get(position.symbol, float(position.current_weight))
        if weight <= 0.0:
            continue
        proposed_rows[position.symbol] = FactorExposure(
            symbol=position.symbol,
            weight=weight,
            loadings=tuple(position.factor_loadings),
        )
    for symbol, weight in target_weights.items():
        if weight <= 0.0 or symbol in proposed_rows:
            continue
        metadata = candidate_meta.get(symbol)
        if metadata is None:
            continue
        _candidate_identifier, loadings = metadata
        proposed_rows[symbol] = FactorExposure(
            symbol=symbol,
            weight=weight,
            loadings=loadings,
        )
    proposed_exposures = tuple(proposed_rows[key] for key in sorted(proposed_rows))

    stress_engine = PortfolioStressEngine()
    current_stress = tuple(
        stress_engine.run(current_exposures, scenario)
        for scenario in DEFAULT_STRESS_SCENARIOS
    )
    proposed_stress = tuple(
        stress_engine.run(proposed_exposures, scenario)
        for scenario in DEFAULT_STRESS_SCENARIOS
    )
    worst_current = (
        None
        if not current_stress
        else min(
            ((item.scenario_identifier, item.estimated_portfolio_return) for item in current_stress),
            key=lambda value: value[1],
        )
    )
    worst_proposed = (
        None
        if not proposed_stress
        else min(
            ((item.scenario_identifier, item.estimated_portfolio_return) for item in proposed_stress),
            key=lambda value: value[1],
        )
    )

    series_map = {
        str(symbol).upper(): tuple(float(value) for value in returns)
        for symbol, returns in dict(return_series_by_symbol or {}).items()
    }
    needed = tuple(
        dict.fromkeys(
            (
                *(item.symbol for item in current_exposures),
                *(item.symbol for item in proposed_exposures),
            )
        )
    )
    missing = tuple(sorted(symbol for symbol in needed if symbol not in series_map))
    dynamic_current = None
    dynamic_proposed = None
    if needed and not missing:
        series = tuple(
            AssetReturnSeries(symbol=symbol, returns=series_map[symbol])
            for symbol in needed
        )
        engine = DynamicPortfolioRiskEngine()
        estimate = engine.estimate_covariance(series)
        current_weights = tuple(
            (symbol, next((item.weight for item in current_exposures if item.symbol == symbol), 0.0))
            for symbol in needed
        )
        proposed_weights = tuple(
            (symbol, next((item.weight for item in proposed_exposures if item.symbol == symbol), 0.0))
            for symbol in needed
        )
        dynamic_current = engine.portfolio_risk(estimate, current_weights)
        dynamic_proposed = engine.portfolio_risk(estimate, proposed_weights)

    summary: list[str] = []
    if worst_current is not None and worst_proposed is not None:
        delta = worst_proposed[1] - worst_current[1]
        summary.append(
            f"Worst deterministic stress changes from {worst_current[1]:+.2%} ({worst_current[0]}) to {worst_proposed[1]:+.2%} ({worst_proposed[0]}), delta {delta:+.2%}."
        )
    if dynamic_current is not None and dynamic_proposed is not None:
        summary.append(
            f"Dynamic annualized volatility changes from {dynamic_current.annualized_volatility:.2%} to {dynamic_proposed.annualized_volatility:.2%}."
        )
        summary.append(
            f"Stressed dynamic volatility changes from {dynamic_current.stressed_annualized_volatility:.2%} to {dynamic_proposed.stressed_annualized_volatility:.2%}."
        )
    elif missing:
        summary.append(
            "Dynamic covariance remains unavailable because complete point-in-time return histories are missing for: "
            + ", ".join(missing)
            + "."
        )

    return PortfolioRiskSynthesis(
        identifier=f"portfolio-risk-synthesis:{getattr(portfolio, 'identifier', 'portfolio')}:{as_of.isoformat()}",
        as_of=as_of,
        current_factor_exposures=_aggregate_factor_exposures(current_exposures),
        proposed_factor_exposures=_aggregate_factor_exposures(proposed_exposures),
        current_stress_results=current_stress,
        proposed_stress_results=proposed_stress,
        worst_current_stress=worst_current,
        worst_proposed_stress=worst_proposed,
        dynamic_current=dynamic_current,
        dynamic_proposed=dynamic_proposed,
        missing_dynamic_return_series=missing,
        risk_change_summary=tuple(summary),
    )


__all__ = [
    "PortfolioRiskSynthesis",
    "build_portfolio_risk_synthesis",
]
