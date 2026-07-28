"""Governed paper-only execution across all classified liquid public markets.

The authority consumes the same ``MultiAssetInstrumentProfile`` used by governed
portfolio construction. It never creates a competing instrument, approval,
custody, leverage, margin, contract, or execution-model authority. Paper activity
is routed through asset-aware sessions, certified point-in-time quotes, contract
multipliers, and canonical cross-currency portfolio state. No live-order authority
exists here.
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
from typing import Any, Mapping, Protocol, runtime_checkable

from governance.eligible_universe import SQLiteCertifiedEligibleUniverseStore
from cio import CandidateAssetClass
from governance import TradingSessionModel
from portfolio.construction_models import (
    ConstructionStatus,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.execution_eligibility import (
    CertifiedExecutionEligibilityAuthority,
    ExecutionEligibilityError,
)
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
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
    """Raised when governed paper implementation cannot proceed safely."""


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
class MultiAssetExecutionPolicy:
    """Versioned paper-fill assumptions; never an instrument authority."""

    version: str = "multi-asset-paper-execution.v2"
    maximum_quote_age_minutes: int = 5
    us_equity_commission_bps: float = 0.0
    us_etf_commission_bps: float = 0.0
    cash_equivalent_commission_bps: float = 0.0
    maximum_volume_participation: float = 0.10
    crypto_commission_bps: float = 10.0
    fx_commission_bps: float = 1.0
    international_equity_commission_bps: float = 5.0
    fixed_income_commission_bps: float = 2.0
    commodity_commission_bps: float = 4.0
    real_estate_commission_bps: float = 5.0
    future_commission_bps: float = 2.0
    option_commission_bps: float = 5.0
    volatility_commission_bps: float = 5.0
    alternative_commission_bps: float = 6.0
    minimum_trade_base_amount: float = 1.0
    reconciliation_tolerance: float = 0.01

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        if isinstance(self.maximum_quote_age_minutes, bool) or not isinstance(
            self.maximum_quote_age_minutes,
            int,
        ):
            raise TypeError("maximum_quote_age_minutes must be an integer")
        if self.maximum_quote_age_minutes < 1:
            raise ValueError("maximum_quote_age_minutes must be positive")
        object.__setattr__(
            self,
            "maximum_volume_participation",
            _number(
                self.maximum_volume_participation,
                field_name="maximum_volume_participation",
                minimum=0.000000000001,
                maximum=1.0,
            ),
        )
        for field_name in (
            "us_equity_commission_bps",
            "us_etf_commission_bps",
            "cash_equivalent_commission_bps",
            "crypto_commission_bps",
            "fx_commission_bps",
            "international_equity_commission_bps",
            "fixed_income_commission_bps",
            "commodity_commission_bps",
            "real_estate_commission_bps",
            "future_commission_bps",
            "option_commission_bps",
            "volatility_commission_bps",
            "alternative_commission_bps",
            "minimum_trade_base_amount",
            "reconciliation_tolerance",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name, minimum=0.0),
            )

    def session_model(self, asset_class: CandidateAssetClass) -> TradingSessionModel:
        try:
            return {
                CandidateAssetClass.US_EQUITY: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.US_ETF: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.CASH_EQUIVALENT: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.CRYPTO: TradingSessionModel.CONTINUOUS_24_7,
                CandidateAssetClass.FX: TradingSessionModel.CONTINUOUS_24_5,
                CandidateAssetClass.FIXED_INCOME: TradingSessionModel.DEALER_24_5,
                CandidateAssetClass.INTERNATIONAL_EQUITY: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.COMMODITY: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.REAL_ESTATE: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.FUTURE: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.OPTION: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.VOLATILITY: TradingSessionModel.EXCHANGE_LOCAL,
                CandidateAssetClass.ALTERNATIVE: TradingSessionModel.EXCHANGE_LOCAL,
            }[asset_class]
        except KeyError as error:
            raise MultiAssetExecutionError(
                f"{asset_class.value} is outside classified governed execution"
            ) from error

    def commission_bps(self, asset_class: CandidateAssetClass) -> float:
        return {
            CandidateAssetClass.US_EQUITY: self.us_equity_commission_bps,
            CandidateAssetClass.US_ETF: self.us_etf_commission_bps,
            CandidateAssetClass.CASH_EQUIVALENT: self.cash_equivalent_commission_bps,
            CandidateAssetClass.CRYPTO: self.crypto_commission_bps,
            CandidateAssetClass.FX: self.fx_commission_bps,
            CandidateAssetClass.INTERNATIONAL_EQUITY: self.international_equity_commission_bps,
            CandidateAssetClass.FIXED_INCOME: self.fixed_income_commission_bps,
            CandidateAssetClass.COMMODITY: self.commodity_commission_bps,
            CandidateAssetClass.REAL_ESTATE: self.real_estate_commission_bps,
            CandidateAssetClass.FUTURE: self.future_commission_bps,
            CandidateAssetClass.OPTION: self.option_commission_bps,
            CandidateAssetClass.VOLATILITY: self.volatility_commission_bps,
            CandidateAssetClass.ALTERNATIVE: self.alternative_commission_bps,
        }[asset_class]

    @staticmethod
    def fractional_quantity(
        asset_class: CandidateAssetClass,
        instrument_type: str | None = None,
    ) -> bool:
        if instrument_type is not None:
            return instrument_type in {"spot", "token", "stablecoin", "bond", "common_stock", "preferred_stock", "fund"}
        return asset_class in {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.US_ETF,
            CandidateAssetClass.CASH_EQUIVALENT,
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FX,
            CandidateAssetClass.FIXED_INCOME,
        }


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
            _text(self.instrument_identifier, field_name="instrument_identifier"),
        )
        object.__setattr__(self, "venue", _text(self.venue, field_name="venue").upper())
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
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(self.instrument_identifier, field_name="instrument_identifier"),
        )
        object.__setattr__(self, "venue", _text(self.venue, field_name="venue").upper())
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
        profile: MultiAssetInstrumentProfile,
        *,
        session_model: TradingSessionModel,
        as_of: datetime,
    ) -> InstrumentSession: ...


@runtime_checkable
class MultiAssetQuoteProvider(Protocol):
    def quotes(
        self,
        profiles: tuple[MultiAssetInstrumentProfile, ...],
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
    settlement_currency: str
    fx_rate_to_base: float
    gross_amount_local: float
    gross_amount_base: float
    commission_local: float
    commission_base: float
    adverse_spread_base: float
    quote_source_identifier: str
    fx_source_identifier: str
    quote_certification_identifier: str
    approval_identifier: str
    custody_settlement_identifier: str
    execution_model_version: str
    contract_multiplier: float = 1.0

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "instrument_identifier",
            "quote_source_identifier",
            "fx_source_identifier",
            "quote_certification_identifier",
            "approval_identifier",
            "custody_settlement_identifier",
            "execution_model_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(self, "venue", _text(self.venue, field_name="venue").upper())
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
            "contract_multiplier",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name, minimum=0.0),
            )
        if self.quantity <= 0.0:
            raise ValueError("fill quantity must be positive")
        object.__setattr__(
            self,
            "price_currency",
            _currency(self.price_currency, field_name="price_currency"),
        )
        object.__setattr__(
            self,
            "settlement_currency",
            _currency(self.settlement_currency, field_name="settlement_currency"),
        )


@dataclass(frozen=True, slots=True)
class MultiAssetOrderResult:
    symbol: str
    instrument_identifier: str
    side: TradeSide
    status: MultiAssetOrderStatus
    requested_base_amount: float
    filled_base_amount: float
    reason: str
    fill_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(
            self,
            "instrument_identifier",
            _text(self.instrument_identifier, field_name="instrument_identifier"),
        )
        if not isinstance(self.side, TradeSide):
            raise TypeError("side must be TradeSide")
        if not isinstance(self.status, MultiAssetOrderStatus):
            raise TypeError("status must be MultiAssetOrderStatus")
        for field_name in ("requested_base_amount", "filled_base_amount"):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name, minimum=0.0),
            )
        object.__setattr__(self, "reason", _text(self.reason, field_name="reason"))
        identifiers = tuple(
            _text(item, field_name="fill_identifiers") for item in self.fill_identifiers
        )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("fill_identifiers cannot contain duplicates")
        object.__setattr__(self, "fill_identifiers", identifiers)


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
    policy_version: str
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
            "policy_version",
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
            raise TypeError("order_results must contain MultiAssetOrderResult values")
        if not isinstance(self.fills, tuple) or not all(
            isinstance(item, MultiAssetPaperFill) for item in self.fills
        ):
            raise TypeError("fills must contain MultiAssetPaperFill values")
        if not isinstance(self.reconciliation, MultiAssetExecutionReconciliation):
            raise TypeError("reconciliation must be MultiAssetExecutionReconciliation")
        for field_name in ("profile_identifiers", "source_identifiers"):
            values = tuple(
                _text(item, field_name=field_name) for item in getattr(self, field_name)
            )
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
            object.__setattr__(self, field_name, values)
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("attempt must be an integer")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")


class SQLiteMultiAssetPaperExecutionStore:
    """Append-only, SHA-256-chained execution-attempt authority."""

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
            previous_hash = self._GENESIS_HASH if tail is None else str(tail["content_hash"])
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
        return None if row is None else batch_from_dict(json.loads(str(row["payload_json"])))

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
    """Apply governed paper fills and publish only reconciled canonical state."""

    def __init__(
        self,
        *,
        session_provider: InstrumentSessionProvider,
        quote_provider: MultiAssetQuoteProvider,
        store: SQLiteMultiAssetPaperExecutionStore,
        portfolio_store: SQLiteCanonicalPortfolioStore,
        universe_store: SQLiteCertifiedEligibleUniverseStore,
        policy: MultiAssetExecutionPolicy | None = None,
    ) -> None:
        if not isinstance(session_provider, InstrumentSessionProvider):
            raise TypeError("session_provider must implement InstrumentSessionProvider")
        if not isinstance(quote_provider, MultiAssetQuoteProvider):
            raise TypeError("quote_provider must implement MultiAssetQuoteProvider")
        if not isinstance(store, SQLiteMultiAssetPaperExecutionStore):
            raise TypeError("store must be SQLiteMultiAssetPaperExecutionStore")
        if not isinstance(portfolio_store, SQLiteCanonicalPortfolioStore):
            raise TypeError("portfolio_store must be SQLiteCanonicalPortfolioStore")
        if not isinstance(
            universe_store,
            SQLiteCertifiedEligibleUniverseStore,
        ):
            raise TypeError(
                "universe_store must be SQLiteCertifiedEligibleUniverseStore"
            )
        self.session_provider = session_provider
        self.quote_provider = quote_provider
        self.store = store
        self.portfolio_store = portfolio_store
        self.universe_store = universe_store
        self.eligibility_authority = CertifiedExecutionEligibilityAuthority(
            universe_store
        )
        self.policy = policy or MultiAssetExecutionPolicy()

    def execute(
        self,
        *,
        construction: PortfolioConstructionResult,
        decision_identifier: str,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        as_of: datetime,
    ) -> MultiAssetExecutionBatch:
        if not isinstance(construction, PortfolioConstructionResult):
            raise TypeError("construction must be PortfolioConstructionResult")
        decision = _text(decision_identifier, field_name="decision_identifier")
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be CanonicalPortfolioSnapshot")
        timestamp = _aware(as_of, field_name="as_of")
        if construction.as_of > timestamp or portfolio.as_of > timestamp:
            raise MultiAssetExecutionError(
                "construction and portfolio timestamps cannot follow execution time"
            )
        if construction.status is ConstructionStatus.BLOCKED:
            raise MultiAssetExecutionError("blocked construction cannot enter execution")

        normalized_profiles = {
            _text(key, field_name="profile symbol").upper(): value
            for key, value in profiles.items()
        }
        trade_symbols = tuple(item.symbol for item in construction.trades)
        if set(normalized_profiles) != set(trade_symbols):
            missing = sorted(set(trade_symbols) - set(normalized_profiles))
            extra = sorted(set(normalized_profiles) - set(trade_symbols))
            raise MultiAssetExecutionError(
                "execution profiles must exactly match construction trades: "
                f"missing={missing} extra={extra}"
            )
        instrument_ids: list[str] = []
        trades_by_symbol = {item.symbol: item for item in construction.trades}
        for symbol, profile in normalized_profiles.items():
            self._require_profile(symbol, profile, trade=trades_by_symbol[symbol])
            instrument_ids.append(profile.instrument_identifier)
        if len(instrument_ids) != len(set(instrument_ids)):
            raise MultiAssetExecutionError(
                "execution profiles contain duplicate instrument identifiers"
            )
        eligibility = None
        if construction.trades:
            try:
                eligibility = self.eligibility_authority.authorize(
                    construction=construction,
                    execution_timestamp=timestamp,
                    owned_instruments={
                        item.symbol: item.instrument_identifier
                        for item in portfolio.positions
                    },
                    execution_instruments={
                        symbol: profile.instrument_identifier
                        for symbol, profile in normalized_profiles.items()
                    },
                    approval_identifiers={
                        symbol: profile.approval_identifier
                        for symbol, profile in normalized_profiles.items()
                    },
                    approval_states={
                        symbol: profile.approval_state
                        for symbol, profile in normalized_profiles.items()
                    },
                    asset_classes={
                        symbol: profile.asset_class
                        for symbol, profile in normalized_profiles.items()
                    },
                )
            except ExecutionEligibilityError as error:
                raise MultiAssetExecutionError(str(error)) from error

        batch_identifier = f"multi-asset-execution:{construction.request_identifier}"
        previous = self.store.latest_batch(batch_identifier)
        if previous is not None:
            if previous.decision_identifier != decision:
                raise MultiAssetExecutionError(
                    "execution retry decision identifier does not match prior attempt"
                )
            if previous.status in {
                MultiAssetExecutionStatus.COMPLETED,
                MultiAssetExecutionStatus.NO_ACTION,
            }:
                return previous
            if portfolio.identifier != previous.ending_snapshot.identifier:
                raise MultiAssetExecutionError(
                    "retry must resume from the exact prior ending portfolio snapshot"
                )
        attempt = 1 if previous is None else previous.attempt + 1
        self.store.verify_integrity()
        self.portfolio_store.verify_integrity()
        self.store.append(
            event_identifier=f"event:{batch_identifier}:attempt:{attempt}:started",
            batch_identifier=batch_identifier,
            event_type=MultiAssetExecutionEventType.BATCH_STARTED,
            occurred_at=timestamp,
            payload={
                "decision_identifier": decision,
                "construction_identifier": construction.request_identifier,
                "beginning_snapshot_identifier": portfolio.identifier,
                "policy_version": self.policy.version,
                "profile_identifiers": [
                    self._profile_identifier(item)
                    for item in normalized_profiles.values()
                ],
                "execution_eligibility": (
                    None if eligibility is None else eligibility.to_dict()
                ),
            },
        )

        if not construction.trades:
            reconciliation = self._unchanged_reconciliation(portfolio)
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
                policy_version=self.policy.version,
                profile_identifiers=(),
                source_identifiers=(),
                attempt=attempt,
            )
            self._record(batch)
            return batch

        previous_results = (
            {} if previous is None else {item.symbol: item for item in previous.order_results}
        )
        cumulative_fills = [] if previous is None else list(previous.fills)
        cumulative_sources = [] if previous is None else list(previous.source_identifiers)
        if eligibility is not None:
            cumulative_sources.extend(
                (
                    eligibility.publication_identifier,
                    eligibility.publication_content_hash,
                    eligibility.certification_identifier,
                    eligibility.security_master_catalog_identifier,
                    eligibility.security_master_snapshot_identifier,
                )
            )
        order_results: dict[str, MultiAssetOrderResult] = dict(previous_results)
        fill_ids = {item.identifier for item in cumulative_fills}

        pending_profiles: list[MultiAssetInstrumentProfile] = []
        sessions: dict[str, InstrumentSession] = {}
        for trade in construction.trades:
            prior = previous_results.get(trade.symbol)
            if prior is not None and prior.status is MultiAssetOrderStatus.FILLED:
                continue
            profile = normalized_profiles[trade.symbol]
            model = (
                profile.trading_session_model
                or self.policy.session_model(profile.asset_class)
            )
            session = self.session_provider.session(
                profile,
                session_model=model,
                as_of=timestamp,
            )
            self._validate_session(session, profile=profile, model=model, as_of=timestamp)
            sessions[trade.symbol] = session
            cumulative_sources.append(session.source_identifier)
            if session.status is InstrumentSessionStatus.OPEN:
                pending_profiles.append(profile)

        quotes: Mapping[str, MultiAssetQuote]
        if pending_profiles:
            quotes = self.quote_provider.quotes(tuple(pending_profiles), as_of=timestamp)
            if not isinstance(quotes, Mapping):
                raise MultiAssetExecutionError("quote provider must return a symbol mapping")
            expected = {item.symbol for item in pending_profiles}
            if set(quotes) != expected:
                raise MultiAssetExecutionError(
                    "quote coverage must exactly match open execution profiles: "
                    f"missing={sorted(expected-set(quotes))} "
                    f"extra={sorted(set(quotes)-expected)}"
                )
        else:
            quotes = {}

        position_by_symbol = {item.symbol: item for item in portfolio.positions}
        updated_positions = dict(position_by_symbol)
        cash = portfolio.cash_amount
        new_fills: list[MultiAssetPaperFill] = []

        ordered_trades = tuple(
            sorted(
                construction.trades,
                key=lambda item: 0 if item.side is TradeSide.SELL else 1,
            )
        )
        for trade in ordered_trades:
            prior = previous_results.get(trade.symbol)
            if prior is not None and prior.status is MultiAssetOrderStatus.FILLED:
                continue
            profile = normalized_profiles[trade.symbol]
            requested_total = round(trade.trade_weight * portfolio.nav, 8)
            already_filled = 0.0 if prior is None else prior.filled_base_amount
            requested_remaining = round(max(0.0, requested_total - already_filled), 8)
            if requested_remaining <= self.policy.reconciliation_tolerance:
                order_results[trade.symbol] = MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.FILLED,
                    requested_base_amount=requested_total,
                    filled_base_amount=already_filled,
                    reason="cumulative paper fill satisfies requested construction",
                    fill_identifiers=() if prior is None else prior.fill_identifiers,
                )
                continue
            session = sessions[trade.symbol]
            if session.status is not InstrumentSessionStatus.OPEN:
                order_results[trade.symbol] = MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.HELD,
                    requested_base_amount=requested_total,
                    filled_base_amount=already_filled,
                    reason=f"{session.session_model.value} session is {session.status.value}",
                    fill_identifiers=() if prior is None else prior.fill_identifiers,
                )
                continue

            quote = quotes[trade.symbol]
            self._validate_quote(
                quote=quote,
                profile=profile,
                as_of=timestamp,
                base_currency=portfolio.base_currency,
            )
            cumulative_sources.extend(
                (
                    quote.quote_source_identifier,
                    quote.fx_source_identifier,
                    quote.quote_certification_identifier,
                    profile.approval_identifier,
                    profile.custody_settlement_identifier,
                    profile.execution_model_version,
                )
            )
            if quote.halted:
                order_results[trade.symbol] = MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.REJECTED,
                    requested_base_amount=requested_total,
                    filled_base_amount=already_filled,
                    reason="instrument is halted",
                    fill_identifiers=() if prior is None else prior.fill_identifiers,
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
                attempt=attempt,
                requested_total=requested_total,
                requested_remaining=requested_remaining,
                already_filled=already_filled,
                prior_fill_identifiers=() if prior is None else prior.fill_identifiers,
            )
            order_results[trade.symbol] = result
            if fill is not None:
                if fill.identifier in fill_ids:
                    raise MultiAssetExecutionError("execution generated a duplicate fill identifier")
                fill_ids.add(fill.identifier)
                new_fills.append(fill)
                cumulative_fills.append(fill)
                if next_position is None:
                    updated_positions.pop(trade.symbol, None)
                else:
                    updated_positions[trade.symbol] = next_position

        revalued_beginning_nav = self._revalued_beginning_nav(
            portfolio=portfolio,
            quotes=quotes,
        )
        commission_base = round(sum(item.commission_base for item in new_fills), 8)
        adverse_spread_base = round(
            sum(item.adverse_spread_base for item in new_fills),
            8,
        )
        mark_change = round(revalued_beginning_nav - portfolio.nav, 8)
        if new_fills:
            implementation_events = tuple(
                list(portfolio.implementation_events)
                + [self._implementation_event(item, occurred_at=timestamp) for item in new_fills]
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
                        portfolio.source_identifiers + tuple(cumulative_sources)
                    )
                ),
            )
        else:
            ending_snapshot = portfolio

        expected_ending_nav = round(
            portfolio.nav + mark_change - commission_base - adverse_spread_base,
            8,
        )
        difference = round(ending_snapshot.nav - expected_ending_nav, 8)
        reconciled = abs(difference) <= self.policy.reconciliation_tolerance
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
            raise MultiAssetExecutionError("multi-asset paper ledger did not reconcile")

        ordered_results = tuple(order_results[item.symbol] for item in construction.trades)
        statuses = {item.status for item in ordered_results}
        if statuses <= {MultiAssetOrderStatus.FILLED}:
            status = MultiAssetExecutionStatus.COMPLETED
        elif new_fills or any(item.filled_base_amount > 0 for item in ordered_results):
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
            order_results=ordered_results,
            fills=tuple(cumulative_fills),
            reconciliation=reconciliation,
            policy_version=self.policy.version,
            profile_identifiers=tuple(
                self._profile_identifier(normalized_profiles[symbol])
                for symbol in trade_symbols
            ),
            source_identifiers=tuple(dict.fromkeys(cumulative_sources)),
            attempt=attempt,
        )
        if new_fills:
            self.portfolio_store.append(ending_snapshot)
        self._record(batch)
        return batch

    def _require_profile(
        self,
        symbol: str,
        profile: MultiAssetInstrumentProfile,
        *,
        trade: TradeProposal,
    ) -> None:
        if not isinstance(profile, MultiAssetInstrumentProfile):
            raise TypeError("profiles must contain MultiAssetInstrumentProfile values")
        if profile.symbol != symbol:
            raise MultiAssetExecutionError("profile key must match profile symbol")
        if trade.symbol != symbol:
            raise MultiAssetExecutionError("profile trade must match profile symbol")
        if (
            trade.side is TradeSide.BUY
            and profile.asset_class in {CandidateAssetClass.CRYPTO, CandidateAssetClass.FX}
            and (not profile.unlevered or not profile.spot_only or profile.gross_leverage > 1.0 + _EPSILON)
        ):
            raise MultiAssetExecutionError(
                f"{profile.symbol} execution requires unlevered spot exposure"
            )
        derivatives = {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION, CandidateAssetClass.VOLATILITY}
        if trade.side is TradeSide.BUY and profile.asset_class in derivatives:
            required = (profile.contract_model_version, profile.margin_model_version, profile.lifecycle_model_version)
            if any(item is None for item in required):
                raise MultiAssetExecutionError(f"{profile.symbol} derivative execution profile is incomplete")
            if profile.asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.VOLATILITY} and profile.roll_model_version is None:
                raise MultiAssetExecutionError(f"{profile.symbol} requires a certified roll model")
            if not profile.defined_risk:
                raise MultiAssetExecutionError(f"{profile.symbol} requires defined paper risk")

    @staticmethod
    def _profile_identifier(profile: MultiAssetInstrumentProfile) -> str:
        return ":".join(
            (
                profile.instrument_identifier,
                profile.approval_identifier,
                profile.custody_settlement_identifier,
                profile.execution_model_version,
                profile.instrument_type,
                str(profile.contract_multiplier),
                profile.contract_model_version or "no-contract-model",
                profile.margin_model_version or "no-margin-model",
                profile.lifecycle_model_version or "no-lifecycle-model",
                profile.roll_model_version or "no-roll-model",
                (
                    "default-session"
                    if profile.trading_session_model is None
                    else profile.trading_session_model.value
                ),
            )
        )

    @staticmethod
    def _validate_session(
        session: InstrumentSession,
        *,
        profile: MultiAssetInstrumentProfile,
        model: TradingSessionModel,
        as_of: datetime,
    ) -> None:
        if session.instrument_identifier != profile.instrument_identifier:
            raise MultiAssetExecutionError("session instrument does not match profile")
        if session.venue != profile.venue:
            raise MultiAssetExecutionError("session venue does not match profile")
        if session.session_model is not model:
            raise MultiAssetExecutionError("session model does not match asset class")
        if session.as_of != as_of:
            raise MultiAssetExecutionError("session timestamp does not match execution")

    def _validate_quote(
        self,
        *,
        quote: MultiAssetQuote,
        profile: MultiAssetInstrumentProfile,
        as_of: datetime,
        base_currency: str,
    ) -> None:
        if quote.symbol != profile.symbol:
            raise MultiAssetExecutionError("quote symbol does not match profile")
        if quote.instrument_identifier != profile.instrument_identifier:
            raise MultiAssetExecutionError("quote instrument does not match profile")
        if quote.venue != profile.venue:
            raise MultiAssetExecutionError("quote venue does not match profile")
        if quote.price_currency != profile.price_currency:
            raise MultiAssetExecutionError("quote currency does not match profile")
        if quote.observed_at > as_of or quote.fx_observed_at > as_of:
            raise MultiAssetExecutionError(
                "quote or FX evidence is future-known at execution time"
            )
        maximum_age = timedelta(minutes=self.policy.maximum_quote_age_minutes)
        if as_of - quote.observed_at > maximum_age:
            raise MultiAssetExecutionError("quote is stale")
        if as_of - quote.fx_observed_at > maximum_age:
            raise MultiAssetExecutionError("FX conversion evidence is stale")
        if profile.price_currency == base_currency and abs(quote.fx_rate_to_base - 1.0) > _EPSILON:
            raise MultiAssetExecutionError(
                "base-currency quote must use an FX rate of 1.0"
            )

    def _fill_trade(
        self,
        *,
        trade: TradeProposal,
        profile: MultiAssetInstrumentProfile,
        quote: MultiAssetQuote,
        portfolio: CanonicalPortfolioSnapshot,
        current_position: CanonicalPortfolioPosition | None,
        available_cash: float,
        attempted_at: datetime,
        batch_identifier: str,
        attempt: int,
        requested_total: float,
        requested_remaining: float,
        already_filled: float,
        prior_fill_identifiers: tuple[str, ...],
    ) -> tuple[
        MultiAssetPaperFill | None,
        MultiAssetOrderResult,
        float,
        CanonicalPortfolioPosition | None,
    ]:
        if requested_remaining < self.policy.minimum_trade_base_amount:
            return (
                None,
                MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.REJECTED,
                    requested_base_amount=requested_total,
                    filled_base_amount=already_filled,
                    reason="remaining trade is below the minimum base amount",
                    fill_identifiers=prior_fill_identifiers,
                ),
                available_cash,
                current_position,
            )
        fill_price = quote.bid if trade.side is TradeSide.SELL else quote.ask
        mark_price = quote.last
        per_unit_base = fill_price * quote.fx_rate_to_base * profile.contract_multiplier
        base_cap = min(
            requested_remaining,
            quote.available_base_notional * self.policy.maximum_volume_participation,
        )
        if trade.side is TradeSide.SELL:
            if current_position is None:
                return (
                    None,
                    MultiAssetOrderResult(
                        symbol=trade.symbol,
                        instrument_identifier=profile.instrument_identifier,
                        side=trade.side,
                        status=MultiAssetOrderStatus.REJECTED,
                        requested_base_amount=requested_total,
                        filled_base_amount=already_filled,
                        reason="sell has no canonical owned position",
                        fill_identifiers=prior_fill_identifiers,
                    ),
                    available_cash,
                    current_position,
                )
            if current_position.instrument_identifier not in {
                None,
                profile.instrument_identifier,
            }:
                raise MultiAssetExecutionError(
                    "owned position identity does not match execution profile"
                )
            quantity_cap = current_position.quantity
        else:
            commission_rate = self.policy.commission_bps(profile.asset_class) / 10_000
            base_cap = min(base_cap, available_cash / (1.0 + commission_rate))
            quantity_cap = float("inf")
        raw_quantity = min(base_cap / per_unit_base, quantity_cap)
        quantity = (
            round(max(0.0, raw_quantity), 12)
            if self.policy.fractional_quantity(
                profile.asset_class, profile.instrument_type
            )
            else float(max(0, floor(raw_quantity)))
        )
        if quantity <= _EPSILON:
            return (
                None,
                MultiAssetOrderResult(
                    symbol=trade.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    side=trade.side,
                    status=MultiAssetOrderStatus.REJECTED,
                    requested_base_amount=requested_total,
                    filled_base_amount=already_filled,
                    reason="cash, ownership, or liquidity permits no paper fill",
                    fill_identifiers=prior_fill_identifiers,
                ),
                available_cash,
                current_position,
            )

        gross_local = round(quantity * fill_price * profile.contract_multiplier, 12)
        gross_base = round(gross_local * quote.fx_rate_to_base, 8)
        commission_local = round(
            gross_local * self.policy.commission_bps(profile.asset_class) / 10_000,
            12,
        )
        commission_base = round(commission_local * quote.fx_rate_to_base, 8)
        adverse_spread_base = round(
            quantity * abs(fill_price - mark_price) * quote.fx_rate_to_base * profile.contract_multiplier,
            8,
        )
        if trade.side is TradeSide.BUY:
            total_cash_use = gross_base + commission_base
            if total_cash_use > available_cash + self.policy.reconciliation_tolerance:
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
            next_cash = round(available_cash + gross_base - commission_base, 8)
            remaining = round(current_position.quantity - quantity, 12)
            next_position = (
                None
                if remaining <= _EPSILON
                else CanonicalPortfolioPosition(
                    symbol=current_position.symbol,
                    instrument_identifier=profile.instrument_identifier,
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
                    contract_multiplier=profile.contract_multiplier,
                )
            )

        fill_identifier = (
            f"fill:{batch_identifier}:attempt:{attempt}:{trade.symbol}:{trade.side.value}"
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
            settlement_currency=profile.settlement_currency,
            fx_rate_to_base=quote.fx_rate_to_base,
            gross_amount_local=gross_local,
            gross_amount_base=gross_base,
            commission_local=commission_local,
            commission_base=commission_base,
            adverse_spread_base=adverse_spread_base,
            quote_source_identifier=quote.quote_source_identifier,
            fx_source_identifier=quote.fx_source_identifier,
            quote_certification_identifier=quote.quote_certification_identifier,
            approval_identifier=profile.approval_identifier,
            custody_settlement_identifier=profile.custody_settlement_identifier,
            execution_model_version=profile.execution_model_version,
            contract_multiplier=profile.contract_multiplier,
        )
        cumulative_amount = round(already_filled + gross_base, 8)
        status = (
            MultiAssetOrderStatus.FILLED
            if cumulative_amount + self.policy.reconciliation_tolerance >= requested_total
            else MultiAssetOrderStatus.PARTIALLY_FILLED
        )
        result = MultiAssetOrderResult(
            symbol=trade.symbol,
            instrument_identifier=profile.instrument_identifier,
            side=trade.side,
            status=status,
            requested_base_amount=requested_total,
            filled_base_amount=cumulative_amount,
            reason=(
                "paper fill completed"
                if status is MultiAssetOrderStatus.FILLED
                else "paper fill was limited by cash, ownership, or liquidity"
            ),
            fill_identifiers=prior_fill_identifiers + (fill.identifier,),
        )
        return fill, result, next_cash, next_position

    @staticmethod
    def _buy_position(
        *,
        current: CanonicalPortfolioPosition | None,
        profile: MultiAssetInstrumentProfile,
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
            (old_local_cost + gross_local + commission_local) / (total_quantity * profile.contract_multiplier),
            12,
        )
        average_base = round(
            (old_base_cost + gross_base + commission_base) / (total_quantity * profile.contract_multiplier),
            12,
        )
        return CanonicalPortfolioPosition(
            symbol=profile.symbol,
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            asset_class=profile.asset_class.value,
            quantity=total_quantity,
            average_cost=average_local,
            average_cost_base=(
                None if profile.price_currency == "USD" else average_base
            ),
            mark_price=quote.last,
            updated_at=attempted_at,
            price_currency=profile.price_currency,
            settlement_currency=profile.settlement_currency,
            fx_rate_to_base=quote.fx_rate_to_base,
            fx_rate_observed_at=quote.fx_observed_at,
            fx_rate_source_identifier=quote.fx_source_identifier,
            contract_multiplier=profile.contract_multiplier,
        )

    @staticmethod
    def _implementation_event(
        fill: MultiAssetPaperFill,
        *,
        occurred_at: datetime,
    ) -> CanonicalImplementationEvent:
        return CanonicalImplementationEvent(
            identifier=fill.identifier,
            occurred_at=occurred_at,
            action=fill.side.value,
            symbol=fill.symbol,
            instrument_identifier=fill.instrument_identifier,
            venue=fill.venue,
            asset_class=fill.asset_class.value,
            quantity=fill.quantity,
            price=fill.fill_price_local,
            gross_amount=fill.gross_amount_local,
            cost_amount=fill.commission_local,
            rationale="Governed universal-market paper fill; no broker order submitted.",
            source_identifier=fill.quote_source_identifier,
            price_currency=fill.price_currency,
            settlement_currency=fill.settlement_currency,
            fx_rate_to_base=fill.fx_rate_to_base,
            fx_rate_source_identifier=fill.fx_source_identifier,
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
                else position.quantity * quote.last * quote.fx_rate_to_base * position.contract_multiplier
            )
        return round(value, 8)

    @staticmethod
    def _unchanged_reconciliation(
        portfolio: CanonicalPortfolioSnapshot,
    ) -> MultiAssetExecutionReconciliation:
        return MultiAssetExecutionReconciliation(
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

    def _record(self, batch: MultiAssetExecutionBatch) -> None:
        self.store.append(
            event_identifier=f"event:{batch.identifier}:attempt:{batch.attempt}:recorded",
            batch_identifier=batch.identifier,
            event_type=MultiAssetExecutionEventType.ATTEMPT_RECORDED,
            occurred_at=batch.attempted_at,
            payload=batch_to_dict(batch),
        )
        self.store.verify_integrity()


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
        "settlement_currency": value.settlement_currency,
        "fx_rate_to_base": value.fx_rate_to_base,
        "gross_amount_local": value.gross_amount_local,
        "gross_amount_base": value.gross_amount_base,
        "commission_local": value.commission_local,
        "commission_base": value.commission_base,
        "adverse_spread_base": value.adverse_spread_base,
        "quote_source_identifier": value.quote_source_identifier,
        "fx_source_identifier": value.fx_source_identifier,
        "quote_certification_identifier": value.quote_certification_identifier,
        "approval_identifier": value.approval_identifier,
        "custody_settlement_identifier": value.custody_settlement_identifier,
        "execution_model_version": value.execution_model_version,
        "contract_multiplier": value.contract_multiplier,
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
                "fill_identifiers": list(item.fill_identifiers),
            }
            for item in value.order_results
        ],
        "fills": [fill_to_dict(item) for item in value.fills],
        "reconciliation": {
            "beginning_nav": value.reconciliation.beginning_nav,
            "revalued_beginning_nav": value.reconciliation.revalued_beginning_nav,
            "mark_change_base": value.reconciliation.mark_change_base,
            "commission_base": value.reconciliation.commission_base,
            "adverse_spread_base": value.reconciliation.adverse_spread_base,
            "expected_ending_nav": value.reconciliation.expected_ending_nav,
            "ending_nav": value.reconciliation.ending_nav,
            "difference": value.reconciliation.difference,
            "reconciled": value.reconciliation.reconciled,
        },
        "policy_version": value.policy_version,
        "profile_identifiers": list(value.profile_identifiers),
        "source_identifiers": list(value.source_identifiers),
        "attempt": value.attempt,
        "schema_version": value.schema_version,
    }


def batch_from_dict(value: Mapping[str, Any]) -> MultiAssetExecutionBatch:
    reconciliation = value["reconciliation"]
    if not isinstance(reconciliation, Mapping):
        raise TypeError("reconciliation must encode an object")
    ending_snapshot = value["ending_snapshot"]
    if not isinstance(ending_snapshot, Mapping):
        raise TypeError("ending_snapshot must encode an object")
    return MultiAssetExecutionBatch(
        identifier=str(value["identifier"]),
        decision_identifier=str(value["decision_identifier"]),
        construction_identifier=str(value["construction_identifier"]),
        attempted_at=datetime.fromisoformat(str(value["attempted_at"])),
        status=MultiAssetExecutionStatus(str(value["status"])),
        beginning_snapshot_identifier=str(value["beginning_snapshot_identifier"]),
        ending_snapshot=snapshot_from_dict(ending_snapshot),
        order_results=tuple(
            MultiAssetOrderResult(
                symbol=str(item["symbol"]),
                instrument_identifier=str(item["instrument_identifier"]),
                side=TradeSide(str(item["side"])),
                status=MultiAssetOrderStatus(str(item["status"])),
                requested_base_amount=float(item["requested_base_amount"]),
                filled_base_amount=float(item["filled_base_amount"]),
                reason=str(item["reason"]),
                fill_identifiers=tuple(
                    str(identifier) for identifier in item.get("fill_identifiers", ())
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
                settlement_currency=str(item["settlement_currency"]),
                fx_rate_to_base=float(item["fx_rate_to_base"]),
                gross_amount_local=float(item["gross_amount_local"]),
                gross_amount_base=float(item["gross_amount_base"]),
                commission_local=float(item["commission_local"]),
                commission_base=float(item["commission_base"]),
                adverse_spread_base=float(item["adverse_spread_base"]),
                quote_source_identifier=str(item["quote_source_identifier"]),
                fx_source_identifier=str(item["fx_source_identifier"]),
                quote_certification_identifier=str(
                    item["quote_certification_identifier"]
                ),
                approval_identifier=str(item["approval_identifier"]),
                custody_settlement_identifier=str(
                    item["custody_settlement_identifier"]
                ),
                execution_model_version=str(item["execution_model_version"]),
                contract_multiplier=float(item.get("contract_multiplier", 1.0)),
            )
            for item in value.get("fills", ())
        ),
        reconciliation=MultiAssetExecutionReconciliation(
            beginning_nav=float(reconciliation["beginning_nav"]),
            revalued_beginning_nav=float(reconciliation["revalued_beginning_nav"]),
            mark_change_base=float(reconciliation["mark_change_base"]),
            commission_base=float(reconciliation["commission_base"]),
            adverse_spread_base=float(reconciliation["adverse_spread_base"]),
            expected_ending_nav=float(reconciliation["expected_ending_nav"]),
            ending_nav=float(reconciliation["ending_nav"]),
            difference=float(reconciliation["difference"]),
            reconciled=bool(reconciliation["reconciled"]),
        ),
        policy_version=str(value["policy_version"]),
        profile_identifiers=tuple(
            str(item) for item in value.get("profile_identifiers", ())
        ),
        source_identifiers=tuple(
            str(item) for item in value.get("source_identifiers", ())
        ),
        attempt=int(value["attempt"]),
        schema_version=str(
            value.get("schema_version", "multi-asset-paper-execution-batch.v1")
        ),
    )


__all__ = [
    "InstrumentSession",
    "InstrumentSessionProvider",
    "InstrumentSessionStatus",
    "MultiAssetExecutionBatch",
    "MultiAssetExecutionError",
    "MultiAssetExecutionEventType",
    "MultiAssetExecutionIntegrityError",
    "MultiAssetExecutionPolicy",
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
    "fill_to_dict",
]
