"""Cost-aware portfolio construction contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import exp, isfinite, log1p

from cio import CIOAction, CIODecision, CandidateDecisionRecord


class ConstructionStatus(str, Enum):
    FEASIBLE = "feasible"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NO_ACTION = "no_action"


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _loading_tuple(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized: list[tuple[str, float]] = []
    for name, loading in value:
        normalized.append(
            (
                _required_text(name, field_name=f"{field_name} name"),
                _finite(
                    loading,
                    field_name=f"{field_name} loading",
                    minimum=-1.0,
                    maximum=1.0,
                ),
            )
        )
    if len(normalized) != len({name for name, _ in normalized}):
        raise ValueError(f"{field_name} names must be unique")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ExposureLimit:
    name: str
    maximum_absolute_weight: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _required_text(self.name, field_name="name"),
        )
        object.__setattr__(
            self,
            "maximum_absolute_weight",
            _finite(
                self.maximum_absolute_weight,
                field_name="maximum_absolute_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionPolicy:
    version: str = "portfolio-construction.v3"
    minimum_cash_weight: float = 0.02
    maximum_position_weight: float = 0.10
    default_maximum_sector_weight: float = 0.25
    default_maximum_correlation_bucket_weight: float = 0.25
    maximum_turnover: float = 0.20
    maximum_total_cost_return: float = 0.005
    minimum_replacement_edge: float = 0.01
    minimum_expected_return_improvement: float = 0.0001
    minimum_geometric_return_improvement: float = 0.0
    minimum_probability_outperforming_current: float = 0.50
    maximum_expected_shortfall: float = -0.12
    maximum_stressed_drawdown: float = -0.20
    maximum_liquidity_adjusted_loss: float = -0.22
    optimizer_beam_width: int = 4
    maximum_daily_volume_participation: float = 0.10
    execution_days: int = 3
    sector_limits: tuple[ExposureLimit, ...] = ()
    factor_limits: tuple[ExposureLimit, ...] = ()
    correlation_limits: tuple[ExposureLimit, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "minimum_cash_weight",
            "maximum_position_weight",
            "default_maximum_sector_weight",
            "default_maximum_correlation_bucket_weight",
            "maximum_turnover",
            "maximum_total_cost_return",
            "minimum_replacement_edge",
            "minimum_expected_return_improvement",
            "minimum_geometric_return_improvement",
            "minimum_probability_outperforming_current",
            "maximum_daily_volume_participation",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        for field_name in (
            "maximum_expected_shortfall",
            "maximum_stressed_drawdown",
            "maximum_liquidity_adjusted_loss",
        ):
            value = _finite(getattr(self, field_name), field_name=field_name)
            if value >= 0.0:
                raise ValueError(f"{field_name} must be negative")
            object.__setattr__(self, field_name, value)
        if isinstance(self.optimizer_beam_width, bool) or not isinstance(
            self.optimizer_beam_width, int
        ):
            raise TypeError("optimizer_beam_width must be an integer")
        if self.optimizer_beam_width < 1:
            raise ValueError("optimizer_beam_width must be positive")
        if self.minimum_cash_weight >= 1.0:
            raise ValueError("minimum_cash_weight must be below 1.0")
        if self.maximum_position_weight <= 0.0:
            raise ValueError("maximum_position_weight must be positive")
        if self.maximum_turnover <= 0.0:
            raise ValueError("maximum_turnover must be positive")
        if self.maximum_daily_volume_participation <= 0.0:
            raise ValueError(
                "maximum_daily_volume_participation must be positive"
            )
        if isinstance(self.execution_days, bool) or not isinstance(
            self.execution_days,
            int,
        ):
            raise TypeError("execution_days must be an integer")
        if self.execution_days < 1:
            raise ValueError("execution_days must be positive")
        for field_name in (
            "sector_limits",
            "factor_limits",
            "correlation_limits",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, ExposureLimit) for item in values
            ):
                raise TypeError(
                    f"{field_name} must contain ExposureLimit values"
                )
            names = tuple(item.name for item in values)
            if len(names) != len(set(names)):
                raise ValueError(f"{field_name} names must be unique")

    def sector_limit(self, sector: str) -> float:
        return next(
            (
                item.maximum_absolute_weight
                for item in self.sector_limits
                if item.name == sector
            ),
            self.default_maximum_sector_weight,
        )

    def factor_limit(self, factor: str) -> float | None:
        return next(
            (
                item.maximum_absolute_weight
                for item in self.factor_limits
                if item.name == factor
            ),
            None,
        )

    def correlation_limit(self, bucket: str) -> float:
        return next(
            (
                item.maximum_absolute_weight
                for item in self.correlation_limits
                if item.name == bucket
            ),
            self.default_maximum_correlation_bucket_weight,
        )


@dataclass(frozen=True, slots=True)
class PortfolioAsset:
    symbol: str
    current_weight: float
    expected_return: float
    sector: str
    factor_loadings: tuple[tuple[str, float], ...]
    correlation_bucket: str
    average_daily_dollar_volume: float
    transaction_cost_bps: float
    slippage_bps: float
    minimum_weight: float = 0.0
    funding_eligible: bool = False
    instrument_identifier: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("symbol", "sector", "correlation_bucket"):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        for field_name in ("current_weight", "minimum_weight"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.minimum_weight > self.current_weight:
            raise ValueError("minimum_weight cannot exceed current_weight")
        object.__setattr__(
            self,
            "expected_return",
            _finite(self.expected_return, field_name="expected_return"),
        )
        object.__setattr__(
            self,
            "factor_loadings",
            _loading_tuple(
                self.factor_loadings,
                field_name="factor_loadings",
            ),
        )
        object.__setattr__(
            self,
            "average_daily_dollar_volume",
            _finite(
                self.average_daily_dollar_volume,
                field_name="average_daily_dollar_volume",
                minimum=0.0,
            ),
        )
        for field_name in ("transaction_cost_bps", "slippage_bps"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if not isinstance(self.funding_eligible, bool):
            raise TypeError("funding_eligible must be a bool")
        object.__setattr__(
            self,
            "instrument_identifier",
            _optional_text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )

    @property
    def total_cost_bps(self) -> float:
        return round(self.transaction_cost_bps + self.slippage_bps, 8)


@dataclass(frozen=True, slots=True)
class ConstructionIntent:
    candidate_identifier: str
    symbol: str
    action: CIOAction
    requested_target_weight: float | None
    expected_return: float
    opportunity_edge: float
    maximum_position_weight: float
    sector: str
    factor_loadings: tuple[tuple[str, float], ...]
    correlation_bucket: str
    average_daily_dollar_volume: float
    transaction_cost_bps: float
    slippage_bps: float
    priority_rank: int
    instrument_identifier: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_identifier",
            "symbol",
            "sector",
            "correlation_bucket",
        ):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        if not isinstance(self.action, CIOAction):
            raise TypeError("action must be a CIOAction")
        if self.requested_target_weight is not None:
            object.__setattr__(
                self,
                "requested_target_weight",
                _finite(
                    self.requested_target_weight,
                    field_name="requested_target_weight",
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        object.__setattr__(
            self,
            "expected_return",
            _finite(self.expected_return, field_name="expected_return"),
        )
        object.__setattr__(
            self,
            "opportunity_edge",
            _finite(self.opportunity_edge, field_name="opportunity_edge"),
        )
        object.__setattr__(
            self,
            "maximum_position_weight",
            _finite(
                self.maximum_position_weight,
                field_name="maximum_position_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "factor_loadings",
            _loading_tuple(
                self.factor_loadings,
                field_name="factor_loadings",
            ),
        )
        object.__setattr__(
            self,
            "average_daily_dollar_volume",
            _finite(
                self.average_daily_dollar_volume,
                field_name="average_daily_dollar_volume",
                minimum=0.0,
            ),
        )
        for field_name in ("transaction_cost_bps", "slippage_bps"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if isinstance(self.priority_rank, bool) or not isinstance(
            self.priority_rank,
            int,
        ):
            raise TypeError("priority_rank must be an integer")
        if self.priority_rank < 1:
            raise ValueError("priority_rank must be positive")
        object.__setattr__(
            self,
            "instrument_identifier",
            _optional_text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        sized_actions = {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.REDUCE,
            CIOAction.EXIT,
        }
        if self.action in sized_actions and self.requested_target_weight is None:
            raise ValueError(f"{self.action.value} requires a target weight")
        if self.action is CIOAction.EXIT and self.requested_target_weight != 0.0:
            raise ValueError("exit target weight must be zero")
        if self.action in {
            CIOAction.WATCH,
            CIOAction.INSUFFICIENT_EVIDENCE,
            CIOAction.NO_SUPERIOR_OPPORTUNITY,
            CIOAction.NO_MATERIAL_CHANGE,
        } and self.requested_target_weight is not None:
            raise ValueError("abstention intents cannot request a target weight")

    @classmethod
    def from_cio(
        cls,
        candidate: CandidateDecisionRecord,
        decision: CIODecision,
        *,
        sector: str,
        factor_loadings: tuple[tuple[str, float], ...],
        correlation_bucket: str,
        priority_rank: int,
    ) -> "ConstructionIntent":
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be CandidateDecisionRecord")
        if not isinstance(decision, CIODecision):
            raise TypeError("decision must be CIODecision")
        if decision.candidate_identifier != candidate.identifier:
            raise ValueError("decision and candidate identifiers do not match")
        expected_return = cls.annualized_return(
            decision.expected_return,
            horizon_days=decision.decision_horizon_days,
        )
        alternative_return = decision.return_reconciliation.alternative_return
        return cls(
            candidate_identifier=candidate.identifier,
            symbol=candidate.instrument.symbol,
            action=decision.action,
            requested_target_weight=decision.recommended_position_weight,
            expected_return=expected_return,
            opportunity_edge=round(expected_return - alternative_return, 8),
            maximum_position_weight=candidate.maximum_position_weight,
            sector=sector,
            factor_loadings=factor_loadings,
            correlation_bucket=correlation_bucket,
            average_daily_dollar_volume=(
                candidate.instrument.average_daily_dollar_volume
            ),
            transaction_cost_bps=candidate.transaction_cost_bps,
            slippage_bps=candidate.slippage_bps,
            priority_rank=priority_rank,
            instrument_identifier=candidate.instrument.instrument_id,
        )

    @staticmethod
    def annualized_return(total_return: float, *, horizon_days: int) -> float:
        """Normalize a decision-horizon total return for portfolio comparison."""

        if total_return <= -1.0:
            return -1.0
        years = horizon_days / 365.25
        return round(exp(log1p(total_return) / years) - 1.0, 8)


@dataclass(frozen=True, slots=True)
class PortfolioScenario:
    """One common scenario applied to the complete portfolio."""

    name: str
    probability: float
    cash_return: float
    asset_returns: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, field_name="name"))
        object.__setattr__(
            self, "probability", _finite(self.probability, field_name="probability", minimum=0.0, maximum=1.0)
        )
        object.__setattr__(self, "cash_return", _finite(self.cash_return, field_name="cash_return"))
        if not isinstance(self.asset_returns, tuple):
            raise TypeError("asset_returns must be a tuple")
        normalized = tuple(
            (
                _required_text(symbol, field_name="scenario symbol").upper(),
                _finite(value, field_name=f"scenario_return:{symbol}", minimum=-1.0),
            )
            for symbol, value in self.asset_returns
        )
        if len(normalized) != len({symbol for symbol, _ in normalized}):
            raise ValueError("scenario asset returns must be unique")
        object.__setattr__(self, "asset_returns", normalized)

    def return_for(self, symbol: str, fallback: float) -> float:
        resolved = symbol.strip().upper()
        return next((value for name, value in self.asset_returns if name == resolved), fallback)


@dataclass(frozen=True, slots=True)
class PortfolioScenarioMetrics:
    expected_geometric_return: float
    expected_shortfall: float
    worst_case_return: float
    probability_outperforming_current: float
    liquidity_adjusted_loss: float

    def __post_init__(self) -> None:
        for field_name in (
            "expected_geometric_return",
            "expected_shortfall",
            "worst_case_return",
            "liquidity_adjusted_loss",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name=field_name))
        object.__setattr__(
            self,
            "probability_outperforming_current",
            _finite(
                self.probability_outperforming_current,
                field_name="probability_outperforming_current",
                minimum=0.0,
                maximum=1.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionRequest:
    identifier: str
    as_of: datetime
    portfolio_value: float
    cash_weight: float
    cash_expected_return: float
    positions: tuple[PortfolioAsset, ...]
    intents: tuple[ConstructionIntent, ...]
    eligible_universe_publication_identifier: str | None = None
    scenarios: tuple[PortfolioScenario, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "portfolio_value",
            _finite(
                self.portfolio_value,
                field_name="portfolio_value",
                minimum=0.0,
            ),
        )
        if self.portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        object.__setattr__(
            self,
            "cash_weight",
            _finite(
                self.cash_weight,
                field_name="cash_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "cash_expected_return",
            _finite(
                self.cash_expected_return,
                field_name="cash_expected_return",
            ),
        )
        if not isinstance(self.positions, tuple) or not all(
            isinstance(item, PortfolioAsset) for item in self.positions
        ):
            raise TypeError("positions must contain PortfolioAsset values")
        if not isinstance(self.intents, tuple) or not all(
            isinstance(item, ConstructionIntent) for item in self.intents
        ):
            raise TypeError("intents must contain ConstructionIntent values")
        symbols = tuple(item.symbol for item in self.positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("position symbols must be unique")
        intent_symbols = tuple(item.symbol for item in self.intents)
        if len(intent_symbols) != len(set(intent_symbols)):
            raise ValueError("intent symbols must be unique")
        if sum(item.current_weight for item in self.positions) + self.cash_weight > 1.000001:
            raise ValueError("portfolio weights cannot exceed 1.0")
        if abs(
            sum(item.current_weight for item in self.positions)
            + self.cash_weight
            - 1.0
        ) > 0.000001:
            raise ValueError("portfolio weights and cash must sum to 1.0")
        if not isinstance(self.scenarios, tuple) or not all(
            isinstance(item, PortfolioScenario) for item in self.scenarios
        ):
            raise TypeError("scenarios must contain PortfolioScenario values")
        if self.scenarios:
            if abs(sum(item.probability for item in self.scenarios) - 1.0) > 0.000001:
                raise ValueError("portfolio scenario probabilities must sum to 1.0")
            names = tuple(item.name for item in self.scenarios)
            if len(names) != len(set(names)):
                raise ValueError("portfolio scenario names must be unique")
        object.__setattr__(
            self,
            "eligible_universe_publication_identifier",
            _optional_text(
                self.eligible_universe_publication_identifier,
                field_name="eligible_universe_publication_identifier",
            ),
        )


@dataclass(frozen=True, slots=True)
class TradeProposal:
    symbol: str
    side: TradeSide
    from_weight: float
    to_weight: float
    trade_weight: float
    estimated_cost_return: float
    reason: str
    funding_for: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _required_text(self.symbol, field_name="symbol").upper(),
        )
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be a TradeSide")
        for field_name in (
            "from_weight",
            "to_weight",
            "trade_weight",
            "estimated_cost_return",
        ):
            maximum = 1.0 if field_name != "estimated_cost_return" else None
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=maximum,
                ),
            )
        if self.trade_weight <= 0.0:
            raise ValueError("trade_weight must be positive")
        if abs(abs(self.to_weight - self.from_weight) - self.trade_weight) > 0.000001:
            raise ValueError("trade_weight must equal the absolute weight change")
        if self.side is TradeSide.BUY and self.to_weight <= self.from_weight:
            raise ValueError("buy proposal must increase weight")
        if self.side is TradeSide.SELL and self.to_weight >= self.from_weight:
            raise ValueError("sell proposal must reduce weight")
        object.__setattr__(
            self,
            "reason",
            _required_text(self.reason, field_name="reason"),
        )
        if not isinstance(self.funding_for, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.funding_for
        ):
            raise TypeError("funding_for must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    name: str
    satisfied: bool
    value: float
    limit: float
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _required_text(self.name, field_name="name"),
        )
        if not isinstance(self.satisfied, bool):
            raise TypeError("satisfied must be a bool")
        object.__setattr__(
            self,
            "value",
            _finite(self.value, field_name="value"),
        )
        object.__setattr__(
            self,
            "limit",
            _finite(self.limit, field_name="limit"),
        )
        object.__setattr__(
            self,
            "detail",
            _required_text(self.detail, field_name="detail"),
        )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionResult:
    request_identifier: str
    as_of: datetime
    status: ConstructionStatus
    policy_version: str
    target_cash_weight: float
    target_weights: tuple[tuple[str, float], ...]
    trades: tuple[TradeProposal, ...]
    turnover: float
    estimated_cost_return: float
    expected_return_before: float
    expected_return_after_cost: float
    expected_return_improvement: float
    constraints: tuple[ConstraintCheck, ...]
    blocks: tuple[str, ...]
    eligible_universe_publication_identifier: str | None = None
    instrument_identifiers: tuple[tuple[str, str], ...] = ()
    scenario_metrics_before: PortfolioScenarioMetrics | None = None
    scenario_metrics_after: PortfolioScenarioMetrics | None = None

    def __post_init__(self) -> None:
        for field_name in ("request_identifier", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.status, ConstructionStatus):
            raise TypeError("status must be a ConstructionStatus")
        object.__setattr__(
            self,
            "target_cash_weight",
            _finite(
                self.target_cash_weight,
                field_name="target_cash_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if not isinstance(self.target_weights, tuple):
            raise TypeError("target_weights must be a tuple")
        normalized: list[tuple[str, float]] = []
        for symbol, weight in self.target_weights:
            normalized.append(
                (
                    _required_text(symbol, field_name="symbol").upper(),
                    _finite(
                        weight,
                        field_name=f"target_weight:{symbol}",
                        minimum=0.0,
                        maximum=1.0,
                    ),
                )
            )
        if len(normalized) != len({symbol for symbol, _ in normalized}):
            raise ValueError("target symbols must be unique")
        object.__setattr__(self, "target_weights", tuple(normalized))
        if abs(sum(weight for _, weight in normalized) + self.target_cash_weight - 1.0) > 0.00001:
            raise ValueError("target weights and cash must sum to 1.0")
        if not isinstance(self.trades, tuple) or not all(
            isinstance(item, TradeProposal) for item in self.trades
        ):
            raise TypeError("trades must contain TradeProposal values")
        for field_name in (
            "turnover",
            "estimated_cost_return",
            "expected_return_before",
            "expected_return_after_cost",
            "expected_return_improvement",
        ):
            minimum = 0.0 if field_name in {"turnover", "estimated_cost_return"} else None
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        if not isinstance(self.constraints, tuple) or not all(
            isinstance(item, ConstraintCheck) for item in self.constraints
        ):
            raise TypeError("constraints must contain ConstraintCheck values")
        if not isinstance(self.blocks, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.blocks
        ):
            raise TypeError("blocks must contain non-empty strings")
        if self.status is ConstructionStatus.FEASIBLE and self.blocks:
            raise ValueError("feasible result cannot contain blocks")
        for field_name in ("scenario_metrics_before", "scenario_metrics_after"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, PortfolioScenarioMetrics):
                raise TypeError(f"{field_name} must be PortfolioScenarioMetrics or None")
        object.__setattr__(
            self,
            "eligible_universe_publication_identifier",
            _optional_text(
                self.eligible_universe_publication_identifier,
                field_name="eligible_universe_publication_identifier",
            ),
        )
        if not isinstance(self.instrument_identifiers, tuple):
            raise TypeError("instrument_identifiers must be a tuple")
        normalized_identifiers = tuple(
            (
                _required_text(symbol, field_name="instrument symbol").upper(),
                _required_text(
                    instrument_identifier,
                    field_name="instrument_identifier",
                ),
            )
            for symbol, instrument_identifier in self.instrument_identifiers
        )
        symbols = tuple(symbol for symbol, _ in normalized_identifiers)
        identifiers = tuple(identifier for _, identifier in normalized_identifiers)
        if len(symbols) != len(set(symbols)):
            raise ValueError("instrument identifier symbols must be unique")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("instrument identifiers must be unique")
        object.__setattr__(
            self,
            "instrument_identifiers",
            normalized_identifiers,
        )
        if self.eligible_universe_publication_identifier is not None:
            trade_symbols = {item.symbol for item in self.trades}
            if set(symbols) != trade_symbols:
                missing = sorted(trade_symbols - set(symbols))
                extra = sorted(set(symbols) - trade_symbols)
                raise ValueError(
                    "governed construction instrument identities must exactly "
                    f"match trades: missing={missing} extra={extra}"
                )

    def instrument_identifier(self, symbol: str) -> str | None:
        resolved = _required_text(symbol, field_name="symbol").upper()
        return next(
            (
                instrument_identifier
                for mapped_symbol, instrument_identifier in self.instrument_identifiers
                if mapped_symbol == resolved
            ),
            None,
        )


__all__ = [
    "ConstructionIntent",
    "ConstructionStatus",
    "ConstraintCheck",
    "ExposureLimit",
    "PortfolioAsset",
    "PortfolioConstructionPolicy",
    "PortfolioConstructionRequest",
    "PortfolioConstructionResult",
    "PortfolioScenario",
    "PortfolioScenarioMetrics",
    "TradeProposal",
    "TradeSide",
]
