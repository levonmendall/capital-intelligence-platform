"""Canonical append-only portfolio-state authority.

The store owns cash, positions, valuation snapshots, and implementation history
for every active paper portfolio.  Legacy mandate/trading databases may be read
once by the migration command, but are never an active state source.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping


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


def _number(value: object, *, field_name: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return round(normalized, 12)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class CanonicalPortfolioPosition:
    symbol: str
    quantity: float
    average_cost: float
    mark_price: float
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(self, "quantity", _number(self.quantity, field_name="quantity"))
        object.__setattr__(self, "average_cost", _number(self.average_cost, field_name="average_cost"))
        object.__setattr__(self, "mark_price", _number(self.mark_price, field_name="mark_price"))
        _aware(self.updated_at, field_name="updated_at")
        if self.quantity <= 0 or self.mark_price <= 0:
            raise ValueError("portfolio positions require positive quantity and mark_price")

    @property
    def cost_basis(self) -> float:
        return round(self.quantity * self.average_cost, 8)

    @property
    def market_value(self) -> float:
        return round(self.quantity * self.mark_price, 8)

    @property
    def unrealized_gain(self) -> float:
        return round(self.market_value - self.cost_basis, 8)


@dataclass(frozen=True, slots=True)
class CanonicalImplementationEvent:
    identifier: str
    occurred_at: datetime
    action: str
    symbol: str | None
    quantity: float
    price: float
    gross_amount: float
    cost_amount: float = 0.0
    rationale: str = ""
    source_identifier: str = "canonical-portfolio"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.occurred_at, field_name="occurred_at")
        object.__setattr__(self, "action", _text(self.action, field_name="action").upper())
        if self.symbol is not None:
            object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        for field_name in ("quantity", "price", "gross_amount", "cost_amount"):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "rationale", str(self.rationale).strip())
        object.__setattr__(self, "source_identifier", _text(self.source_identifier, field_name="source_identifier"))


@dataclass(frozen=True, slots=True)
class CanonicalPortfolioSnapshot:
    identifier: str
    portfolio_code: str
    display_name: str
    constraint_profile: str
    as_of: datetime
    starting_capital: float
    cash_amount: float
    positions: tuple[CanonicalPortfolioPosition, ...]
    implementation_events: tuple[CanonicalImplementationEvent, ...] = ()
    source_identifiers: tuple[str, ...] = ()
    schema_version: str = "canonical-portfolio-state.v1"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "display_name", "constraint_profile", "schema_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "portfolio_code", _text(self.portfolio_code, field_name="portfolio_code").upper())
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "starting_capital", _number(self.starting_capital, field_name="starting_capital"))
        object.__setattr__(self, "cash_amount", _number(self.cash_amount, field_name="cash_amount"))
        if self.starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        if not isinstance(self.positions, tuple) or not all(isinstance(item, CanonicalPortfolioPosition) for item in self.positions):
            raise TypeError("positions must contain CanonicalPortfolioPosition values")
        if not isinstance(self.implementation_events, tuple) or not all(isinstance(item, CanonicalImplementationEvent) for item in self.implementation_events):
            raise TypeError("implementation_events must contain CanonicalImplementationEvent values")
        symbols = tuple(item.symbol for item in self.positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("portfolio position symbols must be unique")
        event_ids = tuple(item.identifier for item in self.implementation_events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("implementation event identifiers must be unique")
        sources = tuple(_text(item, field_name="source_identifiers") for item in self.source_identifiers)
        if len(sources) != len(set(sources)):
            raise ValueError("source_identifiers cannot contain duplicates")
        object.__setattr__(self, "source_identifiers", sources)

    @property
    def holdings_value(self) -> float:
        return round(sum(item.market_value for item in self.positions), 8)

    @property
    def nav(self) -> float:
        return round(self.cash_amount + self.holdings_value, 8)

    @property
    def total_return(self) -> float:
        return 0.0 if self.starting_capital == 0 else round((self.nav / self.starting_capital) - 1.0, 12)


class CanonicalPortfolioIntegrityError(RuntimeError):
    """Raised when the append-only portfolio event chain is invalid."""


class SQLiteCanonicalPortfolioStore:
    """Persist complete portfolio snapshots in one tamper-evident event chain."""

    _TABLE = "canonical_portfolio_events"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    portfolio_code TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_canonical_portfolio_code
                    ON {self._TABLE}(portfolio_code, sequence);
                CREATE TRIGGER IF NOT EXISTS canonical_portfolio_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'canonical portfolio events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS canonical_portfolio_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'canonical portfolio events are append-only'); END;
            """)

    @staticmethod
    def _hash(*, sequence: int, event_identifier: str, portfolio_code: str, occurred_at: str, payload_json: str, previous_hash: str) -> str:
        value = "|".join((str(sequence), event_identifier, portfolio_code, occurred_at, payload_json, previous_hash))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def append(self, snapshot: CanonicalPortfolioSnapshot) -> int:
        payload_json = _canonical_json(snapshot_to_dict(snapshot))
        with self._connect() as connection:
            prior = connection.execute(
                f"SELECT sequence, previous_hash, content_hash, payload_json FROM {self._TABLE} WHERE event_identifier = ?",
                (snapshot.identifier,),
            ).fetchone()
            if prior is not None:
                if prior["payload_json"] != payload_json:
                    raise ValueError("portfolio snapshot identifier already exists with different content")
                return int(prior["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = "0" * 64 if tail is None else str(tail["content_hash"])
            occurred_at = snapshot.as_of.astimezone(timezone.utc).isoformat()
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=snapshot.identifier,
                portfolio_code=snapshot.portfolio_code,
                occurred_at=occurred_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""INSERT INTO {self._TABLE} (
                    sequence, event_identifier, portfolio_code, occurred_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sequence, snapshot.identifier, snapshot.portfolio_code, occurred_at, payload_json, previous_hash, content_hash),
            )
        return sequence

    def verify_integrity(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {self._TABLE} ORDER BY sequence").fetchall()
        expected_previous = "0" * 64
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise CanonicalPortfolioIntegrityError("portfolio event sequence is not contiguous")
            if str(row["previous_hash"]) != expected_previous:
                raise CanonicalPortfolioIntegrityError("portfolio event previous-hash link is invalid")
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                portfolio_code=str(row["portfolio_code"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=expected_previous,
            )
            if str(row["content_hash"]) != expected_hash:
                raise CanonicalPortfolioIntegrityError("portfolio event content hash is invalid")
            expected_previous = expected_hash

    def latest(self, portfolio_code: str) -> CanonicalPortfolioSnapshot | None:
        normalized = _text(portfolio_code, field_name="portfolio_code").upper()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE portfolio_code = ? ORDER BY sequence DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        return None if row is None else snapshot_from_dict(json.loads(row["payload_json"]))

    def list_latest(self) -> tuple[CanonicalPortfolioSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(f"""
                SELECT events.payload_json
                FROM {self._TABLE} AS events
                INNER JOIN (
                    SELECT portfolio_code, MAX(sequence) AS sequence
                    FROM {self._TABLE}
                    GROUP BY portfolio_code
                ) AS latest
                ON events.portfolio_code = latest.portfolio_code
                AND events.sequence = latest.sequence
                ORDER BY events.portfolio_code
            """).fetchall()
        return tuple(snapshot_from_dict(json.loads(row["payload_json"])) for row in rows)

    def history(self, portfolio_code: str, *, limit: int = 250) -> tuple[CanonicalPortfolioSnapshot, ...]:
        normalized = _text(portfolio_code, field_name="portfolio_code").upper()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE portfolio_code = ? ORDER BY sequence DESC LIMIT ?",
                (normalized, limit),
            ).fetchall()
        return tuple(snapshot_from_dict(json.loads(row["payload_json"])) for row in rows)


def position_to_dict(value: CanonicalPortfolioPosition) -> dict[str, Any]:
    return {
        "symbol": value.symbol,
        "quantity": value.quantity,
        "average_cost": value.average_cost,
        "mark_price": value.mark_price,
        "updated_at": value.updated_at.isoformat(),
    }


def event_to_dict(value: CanonicalImplementationEvent) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "occurred_at": value.occurred_at.isoformat(),
        "action": value.action,
        "symbol": value.symbol,
        "quantity": value.quantity,
        "price": value.price,
        "gross_amount": value.gross_amount,
        "cost_amount": value.cost_amount,
        "rationale": value.rationale,
        "source_identifier": value.source_identifier,
    }


def snapshot_to_dict(value: CanonicalPortfolioSnapshot) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "portfolio_code": value.portfolio_code,
        "display_name": value.display_name,
        "constraint_profile": value.constraint_profile,
        "as_of": value.as_of.isoformat(),
        "starting_capital": value.starting_capital,
        "cash_amount": value.cash_amount,
        "positions": [position_to_dict(item) for item in value.positions],
        "implementation_events": [event_to_dict(item) for item in value.implementation_events],
        "source_identifiers": list(value.source_identifiers),
        "schema_version": value.schema_version,
    }


def snapshot_from_dict(value: Mapping[str, Any]) -> CanonicalPortfolioSnapshot:
    try:
        return CanonicalPortfolioSnapshot(
            identifier=str(value["identifier"]),
            portfolio_code=str(value["portfolio_code"]),
            display_name=str(value["display_name"]),
            constraint_profile=str(value["constraint_profile"]),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            starting_capital=float(value["starting_capital"]),
            cash_amount=float(value["cash_amount"]),
            positions=tuple(
                CanonicalPortfolioPosition(
                    symbol=str(item["symbol"]),
                    quantity=float(item["quantity"]),
                    average_cost=float(item.get("average_cost", item["mark_price"])),
                    mark_price=float(item["mark_price"]),
                    updated_at=datetime.fromisoformat(str(item["updated_at"])),
                )
                for item in value.get("positions", ())
            ),
            implementation_events=tuple(
                CanonicalImplementationEvent(
                    identifier=str(item["identifier"]),
                    occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
                    action=str(item["action"]),
                    symbol=None if item.get("symbol") is None else str(item["symbol"]),
                    quantity=float(item.get("quantity", 0.0)),
                    price=float(item.get("price", 0.0)),
                    gross_amount=float(item.get("gross_amount", 0.0)),
                    cost_amount=float(item.get("cost_amount", 0.0)),
                    rationale=str(item.get("rationale", "")),
                    source_identifier=str(item.get("source_identifier", "canonical-portfolio")),
                )
                for item in value.get("implementation_events", ())
            ),
            source_identifiers=tuple(str(item) for item in value.get("source_identifiers", ())),
            schema_version=str(value.get("schema_version", "canonical-portfolio-state.v1")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid canonical portfolio snapshot payload") from error


def snapshot_summary(value: CanonicalPortfolioSnapshot) -> dict[str, Any]:
    return {
        "code": value.portfolio_code,
        "name": value.display_name,
        "risk": value.constraint_profile,
        "constraint_profile": value.constraint_profile,
        "starting_capital": value.starting_capital,
        "cash": value.cash_amount,
        "nav": value.nav,
        "as_of": value.as_of.isoformat(),
        "snapshot_identifier": value.identifier,
    }


def snapshot_details(value: CanonicalPortfolioSnapshot, *, history: Iterable[CanonicalPortfolioSnapshot] = ()) -> dict[str, Any]:
    payload = snapshot_summary(value)
    payload["total_return"] = value.total_return
    payload["return_pct"] = value.total_return
    payload["holdings"] = [
        {
            "mandate_code": value.portfolio_code,
            "portfolio_code": value.portfolio_code,
            "symbol": item.symbol,
            "quantity": item.quantity,
            "average_cost": item.average_cost,
            "current_price": item.mark_price,
            "cost_basis": item.cost_basis,
            "market_value": item.market_value,
            "unrealized_gain": item.unrealized_gain,
            "updated_at": item.updated_at.isoformat(),
        }
        for item in value.positions
    ]
    payload["trades"] = [
        {
            "id": item.identifier,
            "created_at": item.occurred_at.isoformat(),
            "mandate_code": value.portfolio_code,
            "portfolio_code": value.portfolio_code,
            "side": item.action,
            "symbol": item.symbol,
            "quantity": item.quantity,
            "price": item.price,
            "gross_amount": item.gross_amount,
            "cost_amount": item.cost_amount,
            "rationale": item.rationale,
            "source_identifier": item.source_identifier,
        }
        for item in sorted(value.implementation_events, key=lambda event: event.occurred_at, reverse=True)
    ]
    payload["snapshots"] = [
        {
            "id": item.identifier,
            "created_at": item.as_of.isoformat(),
            "mandate_code": item.portfolio_code,
            "portfolio_code": item.portfolio_code,
            "cash": item.cash_amount,
            "holdings_value": item.holdings_value,
            "nav": item.nav,
        }
        for item in history
    ]
    return payload


__all__ = [
    "CanonicalImplementationEvent",
    "CanonicalPortfolioIntegrityError",
    "CanonicalPortfolioPosition",
    "CanonicalPortfolioSnapshot",
    "SQLiteCanonicalPortfolioStore",
    "event_to_dict",
    "position_to_dict",
    "snapshot_details",
    "snapshot_from_dict",
    "snapshot_summary",
    "snapshot_to_dict",
]
