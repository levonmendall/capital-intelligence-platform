"""Governed Alpaca paper-order execution and broker-event reconciliation.

The module records every observed paper-order state and fill activity in an
append-only SHA-256 chain. It requires an active provider activation for the
paper-only Alpaca transport before submitting an order. It never accepts the live
brokerage domain and never grants real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Mapping

from governance.data_readiness_core import DataDomain
from governance.provider_activation import (
    ProviderActivation,
    ProviderActivationError,
    SQLiteProviderActivationStore,
)
from providers.alpaca_paper import AlpacaPaperProviderError
from providers.alpaca_paper_broker import (
    AlpacaPaperBrokerClient,
    AlpacaPaperOrderRequest,
)


ALPACA_PAPER_PROVIDER_IDENTIFIER = "alpaca-paper-broker"
_REQUIRED_DOMAINS = frozenset(
    {
        DataDomain.MARKET_PRICES,
        DataDomain.QUOTES_LIQUIDITY,
        DataDomain.EXECUTION_INPUTS,
    }
)
_FINAL_ORDER_STATUSES = frozenset(
    {"filled", "canceled", "expired", "rejected", "done_for_day"}
)


class AlpacaPaperBrokerError(RuntimeError):
    """Raised when the paper broker cannot submit or reconcile safely."""


class AlpacaPaperBrokerIntegrityError(AlpacaPaperBrokerError):
    """Raised when the append-only paper-broker ledger is invalid."""


class AlpacaPaperBrokerEventType(str, Enum):
    ORDER_SNAPSHOT = "order_snapshot"
    FILL_ACTIVITY = "fill_activity"
    RECONCILIATION = "reconciliation"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _timestamp(value: object, *, field_name: str, fallback: datetime | None = None) -> datetime:
    if value is None or (isinstance(value, str) and not value.strip()):
        if fallback is None:
            raise ValueError(f"{field_name} is unavailable")
        return _aware(fallback, field_name=field_name)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is invalid") from error
    return _aware(parsed, field_name=field_name)


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float = 0.0,
    default: float | None = None,
) -> float:
    if value is None or value == "":
        if default is None:
            raise ValueError(f"{field_name} is unavailable")
        return default
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{field_name} must be numeric") from error
    if not isfinite(normalized) or normalized < minimum:
        raise ValueError(f"{field_name} must be finite and at least {minimum}")
    return round(normalized, 12)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _payload_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def require_alpaca_paper_provider_activation(
    store: SQLiteProviderActivationStore,
    *,
    evaluated_at: datetime,
) -> ProviderActivation:
    """Require the exact active paper-only Alpaca provider approval."""

    if not isinstance(store, SQLiteProviderActivationStore):
        raise TypeError("store must be SQLiteProviderActivationStore")
    timestamp = _aware(evaluated_at, field_name="evaluated_at")
    store.verify_integrity()
    activation = store.active(
        ALPACA_PAPER_PROVIDER_IDENTIFIER,
        evaluated_at=timestamp,
    )
    if activation is None or not activation.enabled:
        raise ProviderActivationError("Alpaca paper broker activation is unavailable")
    missing = _REQUIRED_DOMAINS - set(activation.approved_domains)
    if missing:
        raise ProviderActivationError(
            "Alpaca paper activation is missing required domains: "
            + ", ".join(sorted(item.value for item in missing))
        )
    if not activation.paper_simulation_approved:
        raise ProviderActivationError("Alpaca activation does not approve paper simulation")
    return activation


@dataclass(frozen=True, slots=True)
class AlpacaPaperOrderSnapshot:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    requested_quantity: float
    requested_notional: float
    filled_quantity: float
    filled_average_price: float
    observed_at: datetime
    submitted_at: datetime
    request_id: str | None
    payload_sha256: str

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        observed_at: datetime,
        request_id: str | None = None,
    ) -> "AlpacaPaperOrderSnapshot":
        observed = _aware(observed_at, field_name="observed_at")
        order_id = _text(payload.get("id"), field_name="order id")
        client_order_id = _text(
            payload.get("client_order_id"),
            field_name="client_order_id",
        )
        submitted = _timestamp(
            payload.get("submitted_at") or payload.get("created_at"),
            field_name="submitted_at",
            fallback=observed,
        )
        status = _text(payload.get("status"), field_name="order status").lower()
        side = _text(payload.get("side"), field_name="order side").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("Alpaca order side must be buy or sell")
        return cls(
            broker_order_id=order_id,
            client_order_id=client_order_id,
            symbol=_text(payload.get("symbol"), field_name="symbol").upper(),
            side=side,
            status=status,
            requested_quantity=_number(
                payload.get("qty"),
                field_name="requested quantity",
                default=0.0,
            ),
            requested_notional=_number(
                payload.get("notional"),
                field_name="requested notional",
                default=0.0,
            ),
            filled_quantity=_number(
                payload.get("filled_qty"),
                field_name="filled quantity",
                default=0.0,
            ),
            filled_average_price=_number(
                payload.get("filled_avg_price"),
                field_name="filled average price",
                default=0.0,
            ),
            observed_at=observed,
            submitted_at=submitted,
            request_id=(
                None
                if request_id is None or not request_id.strip()
                else request_id.strip()
            ),
            payload_sha256=_payload_hash(payload),
        )

    @property
    def event_identifier(self) -> str:
        material = "|".join(
            (
                self.broker_order_id,
                self.status,
                format(self.filled_quantity, ".12g"),
                format(self.filled_average_price, ".12g"),
                self.payload_sha256,
            )
        )
        return "alpaca-order-event:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        payload["submitted_at"] = self.submitted_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class AlpacaPaperFillActivity:
    activity_identifier: str
    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    occurred_at: datetime
    payload_sha256: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AlpacaPaperFillActivity":
        activity_type = str(payload.get("activity_type", "FILL")).upper()
        if activity_type not in {"FILL", "TRD"}:
            raise ValueError("account activity is not a fill")
        side = _text(payload.get("side"), field_name="fill side").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("fill side must be buy or sell")
        activity_id = _text(
            payload.get("id") or payload.get("event_id") or payload.get("ref_id"),
            field_name="fill activity id",
        )
        order_id = _text(
            payload.get("order_id")
            or payload.get("orderid")
            or payload.get("orderId"),
            field_name="fill order id",
        )
        return cls(
            activity_identifier=activity_id,
            broker_order_id=order_id,
            symbol=_text(payload.get("symbol"), field_name="fill symbol").upper(),
            side=side,
            quantity=_number(payload.get("qty"), field_name="fill quantity", minimum=0.0),
            price=_number(payload.get("price"), field_name="fill price", minimum=0.0),
            occurred_at=_timestamp(
                payload.get("transaction_time")
                or payload.get("event_at")
                or payload.get("date"),
                field_name="fill timestamp",
            ),
            payload_sha256=_payload_hash(payload),
        )

    @property
    def event_identifier(self) -> str:
        return f"alpaca-fill-activity:{self.activity_identifier}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["occurred_at"] = self.occurred_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class AlpacaPaperBrokerReconciliation:
    identifier: str
    evaluated_at: datetime
    provider_activation_identifier: str
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    final_status: str
    final_filled_quantity: float
    final_average_price: float
    activity_identifiers: tuple[str, ...]
    activity_filled_quantity: float
    activity_average_price: float
    quantity_difference: float
    price_difference: float
    reconciled: bool
    blockers: tuple[str, ...]
    source_identifiers: tuple[str, ...]
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evaluated_at"] = self.evaluated_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class AlpacaPaperRoundTripReport:
    identifier: str
    evaluated_at: datetime
    symbol: str
    opening_quantity: float
    closing_quantity: float
    net_quantity_change: float
    buy_reconciliation: AlpacaPaperBrokerReconciliation
    sell_reconciliation: AlpacaPaperBrokerReconciliation
    reconciled: bool
    blockers: tuple[str, ...]
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "symbol": self.symbol,
            "opening_quantity": self.opening_quantity,
            "closing_quantity": self.closing_quantity,
            "net_quantity_change": self.net_quantity_change,
            "buy_reconciliation": self.buy_reconciliation.to_dict(),
            "sell_reconciliation": self.sell_reconciliation.to_dict(),
            "reconciled": self.reconciled,
            "blockers": list(self.blockers),
            "real_money_authorized": False,
        }


class SQLiteAlpacaPaperBrokerStore:
    """Append-only, hash-chained broker order and fill event authority."""

    _TABLE = "alpaca_paper_broker_events"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
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
                    broker_order_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS alpaca_paper_broker_order_lookup
                    ON {self._TABLE}(broker_order_id, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                    BEFORE UPDATE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'Alpaca paper broker history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                    BEFORE DELETE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'Alpaca paper broker history is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        broker_order_id: str,
        event_type: str,
        observed_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                broker_order_id,
                event_type,
                observed_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(
        self,
        *,
        event_identifier: str,
        broker_order_id: str,
        event_type: AlpacaPaperBrokerEventType,
        observed_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        identifier = _text(event_identifier, field_name="event_identifier")
        order_id = _text(broker_order_id, field_name="broker_order_id")
        if not isinstance(event_type, AlpacaPaperBrokerEventType):
            raise TypeError("event_type must be AlpacaPaperBrokerEventType")
        timestamp = _aware(observed_at, field_name="observed_at").isoformat()
        payload_json = _canonical_json(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json, event_type FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_json"]) != payload_json
                    or str(existing["event_type"]) != event_type.value
                ):
                    raise AlpacaPaperBrokerIntegrityError(
                        "broker event identifier already exists with different content"
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
                broker_order_id=order_id,
                event_type=event_type.value,
                observed_at=timestamp,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, broker_order_id, event_type,
                    observed_at, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    order_id,
                    event_type.value,
                    timestamp,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, 1):
            if int(row["sequence"]) != expected:
                raise AlpacaPaperBrokerIntegrityError("broker event sequence is not contiguous")
            if str(row["previous_hash"]) != previous_hash:
                raise AlpacaPaperBrokerIntegrityError("broker event previous hash is invalid")
            expected_hash = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                broker_order_id=str(row["broker_order_id"]),
                event_type=str(row["event_type"]),
                observed_at=str(row["observed_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise AlpacaPaperBrokerIntegrityError("broker event content hash is invalid")
            previous_hash = expected_hash
        return True


class AlpacaPaperBrokerExecutor:
    """Submit one paper order and reconcile Alpaca order and FILL evidence."""

    def __init__(
        self,
        *,
        client: AlpacaPaperBrokerClient,
        activation_store: SQLiteProviderActivationStore,
        event_store: SQLiteAlpacaPaperBrokerStore,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(client, AlpacaPaperBrokerClient):
            raise TypeError("client must be AlpacaPaperBrokerClient")
        if not isinstance(activation_store, SQLiteProviderActivationStore):
            raise TypeError("activation_store must be SQLiteProviderActivationStore")
        if not isinstance(event_store, SQLiteAlpacaPaperBrokerStore):
            raise TypeError("event_store must be SQLiteAlpacaPaperBrokerStore")
        self.client = client
        self.activation_store = activation_store
        self.event_store = event_store
        self.sleep = sleep

    @staticmethod
    def _position_quantity(payload: Mapping[str, Any] | None) -> float:
        if payload is None:
            return 0.0
        return _number(payload.get("qty"), field_name="position quantity", default=0.0)

    def _record_snapshot(self, snapshot: AlpacaPaperOrderSnapshot) -> None:
        self.event_store.append(
            event_identifier=snapshot.event_identifier,
            broker_order_id=snapshot.broker_order_id,
            event_type=AlpacaPaperBrokerEventType.ORDER_SNAPSHOT,
            observed_at=snapshot.observed_at,
            payload=snapshot.to_dict(),
        )

    def _record_fill(self, fill: AlpacaPaperFillActivity) -> None:
        self.event_store.append(
            event_identifier=fill.event_identifier,
            broker_order_id=fill.broker_order_id,
            event_type=AlpacaPaperBrokerEventType.FILL_ACTIVITY,
            observed_at=fill.occurred_at,
            payload=fill.to_dict(),
        )

    def submit_and_reconcile(
        self,
        request: AlpacaPaperOrderRequest,
        *,
        evaluated_at: datetime | None = None,
        order_timeout_seconds: int = 90,
        activity_timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
        quantity_tolerance: float = 0.00000001,
        price_tolerance: float = 0.01,
    ) -> AlpacaPaperBrokerReconciliation:
        now = evaluated_at or datetime.now(timezone.utc)
        now = _aware(now, field_name="evaluated_at")
        if isinstance(order_timeout_seconds, bool) or order_timeout_seconds < 1:
            raise ValueError("order_timeout_seconds must be positive")
        if isinstance(activity_timeout_seconds, bool) or activity_timeout_seconds < 1:
            raise ValueError("activity_timeout_seconds must be positive")
        if poll_interval_seconds <= 0.0:
            raise ValueError("poll_interval_seconds must be positive")
        activation = require_alpaca_paper_provider_activation(
            self.activation_store,
            evaluated_at=now,
        )
        account = self.client.account()
        if str(account.get("status", "")).upper() != "ACTIVE":
            raise AlpacaPaperBrokerError("Alpaca paper account is not ACTIVE")
        if account.get("trading_blocked") is True or account.get("account_blocked") is True:
            raise AlpacaPaperBrokerError("Alpaca paper account is blocked")

        submitted_payload, request_id = self.client.submit_order(request)
        submitted_at = datetime.now(timezone.utc)
        snapshot = AlpacaPaperOrderSnapshot.from_payload(
            submitted_payload,
            observed_at=submitted_at,
            request_id=request_id,
        )
        if snapshot.client_order_id != request.client_order_id:
            raise AlpacaPaperBrokerError("Alpaca returned a different client_order_id")
        if snapshot.symbol != request.symbol or snapshot.side != request.side:
            raise AlpacaPaperBrokerError("Alpaca returned a different symbol or side")
        self._record_snapshot(snapshot)

        deadline = time.monotonic() + order_timeout_seconds
        final_snapshot = snapshot
        while final_snapshot.status not in _FINAL_ORDER_STATUSES and time.monotonic() < deadline:
            self.sleep(poll_interval_seconds)
            payload = self.client.order(snapshot.broker_order_id)
            final_snapshot = AlpacaPaperOrderSnapshot.from_payload(
                payload,
                observed_at=datetime.now(timezone.utc),
            )
            self._record_snapshot(final_snapshot)
        if final_snapshot.status not in _FINAL_ORDER_STATUSES:
            self.client.cancel_order(final_snapshot.broker_order_id)
            self.sleep(poll_interval_seconds)
            payload = self.client.order(final_snapshot.broker_order_id)
            final_snapshot = AlpacaPaperOrderSnapshot.from_payload(
                payload,
                observed_at=datetime.now(timezone.utc),
            )
            self._record_snapshot(final_snapshot)

        activity_deadline = time.monotonic() + activity_timeout_seconds
        activities: tuple[AlpacaPaperFillActivity, ...] = ()
        after = (snapshot.submitted_at - timedelta(minutes=2)).isoformat()
        until = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        while time.monotonic() < activity_deadline:
            raw_activities = self.client.fill_activities(after=after, until=until)
            parsed: list[AlpacaPaperFillActivity] = []
            for raw in raw_activities:
                try:
                    item = AlpacaPaperFillActivity.from_payload(raw)
                except (TypeError, ValueError):
                    continue
                if item.broker_order_id == final_snapshot.broker_order_id:
                    parsed.append(item)
            activities = tuple(parsed)
            activity_quantity = round(sum(item.quantity for item in activities), 12)
            if (
                final_snapshot.filled_quantity <= quantity_tolerance
                or abs(activity_quantity - final_snapshot.filled_quantity)
                <= quantity_tolerance
            ):
                break
            self.sleep(poll_interval_seconds)

        activity_ids = tuple(item.activity_identifier for item in activities)
        activity_quantity = round(sum(item.quantity for item in activities), 12)
        activity_notional = round(
            sum(item.quantity * item.price for item in activities),
            12,
        )
        activity_average = (
            0.0
            if activity_quantity <= 0.0
            else round(activity_notional / activity_quantity, 12)
        )
        quantity_difference = round(
            activity_quantity - final_snapshot.filled_quantity,
            12,
        )
        price_difference = round(
            activity_average - final_snapshot.filled_average_price,
            12,
        )
        blockers: list[str] = []
        if final_snapshot.status != "filled":
            blockers.append(f"final order status is {final_snapshot.status}")
        if final_snapshot.filled_quantity <= 0.0:
            blockers.append("broker reported no filled quantity")
        if not activities:
            blockers.append("no Alpaca FILL activities matched the order")
        if len(activity_ids) != len(set(activity_ids)):
            blockers.append("duplicate Alpaca fill activity identifiers detected")
        if abs(quantity_difference) > quantity_tolerance:
            blockers.append("fill-activity quantity does not match final order quantity")
        if activities and abs(price_difference) > price_tolerance:
            blockers.append("fill-activity average price does not match final order price")
        if any(item.symbol != final_snapshot.symbol for item in activities):
            blockers.append("fill activity symbol mismatch")
        if any(item.side != final_snapshot.side for item in activities):
            blockers.append("fill activity side mismatch")

        for fill in activities:
            self._record_fill(fill)
        reconciliation = AlpacaPaperBrokerReconciliation(
            identifier=f"alpaca-paper-reconciliation:{final_snapshot.broker_order_id}",
            evaluated_at=datetime.now(timezone.utc),
            provider_activation_identifier=activation.identifier,
            broker_order_id=final_snapshot.broker_order_id,
            client_order_id=final_snapshot.client_order_id,
            symbol=final_snapshot.symbol,
            side=final_snapshot.side,
            final_status=final_snapshot.status,
            final_filled_quantity=final_snapshot.filled_quantity,
            final_average_price=final_snapshot.filled_average_price,
            activity_identifiers=activity_ids,
            activity_filled_quantity=activity_quantity,
            activity_average_price=activity_average,
            quantity_difference=quantity_difference,
            price_difference=price_difference,
            reconciled=not blockers,
            blockers=tuple(blockers),
            source_identifiers=tuple(
                dict.fromkeys(
                    (
                        activation.identifier,
                        activation.certification_identifier,
                        final_snapshot.event_identifier,
                        *(item.event_identifier for item in activities),
                        *(() if request_id is None else (f"alpaca-request:{request_id}",)),
                    )
                )
            ),
        )
        self.event_store.append(
            event_identifier=reconciliation.identifier,
            broker_order_id=final_snapshot.broker_order_id,
            event_type=AlpacaPaperBrokerEventType.RECONCILIATION,
            observed_at=reconciliation.evaluated_at,
            payload=reconciliation.to_dict(),
        )
        self.event_store.verify_integrity()
        return reconciliation

    def round_trip_smoke(
        self,
        *,
        symbol: str = "BTC/USD",
        notional: float = 1.0,
        evaluated_at: datetime | None = None,
    ) -> AlpacaPaperRoundTripReport:
        now = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        normalized_symbol = _text(symbol, field_name="symbol").upper()
        amount = _number(notional, field_name="notional", minimum=0.01)
        opening = self._position_quantity(self.client.position(normalized_symbol))
        run_material = f"{normalized_symbol}|{amount}|{now.isoformat()}"
        run_id = hashlib.sha256(run_material.encode("utf-8")).hexdigest()[:20]
        crypto = "/" in normalized_symbol
        buy = self.submit_and_reconcile(
            AlpacaPaperOrderRequest(
                client_order_id=f"cip-smoke-buy-{run_id}",
                symbol=normalized_symbol,
                side="buy",
                order_type="market",
                time_in_force="gtc" if crypto else "day",
                notional=amount,
            ),
            evaluated_at=now,
        )
        if not buy.reconciled:
            raise AlpacaPaperBrokerError(
                "paper smoke buy failed reconciliation: " + "; ".join(buy.blockers)
            )
        sell = self.submit_and_reconcile(
            AlpacaPaperOrderRequest(
                client_order_id=f"cip-smoke-sell-{run_id}",
                symbol=normalized_symbol,
                side="sell",
                order_type="market",
                time_in_force="gtc" if crypto else "day",
                quantity=buy.final_filled_quantity,
            ),
            evaluated_at=datetime.now(timezone.utc),
        )
        closing = self._position_quantity(self.client.position(normalized_symbol))
        net_change = round(closing - opening, 12)
        blockers: list[str] = []
        if not buy.reconciled:
            blockers.append("buy order did not reconcile")
        if not sell.reconciled:
            blockers.append("sell order did not reconcile")
        if abs(net_change) > 0.00000001:
            blockers.append("paper smoke did not return the broker position to its opening quantity")
        return AlpacaPaperRoundTripReport(
            identifier=f"alpaca-paper-round-trip:{run_id}",
            evaluated_at=datetime.now(timezone.utc),
            symbol=normalized_symbol,
            opening_quantity=opening,
            closing_quantity=closing,
            net_quantity_change=net_change,
            buy_reconciliation=buy,
            sell_reconciliation=sell,
            reconciled=not blockers,
            blockers=tuple(blockers),
        )


__all__ = [
    "ALPACA_PAPER_PROVIDER_IDENTIFIER",
    "AlpacaPaperBrokerError",
    "AlpacaPaperBrokerEventType",
    "AlpacaPaperBrokerExecutor",
    "AlpacaPaperBrokerIntegrityError",
    "AlpacaPaperBrokerReconciliation",
    "AlpacaPaperFillActivity",
    "AlpacaPaperOrderSnapshot",
    "AlpacaPaperRoundTripReport",
    "SQLiteAlpacaPaperBrokerStore",
    "require_alpaca_paper_provider_activation",
]
