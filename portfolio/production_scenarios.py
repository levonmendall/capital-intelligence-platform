"""Build one common, point-in-time scenario set for production construction."""

from __future__ import annotations

from datetime import datetime
from math import exp, log1p
from statistics import mean
from typing import Iterable

from portfolio.scenario_authority import (
    GovernedPortfolioScenario,
    GovernedPortfolioScenarioSet,
)


def _annualize(total_return: float, horizon_days: int) -> float:
    value = float(total_return)
    if value <= -1.0:
        return -1.0
    if horizon_days < 1:
        raise ValueError("candidate decision horizon must be positive")
    return max(-1.0, exp(log1p(value) * (365.25 / horizon_days)) - 1.0)


def _probability(values: Iterable[float]) -> float:
    resolved = tuple(float(item) for item in values)
    if not resolved:
        raise ValueError("portfolio scenario probability inputs cannot be empty")
    return mean(resolved)


def build_governed_portfolio_scenario_set(
    *,
    identifier: str,
    source_identifier: str,
    as_of: datetime,
    knowledge_cutoff: datetime,
    candidates: tuple[object, ...],
    cash_expected_return: float,
) -> GovernedPortfolioScenarioSet:
    """Normalize candidate bear/base/bull paths into a common annual horizon.

    The builder does not invent expected returns. It converts each candidate's
    disclosed point-in-time distribution to one common 365-day construction
    horizon and uses the cross-sectional mean disclosed probabilities as the
    common scenario weights.
    """

    if not candidates:
        raise ValueError("portfolio scenarios require at least one candidate")
    symbols = tuple(
        str(candidate.instrument.symbol).strip().upper()
        for candidate in candidates
    )
    if any(not symbol for symbol in symbols):
        raise ValueError("candidate scenario symbols cannot be empty")
    if len(symbols) != len(set(symbols)):
        raise ValueError("portfolio scenario candidates must be unique by symbol")

    raw_probabilities = {
        "bear": _probability(candidate.bear_case_probability for candidate in candidates),
        "base": _probability(candidate.base_case_probability for candidate in candidates),
        "bull": _probability(candidate.bull_case_probability for candidate in candidates),
    }
    probability_total = sum(raw_probabilities.values())
    if probability_total <= 0.0:
        raise ValueError("portfolio scenario probabilities must be positive")
    probabilities = {
        name: value / probability_total
        for name, value in raw_probabilities.items()
    }

    def returns(field_name: str) -> tuple[tuple[str, float], ...]:
        return tuple(
            sorted(
                (
                    str(candidate.instrument.symbol).strip().upper(),
                    round(
                        _annualize(
                            float(getattr(candidate, field_name)),
                            int(candidate.decision_horizon_days),
                        ),
                        10,
                    ),
                )
                for candidate in candidates
            )
        )

    scenario_values = (
        GovernedPortfolioScenario(
            name="common_bear",
            probability=probabilities["bear"],
            cash_return=float(cash_expected_return),
            asset_returns=returns("bear_case_return"),
        ),
        GovernedPortfolioScenario(
            name="common_base",
            probability=probabilities["base"],
            cash_return=float(cash_expected_return),
            asset_returns=returns("base_case_return"),
        ),
        GovernedPortfolioScenario(
            name="common_bull",
            probability=probabilities["bull"],
            cash_return=float(cash_expected_return),
            asset_returns=returns("bull_case_return"),
        ),
    )
    evidence_identifiers = tuple(
        dict.fromkeys(
            identifier
            for candidate in candidates
            for identifier in tuple(candidate.evidence_identifiers)
        )
    )
    model_versions = tuple(
        dict.fromkeys(
            str(version)
            for candidate in candidates
            for version in tuple(candidate.model_versions)
        )
    )
    return GovernedPortfolioScenarioSet(
        identifier=str(identifier),
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        horizon_days=365,
        scenarios=scenario_values,
        source_identifier=str(source_identifier),
        model_versions=(
            "production-common-scenario-normalization.v1",
            *(model_versions or ("candidate-model-version-unavailable",)),
        ),
        evidence_identifiers=(
            evidence_identifiers
            or (f"scenario-source:{source_identifier}",)
        ),
    )


__all__ = ["build_governed_portfolio_scenario_set"]
