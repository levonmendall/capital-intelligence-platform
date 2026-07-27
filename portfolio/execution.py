"""Paper-only order orchestration for canonical portfolio construction results.

This module simulates implementation and records evidence.  It has no broker,
network, or live-order authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from cio.persistence import SQLiteCIOJournal
from evaluation.persistence import append_paper_trade_fill
from evaluation.walk_forward import PaperTradeFill
from portfolio.construction_api import (
    ConstructionStatus,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)


_EPSILON = 1e-9


def _text(value: object, *, field_name: str) -> str:
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


def _number(
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
    return round(normalized, 12)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


class MarketSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    HOLIDAY = "holiday"


class PaperOrderStatus(str, Enum):
    PENDING = "pending"
    HELD = "held"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaperExecutionStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    HELD = "held"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NO_ACTION = "no_action"


class PaperExecutionEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    ATTEMPT_COMPLETED = "attempt_completed"
    FILL_RECORDED = "fill_recorded"
    ORDER_CANCELLED = "order_cancelled"
    BATCH_FAILED = "batch_failed"


class PaperExecutionError(RuntimeError):
    """Raised when a paper execution batch cannot be safely processed."""


class PaperExecutionIntegrityError(RuntimeError):
    """Raised when the append-only paper execution chain is invalid."""


@dataclass(frozen=True, slots=True)
class PaperExecutionPolicy:
    version: str = "paper-execution.v1"
    calendar_name: str = "XNYS"
    maximum_quote_age_minutes: int = 5
    maximum_daily_volume_participation: float = 0.10
    commission_bps: float = 0.0
    maximum_realized_cost_return: float = 0.01
    maximum_order_age_hours: int = 24
    allow_partial_fills: bool = True
    reconciliation_tolerance: float = 0.01

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        object.__setattr__(self, "calendar_name", _text(self.calendar_name, field_name="calendar_name"))
        for field_name in ("maximum_quote_age_minutes", "maximum_order_age_hours"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        object.__setattr__(
            self,
            "maximum_daily_volume_participation",
            _number(
                self.maximum_daily_volume_participation,
                field_name="maximum_daily_volume_participation",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if self.maximum_daily_volume_participation <= 0.0:
            raise ValueError("maximum_daily_volume_participation must be positive")
        for field_name in ("commission_bps", "maximum_realized_cost_return", "reconciliation_tolerance"):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name, minimum=0.0),
            )
        if not isinstance(self.allow_partial_fills, bool):
            raise TypeError("allow_partial_fills must be a bool")


@dataclass(frozen=True, slots=True)
class MarketSession:
    as_of: datetime
    status: MarketSessionStatus
    calendar_name: str
    opened_at: datetime | None = None
    closes_at: datetime | None = None

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.status, MarketSessionStatus):
            raise TypeError("status must be MarketSessionStatus")
        object.__setattr__(self, "calendar_name", _text(self.calendar_name, field_name="calendar_name"))
        for field_name in ("opened_at", "closes_at"):
            value = getattr(self, field_name)
            if value is not None:
                _aware(value, field_name=field_name)
        if self.status is MarketSessionStatus.OPEN:
            if self.opened_at is None or self.closes_at is None:
                raise ValueError("open session requires opened_at and closes_at")
            if not self.opened_at <= self.as_of < self.closes_at:
                raise ValueError("open session as_of must be inside session boundaries")


@dataclass(frozen=True, slots=True)
class PaperQuote:
    symbol: str
    as_of: datetime
    bid: float
    ask: float
    last: float
    available_dollar_volume: float
    halted: bool = False
    source_identifier: str = "paper-quote"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        _aware(self.as_of, field_name="as_of")
        for field_name in ("bid", "ask", "last"):
            value = _number(getattr(self, field_name), field_name=field_name, minimum=0.0)
            if value <= 0.0:
                raise ValueError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)
        if self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")
        object.__setattr__(
            self,
            "available_dollar_volume",
            _number(self.available_dollar_volume, field_name="available_dollar_volume", minimum=0.0),
        )
        if not isinstance(self.halted, bool):
            raise TypeError("halted must be a bool")
        object.__setattr__(self, "source_identifier", _text(self.source_identifier, field_name="source_identifier"))


@dataclass(frozen=True, slots=True)
class PaperPosition:
    symbol: str
    quantity: float
    mark_price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(self, "quantity", _number(self.quantity, field_name="quantity", minimum=0.0))
        object.__setattr__(self, "mark_price", _number(self.mark_price, field_name="mark_price", minimum=0.0))
        if self.quantity <= 0.0 or self.mark_price <= 0.0:
            raise ValueError("paper positions require positive quantity and mark_price")

    @property
    def market_value(self) -> float:
        return round(self.quantity * self.mark_price, 8)


@dataclass(frozen=True, slots=True)
class PaperPortfolioState:
    identifier: str
    as_of: datetime
    cash_amount: float
    positions: tuple[PaperPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "cash_amount", _number(self.cash_amount, field_name="cash_amount", minimum=0.0))
        if not isinstance(self.positions, tuple) or not all(isinstance(item, PaperPosition) for item in self.positions):
            raise TypeError("positions must contain PaperPosition values")
        if self.nav <= 0.0:
            raise ValueError("paper portfolio NAV must be positive")
        symbols = tuple(item.symbol for item in self.positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("paper position symbols must be unique")

    @property
    def nav(self) -> float:
        return round(self.cash_amount + sum(item.market_value for item in self.positions), 8)

    def quantity(self, symbol: str) -> float:
        normalized = _text(symbol, field_name="symbol").upper()
        return next((item.quantity for item in self.positions if item.symbol == normalized), 0.0)

    def weight(self, symbol: str) -> float:
        normalized = _text(symbol, field_name="symbol").upper()
        nav = self.nav
        return 0.0 if nav <= 0.0 else round(
            next((item.market_value for item in self.positions if item.symbol == normalized), 0.0) / nav,
            10,
        )

    @property
    def cash_weight(self) -> float:
        return round(self.cash_amount / self.nav, 10)


@dataclass(frozen=True, slots=True)
class PaperOrder:
    identifier: str
    symbol: str
    side: TradeSide
    created_at: datetime
    requested_weight: float
    requested_notional: float
    filled_reference_notional: float
    estimated_cost_return: float
    status: PaperOrderStatus
    reason: str
    funding_for: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "reason"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        if not isinstance(self.status, PaperOrderStatus):
            raise TypeError("status must be PaperOrderStatus")
        _aware(self.created_at, field_name="created_at")
        for field_name in ("requested_weight", "requested_notional", "filled_reference_notional", "estimated_cost_return"):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name=field_name, minimum=0.0))
        if self.requested_weight <= 0.0 or self.requested_notional <= 0.0:
            raise ValueError("paper order requested values must be positive")
        if self.filled_reference_notional > self.requested_notional + _EPSILON:
            raise ValueError("filled_reference_notional cannot exceed requested_notional")
        if not isinstance(self.funding_for, tuple) or not all(isinstance(item, str) and item.strip() for item in self.funding_for):
            raise TypeError("funding_for must contain non-empty strings")

    @property
    def remaining_notional(self) -> float:
        return round(max(0.0, self.requested_notional - self.filled_reference_notional), 12)


@dataclass(frozen=True, slots=True)
class PaperFill:
    identifier: str
    order_identifier: str
    symbol: str
    side: TradeSide
    filled_at: datetime
    quantity: float
    reference_price: float
    fill_price: float
    gross_amount: float
    commission_amount: float
    realized_cost_return: float
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in ("identifier", "order_identifier", "source_identifier"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        _aware(self.filled_at, field_name="filled_at")
        for field_name in ("quantity", "reference_price", "fill_price", "gross_amount", "commission_amount", "realized_cost_return"):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name=field_name, minimum=0.0))
        if self.quantity <= 0.0 or self.reference_price <= 0.0 or self.fill_price <= 0.0 or self.gross_amount <= 0.0:
            raise ValueError("paper fill quantity and prices must be positive")


@dataclass(frozen=True, slots=True)
class PaperReconciliation:
    beginning_nav: float
    ending_nav: float
    cash_change: float
    gross_buys: float
    gross_sells: float
    commissions: float
    mark_change: float
    identity_difference: float
    target_drift: tuple[tuple[str, float], ...]
    reconciled: bool

    def __post_init__(self) -> None:
        for field_name in (
            "beginning_nav", "ending_nav", "cash_change", "gross_buys", "gross_sells",
            "commissions", "mark_change", "identity_difference",
        ):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.target_drift, tuple):
            raise TypeError("target_drift must be a tuple")
        if not isinstance(self.reconciled, bool):
            raise TypeError("reconciled must be a bool")


@dataclass(frozen=True, slots=True)
class PaperExecutionBatch:
    identifier: str
    decision_identifier: str
    construction_request_identifier: str
    started_at: datetime
    updated_at: datetime
    status: PaperExecutionStatus
    policy_version: str
    beginning_portfolio: PaperPortfolioState
    ending_portfolio: PaperPortfolioState
    orders: tuple[PaperOrder, ...]
    fills: tuple[PaperFill, ...]
    reconciliation: PaperReconciliation | None
    attempt_count: int
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "decision_identifier", "construction_request_identifier", "policy_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _aware(self.started_at, field_name="started_at")
        _aware(self.updated_at, field_name="updated_at")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at cannot predate started_at")
        if not isinstance(self.status, PaperExecutionStatus):
            raise TypeError("status must be PaperExecutionStatus")
        if not isinstance(self.beginning_portfolio, PaperPortfolioState) or not isinstance(self.ending_portfolio, PaperPortfolioState):
            raise TypeError("portfolio states must be PaperPortfolioState values")
        if not isinstance(self.orders, tuple) or not all(isinstance(item, PaperOrder) for item in self.orders):
            raise TypeError("orders must contain PaperOrder values")
        if not isinstance(self.fills, tuple) or not all(isinstance(item, PaperFill) for item in self.fills):
            raise TypeError("fills must contain PaperFill values")
        if self.reconciliation is not None and not isinstance(self.reconciliation, PaperReconciliation):
            raise TypeError("reconciliation must be PaperReconciliation or None")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int) or self.attempt_count < 1:
            raise ValueError("attempt_count must be a positive integer")
        if not isinstance(self.errors, tuple) or not all(isinstance(item, str) and item.strip() for item in self.errors):
            raise TypeError("errors must contain non-empty strings")


class MarketSessionProvider(Protocol):
    def session(self, *, as_of: datetime, calendar_name: str) -> MarketSession: ...


class PaperQuoteProvider(Protocol):
    def quotes(self, *, symbols: tuple[str, ...], as_of: datetime) -> Mapping[str, PaperQuote]: ...


@dataclass(frozen=True, slots=True)
class PaperExecutionOperationalEvent:
    sequence: int
    event_identifier: str
    batch_identifier: str
    event_type: PaperExecutionEventType
    occurred_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


class SQLitePaperExecutionStore:
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_execution_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    batch_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_paper_execution_batch
                    ON paper_execution_events(batch_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS paper_execution_no_update
                BEFORE UPDATE ON paper_execution_events BEGIN
                    SELECT RAISE(ABORT, 'paper execution events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_execution_no_delete
                BEFORE DELETE ON paper_execution_events BEGIN
                    SELECT RAISE(ABORT, 'paper execution events are append-only');
                END;
                """
            )

    def append(
        self,
        *,
        event_identifier: str,
        batch_identifier: str,
        event_type: PaperExecutionEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> PaperExecutionOperationalEvent:
        identifier = _text(event_identifier, field_name="event_identifier")
        batch_id = _text(batch_identifier, field_name="batch_identifier")
        if not isinstance(event_type, PaperExecutionEventType):
            raise TypeError("event_type must be PaperExecutionEventType")
        occurred = _aware(occurred_at, field_name="occurred_at")
        payload_json = _canonical_json(payload)
        recorded = datetime.now(timezone.utc)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM paper_execution_events WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                event = self._from_row(existing)
                if event.payload_json != payload_json or event.event_type is not event_type or event.batch_identifier != batch_id:
                    raise PaperExecutionIntegrityError("immutable event identifier has conflicting content")
                connection.rollback()
                return event
            previous = connection.execute(
                "SELECT sequence, content_hash FROM paper_execution_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if previous is None else int(previous["sequence"]) + 1
            previous_hash = self._GENESIS_HASH if previous is None else str(previous["content_hash"])
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                batch_identifier=batch_id,
                event_type=event_type,
                occurred_at=occurred,
                recorded_at=recorded,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                """INSERT INTO paper_execution_events
                (sequence,event_identifier,batch_identifier,event_type,occurred_at,recorded_at,payload_json,previous_hash,content_hash)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (sequence, identifier, batch_id, event_type.value, occurred.isoformat(), recorded.isoformat(), payload_json, previous_hash, content_hash),
            )
            connection.commit()
            return PaperExecutionOperationalEvent(sequence, identifier, batch_id, event_type, occurred, payload_json, previous_hash, content_hash)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(self, *, batch_identifier: str | None = None) -> tuple[PaperExecutionOperationalEvent, ...]:
        if batch_identifier is None:
            query, parameters = "SELECT * FROM paper_execution_events ORDER BY sequence", ()
        else:
            query, parameters = (
                "SELECT * FROM paper_execution_events WHERE batch_identifier = ? ORDER BY sequence",
                (_text(batch_identifier, field_name="batch_identifier"),),
            )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def latest_batch(self, batch_identifier: str) -> PaperExecutionBatch | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM paper_execution_events
                WHERE batch_identifier = ? AND event_type = ?
                ORDER BY sequence DESC LIMIT 1""",
                (_text(batch_identifier, field_name="batch_identifier"), PaperExecutionEventType.ATTEMPT_COMPLETED.value),
            ).fetchone()
        return None if row is None else batch_from_dict(json.loads(str(row["payload_json"]))["batch"])

    def verify_integrity(self) -> bool:
        previous_hash = self._GENESIS_HASH
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM paper_execution_events ORDER BY sequence").fetchall()
        for expected, row in enumerate(rows, start=1):
            event = self._from_row(row)
            recorded_at = datetime.fromisoformat(str(row["recorded_at"]))
            if event.sequence != expected or event.previous_hash != previous_hash:
                raise PaperExecutionIntegrityError("paper execution chain is not contiguous")
            actual = self._hash(
                sequence=event.sequence,
                event_identifier=event.event_identifier,
                batch_identifier=event.batch_identifier,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                recorded_at=recorded_at,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if actual != event.content_hash:
                raise PaperExecutionIntegrityError("paper execution event hash does not match")
            previous_hash = event.content_hash
        return True

    @staticmethod
    def _hash(**values: Any) -> str:
        normalized = dict(values)
        normalized["event_type"] = normalized["event_type"].value
        normalized["occurred_at"] = normalized["occurred_at"].isoformat()
        normalized["recorded_at"] = normalized["recorded_at"].isoformat()
        return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PaperExecutionOperationalEvent:
        return PaperExecutionOperationalEvent(
            sequence=int(row["sequence"]),
            event_identifier=str(row["event_identifier"]),
            batch_identifier=str(row["batch_identifier"]),
            event_type=PaperExecutionEventType(str(row["event_type"])),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class PaperExecutionOrchestrator:
    def __init__(
        self,
        *,
        session_provider: MarketSessionProvider,
        quote_provider: PaperQuoteProvider,
        store: SQLitePaperExecutionStore,
        journal: SQLiteCIOJournal | None = None,
        policy: PaperExecutionPolicy | None = None,
    ) -> None:
        self.session_provider = session_provider
        self.quote_provider = quote_provider
        self.store = store
        self.journal = journal
        self.policy = policy or PaperExecutionPolicy()

    def execute(
        self,
        *,
        construction: PortfolioConstructionResult,
        decision_identifier: str,
        portfolio: PaperPortfolioState,
        as_of: datetime,
    ) -> PaperExecutionBatch:
        if not isinstance(construction, PortfolioConstructionResult):
            raise TypeError("construction must be PortfolioConstructionResult")
        decision_id = _text(decision_identifier, field_name="decision_identifier")
        now = _aware(as_of, field_name="as_of")
        if construction.as_of > now:
            raise PaperExecutionError("construction result cannot be from the future")
        if construction.status is ConstructionStatus.BLOCKED:
            raise PaperExecutionError("blocked construction cannot enter paper execution")
        if portfolio.as_of > now:
            raise PaperExecutionError("portfolio state cannot be from the future")
        self.store.verify_integrity()
        batch_id = f"paper-execution:{construction.request_identifier}"
        prior = self.store.latest_batch(batch_id)
        if prior is not None and prior.status in {
            PaperExecutionStatus.COMPLETED,
            PaperExecutionStatus.NO_ACTION,
            PaperExecutionStatus.CANCELLED,
        }:
            self._publish_journal_fills(prior)
            return prior

        if prior is None:
            self.store.append(
                event_identifier=f"event:{batch_id}:started",
                batch_identifier=batch_id,
                event_type=PaperExecutionEventType.BATCH_STARTED,
                occurred_at=now,
                payload={"construction_request_identifier": construction.request_identifier, "decision_identifier": decision_id},
            )
            beginning = portfolio
            current = portfolio
            orders = self._create_orders(construction, portfolio, now)
            fills: list[PaperFill] = []
            attempt = 1
        else:
            if portfolio != prior.ending_portfolio:
                raise PaperExecutionError("resume portfolio must match the latest paper execution state")
            if prior.decision_identifier != decision_id or prior.construction_request_identifier != construction.request_identifier:
                raise PaperExecutionError("existing batch identity conflicts with execution request")
            beginning = prior.beginning_portfolio
            current = prior.ending_portfolio
            orders = list(prior.orders)
            fills = list(prior.fills)
            attempt = prior.attempt_count + 1

        if construction.status is ConstructionStatus.NO_ACTION or not construction.trades:
            reconciliation = self._reconcile(beginning, current, (), construction)
            batch = PaperExecutionBatch(
                batch_id, decision_id, construction.request_identifier, now if prior is None else prior.started_at,
                now, PaperExecutionStatus.NO_ACTION, self.policy.version, beginning, current, tuple(orders), tuple(fills), reconciliation, attempt,
            )
            self._persist_attempt(batch)
            return batch

        session = self.session_provider.session(as_of=now, calendar_name=self.policy.calendar_name)
        if session.calendar_name != self.policy.calendar_name:
            raise PaperExecutionError("market session calendar does not match execution policy")
        if session.status is not MarketSessionStatus.OPEN:
            held = [
                self._replace_order(item, status=PaperOrderStatus.HELD, reason=f"market session is {session.status.value}")
                if item.status in {PaperOrderStatus.PENDING, PaperOrderStatus.HELD, PaperOrderStatus.PARTIALLY_FILLED}
                else item
                for item in orders
            ]
            batch = PaperExecutionBatch(
                batch_id, decision_id, construction.request_identifier, now if prior is None else prior.started_at,
                now, PaperExecutionStatus.HELD, self.policy.version, beginning, current, tuple(held), tuple(fills), None, attempt,
            )
            self._persist_attempt(batch)
            return batch

        open_orders = tuple(item for item in orders if item.status in {PaperOrderStatus.PENDING, PaperOrderStatus.HELD, PaperOrderStatus.PARTIALLY_FILLED})
        symbols = tuple(sorted({item.symbol for item in open_orders}))
        raw_quotes = self.quote_provider.quotes(symbols=symbols, as_of=now)
        quotes = {str(symbol).upper(): quote for symbol, quote in raw_quotes.items()}
        working_positions = {item.symbol: [item.quantity, item.mark_price] for item in current.positions}
        cash = current.cash_amount
        updated_orders: dict[str, PaperOrder] = {item.identifier: item for item in orders}
        new_fills: list[PaperFill] = []

        # Sells always precede buys. Funding-linked buys require complete funding sells.
        ordered = sorted(open_orders, key=lambda item: (0 if item.side is TradeSide.SELL else 1, item.symbol))
        for order in ordered:
            if now - order.created_at > timedelta(hours=self.policy.maximum_order_age_hours):
                updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.EXPIRED, reason="order age exceeded policy")
                continue
            if order.side is TradeSide.BUY:
                blockers = [
                    value for value in updated_orders.values()
                    if value.side is TradeSide.SELL and order.symbol in value.funding_for and value.status is not PaperOrderStatus.FILLED
                ]
                if blockers:
                    updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.HELD, reason="funding sale dependency is incomplete")
                    continue
            quote = quotes.get(order.symbol)
            invalid_reason = self._quote_error(quote, symbol=order.symbol, as_of=now)
            if invalid_reason is not None:
                updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.REJECTED, reason=invalid_reason)
                continue
            assert quote is not None
            quantity_cap = quote.available_dollar_volume * self.policy.maximum_daily_volume_participation / (quote.ask if order.side is TradeSide.BUY else quote.bid)
            desired = min(order.remaining_notional / quote.last, quantity_cap)
            if order.side is TradeSide.SELL:
                desired = min(desired, working_positions.get(order.symbol, [0.0, quote.last])[0])
            else:
                unit_cost = quote.ask * (1.0 + self.policy.commission_bps / 10000.0)
                desired = min(desired, cash / unit_cost if unit_cost > 0.0 else 0.0)
            if desired <= _EPSILON:
                reason = "insufficient owned quantity" if order.side is TradeSide.SELL else "insufficient paper cash"
                updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.REJECTED, reason=reason)
                continue
            if not self.policy.allow_partial_fills and desired + _EPSILON < order.remaining_quantity:
                updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.HELD, reason="liquidity or cash cannot complete order")
                continue
            fill_price = quote.ask if order.side is TradeSide.BUY else quote.bid
            gross = desired * fill_price
            commission = gross * self.policy.commission_bps / 10000.0
            adverse = (fill_price - quote.last) * desired if order.side is TradeSide.BUY else (quote.last - fill_price) * desired
            cost_return = max(0.0, adverse + commission) / beginning.nav
            if cost_return > self.policy.maximum_realized_cost_return + _EPSILON:
                updated_orders[order.identifier] = self._replace_order(order, status=PaperOrderStatus.REJECTED, reason="realized cost exceeds policy")
                continue
            if order.side is TradeSide.BUY:
                cash -= gross + commission
                quantity, _ = working_positions.get(order.symbol, [0.0, quote.last])
                working_positions[order.symbol] = [quantity + desired, quote.last]
            else:
                quantity, _ = working_positions.get(order.symbol, [0.0, quote.last])
                remaining = max(0.0, quantity - desired)
                cash += gross - commission
                if remaining <= _EPSILON:
                    working_positions.pop(order.symbol, None)
                else:
                    working_positions[order.symbol] = [remaining, quote.last]
            fill_number = 1 + sum(item.order_identifier == order.identifier for item in fills + new_fills)
            fill = PaperFill(
                identifier=f"{batch_id}:fill:{order.symbol}:{fill_number}",
                order_identifier=order.identifier,
                symbol=order.symbol,
                side=order.side,
                filled_at=now,
                quantity=desired,
                reference_price=quote.last,
                fill_price=fill_price,
                gross_amount=gross,
                commission_amount=commission,
                realized_cost_return=cost_return,
                source_identifier=quote.source_identifier,
            )
            new_fills.append(fill)
            filled_reference_notional = order.filled_reference_notional + desired * quote.last
            status = PaperOrderStatus.FILLED if filled_reference_notional + _EPSILON >= order.requested_notional else PaperOrderStatus.PARTIALLY_FILLED
            updated_orders[order.identifier] = self._replace_order(
                order,
                filled_reference_notional=filled_reference_notional,
                status=status,
                reason="paper fill completed" if status is PaperOrderStatus.FILLED else "paper fill partially completed",
            )

        ending = PaperPortfolioState(
            identifier=f"{batch_id}:portfolio:{attempt}",
            as_of=now,
            cash_amount=max(0.0, cash),
            positions=tuple(
                PaperPosition(symbol=symbol, quantity=values[0], mark_price=values[1])
                for symbol, values in sorted(working_positions.items())
                if values[0] > _EPSILON
            ),
        )
        all_fills = tuple(fills + new_fills)
        reconciliation = self._reconcile(current, ending, tuple(new_fills), construction)
        if not reconciliation.reconciled:
            self.store.append(
                event_identifier=f"event:{batch_id}:failed:{attempt}",
                batch_identifier=batch_id,
                event_type=PaperExecutionEventType.BATCH_FAILED,
                occurred_at=now,
                payload={"error": "paper ledger did not reconcile", "identity_difference": reconciliation.identity_difference},
            )
            raise PaperExecutionError("paper ledger did not reconcile")
        for fill in new_fills:
            self.store.append(
                event_identifier=f"event:{fill.identifier}",
                batch_identifier=batch_id,
                event_type=PaperExecutionEventType.FILL_RECORDED,
                occurred_at=fill.filled_at,
                payload={"fill": fill_to_dict(fill)},
            )
        order_values = tuple(updated_orders[key] for key in sorted(updated_orders))
        statuses = {item.status for item in order_values}
        if statuses <= {PaperOrderStatus.FILLED}:
            status = PaperExecutionStatus.COMPLETED
        elif not all_fills and statuses <= {PaperOrderStatus.REJECTED, PaperOrderStatus.EXPIRED}:
            status = PaperExecutionStatus.FAILED
        elif statuses <= {PaperOrderStatus.HELD, PaperOrderStatus.PENDING, PaperOrderStatus.PARTIALLY_FILLED} and not all_fills:
            status = PaperExecutionStatus.HELD
        else:
            status = PaperExecutionStatus.PARTIAL
        batch = PaperExecutionBatch(
            batch_id, decision_id, construction.request_identifier, now if prior is None else prior.started_at,
            now, status, self.policy.version, beginning, ending, order_values, all_fills, reconciliation, attempt,
            tuple(item.reason for item in order_values if item.status in {PaperOrderStatus.REJECTED, PaperOrderStatus.EXPIRED}),
        )
        self._persist_attempt(batch)
        self._publish_journal_fills(batch)
        return batch

    def cancel_open_orders(self, *, batch_identifier: str, cancelled_at: datetime, reason: str) -> PaperExecutionBatch:
        batch_id = _text(batch_identifier, field_name="batch_identifier")
        now = _aware(cancelled_at, field_name="cancelled_at")
        message = _text(reason, field_name="reason")
        batch = self.store.latest_batch(batch_id)
        if batch is None:
            raise PaperExecutionError("paper execution batch does not exist")
        if batch.status in {PaperExecutionStatus.COMPLETED, PaperExecutionStatus.NO_ACTION, PaperExecutionStatus.CANCELLED}:
            return batch
        orders = tuple(
            self._replace_order(item, status=PaperOrderStatus.CANCELLED, reason=message)
            if item.status in {PaperOrderStatus.PENDING, PaperOrderStatus.HELD, PaperOrderStatus.PARTIALLY_FILLED}
            else item
            for item in batch.orders
        )
        cancelled = PaperExecutionBatch(
            batch.identifier, batch.decision_identifier, batch.construction_request_identifier,
            batch.started_at, now, PaperExecutionStatus.CANCELLED, batch.policy_version,
            batch.beginning_portfolio, batch.ending_portfolio, orders, batch.fills,
            batch.reconciliation, batch.attempt_count + 1, batch.errors,
        )
        self.store.append(
            event_identifier=f"event:{batch_id}:cancelled",
            batch_identifier=batch_id,
            event_type=PaperExecutionEventType.ORDER_CANCELLED,
            occurred_at=now,
            payload={"reason": message},
        )
        self._persist_attempt(cancelled)
        return cancelled

    def _create_orders(self, construction: PortfolioConstructionResult, portfolio: PaperPortfolioState, created_at: datetime) -> list[PaperOrder]:
        orders: list[PaperOrder] = []
        for proposal in construction.trades:
            actual_weight = portfolio.weight(proposal.symbol)
            if abs(actual_weight - proposal.from_weight) > 0.005:
                raise PaperExecutionError(f"paper portfolio weight for {proposal.symbol} does not match construction origin")
            requested_notional = proposal.trade_weight * portfolio.nav
            orders.append(
                PaperOrder(
                    identifier=f"paper-order:{construction.request_identifier}:{proposal.symbol}:{proposal.side.value}",
                    symbol=proposal.symbol,
                    side=proposal.side,
                    created_at=created_at,
                    requested_weight=proposal.trade_weight,
                    requested_notional=requested_notional,
                    filled_reference_notional=0.0,
                    estimated_cost_return=proposal.estimated_cost_return,
                    status=PaperOrderStatus.PENDING,
                    reason=proposal.reason,
                    funding_for=proposal.funding_for,
                )
            )
        return orders

    def _quote_error(self, quote: PaperQuote | None, *, symbol: str, as_of: datetime) -> str | None:
        if quote is None:
            return f"quote is missing for {symbol}"
        if quote.symbol != symbol:
            return "quote symbol does not match order"
        if quote.as_of > as_of:
            return "quote is from the future"
        age = as_of - quote.as_of
        if age > timedelta(minutes=self.policy.maximum_quote_age_minutes):
            return "quote is stale"
        if quote.halted:
            return "security is halted"
        return None

    def _reconcile(
        self,
        beginning: PaperPortfolioState,
        ending: PaperPortfolioState,
        fills: tuple[PaperFill, ...],
        construction: PortfolioConstructionResult,
    ) -> PaperReconciliation:
        gross_buys = sum(item.gross_amount for item in fills if item.side is TradeSide.BUY)
        gross_sells = sum(item.gross_amount for item in fills if item.side is TradeSide.SELL)
        commissions = sum(item.commission_amount for item in fills)
        cash_change = ending.cash_amount - beginning.cash_amount
        beginning_marks = {item.symbol: item.quantity * item.mark_price for item in beginning.positions}
        ending_marks = {item.symbol: item.quantity * item.mark_price for item in ending.positions}
        quantity_flow_mark = 0.0
        for fill in fills:
            signed = fill.quantity * fill.fill_price * (1.0 if fill.side is TradeSide.BUY else -1.0)
            quantity_flow_mark += signed
        mark_change = sum(ending_marks.values()) - sum(beginning_marks.values()) - quantity_flow_mark
        expected_ending = beginning.nav + mark_change - commissions
        identity_difference = ending.nav - expected_ending
        target = dict(construction.target_weights)
        drift_symbols = sorted(set(target) | {item.symbol for item in ending.positions})
        target_drift = tuple((symbol, round(ending.weight(symbol) - target.get(symbol, 0.0), 10)) for symbol in drift_symbols) + (("CASH", round(ending.cash_weight - construction.target_cash_weight, 10)),)
        return PaperReconciliation(
            beginning_nav=beginning.nav,
            ending_nav=ending.nav,
            cash_change=cash_change,
            gross_buys=gross_buys,
            gross_sells=gross_sells,
            commissions=commissions,
            mark_change=mark_change,
            identity_difference=identity_difference,
            target_drift=target_drift,
            reconciled=abs(identity_difference) <= self.policy.reconciliation_tolerance,
        )

    def _persist_attempt(self, batch: PaperExecutionBatch) -> None:
        self.store.append(
            event_identifier=f"event:{batch.identifier}:attempt:{batch.attempt_count}",
            batch_identifier=batch.identifier,
            event_type=PaperExecutionEventType.ATTEMPT_COMPLETED,
            occurred_at=batch.updated_at,
            payload={"batch": batch_to_dict(batch)},
        )

    def _publish_journal_fills(self, batch: PaperExecutionBatch) -> None:
        if self.journal is None or batch.reconciliation is None or not batch.reconciliation.reconciled:
            return
        self.journal.verify_integrity()
        order_by_id = {item.identifier: item for item in batch.orders}
        for fill in batch.fills:
            order = order_by_id[fill.order_identifier]
            filled_weight = fill.gross_amount / batch.beginning_portfolio.nav
            append_paper_trade_fill(
                self.journal,
                PaperTradeFill(
                    identifier=fill.identifier,
                    decision_identifier=batch.decision_identifier,
                    construction_request_identifier=batch.construction_request_identifier,
                    symbol=fill.symbol,
                    side=fill.side,
                    proposed_at=order.created_at,
                    filled_at=fill.filled_at,
                    proposed_weight=order.requested_weight,
                    filled_weight=filled_weight,
                    reference_price=fill.reference_price,
                    fill_price=fill.fill_price,
                    estimated_cost_return=round(order.estimated_cost_return * (fill.quantity * fill.reference_price / order.requested_notional), 10),
                    realized_cost_return=fill.realized_cost_return,
                    source_identifier=fill.source_identifier,
                ),
            )

    @staticmethod
    def _replace_order(
        order: PaperOrder,
        *,
        filled_reference_notional: float | None = None,
        status: PaperOrderStatus | None = None,
        reason: str | None = None,
    ) -> PaperOrder:
        return PaperOrder(
            identifier=order.identifier,
            symbol=order.symbol,
            side=order.side,
            created_at=order.created_at,
            requested_weight=order.requested_weight,
            requested_notional=order.requested_notional,
            filled_reference_notional=order.filled_reference_notional if filled_reference_notional is None else filled_reference_notional,
            estimated_cost_return=order.estimated_cost_return,
            status=order.status if status is None else status,
            reason=order.reason if reason is None else reason,
            funding_for=order.funding_for,
        )


def position_to_dict(value: PaperPosition) -> dict[str, Any]:
    return {"symbol": value.symbol, "quantity": value.quantity, "mark_price": value.mark_price}


def portfolio_to_dict(value: PaperPortfolioState) -> dict[str, Any]:
    return {"identifier": value.identifier, "as_of": value.as_of.isoformat(), "cash_amount": value.cash_amount, "positions": [position_to_dict(item) for item in value.positions]}


def order_to_dict(value: PaperOrder) -> dict[str, Any]:
    return {
        "identifier": value.identifier, "symbol": value.symbol, "side": value.side.value,
        "created_at": value.created_at.isoformat(), "requested_weight": value.requested_weight,
        "requested_notional": value.requested_notional, "filled_reference_notional": value.filled_reference_notional,
        "estimated_cost_return": value.estimated_cost_return, "status": value.status.value, "reason": value.reason,
        "funding_for": list(value.funding_for),
    }


def fill_to_dict(value: PaperFill) -> dict[str, Any]:
    return {
        "identifier": value.identifier, "order_identifier": value.order_identifier, "symbol": value.symbol,
        "side": value.side.value, "filled_at": value.filled_at.isoformat(), "quantity": value.quantity,
        "reference_price": value.reference_price, "fill_price": value.fill_price,
        "gross_amount": value.gross_amount, "commission_amount": value.commission_amount,
        "realized_cost_return": value.realized_cost_return, "source_identifier": value.source_identifier,
    }


def reconciliation_to_dict(value: PaperReconciliation) -> dict[str, Any]:
    return {
        "beginning_nav": value.beginning_nav, "ending_nav": value.ending_nav,
        "cash_change": value.cash_change, "gross_buys": value.gross_buys, "gross_sells": value.gross_sells,
        "commissions": value.commissions, "mark_change": value.mark_change,
        "identity_difference": value.identity_difference,
        "target_drift": [[symbol, drift] for symbol, drift in value.target_drift],
        "reconciled": value.reconciled,
    }


def batch_to_dict(value: PaperExecutionBatch) -> dict[str, Any]:
    return {
        "identifier": value.identifier, "decision_identifier": value.decision_identifier,
        "construction_request_identifier": value.construction_request_identifier,
        "started_at": value.started_at.isoformat(), "updated_at": value.updated_at.isoformat(),
        "status": value.status.value, "policy_version": value.policy_version,
        "beginning_portfolio": portfolio_to_dict(value.beginning_portfolio),
        "ending_portfolio": portfolio_to_dict(value.ending_portfolio),
        "orders": [order_to_dict(item) for item in value.orders],
        "fills": [fill_to_dict(item) for item in value.fills],
        "reconciliation": None if value.reconciliation is None else reconciliation_to_dict(value.reconciliation),
        "attempt_count": value.attempt_count, "errors": list(value.errors),
    }


def portfolio_from_dict(value: Mapping[str, Any]) -> PaperPortfolioState:
    return PaperPortfolioState(
        identifier=str(value["identifier"]), as_of=datetime.fromisoformat(str(value["as_of"])),
        cash_amount=float(value["cash_amount"]),
        positions=tuple(PaperPosition(symbol=str(item["symbol"]), quantity=float(item["quantity"]), mark_price=float(item["mark_price"])) for item in value["positions"]),
    )


def order_from_dict(value: Mapping[str, Any]) -> PaperOrder:
    return PaperOrder(
        identifier=str(value["identifier"]), symbol=str(value["symbol"]), side=TradeSide(str(value["side"])),
        created_at=datetime.fromisoformat(str(value["created_at"])), requested_weight=float(value["requested_weight"]),
        requested_notional=float(value["requested_notional"]), filled_reference_notional=float(value["filled_reference_notional"]),
        estimated_cost_return=float(value["estimated_cost_return"]), status=PaperOrderStatus(str(value["status"])),
        reason=str(value["reason"]), funding_for=tuple(value.get("funding_for", ())),
    )


def fill_from_dict(value: Mapping[str, Any]) -> PaperFill:
    return PaperFill(
        identifier=str(value["identifier"]), order_identifier=str(value["order_identifier"]), symbol=str(value["symbol"]),
        side=TradeSide(str(value["side"])), filled_at=datetime.fromisoformat(str(value["filled_at"])),
        quantity=float(value["quantity"]), reference_price=float(value["reference_price"]), fill_price=float(value["fill_price"]),
        gross_amount=float(value["gross_amount"]), commission_amount=float(value["commission_amount"]),
        realized_cost_return=float(value["realized_cost_return"]), source_identifier=str(value["source_identifier"]),
    )


def reconciliation_from_dict(value: Mapping[str, Any]) -> PaperReconciliation:
    return PaperReconciliation(
        beginning_nav=float(value["beginning_nav"]), ending_nav=float(value["ending_nav"]), cash_change=float(value["cash_change"]),
        gross_buys=float(value["gross_buys"]), gross_sells=float(value["gross_sells"]), commissions=float(value["commissions"]),
        mark_change=float(value["mark_change"]), identity_difference=float(value["identity_difference"]),
        target_drift=tuple((str(item[0]), float(item[1])) for item in value["target_drift"]), reconciled=bool(value["reconciled"]),
    )


def batch_from_dict(value: Mapping[str, Any]) -> PaperExecutionBatch:
    reconciliation = value.get("reconciliation")
    return PaperExecutionBatch(
        identifier=str(value["identifier"]), decision_identifier=str(value["decision_identifier"]),
        construction_request_identifier=str(value["construction_request_identifier"]),
        started_at=datetime.fromisoformat(str(value["started_at"])), updated_at=datetime.fromisoformat(str(value["updated_at"])),
        status=PaperExecutionStatus(str(value["status"])), policy_version=str(value["policy_version"]),
        beginning_portfolio=portfolio_from_dict(value["beginning_portfolio"]), ending_portfolio=portfolio_from_dict(value["ending_portfolio"]),
        orders=tuple(order_from_dict(item) for item in value["orders"]), fills=tuple(fill_from_dict(item) for item in value["fills"]),
        reconciliation=None if reconciliation is None else reconciliation_from_dict(reconciliation),
        attempt_count=int(value["attempt_count"]), errors=tuple(value.get("errors", ())),
    )


__all__ = [
    "MarketSession", "MarketSessionProvider", "MarketSessionStatus", "PaperExecutionBatch",
    "PaperExecutionError", "PaperExecutionIntegrityError", "PaperExecutionOrchestrator",
    "PaperExecutionPolicy", "PaperExecutionStatus", "PaperFill", "PaperOrder", "PaperOrderStatus",
    "PaperPortfolioState", "PaperPosition", "PaperQuote", "PaperQuoteProvider", "PaperReconciliation",
    "SQLitePaperExecutionStore", "batch_from_dict", "batch_to_dict", "portfolio_from_dict", "portfolio_to_dict",
]
