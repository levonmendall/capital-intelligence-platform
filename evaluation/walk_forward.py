"""Walk-forward, universe-integrity, and paper-execution controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from portfolio.construction_api import TradeSide


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(value: object, *, field_name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return round(normalized, 10)


class WalkForwardVerdict(str, Enum):
    VALID = "valid"
    LOOKAHEAD_VIOLATION = "lookahead_violation"
    UNIVERSE_VIOLATION = "universe_violation"
    OVERLAPPING_WINDOWS = "overlapping_windows"


@dataclass(frozen=True, slots=True)
class PointInTimeResearchRecord:
    identifier: str
    symbol: str
    observed_at: datetime
    available_at: datetime
    model_input: bool

    def __post_init__(self) -> None:
        for field_name in ("identifier", "symbol"):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        _aware(self.observed_at, field_name="observed_at")
        _aware(self.available_at, field_name="available_at")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot predate observation")
        if not isinstance(self.model_input, bool):
            raise TypeError("model_input must be a bool")


@dataclass(frozen=True, slots=True)
class PointInTimeUniverseMembership:
    symbol: str
    eligible_from: datetime
    eligible_until: datetime | None
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _required_text(self.symbol, field_name="symbol").upper(),
        )
        object.__setattr__(
            self,
            "source_identifier",
            _required_text(
                self.source_identifier,
                field_name="source_identifier",
            ),
        )
        _aware(self.eligible_from, field_name="eligible_from")
        if self.eligible_until is not None:
            _aware(self.eligible_until, field_name="eligible_until")
            if self.eligible_until <= self.eligible_from:
                raise ValueError("eligible_until must follow eligible_from")

    def contains(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return self.eligible_from <= resolved and (
            self.eligible_until is None or resolved < self.eligible_until
        )


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    identifier: str
    training_started_at: datetime
    training_ended_at: datetime
    decision_at: datetime
    evaluation_ended_at: datetime
    research_records: tuple[PointInTimeResearchRecord, ...]
    universe_memberships: tuple[PointInTimeUniverseMembership, ...]
    evaluated_symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        for field_name in (
            "training_started_at",
            "training_ended_at",
            "decision_at",
            "evaluation_ended_at",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if not (
            self.training_started_at
            < self.training_ended_at
            <= self.decision_at
            < self.evaluation_ended_at
        ):
            raise ValueError("walk-forward windows must be ordered and non-overlapping")
        if not isinstance(self.research_records, tuple) or not all(
            isinstance(item, PointInTimeResearchRecord)
            for item in self.research_records
        ):
            raise TypeError(
                "research_records must contain PointInTimeResearchRecord values"
            )
        if not isinstance(self.universe_memberships, tuple) or not all(
            isinstance(item, PointInTimeUniverseMembership)
            for item in self.universe_memberships
        ):
            raise TypeError(
                "universe_memberships must contain PointInTimeUniverseMembership values"
            )
        if not isinstance(self.evaluated_symbols, tuple):
            raise TypeError("evaluated_symbols must be a tuple")
        normalized = tuple(
            _required_text(item, field_name="evaluated_symbols").upper()
            for item in self.evaluated_symbols
        )
        if not normalized:
            raise ValueError("evaluated_symbols cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("evaluated_symbols cannot contain duplicates")
        object.__setattr__(self, "evaluated_symbols", normalized)


@dataclass(frozen=True, slots=True)
class WalkForwardAudit:
    fold_identifier: str
    verdict: WalkForwardVerdict
    violations: tuple[str, ...]
    training_record_count: int
    evaluated_symbol_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fold_identifier",
            _required_text(
                self.fold_identifier,
                field_name="fold_identifier",
            ),
        )
        if not isinstance(self.verdict, WalkForwardVerdict):
            raise TypeError("verdict must be WalkForwardVerdict")
        if not isinstance(self.violations, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.violations
        ):
            raise TypeError("violations must contain non-empty strings")
        if self.verdict is WalkForwardVerdict.VALID and self.violations:
            raise ValueError("valid audit cannot contain violations")
        if self.verdict is not WalkForwardVerdict.VALID and not self.violations:
            raise ValueError("invalid audit requires violations")
        for field_name in ("training_record_count", "evaluated_symbol_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")


class WalkForwardAuditor:
    """Reject look-ahead, overlapping windows, and survivorship-biased universes."""

    def audit(self, fold: WalkForwardFold) -> WalkForwardAudit:
        if not isinstance(fold, WalkForwardFold):
            raise TypeError("fold must be WalkForwardFold")
        lookahead = tuple(
            item.identifier
            for item in fold.research_records
            if item.model_input and item.available_at > fold.decision_at
        )
        universe_violations: list[str] = []
        memberships_by_symbol: dict[str, list[PointInTimeUniverseMembership]] = {}
        for membership in fold.universe_memberships:
            memberships_by_symbol.setdefault(membership.symbol, []).append(membership)
        for symbol in fold.evaluated_symbols:
            memberships = memberships_by_symbol.get(symbol, [])
            if not any(item.contains(fold.decision_at) for item in memberships):
                universe_violations.append(symbol)
        violations: list[str] = []
        if lookahead:
            violations.append(
                "look-ahead records unavailable at decision time: "
                + ", ".join(sorted(lookahead))
            )
        if universe_violations:
            violations.append(
                "symbols absent from the point-in-time universe: "
                + ", ".join(sorted(universe_violations))
            )
        if lookahead:
            verdict = WalkForwardVerdict.LOOKAHEAD_VIOLATION
        elif universe_violations:
            verdict = WalkForwardVerdict.UNIVERSE_VIOLATION
        else:
            verdict = WalkForwardVerdict.VALID
        return WalkForwardAudit(
            fold_identifier=fold.identifier,
            verdict=verdict,
            violations=tuple(violations),
            training_record_count=sum(
                item.model_input for item in fold.research_records
            ),
            evaluated_symbol_count=len(fold.evaluated_symbols),
        )


@dataclass(frozen=True, slots=True)
class PaperTradeFill:
    """A simulated fill used to measure implementation rather than claim execution."""

    identifier: str
    decision_identifier: str
    construction_request_identifier: str
    symbol: str
    side: TradeSide
    proposed_at: datetime
    filled_at: datetime
    proposed_weight: float
    filled_weight: float
    reference_price: float
    fill_price: float
    estimated_cost_return: float
    realized_cost_return: float
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "construction_request_identifier",
            "symbol",
            "source_identifier",
        ):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        _aware(self.proposed_at, field_name="proposed_at")
        _aware(self.filled_at, field_name="filled_at")
        if self.filled_at < self.proposed_at:
            raise ValueError("filled_at cannot predate proposal")
        for field_name in (
            "proposed_weight",
            "filled_weight",
            "estimated_cost_return",
            "realized_cost_return",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if self.proposed_weight <= 0.0 or self.filled_weight <= 0.0:
            raise ValueError("paper fill weights must be positive")
        for field_name in ("reference_price", "fill_price"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
            if getattr(self, field_name) <= 0.0:
                raise ValueError(f"{field_name} must be positive")

    @property
    def completion_ratio(self) -> float:
        return round(min(1.0, self.filled_weight / self.proposed_weight), 10)

    @property
    def slippage_return(self) -> float:
        direction = 1.0 if self.side is TradeSide.BUY else -1.0
        return round(
            -direction * (self.fill_price / self.reference_price - 1.0),
            10,
        )


__all__ = [
    "PaperTradeFill",
    "PointInTimeResearchRecord",
    "PointInTimeUniverseMembership",
    "WalkForwardAudit",
    "WalkForwardAuditor",
    "WalkForwardFold",
    "WalkForwardVerdict",
]
