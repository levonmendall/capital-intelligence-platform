"""Advisory portfolio digital twin and branching scenario engine.

The digital twin evaluates only instruments already supplied by the governed CIO and
construction path. It cannot add positions or increase a CIO-approved weight. Its
outputs are scenario evidence, not portfolio instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import exp, isfinite, log
from typing import Any


class ScenarioConfidence(str, Enum):
    SUFFICIENT = "sufficient"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class DigitalTwinPosition:
    instrument_identifier: str
    current_weight: float
    cio_approved_weight: float
    constructed_weight: float
    expected_return: float
    volatility: float
    liquidity_days: float
    transaction_cost: float
    nonlinear_payoff_points: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.instrument_identifier.strip():
            raise ValueError("instrument_identifier is required")
        for name in (
            "current_weight",
            "cio_approved_weight",
            "constructed_weight",
            "volatility",
            "liquidity_days",
            "transaction_cost",
        ):
            value = float(getattr(self, name))
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.constructed_weight > self.cio_approved_weight + 1e-12:
            raise ValueError("simulation cannot increase CIO-approved sizing")
        if self.current_weight > 1.0 or self.cio_approved_weight > 1.0:
            raise ValueError("position weights cannot exceed one")
        points = self.nonlinear_payoff_points
        if points:
            if len(points) < 2:
                raise ValueError("nonlinear payoff requires at least two points")
            if tuple(sorted(points)) != points:
                raise ValueError("nonlinear payoff points must be ordered")


@dataclass(frozen=True, slots=True)
class PortfolioPathScenario:
    identifier: str
    probability: float
    growth: float
    inflation: float
    policy_rates: float
    real_yields: float
    credit_spreads: float
    liquidity: float
    currency: float
    commodities: float
    volatility: float
    correlation: float
    earnings: float
    funding_stress: float
    transaction_cost_multiplier: float
    market_liquidity_multiplier: float
    execution_delay_days: float
    instrument_return_shocks: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("scenario identifier is required")
        if not 0.0 < float(self.probability) <= 1.0:
            raise ValueError("scenario probability must be positive and at most one")
        for name in (
            "growth",
            "inflation",
            "policy_rates",
            "real_yields",
            "credit_spreads",
            "liquidity",
            "currency",
            "commodities",
            "volatility",
            "correlation",
            "earnings",
            "funding_stress",
            "transaction_cost_multiplier",
            "market_liquidity_multiplier",
            "execution_delay_days",
        ):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.transaction_cost_multiplier < 0.0 or self.market_liquidity_multiplier <= 0.0:
            raise ValueError("cost and liquidity multipliers must be valid")
        identifiers = tuple(item[0] for item in self.instrument_return_shocks)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("instrument return shocks must be unique")

    def shock_for(self, instrument_identifier: str) -> float:
        return next(
            (
                float(value)
                for identifier, value in self.instrument_return_shocks
                if identifier == instrument_identifier
            ),
            0.0,
        )


@dataclass(frozen=True, slots=True)
class DigitalTwinAlternative:
    identifier: str
    positions: tuple[DigitalTwinPosition, ...]
    cash_weight: float
    cash_return: float

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("alternative identifier is required")
        if not 0.0 <= float(self.cash_weight) <= 1.0:
            raise ValueError("cash_weight must be between zero and one")
        if abs(
            sum(item.constructed_weight for item in self.positions)
            + self.cash_weight
            - 1.0
        ) > 1e-6:
            raise ValueError("constructed weights and cash must sum to one")
        identifiers = tuple(item.instrument_identifier for item in self.positions)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("alternative positions must be unique")


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario_identifier: str
    probability: float
    gross_return: float
    net_return: float
    drawdown: float
    liquidity_requirement: float
    failure_points: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DigitalTwinResult:
    alternative_identifier: str
    as_of: datetime
    expected_geometric_return: float
    terminal_wealth_distribution: tuple[tuple[str, float, float], ...]
    probability_outperforming_cash: float
    probability_outperforming_reference: float | None
    expected_drawdown: float
    extreme_drawdown: float
    permanent_loss_probability: float
    recovery_time_years: float | None
    liquidity_requirement: float
    dominant_assumptions: tuple[str, ...]
    sensitivity_to_uncertain_inputs: tuple[tuple[str, float], ...]
    scenario_outcomes: tuple[ScenarioOutcome, ...]
    confidence: ScenarioConfidence
    limitation: str | None
    schema_version: str = "portfolio-digital-twin.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternative_identifier": self.alternative_identifier,
            "as_of": self.as_of.isoformat(),
            "expected_geometric_return": self.expected_geometric_return,
            "terminal_wealth_distribution": [
                list(item) for item in self.terminal_wealth_distribution
            ],
            "probability_outperforming_cash": self.probability_outperforming_cash,
            "probability_outperforming_reference": self.probability_outperforming_reference,
            "expected_drawdown": self.expected_drawdown,
            "extreme_drawdown": self.extreme_drawdown,
            "permanent_loss_probability": self.permanent_loss_probability,
            "recovery_time_years": self.recovery_time_years,
            "liquidity_requirement": self.liquidity_requirement,
            "dominant_assumptions": list(self.dominant_assumptions),
            "sensitivity_to_uncertain_inputs": [
                list(item) for item in self.sensitivity_to_uncertain_inputs
            ],
            "confidence": self.confidence.value,
            "limitation": self.limitation,
            "advisory_only": True,
            "can_add_positions": False,
            "can_increase_cio_sizing": False,
        }


class PortfolioDigitalTwin:
    version = "portfolio-digital-twin.v1"

    @staticmethod
    def _nonlinear_return(position: DigitalTwinPosition, linear_return: float) -> float:
        points = position.nonlinear_payoff_points
        if not points:
            return linear_return
        if linear_return <= points[0][0]:
            return float(points[0][1])
        if linear_return >= points[-1][0]:
            return float(points[-1][1])
        for (x0, y0), (x1, y1) in zip(points, points[1:], strict=True):
            if x0 <= linear_return <= x1:
                ratio = (linear_return - x0) / (x1 - x0)
                return float(y0) + ratio * (float(y1) - float(y0))
        return linear_return

    def simulate(
        self,
        alternative: DigitalTwinAlternative,
        scenarios: tuple[PortfolioPathScenario, ...],
        *,
        as_of: datetime,
        reference: DigitalTwinAlternative | None = None,
        initial_wealth: float = 250_000.0,
    ) -> DigitalTwinResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not scenarios:
            raise ValueError("at least one scenario is required")
        probability_total = sum(item.probability for item in scenarios)
        if abs(probability_total - 1.0) > 1e-6:
            raise ValueError("scenario probabilities must sum to one")
        approved = {item.instrument_identifier for item in alternative.positions}
        for scenario in scenarios:
            if {
                identifier for identifier, _ in scenario.instrument_return_shocks
            } - approved:
                raise ValueError("scenario contains an unapproved instrument")
        outcomes: list[ScenarioOutcome] = []
        reference_returns: dict[str, float] = {}
        if reference is not None:
            reference_result = self.simulate(
                reference,
                scenarios,
                as_of=as_of,
                initial_wealth=initial_wealth,
            )
            reference_returns = {
                item.scenario_identifier: item.net_return
                for item in reference_result.scenario_outcomes
            }
        for scenario in scenarios:
            gross = alternative.cash_weight * alternative.cash_return
            costs = 0.0
            liquidity_requirement = 0.0
            failure_points: list[str] = []
            for position in alternative.positions:
                linear = position.expected_return + scenario.shock_for(
                    position.instrument_identifier
                )
                stressed = (
                    linear
                    - position.volatility * max(0.0, scenario.volatility) * 0.25
                )
                payoff = self._nonlinear_return(position, stressed)
                gross += position.constructed_weight * payoff
                turnover = abs(position.constructed_weight - position.current_weight)
                costs += (
                    turnover
                    * position.transaction_cost
                    * scenario.transaction_cost_multiplier
                )
                liquidity_days = (
                    position.liquidity_days / scenario.market_liquidity_multiplier
                    + scenario.execution_delay_days
                )
                liquidity_requirement = max(liquidity_requirement, liquidity_days)
                if liquidity_days > 20.0:
                    failure_points.append(
                        f"{position.instrument_identifier}: stressed exit exceeds 20 days"
                    )
            net = gross - costs
            drawdown = min(
                0.0,
                net
                - abs(scenario.funding_stress) * 0.05
                - abs(scenario.correlation) * 0.02,
            )
            if net <= -0.20:
                failure_points.append(
                    "portfolio path produces material permanent-loss risk"
                )
            outcomes.append(
                ScenarioOutcome(
                    scenario_identifier=scenario.identifier,
                    probability=scenario.probability,
                    gross_return=round(gross, 8),
                    net_return=round(net, 8),
                    drawdown=round(drawdown, 8),
                    liquidity_requirement=round(liquidity_requirement, 8),
                    failure_points=tuple(failure_points),
                )
            )
        expected_log = sum(
            item.probability * log(max(1e-9, 1.0 + item.net_return))
            for item in outcomes
        )
        geometric = exp(expected_log) - 1.0
        cash_return = alternative.cash_return
        outperform_cash = sum(
            item.probability for item in outcomes if item.net_return > cash_return
        )
        outperform_reference = None
        if reference_returns:
            outperform_reference = sum(
                item.probability
                for item in outcomes
                if item.net_return > reference_returns[item.scenario_identifier]
            )
        expected_drawdown = sum(
            item.probability * item.drawdown for item in outcomes
        )
        extreme_drawdown = min(item.drawdown for item in outcomes)
        permanent_loss = sum(
            item.probability for item in outcomes if item.net_return <= -0.20
        )
        recovery = (
            None
            if geometric <= 0.0 or extreme_drawdown >= 0.0
            else abs(extreme_drawdown) / geometric
        )
        liquidity = max(item.liquidity_requirement for item in outcomes)
        sensitivity = (
            (
                "scenario_return_range",
                round(
                    max(item.net_return for item in outcomes)
                    - min(item.net_return for item in outcomes),
                    8,
                ),
            ),
            (
                "scenario_drawdown_range",
                round(
                    max(item.drawdown for item in outcomes)
                    - min(item.drawdown for item in outcomes),
                    8,
                ),
            ),
        )
        scenario_count = len(scenarios)
        confidence = (
            ScenarioConfidence.INSUFFICIENT
            if scenario_count < 3
            else ScenarioConfidence.LIMITED
            if scenario_count < 5
            else ScenarioConfidence.SUFFICIENT
        )
        limitation = (
            "Simulation confidence is insufficient; results must remain informational."
            if confidence is ScenarioConfidence.INSUFFICIENT
            else "Scenario breadth is limited; uncertainty remains material."
            if confidence is ScenarioConfidence.LIMITED
            else None
        )
        dominant = tuple(
            name
            for name, _ in sorted(
                (
                    (
                        "growth",
                        sum(item.probability * abs(item.growth) for item in scenarios),
                    ),
                    (
                        "inflation",
                        sum(
                            item.probability * abs(item.inflation)
                            for item in scenarios
                        ),
                    ),
                    (
                        "credit_spreads",
                        sum(
                            item.probability * abs(item.credit_spreads)
                            for item in scenarios
                        ),
                    ),
                    (
                        "liquidity",
                        sum(
                            item.probability * abs(item.liquidity)
                            for item in scenarios
                        ),
                    ),
                    (
                        "volatility",
                        sum(
                            item.probability * abs(item.volatility)
                            for item in scenarios
                        ),
                    ),
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
        )
        return DigitalTwinResult(
            alternative_identifier=alternative.identifier,
            as_of=as_of,
            expected_geometric_return=round(geometric, 8),
            terminal_wealth_distribution=tuple(
                (
                    item.scenario_identifier,
                    item.probability,
                    round(initial_wealth * (1.0 + item.net_return), 2),
                )
                for item in outcomes
            ),
            probability_outperforming_cash=round(outperform_cash, 8),
            probability_outperforming_reference=(
                None
                if outperform_reference is None
                else round(outperform_reference, 8)
            ),
            expected_drawdown=round(expected_drawdown, 8),
            extreme_drawdown=round(extreme_drawdown, 8),
            permanent_loss_probability=round(permanent_loss, 8),
            recovery_time_years=None if recovery is None else round(recovery, 8),
            liquidity_requirement=round(liquidity, 8),
            dominant_assumptions=dominant,
            sensitivity_to_uncertain_inputs=sensitivity,
            scenario_outcomes=tuple(outcomes),
            confidence=confidence,
            limitation=limitation,
        )


__all__ = [
    "DigitalTwinAlternative",
    "DigitalTwinPosition",
    "DigitalTwinResult",
    "PortfolioDigitalTwin",
    "PortfolioPathScenario",
    "ScenarioConfidence",
    "ScenarioOutcome",
]
