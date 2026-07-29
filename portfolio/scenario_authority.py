"""Governed common-scenario authority for complete-portfolio construction.

The authority carries one common horizon, one knowledge cutoff, explicit source
lineage, and complete returns for every non-cash position. Missing asset coverage
fails closed; expected return is never substituted inside a stress scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from portfolio.construction_models import PortfolioScenario


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _number(value: object, *, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return round(normalized, 10)


@dataclass(frozen=True, slots=True)
class GovernedPortfolioScenario:
    name: str
    probability: float
    cash_return: float
    asset_returns: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, name="name"))
        object.__setattr__(self, "probability", _number(self.probability, name="probability", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "cash_return", _number(self.cash_return, name="cash_return", minimum=-1.0))
        if not isinstance(self.asset_returns, tuple):
            raise TypeError("asset_returns must be a tuple")
        values = tuple(
            (
                _text(symbol, name="scenario symbol").upper(),
                _number(value, name=f"scenario return:{symbol}", minimum=-1.0),
            )
            for symbol, value in self.asset_returns
        )
        if len(values) != len({symbol for symbol, _ in values}):
            raise ValueError("scenario asset returns must be unique")
        object.__setattr__(self, "asset_returns", tuple(sorted(values)))

    @property
    def symbols(self) -> frozenset[str]:
        return frozenset(symbol for symbol, _ in self.asset_returns)


@dataclass(frozen=True, slots=True)
class GovernedPortfolioScenarioSet:
    identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    horizon_days: int
    scenarios: tuple[GovernedPortfolioScenario, ...]
    source_identifier: str
    model_versions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "governed-portfolio-scenario-set.v1"

    def __post_init__(self) -> None:
        for name in ("identifier", "source_identifier", "schema_version"):
            object.__setattr__(self, name, _text(getattr(self, name), name=name))
        _aware(self.as_of, name="as_of")
        _aware(self.knowledge_cutoff, name="knowledge_cutoff")
        if self.knowledge_cutoff > self.as_of:
            raise ValueError("knowledge_cutoff cannot follow as_of")
        if isinstance(self.horizon_days, bool) or not isinstance(self.horizon_days, int):
            raise TypeError("horizon_days must be an integer")
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be positive")
        if not isinstance(self.scenarios, tuple) or not all(isinstance(item, GovernedPortfolioScenario) for item in self.scenarios):
            raise TypeError("scenarios must contain GovernedPortfolioScenario values")
        if len(self.scenarios) < 3:
            raise ValueError("at least three common portfolio scenarios are required")
        names = tuple(item.name for item in self.scenarios)
        if len(names) != len(set(names)):
            raise ValueError("scenario names must be unique")
        if abs(sum(item.probability for item in self.scenarios) - 1.0) > 0.000001:
            raise ValueError("scenario probabilities must sum to 1.0")
        coverage = self.scenarios[0].symbols
        if any(item.symbols != coverage for item in self.scenarios[1:]):
            raise ValueError("every scenario must cover the same complete asset set")
        for name in ("model_versions", "evidence_identifiers"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise TypeError(f"{name} must be a tuple")
            normalized = tuple(_text(item, name=name) for item in values)
            if not normalized:
                raise ValueError(f"{name} cannot be empty")
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{name} cannot contain duplicates")
            object.__setattr__(self, name, normalized)

    @property
    def symbols(self) -> frozenset[str]:
        return self.scenarios[0].symbols

    def validate_coverage(self, symbols: tuple[str, ...] | frozenset[str] | set[str]) -> None:
        expected = frozenset(_text(item, name="portfolio symbol").upper() for item in symbols)
        if self.symbols != expected:
            missing = sorted(expected - self.symbols)
            extra = sorted(self.symbols - expected)
            raise ValueError(
                "governed portfolio scenarios must exactly cover every non-cash asset; "
                f"missing={missing} extra={extra}"
            )

    def construction_scenarios(self, *, symbols: tuple[str, ...] | frozenset[str] | set[str]) -> tuple[PortfolioScenario, ...]:
        self.validate_coverage(symbols)
        return tuple(
            PortfolioScenario(
                name=item.name,
                probability=item.probability,
                cash_return=item.cash_return,
                asset_returns=item.asset_returns,
            )
            for item in self.scenarios
        )


class PortfolioScenarioAuthority:
    """Validate externally assembled cross-asset scenarios for portfolio use."""

    version = "portfolio-scenario-authority.v1"

    def authorize(
        self,
        scenario_set: GovernedPortfolioScenarioSet,
        *,
        as_of: datetime,
        symbols: tuple[str, ...] | frozenset[str] | set[str],
        maximum_age_hours: float = 24.0,
    ) -> tuple[PortfolioScenario, ...]:
        if not isinstance(scenario_set, GovernedPortfolioScenarioSet):
            raise TypeError("scenario_set must be GovernedPortfolioScenarioSet")
        decision_time = _aware(as_of, name="as_of")
        age_hours = (decision_time - scenario_set.as_of).total_seconds() / 3600.0
        if age_hours < 0.0:
            raise ValueError("scenario set cannot be from the future")
        if age_hours > maximum_age_hours:
            raise ValueError("portfolio scenario set is stale")
        return scenario_set.construction_scenarios(symbols=symbols)


__all__ = [
    "GovernedPortfolioScenario",
    "GovernedPortfolioScenarioSet",
    "PortfolioScenarioAuthority",
]
