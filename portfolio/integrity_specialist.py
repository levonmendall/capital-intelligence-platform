"""Non-voting portfolio valuation and execution-integrity specialist.

This operational control function does not analyze investment attractiveness,
vote in the Investment Committee, alter a CIO decision, or authorize real money.
It independently certifies the accounting and valuation consequences of a paper
implementation before a new canonical portfolio snapshot may be published.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

from portfolio.state import CanonicalPortfolioSnapshot


PORTFOLIO_INTEGRITY_SPECIALIST_ROLE = (
    "portfolio_valuation_execution_integrity_specialist"
)
PORTFOLIO_INTEGRITY_SPECIALIST_NAME = (
    "Portfolio Valuation & Execution Integrity Specialist"
)


class PortfolioIntegrityDisposition(str, Enum):
    CERTIFIED = "certified"
    HELD = "held"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class PortfolioIntegrityCertification:
    identifier: str
    execution_identifier: str
    completed_at: datetime
    beginning_snapshot_identifier: str
    ending_snapshot_identifier: str
    disposition: PortfolioIntegrityDisposition
    checks: tuple[str, ...]
    blocks: tuple[str, ...]
    reconciliation_difference: float
    specialist_version: str = "portfolio-integrity-specialist.v1"
    schema_version: str = "portfolio-integrity-certification.v1"

    @property
    def certified(self) -> bool:
        return self.disposition is PortfolioIntegrityDisposition.CERTIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "execution_identifier": self.execution_identifier,
            "role": PORTFOLIO_INTEGRITY_SPECIALIST_ROLE,
            "role_name": PORTFOLIO_INTEGRITY_SPECIALIST_NAME,
            "completed_at": self.completed_at.isoformat(),
            "beginning_snapshot_identifier": self.beginning_snapshot_identifier,
            "ending_snapshot_identifier": self.ending_snapshot_identifier,
            "disposition": self.disposition.value,
            "checks": list(self.checks),
            "blocks": list(self.blocks),
            "reconciliation_difference": self.reconciliation_difference,
            "specialist_version": self.specialist_version,
            "schema_version": self.schema_version,
            "investment_decision_authorized": False,
            "real_money_authorized": False,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PortfolioIntegrityCertification":
        return cls(
            identifier=str(value["identifier"]),
            execution_identifier=str(value["execution_identifier"]),
            completed_at=datetime.fromisoformat(str(value["completed_at"])),
            beginning_snapshot_identifier=str(value["beginning_snapshot_identifier"]),
            ending_snapshot_identifier=str(value["ending_snapshot_identifier"]),
            disposition=PortfolioIntegrityDisposition(str(value["disposition"])),
            checks=tuple(str(item) for item in value.get("checks", ())),
            blocks=tuple(str(item) for item in value.get("blocks", ())),
            reconciliation_difference=float(value["reconciliation_difference"]),
            specialist_version=str(value.get("specialist_version", "portfolio-integrity-specialist.v1")),
            schema_version=str(value.get("schema_version", "portfolio-integrity-certification.v1")),
        )


class PortfolioValuationExecutionIntegritySpecialist:
    """Certify cash, shares, cost basis, marks, NAV, and reconciliation."""

    def __init__(
        self,
        *,
        version: str = "portfolio-integrity-specialist.v1",
        cash_tolerance: float = 0.01,
        quantity_tolerance: float = 0.00000001,
    ) -> None:
        if not isinstance(version, str) or not version.strip():
            raise ValueError("version must be a non-empty string")
        if cash_tolerance < 0.0 or quantity_tolerance < 0.0:
            raise ValueError("specialist tolerances cannot be negative")
        self.version = version.strip()
        self.cash_tolerance = float(cash_tolerance)
        self.quantity_tolerance = float(quantity_tolerance)

    def review_execution(
        self,
        *,
        execution_identifier: str,
        beginning: CanonicalPortfolioSnapshot,
        ending: CanonicalPortfolioSnapshot,
        fills: Sequence[object],
        reconciliation: object,
        completed_at: datetime,
        attempt: int,
    ) -> PortfolioIntegrityCertification:
        if not isinstance(execution_identifier, str) or not execution_identifier.strip():
            raise ValueError("execution_identifier must be a non-empty string")
        if not isinstance(beginning, CanonicalPortfolioSnapshot):
            raise TypeError("beginning must be a CanonicalPortfolioSnapshot")
        if not isinstance(ending, CanonicalPortfolioSnapshot):
            raise TypeError("ending must be a CanonicalPortfolioSnapshot")
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ValueError("attempt must be a positive integer")

        checks: list[str] = []
        blocks: list[str] = []

        if beginning.portfolio_code != ending.portfolio_code:
            blocks.append("portfolio identity changed during implementation")
        else:
            checks.append("portfolio identity preserved")
        if beginning.base_currency != ending.base_currency:
            blocks.append("portfolio base currency changed during implementation")
        else:
            checks.append("base currency preserved")
        if abs(beginning.starting_capital - ending.starting_capital) > self.cash_tolerance:
            blocks.append("starting capital changed during implementation")
        else:
            checks.append("starting capital preserved")
        if ending.as_of > completed_at:
            blocks.append("ending portfolio snapshot is future-dated")
        else:
            checks.append("portfolio timestamp is point-in-time valid")

        reconciled = getattr(reconciliation, "reconciled", None)
        difference = float(getattr(reconciliation, "difference", float("inf")))
        if reconciled is not True or not isfinite(difference):
            blocks.append("execution reconciliation is not certified")
        elif abs(difference) > self.cash_tolerance:
            blocks.append(
                f"execution reconciliation difference {difference:.8f} exceeds tolerance"
            )
        else:
            checks.append("execution NAV reconciliation passed")

        begin_quantity = {item.symbol: item.quantity for item in beginning.positions}
        end_quantity = {item.symbol: item.quantity for item in ending.positions}
        expected_quantity = dict(begin_quantity)
        expected_cash = beginning.cash_amount
        fill_identifiers: set[str] = set()
        touched_symbols: set[str] = set()
        for fill in fills:
            identifier = str(getattr(fill, "identifier", "")).strip()
            symbol = str(getattr(fill, "symbol", "")).strip().upper()
            side = getattr(getattr(fill, "side", None), "value", getattr(fill, "side", ""))
            quantity = float(getattr(fill, "quantity", 0.0))
            gross = float(getattr(fill, "gross_amount_base", 0.0))
            commission = float(getattr(fill, "commission_base", 0.0))
            if not identifier or not symbol or quantity <= 0.0:
                blocks.append("execution contains an incomplete paper fill")
                continue
            if identifier in fill_identifiers:
                blocks.append(f"duplicate fill identifier {identifier}")
            fill_identifiers.add(identifier)
            touched_symbols.add(symbol)
            if side == "buy":
                expected_quantity[symbol] = expected_quantity.get(symbol, 0.0) + quantity
                expected_cash -= gross + commission
            elif side == "sell":
                expected_quantity[symbol] = expected_quantity.get(symbol, 0.0) - quantity
                expected_cash += gross - commission
            else:
                blocks.append(f"fill {identifier} has an unsupported side")

        for symbol in sorted(set(expected_quantity) | set(end_quantity)):
            expected = max(0.0, expected_quantity.get(symbol, 0.0))
            actual = end_quantity.get(symbol, 0.0)
            if abs(expected - actual) > self.quantity_tolerance:
                blocks.append(
                    f"{symbol} quantity does not reconcile: expected {expected:.12f}, "
                    f"observed {actual:.12f}"
                )
        if not any("quantity does not reconcile" in item for item in blocks):
            checks.append("share quantities reconcile to paper fills")

        if abs(expected_cash - ending.cash_amount) > self.cash_tolerance:
            blocks.append("cash does not reconcile to gross fills and transaction costs")
        else:
            checks.append("cash reconciles to gross fills and transaction costs")

        ending_event_ids = {item.identifier for item in ending.implementation_events}
        missing_events = sorted(fill_identifiers - ending_event_ids)
        if missing_events:
            blocks.append(
                "paper fills are missing from canonical implementation history: "
                + ", ".join(missing_events)
            )
        else:
            checks.append("paper fills are preserved in implementation history")

        position_by_symbol = {item.symbol: item for item in ending.positions}
        for symbol in sorted(touched_symbols):
            position = position_by_symbol.get(symbol)
            if position is None:
                continue
            values = (
                position.quantity,
                position.average_cost,
                position.mark_price,
                position.cost_basis,
                position.market_value,
                position.unrealized_gain,
            )
            if not all(isfinite(float(value)) for value in values):
                blocks.append(f"{symbol} valuation contains a non-finite value")
            if position.quantity <= 0.0 or position.average_cost < 0.0 or position.mark_price <= 0.0:
                blocks.append(f"{symbol} position economics are invalid")
            if position.updated_at > completed_at:
                blocks.append(f"{symbol} mark is future-dated")
        if not any(
            "valuation" in item or "position economics" in item or "mark is future" in item
            for item in blocks
        ):
            checks.append("cost basis, marks, market value, and unrealized gain/loss are valid")

        if not fills and beginning.identifier != ending.identifier:
            blocks.append("a no-fill execution changed canonical portfolio identity")

        disposition = (
            PortfolioIntegrityDisposition.CERTIFIED
            if not blocks
            else PortfolioIntegrityDisposition.HELD
        )
        identifier = (
            f"portfolio-integrity:{ending.portfolio_code}:"
            f"{execution_identifier}:attempt:{attempt}"
        )
        return PortfolioIntegrityCertification(
            identifier=identifier,
            execution_identifier=execution_identifier.strip(),
            completed_at=completed_at,
            beginning_snapshot_identifier=beginning.identifier,
            ending_snapshot_identifier=ending.identifier,
            disposition=disposition,
            checks=tuple(checks),
            blocks=tuple(blocks),
            reconciliation_difference=difference,
            specialist_version=self.version,
        )


class SQLitePortfolioIntegrityCertificationStore:
    """Append-only, tamper-evident specialist certification history."""

    _TABLE = "portfolio_integrity_certifications"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
            path = data_dir / "portfolio_integrity.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    certification_identifier TEXT NOT NULL UNIQUE,
                    execution_identifier TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS portfolio_integrity_execution_lookup
                ON {self._TABLE}(execution_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'portfolio integrity history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'portfolio integrity history is append-only'); END;
                """
            )

    @staticmethod
    def _canonical(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        execution_identifier: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                identifier,
                execution_identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, certification: PortfolioIntegrityCertification) -> int:
        payload_json = self._canonical(certification.to_dict())
        occurred_at = certification.completed_at.isoformat()
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE certification_identifier = ?",
                (certification.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != payload_json:
                    raise ValueError(
                        "integrity certification identifier already exists with different content"
                    )
                return int(existing[0])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous_hash = self._GENESIS_HASH if tail is None else str(tail[1])
            content_hash = self._hash(
                sequence=sequence,
                identifier=certification.identifier,
                execution_identifier=certification.execution_identifier,
                occurred_at=occurred_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} (sequence, certification_identifier, "
                "execution_identifier, occurred_at, payload_json, previous_hash, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    certification.identifier,
                    certification.execution_identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def latest(self, execution_identifier: str) -> PortfolioIntegrityCertification | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE execution_identifier = ? ORDER BY sequence DESC LIMIT 1",
                (execution_identifier,),
            ).fetchone()
        return None if row is None else PortfolioIntegrityCertification.from_dict(json.loads(str(row[0])))

    def verify_integrity(self) -> bool:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            sequence, identifier, execution_identifier, occurred_at, payload_json, stored_previous, content_hash = row
            if int(sequence) != expected or str(stored_previous) != previous_hash:
                raise ValueError("portfolio integrity certification chain is invalid")
            expected_hash = self._hash(
                sequence=expected,
                identifier=str(identifier),
                execution_identifier=str(execution_identifier),
                occurred_at=str(occurred_at),
                payload_json=str(payload_json),
                previous_hash=previous_hash,
            )
            if str(content_hash) != expected_hash:
                raise ValueError("portfolio integrity certification content hash is invalid")
            previous_hash = expected_hash
        return True


__all__ = [
    "PORTFOLIO_INTEGRITY_SPECIALIST_NAME",
    "PORTFOLIO_INTEGRITY_SPECIALIST_ROLE",
    "PortfolioIntegrityCertification",
    "PortfolioIntegrityDisposition",
    "PortfolioValuationExecutionIntegritySpecialist",
    "SQLitePortfolioIntegrityCertificationStore",
]
