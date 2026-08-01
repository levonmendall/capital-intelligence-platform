"""Build coherent point-in-time joint scenarios for production construction."""

from __future__ import annotations

from datetime import datetime
from math import exp, log1p

from portfolio.scenario_authority import (
    GovernedPortfolioScenario,
    GovernedPortfolioScenarioSet,
)


_EPSILON = 0.0000000001


def _annualize(total_return: float, horizon_days: int) -> float:
    value = float(total_return)
    if value <= -1.0:
        return -1.0
    if horizon_days < 1:
        raise ValueError("candidate decision horizon must be positive")
    return max(-1.0, exp(log1p(value) * (365.25 / horizon_days)) - 1.0)


def build_governed_portfolio_scenario_set(
    *,
    identifier: str,
    source_identifier: str,
    as_of: datetime,
    knowledge_cutoff: datetime,
    candidates: tuple[object, ...],
    cash_expected_return: float,
) -> GovernedPortfolioScenarioSet:
    """Create shared macro states plus candidate-specific adverse states.

    Common bear, base, and bull probabilities use only the probability mass
    disclosed by every candidate. Residual mass is allocated to idiosyncratic
    bear states rather than averaging incompatible candidate distributions.
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

    probabilities = {
        "bear": min(float(item.bear_case_probability) for item in candidates),
        "base": min(float(item.base_case_probability) for item in candidates),
        "bull": min(float(item.bull_case_probability) for item in candidates),
    }
    common_total = sum(probabilities.values())
    if common_total <= 0.0 or common_total > 1.0 + _EPSILON:
        raise ValueError("common scenario probability mass is invalid")
    residual = max(0.0, 1.0 - common_total)

    annualized = {
        symbol: {
            "bear": _annualize(
                float(candidate.bear_case_return),
                int(candidate.decision_horizon_days),
            ),
            "base": _annualize(
                float(candidate.base_case_return),
                int(candidate.decision_horizon_days),
            ),
            "bull": _annualize(
                float(candidate.bull_case_return),
                int(candidate.decision_horizon_days),
            ),
        }
        for symbol, candidate in zip(symbols, candidates, strict=True)
    }

    def state_returns(state: str) -> tuple[tuple[str, float], ...]:
        return tuple(
            sorted(
                (symbol, round(values[state], 10))
                for symbol, values in annualized.items()
            )
        )

    scenario_values = [
        GovernedPortfolioScenario(
            name="common_bear",
            probability=probabilities["bear"],
            cash_return=float(cash_expected_return),
            asset_returns=state_returns("bear"),
        ),
        GovernedPortfolioScenario(
            name="common_base",
            probability=probabilities["base"],
            cash_return=float(cash_expected_return),
            asset_returns=state_returns("base"),
        ),
        GovernedPortfolioScenario(
            name="common_bull",
            probability=probabilities["bull"],
            cash_return=float(cash_expected_return),
            asset_returns=state_returns("bull"),
        ),
    ]

    if residual > _EPSILON:
        weights = tuple(
            max(
                0.0,
                float(candidate.bear_case_probability) - probabilities["bear"],
            )
            + max(
                0.0,
                float(candidate.base_case_probability) - probabilities["base"],
            )
            + max(
                0.0,
                float(candidate.bull_case_probability) - probabilities["bull"],
            )
            for candidate in candidates
        )
        total_weight = sum(weights)
        if total_weight <= _EPSILON:
            weights = tuple(1.0 for _ in candidates)
            total_weight = float(len(candidates))

        remaining = residual
        for index, (symbol, weight) in enumerate(
            zip(symbols, weights, strict=True)
        ):
            is_last = index == len(symbols) - 1
            probability = (
                remaining
                if is_last
                else residual * weight / total_weight
            )
            remaining = max(0.0, remaining - probability)
            asset_returns = tuple(
                sorted(
                    (
                        other_symbol,
                        round(
                            annualized[other_symbol][
                                "bear" if other_symbol == symbol else "base"
                            ],
                            10,
                        ),
                    )
                    for other_symbol in symbols
                )
            )
            scenario_values.append(
                GovernedPortfolioScenario(
                    name=f"idiosyncratic_bear:{symbol}",
                    probability=probability,
                    cash_return=float(cash_expected_return),
                    asset_returns=asset_returns,
                )
            )

    evidence_identifiers = tuple(
        dict.fromkeys(
            evidence_identifier
            for candidate in candidates
            for evidence_identifier in tuple(candidate.evidence_identifiers)
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
        scenarios=tuple(scenario_values),
        source_identifier=str(source_identifier),
        model_versions=(
            "production-joint-scenario-normalization.v2",
            *(model_versions or ("candidate-model-version-unavailable",)),
        ),
        evidence_identifiers=(
            evidence_identifiers
            or (f"scenario-source:{source_identifier}",)
        ),
    )


__all__ = ["build_governed_portfolio_scenario_set"]
