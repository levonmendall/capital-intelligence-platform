"""Paper-only execution for crypto, FX, and global listed markets.

This authority consumes a canonical construction result and a canonical
cross-currency portfolio snapshot. It applies one exact execution profile per
trade, routes each instrument through its approved session model, requires
certified point-in-time quotes and FX lineage, prohibits leverage, updates the
canonical paper portfolio, and reconciles all local activity in the portfolio's
base currency. It has no broker or live-order authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import floor, isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from cio import CandidateAssetClass
from governance import EXPANSION_ASSET_CLASSES, TradingSessionModel
from portfolio.construction_api import (
    ConstructionStatus,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.state import (
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
    snapshot_from_dict,
    snapshot_to_dict,
)


_EPSILON = 1e-9


class MultiAssetExecutionError(RuntimeError):
    """Raised when multi-asset paper activity cannot be processed safely."""


class MultiAssetExecutionIntegrityError(MultiAssetExecutionError):
    """Raised when the append-only execution chain is invalid."""


class InstrumentSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    HOLIDAY = "holiday"
    MAINTENANCE = "maintenance"


class MultiAssetOrderStatus(str, Enum):
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    HELD = "held"
    REJECTED = "rejected"


class MultiAssetExecutionStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    HELD = "held"
    FAILED = "failed"
    NO_ACTION = "no_action"


class MultiAssetExecutionEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    ATTEMPT_RECORDED = "attempt_recorded"
    BATCH_FAILED = "batch_failed"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


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


def _currency(value: object, *, field_name: str) -> str:
    normalized = _text(value, field_name=field_name).upper()
    if not 3 <= len(normalized) <= 12:
        raise ValueError(f"{field_name} must be a canonical currency or asset code")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class InstrumentExecutionProfile:
    """Approved paper-routing and implementation contract for one symbol."""

    symbol: str
    instrument_identifier: str
    asset_class: CandidateAssetClass
    venue: str
    session_model: TradingSessionModel
    price_currency: str
    settlement_currency: str
    execution_certification_identifier: str
    asset_class_approval_identifier: str | None = None
    maximum_quote_age_minutes: int = 5
    maximum_volume_participation: float = 0.10
    commission_bps: float = 0.0
    minimum_trade_base_amount: float = 1.0
    maximum_position_weight: float = 0.20
    allow_fractional_quantity: bool = True
    notional_multiplier: float = 1.0
    profile_version: str = "multi-asset-execution-profile.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        object.__setattr__(
            self,
            "venue",
            _text(self.venue, field_name="venue").upper(),
        )
        if not isinstance(self.session_model, TradingSessionModel):
            raise TypeError("session_model must be TradingSessionModel")
        object.__setattr__(
            self,
            "price_currency",
            _currency(self.price_currency, field_name="price_currency"),
        )
        object.__setattr__(
            self,
            "settlement_currency",
            _currency(
                self.settlement_currency,
                field_name="settlement_currency",
            ),
        )
        object.__setattr__(
            self,
            "execution_certification_identifier",
            _text(
                self.execution_certification_identifier,
                field_name="execution_certification_identifier",
            ),
        )
        object.__setattr__(
            self,
            "asset_class_approval_identifier",
            _optional_text(
                self.asset_class_approval_identifier,
                field_name="asset_class_approval_identifier",
            ),
        )
        if self.asset_class in EXPANSION_ASSET_CLASSES and (
            self.asset_class_approval_identifier is None
        ):
            raise ValueError(
                "expanded-market execution requires an asset-class approval identifier"
            )
        if isinstance(self.maximum_quote_age_minutes, bool) or not isinstance(
            self.maximum_quote_age_minutes,
            int,
        ):
            raise TypeError("maximum_quote_age_minutes must be an integer")
        if self.maximum_quote_age_minutes < 1:
            raise ValueError("maximum_quote_age_minutes must be positive")
        for field_name in (
            "maximum_volume_participation",
            "maximum_position_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.maximum_volume_participation <= 0.0:
            raise ValueError("maximum_volume_participation must be positive")
        if self.maximum_position_weight <= 0.0:
            raise ValueError("maximum_position_weight must be positive")
        for field_name in ("commission_bps", "minimum_trade_base_amount"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        object.__setattr__(
            self,
            "notional_multiplier",
            _number(
                self.notional_multiplier,
                field_name="notional_multiplier",
                minimum=0.000000000001,
            ),
        )
        if abs(self.notional_multiplier - 1.0) > _EPSILON:
            raise ValueError(
                "multi-asset paper execution prohibits leveraged or synthetic notional multipliers"
            )
        if not isinstance(self.allow_fractional_quantity, bool):
            raise TypeError("allow_fractional_quantity must be a bool")
        object.__setattr__(
            self,
            "profile_version",
            _text(self.profile_version, field_name="profile_version"),
        )
        if self.asset_class is CandidateAssetClass.CRYPTO and (
            self.session_model is not TradingSessionModel.CONTINUOUS_24_7
        ):
            raise ValueError("crypto execution requires a continuous 24/7 session")
        if self.asset_class is CandidateAssetClass.FX and (
            self.session_model is not TradingSessionModel.CONTINUOUS_24_5
        ):
            raise ValueError("FX execution requires a continuous 24/5 session")
        if self.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY and (
            self.session_model is not TradingSessionModel.EXCHANGE_LOCAL
        ):
            raise ValueError(
                "international-equity execution requires a local exchange session"
            )


@dataclass(frozen=True, slots=True)
class InstrumentSession:
    instrument_identifier: str
    venue: str
    session_model: TradingSessionModel
    as_of: datetime
    status: InstrumentSessionStatus
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        object.__setattr__(
            self,
            "venue",
            _text(self.venue, field_name="venue").upper(),
        )
        if not isinstance(self.session_model, TradingSessionModel):
            raise TypeError("session_model must be TradingSessionModel")
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.status, InstrumentSessionStatus):
            raise TypeError("status must be InstrumentSessionStatus")
        object.__setattr__(
            self,
            "source_identifier",
            _text(self.source_identifier, field_name="source_identifier"),
        )


@dataclass(frozen=True, slots=True)
class MultiAssetQuote:
    symbol: str
    instrument_identifier: str
    venue: str
    observed_at: datetime
    bid: float
    ask: float
    last: float
    available_base_notional: float
    price_currency: str
    fx_rate_to_base: float
    fx_observed_at: datetime
    quote_source_identifier: str
    fx_source_identifier: str
    quote_certification_identifier: str
    halted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        object.__setattr__(
            self,
            "venue",
            _text(self.venue, field_name="venue").upper(),
        )
        _aware(self.observed_at, field_name="observed_at")
        for field_name in ("bid", "ask", "last"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.000000000001,
                ),
            )
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        object.__setattr__(
            self,
            "available_base_notional",
            _number(
                self.available_base_notional,
                field_name="available_base_notional",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "price_currency",
            _currency(self.price_currency, field_name="price_currency"),
        )
        object.__setattr__(
            self,
            "fx_rate_to_base",
            _number(
                self.fx_rate_to_base,
                field_name="fx_rate_to_base",
                minimum=0.000000000001,
            ),
        )
        _aware(self.fx_observed_at, field_name="fx_observed_at")
        for field_name in (
            "quote_source_identifier",
            "fx_source_identifier",
            "quote_certification_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.halted, bool):
            raise TypeError("halted must be a bool")


@runtime_checkable
class InstrumentSessionProvider(Protocol):
    def session(
        self,
        profile: InstrumentExecutionProfile,
        *,
        as_of: datetime,
    ) -> InstrumentSession: ...


@runtime_checkable
class MultiAssetQuoteProvider(Protocol):
    def quotes(
        self,
        profiles: tuple[InstrumentExecutionProfile, ...],
        *,
        as_of: datetime,
    ) -> Mapping[str, MultiAssetQuote]: ...


@dataclass(frozen=True, slots=True)
class MultiAssetPaperFill:
    identifier: str
    symbol: str
    instrument_identifier: str
    venue: str
    asset_class: CandidateAssetClass
    side: TradeSide
    quantity: float
    fill_price_local: float
    mark_price_local: float
    price_currency: str
    fx_rate_to_base: float
    gross_amount_local: float
    gross_amount_base: float
    commission_local: float
    commission_base: float
    adverse_spread_base: float
    quote_source_identifier: str
    fx_source_identifier: str
    execution_certification_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "instrument_identifier",
            "quote_source_identifier",
            "fx_source_identifier",
            "execution_certification_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        object.__setattr__(
            self,
            "venue",
            _text(self.venue, field_name="venue").upper(),
        )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        for field_name in (
            "quantity",
            "fill_price_local",
            "mark_price_local",
            "fx_rate_to_base",
            "gross_amount_local",
            "gross_amount_base",
            "commission_local",
            "commission_base",
            "adverse_spread_base",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        object.__setattr__(
            self,
            "price_currency",
            _currency(self.price_currency, field_name="price_currency"),
        )
        if self.quantity <= 0.0:
            raise ValueError("fill quantity must be positive")


@dataclass(frozen=True, slots=True)
class MultiAssetOrderResult:
    symbol: str
    instrument_identifier: str
    side: TradeSide
    status: MultiAssetOrderStatus
    requested_base_amount: float
    filled_base_amount: float
    reason: str
    fill_identifier: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        if not isinstance(self.status, MultiAssetOrderStatus):
            raise TypeError("status must be MultiAssetOrderStatus")
        for field_name in ("requested_base_amount", "filled_base_amount"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        object.__setattr__(self, "reason", _text(self.reason, field_name="reason"))
        object.__setattr__(
            self,
            "fill_identifier",
            _optional_text(
                self.fill_identifier,
                field_name="fill_identifier",
            ),
        )


@dataclass(frozen=True, slots=True)
class MultiAssetExecutionReconciliation:
    beginning_nav: float
    revalued_beginning_nav: float
    mark_change_base: float
    commission_base: float
    adverse_spread_base: float
    expected_ending_nav: float
    ending_nav: float
    difference: float
    reconciled: bool


@dataclass(frozen=True, slots=True)
class MultiAssetExecutionBatch:
    identifier: str
    decision_identifier: str
    construction_identifier: str
    attempted_at: datetime
    status: MultiAssetExecutionStatus
    beginning_snapshot_identifier: str
    ending_snapshot: CanonicalPortfolioSnapshot
    order_results: tuple[MultiAssetOrderResult, ...]
    fills: tuple[MultiAssetPaperFill, ...]
    reconciliation: MultiAssetExecutionReconciliation
    profile_identifiers: tuple[str, ...]
    source_identifiers: tuple[str, ...]
    attempt: int
    schema_version: str = "multi-asset-paper-execution-batch.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "construction_identifier",
            "beginning_snapshot_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.attempted_at, field_name="attempted_at")
        if not isinstance(self.status, MultiAssetExecutionStatus):
            raise TypeError("status must be MultiAssetExecutionStatus")
        if not isinstance(self.ending_snapshot, CanonicalPortfolioSnapshot):
            raise TypeError("ending_snapshot must be CanonicalPortfolioSnapshot")
        if not isinstance(self.order_results, tuple) or not all(
            isinstance(item, MultiAssetOrderResult) for item in self.order_results
        ):
            raise TypeError("order_results must contain MultiAssetOrderResult")
        if not isinstance(self.fills, tuple) or not all(
            isinstance(item, MultiAssetPaperFill) for item in self.fills
        ):
            raise TypeError("fills must contain MultiAssetPaperFill")
        if not isinstance(
            self.reconciliation,
            MultiAssetExecutionReconciliation,
        ):
            raise TypeError(
                "reconciliation must be MultiAssetExecutionReconciliation"
            )
        for field_name in ("profile_identifiers", "source_identifiers"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(value) != len(set(value)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("attempt must be an integer")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")


class SQLiteMultiAssetPaperExecutionStore:
    """Append-only execution attempts and completed batch authority."""

    _TABLE = "multi_asset_paper_execution_events"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    batch_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS multi_asset_execution_lookup
                ON {self._TABLE} (batch_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'multi-asset execution history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'multi-asset execution history is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        batch_identifier: str,
        event_type: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                batch_identifier,
                event_type,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(
        self,
        *,
        event_identifier: str,
        batch_identifier: str,
        event_type: MultiAssetExecutionEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        identifier = _text(event_identifier, field_name="event_identifier")
        batch = _text(batch_identifier, field_name="batch_identifier")
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = _canonical_json(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, event_type, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["event_type"]) != event_type.value
                    or str(existing["payload_json"]) != payload_json
                ):
                    raise MultiAssetExecutionError(
                        "execution event identifier already exists with different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH
                if tail is None
                else str(tail["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                batch_identifier=batch,
                event_type=event_type.value,
                occurred_at=timestamp,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, batch_identifier, event_type,
                    occurred_at, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    batch,
                    event_type.value,
                    timestamp,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def latest_batch(self, identifier: str) -> MultiAssetExecutionBatch | None:
        resolved = _text(identifier, field_name="identifier")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE batch_identifier = ? AND event_type = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (resolved, MultiAssetExecutionEventType.ATTEMPT_RECORDED.value),
            ).fetchone()
        if row is None:
            return None
        return batch_from_dict(json.loads(str(row["payload_json"])))

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise MultiAssetExecutionIntegrityError(
                    "multi-asset execution sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise MultiAssetExecutionIntegrityError(
                    "multi-asset execution previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                batch_identifier=str(row["batch_identifier"]),
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise MultiAssetExecutionIntegrityError(
                    "multi-asset execution content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class MultiAssetPaperExecutionOrchestrator:
    """Simulate asset-aware paper implementation and reconcile in base currency."""

    def __init__(
        self,
        *,
        session_provider: InstrumentSessionProvider,
        quote_provider: MultiAssetQuoteProvider,
        store: SQLiteMultiAssetPaperExecutionStore,
        portfolio_store: SQLiteCanonicalPortfolioStore,
        reconciliation_tolerance: float = 0.01,
    ) -> None:
        if not isinstance(session_provider, InstrumentSessionProvider):
            raise TypeError(
                "session_provider must implement InstrumentSessionProvider"
            )
        if not isinstance(quote_provider, MultiAssetQuoteProvider):
            raise TypeError("quote_provider must implement MultiAssetQuoteProvider")
        if not isinstance(store, SQLiteMultiAssetPaperExecutionStore):
            raise TypeError("store must be SQLiteMultiAssetPaperExecutionStore")
        if not isinstance(portfolio_store, SQLiteCanonicalPortfolioStore):
            raise TypeError("portfolio_store must be SQLiteCanonicalPortfolioStore")
        self.session_provider = session_provider
        self.quote_provider = quote_provider
        self.store = store
        self.portfolio_store = portfolio_store
        self.reconciliation_tolerance = _number(
            reconciliation_tolerance,
            field_name="reconciliation_tolerance",
            minimum=0.0,
        )

    def execute(
        self,
        *,
        construction: PortfolioConstructionResult,
        decision_identifier: str,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: tuple[InstrumentExecutionProfile, ...],
        as_of: datetime,
    ) -> MultiAssetExecutionBatch:
        if not isinstance(construction, PortfolioConstructionResult):
            raise TypeError("construction must be PortfolioConstructionResult")
        decision = _text(decision_identifier, field_name="decision_identifier")
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be CanonicalPortfolioSnapshot")
        timestamp = _aware(as_of, field_name="as_of")
        if construction.as_of > timestamp:
            raise MultiAssetExecutionError(
                "construction timestamp cannot follow execution time"
            )
        if portfolio.as_of > timestamp:
            raise MultiAssetExecutionError(
                "portfolio snapshot cannot follow execution time"
            )
        if construction.status is ConstructionStatus.BLOCKED:
            raise MultiAssetExecutionError(
                "blocked construction cannot enter multi-asset execution"
            )
        if not isinstance(profiles, tuple) or not all(
            isinstance(item, InstrumentExecutionProfile) for item in profiles
        ):
            raise TypeError("profiles must contain InstrumentExecutionProfile")
        profile_by_symbol = {item.symbol: item for item in profiles}
        if len(profile_by_symbol) != len(profiles):
            raise MultiAssetExecutionError(
                "execution profiles contain duplicate symbols"
            )
        profile_instruments = tuple(item.instrument_identifier for item in profiles)
        if len(profile_instruments) != len(set(profile_instruments)):
            raise MultiAssetExecutionError(
                "execution profiles contain duplicate instrument identifiers"
            )
        trade_symbols = tuple(item.symbol for item in construction.trades)
        if set(profile_by_symbol) != set(trade_symbols):
            missing = sorted(set(trade_symbols) - set(profile_by_symbol))
            extra = sorted(set(profile_by_symbol) - set(trade_symbols))
            raise MultiAssetExecutionError(
                "execution profile coverage must exactly match construction trades: "
                f"missing={missing} extra={extra}"
            )

        batch_identifier = f"multi-asset-execution:{construction.request_identifier}"
        previous = self.store.latest_batch(batch_identifier)
        if previous is not None and previous.status in {
            MultiAssetExecutionStatus.COMPLETED,
            MultiAssetExecutionStatus.NO_ACTION,
        }:
            return previous
        if previous is not None and (
            portfolio.identifier != previous.ending_snapshot.identifier
        ):
            raise MultiAssetExecutionError(
                "retry must resume from the exact prior ending portfolio snapshot"
            )
        attempt = 1 if previous is None else previous.attempt + 1
        self.store.verify_integrity()
        self.portfolio_store.verify_integrity()
        self.store.append(
            event_identifier=f"event:{batch_identifier}:started",
            batch_identifier=batch_identifier,
            event_type=MultiAssetExecutionEventType.BATCH_STARTED,
            occurred_at=timestamp,
            payload={
                "decision_identifier": decision,
                "construction_identifier": construction.request_identifier,
                "beginning_snapshot_identifier": portfolio.identifier,
                "profile_identifiers": [
                    f"{item.profile_version}:{item.instrument_identifier}"
                    for item in profiles
                ],
            },
        )

        if not construction.trades:
            reconciliation = MultiAssetExecutionReconciliation(
                beginning_nav=portfolio.nav,
                revalued_beginning_nav=portfolio.nav,
                mark_change_base=0.0,
                commission_base=0.0,
                adverse_spread_base=0.0,
                expected_ending_nav=portfolio.nav,
                ending_nav=portfolio.nav,
                difference=0.0,
                reconciled=True,
            )
            batch = MultiAssetExecutionBatch(
                identifier=batch_identifier,
                decision_identifier=decision,
                construction_identifier=construction.request_identifier,
                attempted_at=timestamp,
                status=MultiAssetExecutionStatus.NO_ACTION,
                beginning_snapshot_identifier=portfolio.identifier,
                ending_snapshot=portfolio,
                order_results=(),
                fills=(),
                reconciliation=reconciliation,
                profile_identifiers=(),
                source_identifiers=(),
                attempt=attempt,
            )
            self._record(batch)
            return batch

        sessions: dict[str, InstrumentSession] = {}
        open_profiles: list[InstrumentExecutionProfile] = []
        for profile in profiles:
            session = self.session_provider.session(profile, as_of=timestamp)
            if session.instrument_identifier != profile.instrument_identifier:
                raise MultiAssetExecutionError(
                    "session result does not match the execution profile instrument"
                )
            if session.venue != profile.venue:
                raise MultiAssetExecutionError(
                    "session result venue does not match the execution profile"
                )
            if session.session_model is not profile.session_model:
                raise MultiAssetExecutionError(
                    "session result model does not match the execution profile"
                )
            if session.as_of != timestamp:
                raise MultiAssetExecutionError(
                    "session result timestamp does not match execution time"
                )
            sessions[profile.symbol] = session
            if session.status is InstrumentSessionStatus.OPEN:
                open_profiles.append(profile)

        quotes: Mapping[str, MultiAssetQuote]
        if open_profiles:
            quotes = self.quote_provider.quotes(
                tuple(open_profiles),
                as_of=timestamp,
            )
            if not isinstance(quotes, Mapping):
                raise MultiAssetExecutionError(
                    "quote provider must return a symbol mapping"
                )
            if set(quotes) != {item.symbol for item in open_profiles}:
                missing = sorted(
                    {item.symbol for item in open_profiles} - set(quotes)
                )
                extra = sorted(set(quotes) - {item.symbol for item in open_profiles})
                raise MultiAssetExecutionError(
                    "quote coverage must exactly match open execution profiles: "
                    f"missing={missing} extra={extra}"
                )
        else:
            quotes = {}

        position_by_symbol = {item.symbol: item for item in portfolio.positions}
        cash = portfolio.cash_amount
        order_results: list[MultiAssetOrderResult] = []
        fills: list[MultiAssetPaperFill] = []
        source_identifiers: list[str] = []
        updated_positions = dict(position_by_symbol)

        ordered_trades = tuple(
            sorted(
                construction.trades,
                key=lambda item: 0 if item.side is TradeSide.SELL else 1,
            )
        )
        for trade in ordered_trades:
            profile = profile_by_symbol[trade.symbol]
            session = sessions[trade.symbol]
            requested_base = round(trade.trade_weight * portfolio.nav, 8)
            if session.status is not InstrumentSessionStatus.OPEN:
                order_results.append(
                    MultiAssetOrderResult(
                        symbol=trade.symbol,
                        instrument_identifier=profile.instrument_identifier,
                        side=trade.side,
                        status=MultiAssetOrderStatus.HELD,
                        requested_base_amount=requested_base,
                        filled_base_amount=0.0,
                        reason=(
                            f"{profile.session_model.value} session is "
                            f"{session.status.value}"
                        ),
                    )
                )
                source_identifiers.append(session.source_identifier)
                continue

            quote = quotes[trade.symbol]
            self._validate_quote(
                quote=quote,
                profile=profile,
                as_of=timestamp,
                base_currency=portfolio.base_currency,
            )
            source_identifiers.extend(
                (
                    session.source_identifier,
                    quote.quote_source_identifier,
                    quote.fx_source_identifier,
                    quote.quote_certification_identifier,
                    profile.execution_certification_identifier,
                )
            )
            if quote.halted:
                order_results.append(
                    MultiAssetOrderResult(
                        symbol=trade.symbol,
                        instrument_identifier=profile.instrument_identifier,
                        side=trade.side,
                        status=MultiAssetOrderStatus.REJECTED,
                        requested_base_amount=requested_base,
                        filled_base_amount=0.0,
                        reason="instrument is halted",
                    )
                )
                continue

            fill, result, cash, next_position = self._fill_trade(
                trade=trade,
                profile=profile,
                quote=quote,
                portfolio=portfolio,
                current_position=updated_positions.get(trade.symbol),
                available_cash=cash,
                attempted_at=timestamp,
                batch_identifier=batch_identifier,
            )
            order_results.append(result)
            if fill is not None:
                fills.append(fill)
                if next_position is None:
                    updated_positions.pop(trade.symbol, None)
                else:
                    updated_positions[trade.symbol] = next_position

        revalued_beginning_nav = self._revalued_beginning_nav(
            portfolio=portfolio,
            quotes=quotes,
        )
        commission_base = round(sum(item.commission_base for item in fills), 8)
        adverse_spread_base = round(
            sum(item.adverse_spread_base for item in fills),
            8,
        )
        mark_change = round(revalued_beginning_nav - portfolio.nav, 8)
        implementation_events = tuple(
            list(portfolio.implementation_events)
            + [
                CanonicalImplementationEvent(
                    identifier=item.identifier,
                    occurred_at=timestamp,
                    action=item.side.value,
                    symbol=item.symbol,
                    instrument_identifier=item.instrument_identifier,
                    venue=item.venue,
                    asset_class=item.asset_class.value,
                    quantity=item.quantity,
                    price=item.fill_price_local,
                    gross_amount=item.gross_amount_local,
                    cost_amount=item.commission_local,
                    rationale=(
                        "Governed multi-asset paper fill; no broker order submitted."
                    ),
                    source_identifier=item.quote_source_identifier,
                    price_currency=item.price_currency,
                    settlement_currency=(
                        profile_by_symbol[item.symbol].settlement_currency
                    ),
                    fx_rate_to_base=item.fx_rate_to_base,
                    fx_rate_source_identifier=item.fx_source_identifier,
                )
                for item in fills
            ]
        )
        ending_snapshot = CanonicalPortfolioSnapshot(
            identifier=f"{portfolio.identifier}:multi-asset-attempt:{attempt}",
            portfolio_code=portfolio.portfolio_code,
            display_name=portfolio.display_name,
            constraint_profile=portfolio.constraint_profile,
            as_of=timestamp,
            starting_capital=portfolio.starting_capital,
            cash_amount=round(cash, 8),
            base_currency=portfolio.base_currency,
            currency_balances=portfolio.currency_balances,
            positions=tuple(
                sorted(updated_positions.values(), key=lambda item: item.symbol)
            ),
            implementation_events=implementation_events,
            source_identifiers=tuple(
                dict.fromkeys(
                    portfolio.source_identifiers + tuple(source_identifiers)
                )
            ),
        )
        expected_ending_nav = round(
            portfolio.nav
            + mark_change
            - commission_base
            - adverse_spread_base,
            8,
        )
        difference = round(ending_snapshot.nav - expected_ending_nav, 8)
        reconciled = abs(difference) <= self.reconciliation_tolerance
        reconciliation = MultiAssetExecutionReconciliation(
            beginning_nav=portfolio.nav,
            revalued_beginning_nav=revalued_beginning_nav,
            mark_change_base=mark_change,
            commission_base=commission_base,
            adverse_spread_base=adverse_spread_base,
            expected_ending_nav=expected_ending_nav,
            ending_nav=ending_snapshot.nav,
            difference=difference,
            reconciled=reconciled,
        )
        if not reconciled:
            self.store.append(
                event_identifier=f"event:{batch_identifier}:attempt:{attempt}:failed",
                batch_identifier=batch_identifier,
                event_type=MultiAssetExecutionEventType.BATCH_FAILED,
                occurred_at=timestamp,
                payload={
                    "classification": "reconciliation",
                    "difference": difference,
                    "expected_ending_nav": expected_ending_nav,
                    "ending_nav": ending_snapshot.nav,
                },
            )
            raise MultiAssetExecutionError(
                "multi-asset paper ledger did not reconcile"
            )

        statuses = {item.status for item in order_results}
        if not order_results:
            status = MultiAssetExecutionStatus.NO_ACTION
        elif statuses <= {MultiAssetOrderStatus.FILLED}:
            status = MultiAssetExecutionStatus.COMPLETED
        elif fills:
            status = MultiAssetExecutionStatus.PARTIAL
        elif statuses <= {MultiAssetOrderStatus.HELD}:
            status = MultiAssetExecutionStatus.HELD
        else:
            status = MultiAssetExecutionStatus.FAILED
        batch = MultiAssetExecutionBatch(
            identifier=batch_identifier,
            decision_identifier=decision,
            construction_identifier=construction.request_identifier,
            attempted_at=timestamp,
            status=status,
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot=ending_snapshot,
            order_results=tuple(order_results),
            fills=tuple(fills),
            reconciliation=reconciliation,
            profile_identifiers=tuple(
                f"{item.profile_version}:{item.instrument_identifier}"
                for item in profiles
            ),
            source_identifiers=tuple(dict.fromkeys(source_identifiers)),
            attempt=attempt,
        )
        if fills:
            self.portfolio_store.append(ending_snapshot)
        self._record(batch)
        return batch

    def _record(self, batch: MultiAssetExecutionBatch) -> None:
        self.store.append(
            event_identifier=(
                f"event:{batch.identifier}:attempt:{batch.attempt}:recorded"
            ),
            batch_identifier=batch.identifier,
            event_type=MultiAssetExecutionEventType.ATTEMPT_RECORDED,
            occurred_at=batch.attempted_at,
            payload=batch_to_dict(batch),
        )
        self.store.verify_integrity()

    @staticmethod
    def _validate_quote(
        *,
        quote: MultiAssetQuote,
        profile: InstrumentExecutionProfile,
        as_of: datetime,
        base_currency: str,
    ) -> None:
        if quote.symbol != profile.symbol:
            raise MultiAssetExecutionError("quote symbol does not match profile")
        if quote.instrument_identifier != profile.instrument_identifier:
            raise MultiAssetExecutionError(
                "quote instrument does not match execution profile"
            )
        if quote.venue != profile.venue:
            raise MultiAssetExecutionError(
                "quote venue does not match execution profile"
            )
        if quote.price_currency != profile.price_currency:
            raise MultiAssetExecutionError(
                "quote currency does not match execution profile"
            )
        if quote.observed_at > as_of or quote.fx_observed_at > as_of:
            raise MultiAssetExecutionError(
                "quote or FX evidence is future-known at execution time"
            )
        maximum_age = timedelta(minutes=profile.maximum_quote_age_minutes)
        if as_of - quote.observed_at > maximum_age:
            raise MultiAssetExecutionError("quote is stale")
        if as_of - quote.fx_observed_at > maximum_age:
            raise MultiAssetExecutionError("FX conversion evidence is stale")
        if quote.price_currency == base_currency:
            if abs(quote.fx_rate_to_base - 1.0) > _EPSILON:
                raise MultiAssetExecutionError(
                    "base-currency quote must use FX rate 1.0"
                )

    @staticmethod
    def _quantity(value: float, *, fractional: bool) -> float:
        if fractional:
            return round(max(0.0, value), 12)
        return float(max(0, floor(value)))

    def _fill_trade(
        self,
        *,
        trade: TradeProposal,
        profile: InstrumentExecutionProfile,
        quote: MultiAssetQuote,
        portfolio: CanonicalPortfolioSnapshot,
        current_position: CanonicalPortfolioPosition | None,
        available_cash: float,
        attempted_at: datetime,
        batch_identifier: str,
    ) -> tuple[
        MultiAssetPaperFill | None,
        MultiAssetOrderResult,
        float,
        CanonicalPortfolioPosition | None,
    ]:
        requested_base = round(trade.trade_weight * portfolio.nav, 8)
        if requested_base < profile.minimum_trade_base_amount:
            return (
                None,
                MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.REJECTED,
                    requested_base_amount=requested_base,
                    filled_base_amount=0.0,
                    reason="requested trade is below the minimum base amount",
                ),
                available_cash,
                current_position,
            )
        fill_price = quote.bid if trade.side is TradeSide.SELL else quote.ask
        mark_price = quote.last
        per_unit_base = fill_price * quote.fx_rate_to_base
        volume_cap_base = (
            quote.available_base_notional * profile.maximum_volume_participation
        )
        base_cap = min(requested_base, volume_cap_base)
        if trade.side is TradeSide.SELL:
            if current_position is None:
                return (
                    None,
                    MultiAssetOrderResult(
                        symbol=trade.symbol,
                        instrument_identifier=profile.instrument_identifier,
                        side=trade.side,
                        status=MultiAssetOrderStatus.REJECTED,
                        requested_base_amount=requested_base,
                        filled_base_amount=0.0,
                        reason="sell has no canonical owned position",
                    ),
                    available_cash,
                    current_position,
                )
            if (
                current_position.instrument_identifier is not None
                and current_position.instrument_identifier
                != profile.instrument_identifier
            ):
                raise MultiAssetExecutionError(
                    "owned position identity does not match execution profile"
                )
            quantity_cap = current_position.quantity
        else:
            commission_rate = profile.commission_bps / 10_000
            base_cap = min(
                base_cap,
                available_cash / max(1.0 + commission_rate, _EPSILON),
            )
            current_weight = (
                0.0
                if current_position is None
                else current_position.market_value / portfolio.nav
            )
            remaining_weight = max(
                0.0,
                profile.maximum_position_weight - current_weight,
            )
            base_cap = min(base_cap, remaining_weight * portfolio.nav)
            quantity_cap = float("inf")
        quantity = self._quantity(
            min(base_cap / per_unit_base, quantity_cap),
            fractional=profile.allow_fractional_quantity,
        )
        if quantity <= _EPSILON:
            return (
                None,
                MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.REJECTED,
                    requested_base_amount=requested_base,
                    filled_base_amount=0.0,
                    reason="cash, ownership, liquidity, or position limit permits no fill",
                ),
                available_cash,
                current_position,
            )
        gross_local = round(quantity * fill_price, 12)
        gross_base = round(gross_local * quote.fx_rate_to_base, 8)
        commission_local = round(
            gross_local * profile.commission_bps / 10_000,
            12,
        )
        commission_base = round(
            commission_local * quote.fx_rate_to_base,
            8,
        )
        adverse_spread_base = round(
            quantity
            * abs(fill_price - mark_price)
            * quote.fx_rate_to_base,
            8,
        )
        if trade.side is TradeSide.BUY:
            total_cash_use = gross_base + commission_base
            if total_cash_use > available_cash + self.reconciliation_tolerance:
                raise MultiAssetExecutionError(
                    "unlevered buy would make base-currency cash negative"
                )
            next_cash = round(available_cash - total_cash_use, 8)
            next_position = self._buy_position(
                current=current_position,
                profile=profile,
                quote=quote,
                quantity=quantity,
                gross_local=gross_local,
                gross_base=gross_base,
                commission_local=commission_local,
                commission_base=commission_base,
                attempted_at=attempted_at,
            )
        else:
            next_cash = round(
                available_cash + gross_base - commission_base,
                8,
            )
            remaining = round(current_position.quantity - quantity, 12)
            next_position = (
                None
                if remaining <= _EPSILON
                else CanonicalPortfolioPosition(
                    symbol=current_position.symbol,
                    instrument_identifier=(
                        current_position.instrument_identifier
                        or profile.instrument_identifier
                    ),
                    venue=profile.venue,
                    asset_class=profile.asset_class.value,
                    quantity=remaining,
                    average_cost=current_position.average_cost,
                    average_cost_base=current_position.average_cost_base,
                    mark_price=quote.last,
                    updated_at=attempted_at,
                    price_currency=profile.price_currency,
                    settlement_currency=profile.settlement_currency,
                    fx_rate_to_base=quote.fx_rate_to_base,
                    fx_rate_observed_at=quote.fx_observed_at,
                    fx_rate_source_identifier=quote.fx_source_identifier,
                )
            )
        fill_identifier = (
            f"fill:{batch_identifier}:{attempted_at.isoformat()}:{trade.symbol}:"
            f"{trade.side.value}"
        )
        fill = MultiAssetPaperFill(
            identifier=fill_identifier,
            symbol=trade.symbol,
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            asset_class=profile.asset_class,
            side=trade.side,
            quantity=quantity,
            fill_price_local=fill_price,
            mark_price_local=mark_price,
            price_currency=profile.price_currency,
            fx_rate_to_base=quote.fx_rate_to_base,
            gross_amount_local=gross_local,
            gross_amount_base=gross_base,
            commission_local=commission_local,
            commission_base=commission_base,
            adverse_spread_base=adverse_spread_base,
            quote_source_identifier=quote.quote_source_identifier,
            fx_source_identifier=quote.fx_source_identifier,
            execution_certification_identifier=(
                profile.execution_certification_identifier
            ),
        )
        fill_status = (
            MultiAssetOrderStatus.FILLED
            if gross_base + self.reconciliation_tolerance >= requested_base
            else MultiAssetOrderStatus.PARTIALLY_FILLED
        )
        result = MultiAssetOrderResult(
            symbol=trade.symbol,
            instrument_identifier=profile.instrument_identifier,
            side=trade.side,
            status=fill_status,
            requested_base_amount=requested_base,
            filled_base_amount=gross_base,
            reason=(
                "paper fill completed"
                if fill_status is MultiAssetOrderStatus.FILLED
                else "paper fill was limited by cash, liquidity, ownership, or position policy"
            ),
            fill_identifier=fill.identifier,
        )
        return fill, result, next_cash, next_position

    @staticmethod
    def _buy_position(
        *,
        current: CanonicalPortfolioPosition | None,
        profile: InstrumentExecutionProfile,
        quote: MultiAssetQuote,
        quantity: float,
        gross_local: float,
        gross_base: float,
        commission_local: float,
        commission_base: float,
        attempted_at: datetime,
    ) -> CanonicalPortfolioPosition:
        old_quantity = 0.0 if current is None else current.quantity
        old_local_cost = 0.0 if current is None else current.local_cost_basis
        old_base_cost = 0.0 if current is None else current.cost_basis
        total_quantity = round(old_quantity + quantity, 12)
        average_local = round(
            (old_local_cost + gross_local + commission_local) / total_quantity,
            12,
        )
        average_base = round(
            (old_base_cost + gross_base + commission_base) / total_quantity,
            12,
        )
        return CanonicalPortfolioPosition(
            symbol=profile.symbol,
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            asset_class=profile.asset_class.value,
            quantity=total_quantity,
            average_cost=average_local,
            average_cost_base=average_base,
            mark_price=quote.last,
            updated_at=attempted_at,
            price_currency=profile.price_currency,
            settlement_currency=profile.settlement_currency,
            fx_rate_to_base=quote.fx_rate_to_base,
            fx_rate_observed_at=quote.fx_observed_at,
            fx_rate_source_identifier=quote.fx_source_identifier,
        )

    @staticmethod
    def _revalued_beginning_nav(
        *,
        portfolio: CanonicalPortfolioSnapshot,
        quotes: Mapping[str, MultiAssetQuote],
    ) -> float:
        value = portfolio.total_cash_value
        for position in portfolio.positions:
            quote = quotes.get(position.symbol)
            value += (
                position.market_value
                if quote is None
                else position.quantity * quote.last * quote.fx_rate_to_base
            )
        return round(value, 8)


def profile_to_dict(value: InstrumentExecutionProfile) -> dict[str, Any]:
    return {
        "symbol": value.symbol,
        "instrument_identifier": value.instrument_identifier,
        "asset_class": value.asset_class.value,
        "venue": value.venue,
        "session_model": value.session_model.value,
        "price_currency": value.price_currency,
        "settlement_currency": value.settlement_currency,
        "execution_certification_identifier": (
            value.execution_certification_identifier
        ),
        "asset_class_approval_identifier": (
            value.asset_class_approval_identifier
        ),
        "maximum_quote_age_minutes": value.maximum_quote_age_minutes,
        "maximum_volume_participation": value.maximum_volume_participation,
        "commission_bps": value.commission_bps,
        "minimum_trade_base_amount": value.minimum_trade_base_amount,
        "maximum_position_weight": value.maximum_position_weight,
        "allow_fractional_quantity": value.allow_fractional_quantity,
        "notional_multiplier": value.notional_multiplier,
        "profile_version": value.profile_version,
    }


def profile_from_dict(value: Mapping[str, Any]) -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        symbol=str(value["symbol"]),
        instrument_identifier=str(value["instrument_identifier"]),
        asset_class=CandidateAssetClass(str(value["asset_class"])),
        venue=str(value["venue"]),
        session_model=TradingSessionModel(str(value["session_model"])),
        price_currency=str(value["price_currency"]),
        settlement_currency=str(value["settlement_currency"]),
        execution_certification_identifier=str(
            value["execution_certification_identifier"]
        ),
        asset_class_approval_identifier=(
            None
            if value.get("asset_class_approval_identifier") is None
            else str(value["asset_class_approval_identifier"])
        ),
        maximum_quote_age_minutes=int(
            value.get("maximum_quote_age_minutes", 5)
        ),
        maximum_volume_participation=float(
            value.get("maximum_volume_participation", 0.10)
        ),
        commission_bps=float(value.get("commission_bps", 0.0)),
        minimum_trade_base_amount=float(
            value.get("minimum_trade_base_amount", 1.0)
        ),
        maximum_position_weight=float(
            value.get("maximum_position_weight", 0.20)
        ),
        allow_fractional_quantity=bool(
            value.get("allow_fractional_quantity", True)
        ),
        notional_multiplier=float(value.get("notional_multiplier", 1.0)),
        profile_version=str(
            value.get("profile_version", "multi-asset-execution-profile.v1")
        ),
    )


def fill_to_dict(value: MultiAssetPaperFill) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "symbol": value.symbol,
        "instrument_identifier": value.instrument_identifier,
        "venue": value.venue,
        "asset_class": value.asset_class.value,
        "side": value.side.value,
        "quantity": value.quantity,
        "fill_price_local": value.fill_price_local,
        "mark_price_local": value.mark_price_local,
        "price_currency": value.price_currency,
        "fx_rate_to_base": value.fx_rate_to_base,
        "gross_amount_local": value.gross_amount_local,
        "gross_amount_base": value.gross_amount_base,
        "commission_local": value.commission_local,
        "commission_base": value.commission_base,
        "adverse_spread_base": value.adverse_spread_base,
        "quote_source_identifier": value.quote_source_identifier,
        "fx_source_identifier": value.fx_source_identifier,
        "execution_certification_identifier": (
            value.execution_certification_identifier
        ),
    }


def batch_to_dict(value: MultiAssetExecutionBatch) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "decision_identifier": value.decision_identifier,
        "construction_identifier": value.construction_identifier,
        "attempted_at": value.attempted_at.isoformat(),
        "status": value.status.value,
        "beginning_snapshot_identifier": value.beginning_snapshot_identifier,
        "ending_snapshot": snapshot_to_dict(value.ending_snapshot),
        "order_results": [
            {
                "symbol": item.symbol,
                "instrument_identifier": item.instrument_identifier,
                "side": item.side.value,
                "status": item.status.value,
                "requested_base_amount": item.requested_base_amount,
                "filled_base_amount": item.filled_base_amount,
                "reason": item.reason,
                "fill_identifier": item.fill_identifier,
            }
            for item in value.order_results
        ],
        "fills": [fill_to_dict(item) for item in value.fills],
        "reconciliation": {
            "beginning_nav": value.reconciliation.beginning_nav,
            "revalued_beginning_nav": (
                value.reconciliation.revalued_beginning_nav
            ),
            "mark_change_base": value.reconciliation.mark_change_base,
            "commission_base": value.reconciliation.commission_base,
            "adverse_spread_base": value.reconciliation.adverse_spread_base,
            "expected_ending_nav": value.reconciliation.expected_ending_nav,
            "ending_nav": value.reconciliation.ending_nav,
            "difference": value.reconciliation.difference,
            "reconciled": value.reconciliation.reconciled,
        },
        "profile_identifiers": list(value.profile_identifiers),
        "source_identifiers": list(value.source_identifiers),
        "attempt": value.attempt,
        "schema_version": value.schema_version,
    }


def batch_from_dict(value: Mapping[str, Any]) -> MultiAssetExecutionBatch:
    reconciliation = value["reconciliation"]
    if not isinstance(reconciliation, Mapping):
        raise TypeError("reconciliation must encode an object")
    return MultiAssetExecutionBatch(
        identifier=str(value["identifier"]),
        decision_identifier=str(value["decision_identifier"]),
        construction_identifier=str(value["construction_identifier"]),
        attempted_at=datetime.fromisoformat(str(value["attempted_at"])),
        status=MultiAssetExecutionStatus(str(value["status"])),
        beginning_snapshot_identifier=str(
            value["beginning_snapshot_identifier"]
        ),
        ending_snapshot=snapshot_from_dict(value["ending_snapshot"]),
        order_results=tuple(
            MultiAssetOrderResult(
                symbol=str(item["symbol"]),
                instrument_identifier=str(item["instrument_identifier"]),
                side=TradeSide(str(item["side"])),
                status=MultiAssetOrderStatus(str(item["status"])),
                requested_base_amount=float(item["requested_base_amount"]),
                filled_base_amount=float(item["filled_base_amount"]),
                reason=str(item["reason"]),
                fill_identifier=(
                    None
                    if item.get("fill_identifier") is None
                    else str(item["fill_identifier"])
                ),
            )
            for item in value.get("order_results", ())
        ),
        fills=tuple(
            MultiAssetPaperFill(
                identifier=str(item["identifier"]),
                symbol=str(item["symbol"]),
                instrument_identifier=str(item["instrument_identifier"]),
                venue=str(item["venue"]),
                asset_class=CandidateAssetClass(str(item["asset_class"])),
                side=TradeSide(str(item["side"])),
                quantity=float(item["quantity"]),
                fill_price_local=float(item["fill_price_local"]),
                mark_price_local=float(item["mark_price_local"]),
                price_currency=str(item["price_currency"]),
                fx_rate_to_base=float(item["fx_rate_to_base"]),
                gross_amount_local=float(item["gross_amount_local"]),
                gross_amount_base=float(item["gross_amount_base"]),
                commission_local=float(item["commission_local"]),
                commission_base=float(item["commission_base"]),
                adverse_spread_base=float(item["adverse_spread_base"]),
                quote_source_identifier=str(item["quote_source_identifier"]),
                fx_source_identifier=str(item["fx_source_identifier"]),
                execution_certification_identifier=str(
                    item["execution_certification_identifier"]
                ),
            )
            for item in value.get("fills", ())
        ),
        reconciliation=MultiAssetExecutionReconciliation(
            beginning_nav=float(reconciliation["beginning_nav"]),
            revalued_beginning_nav=float(
                reconciliation["revalued_beginning_nav"]
            ),
            mark_change_base=float(reconciliation["mark_change_base"]),
            commission_base=float(reconciliation["commission_base"]),
            adverse_spread_base=float(
                reconciliation["adverse_spread_base"]
            ),
            expected_ending_nav=float(
                reconciliation["expected_ending_nav"]
            ),
            ending_nav=float(reconciliation["ending_nav"]),
            difference=float(reconciliation["difference"]),
            reconciled=bool(reconciliation["reconciled"]),
        ),
        profile_identifiers=tuple(
            str(item) for item in value.get("profile_identifiers", ())
        ),
        source_identifiers=tuple(
            str(item) for item in value.get("source_identifiers", ())
        ),
        attempt=int(value["attempt"]),
        schema_version=str(
            value.get(
                "schema_version",
                "multi-asset-paper-execution-batch.v1",
            )
        ),
    )


__all__ = [
    "InstrumentExecutionProfile",
    "InstrumentSession",
    "InstrumentSessionProvider",
    "InstrumentSessionStatus",
    "MultiAssetExecutionBatch",
    "MultiAssetExecutionError",
    "MultiAssetExecutionIntegrityError",
    "MultiAssetExecutionReconciliation",
    "MultiAssetExecutionStatus",
    "MultiAssetOrderResult",
    "MultiAssetOrderStatus",
    "MultiAssetPaperExecutionOrchestrator",
    "MultiAssetPaperFill",
    "MultiAssetQuote",
    "MultiAssetQuoteProvider",
    "SQLiteMultiAssetPaperExecutionStore",
    "batch_from_dict",
    "batch_to_dict",
    "profile_from_dict",
    "profile_to_dict",
]
