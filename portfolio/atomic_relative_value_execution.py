"""Atomic paper implementation for governed relative-value expressions.

This module composes the existing ``MultiAssetPaperExecutionOrchestrator`` rather than
creating another execution authority.  All quotes, session checks, eligible-universe
checks, cost models, fill logic, and reconciliation therefore remain canonical.

The key additional invariant is atomicity: the complete multi-leg construction is
simulated in an isolated paper ledger.  The real canonical portfolio is appended only
when every leg is fully filled and the simulated ending portfolio reconciles.  A held,
rejected, or partial leg commits nothing and the next attempt starts from the unchanged
canonical portfolio.

No naked-short authority is added.  A short economic leg must either reduce an
already-owned implementation instrument or use a separately certified defined-risk
long implementation (for example an inverse/defined-risk instrument) that the
ordinary executor is already authorized to buy.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from opportunity.relative_value import (
    RelativeValueAdmissionPolicy,
    RelativeValueCandidateExpression,
    RelativeValueLegSide,
)
from portfolio.construction_api import PortfolioConstructionResult, TradeSide
from portfolio.multi_asset_execution import (
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetInstrumentProfile,
    MultiAssetOrderStatus,
    MultiAssetPaperExecutionOrchestrator,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore


class AtomicRelativeValueExecutionError(RuntimeError):
    """Raised when an atomic expression cannot be safely paper implemented."""


class AtomicRelativeValueExecutionStatus(str, Enum):
    COMPLETED = "completed"
    HELD = "held"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RelativeValuePaperLegImplementation:
    """Certified mapping from one economic leg to one executable paper instrument."""

    leg_instrument_identifier: str
    leg_symbol: str
    economic_side: RelativeValueLegSide
    execution_instrument_identifier: str
    execution_symbol: str
    execution_side: TradeSide
    implementation_certification_identifier: str
    evidence_identifiers: tuple[str, ...]
    defined_risk_short_implementation: bool = False
    schema_version: str = "relative-value-paper-leg-implementation.v1"

    def __post_init__(self) -> None:
        for name in (
            "leg_instrument_identifier",
            "leg_symbol",
            "execution_instrument_identifier",
            "execution_symbol",
            "implementation_certification_identifier",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if not isinstance(self.economic_side, RelativeValueLegSide):
            raise TypeError("economic_side must be RelativeValueLegSide")
        if not isinstance(self.execution_side, TradeSide):
            raise TypeError("execution_side must be TradeSide")
        if not self.evidence_identifiers:
            raise ValueError("relative-value implementation requires evidence lineage")
        if self.economic_side is RelativeValueLegSide.LONG:
            if self.execution_side is not TradeSide.BUY:
                raise ValueError("long economic legs must use BUY paper implementations")
            if self.defined_risk_short_implementation:
                raise ValueError("long economic legs cannot be short implementations")
        elif self.execution_side is TradeSide.BUY and not self.defined_risk_short_implementation:
            raise ValueError(
                "a short economic leg bought as an implementation must be explicitly "
                "certified as defined-risk/inverse short exposure"
            )


@dataclass(frozen=True, slots=True)
class AtomicRelativeValueExecutionAttempt:
    identifier: str
    expression_identifier: str
    decision_identifier: str
    construction_identifier: str
    attempted_at: datetime
    status: AtomicRelativeValueExecutionStatus
    beginning_snapshot_identifier: str
    ending_snapshot_identifier: str
    underlying_batch_identifier: str | None
    implementation_identifiers: tuple[str, ...]
    reasons: tuple[str, ...]
    attempt: int
    canonical_state_changed: bool
    investment_authority: bool = False
    real_money_authorized: bool = False
    schema_version: str = "atomic-relative-value-paper-execution-attempt.v1"

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "expression_identifier",
            "decision_identifier",
            "construction_identifier",
            "beginning_snapshot_identifier",
            "ending_snapshot_identifier",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.attempted_at.tzinfo is None or self.attempted_at.utcoffset() is None:
            raise ValueError("attempted_at must be timezone-aware")
        if not isinstance(self.status, AtomicRelativeValueExecutionStatus):
            raise TypeError("status must be AtomicRelativeValueExecutionStatus")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        if self.investment_authority or self.real_money_authorized:
            raise ValueError("atomic paper execution cannot authorize capital or real money")
        if self.status is AtomicRelativeValueExecutionStatus.COMPLETED:
            if not self.canonical_state_changed:
                raise ValueError("completed atomic execution must publish one canonical state")
            if self.ending_snapshot_identifier == self.beginning_snapshot_identifier:
                raise ValueError("completed atomic execution must change snapshot identity")
        elif self.canonical_state_changed:
            raise ValueError("non-completed atomic execution cannot change canonical state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "expression_identifier": self.expression_identifier,
            "decision_identifier": self.decision_identifier,
            "construction_identifier": self.construction_identifier,
            "attempted_at": self.attempted_at.isoformat(),
            "status": self.status.value,
            "beginning_snapshot_identifier": self.beginning_snapshot_identifier,
            "ending_snapshot_identifier": self.ending_snapshot_identifier,
            "underlying_batch_identifier": self.underlying_batch_identifier,
            "implementation_identifiers": list(self.implementation_identifiers),
            "reasons": list(self.reasons),
            "attempt": self.attempt,
            "canonical_state_changed": self.canonical_state_changed,
            "investment_authority": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AtomicRelativeValueExecutionAttempt":
        return cls(
            identifier=str(payload["identifier"]),
            expression_identifier=str(payload["expression_identifier"]),
            decision_identifier=str(payload["decision_identifier"]),
            construction_identifier=str(payload["construction_identifier"]),
            attempted_at=datetime.fromisoformat(str(payload["attempted_at"])),
            status=AtomicRelativeValueExecutionStatus(str(payload["status"])),
            beginning_snapshot_identifier=str(payload["beginning_snapshot_identifier"]),
            ending_snapshot_identifier=str(payload["ending_snapshot_identifier"]),
            underlying_batch_identifier=(
                None
                if payload.get("underlying_batch_identifier") is None
                else str(payload["underlying_batch_identifier"])
            ),
            implementation_identifiers=tuple(
                str(item) for item in payload.get("implementation_identifiers", ())
            ),
            reasons=tuple(str(item) for item in payload.get("reasons", ())),
            attempt=int(payload["attempt"]),
            canonical_state_changed=bool(payload["canonical_state_changed"]),
        )


class SQLiteAtomicRelativeValueExecutionStore:
    """Append-only, hash-chained atomic-expression attempt history."""

    _TABLE = "atomic_relative_value_execution_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    execution_identifier TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS atomic_relative_value_execution_lookup
                    ON {self._TABLE}(execution_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'atomic relative-value history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'atomic relative-value history is append-only'); END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _canonical(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        execution_identifier: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                execution_identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, attempt: AtomicRelativeValueExecutionAttempt) -> int:
        if not isinstance(attempt, AtomicRelativeValueExecutionAttempt):
            raise TypeError("attempt must be AtomicRelativeValueExecutionAttempt")
        payload_json = self._canonical(attempt.to_dict())
        event_identifier = f"event:{attempt.identifier}:attempt:{attempt.attempt}"
        occurred_at = attempt.attempted_at.astimezone(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} WHERE event_identifier = ?",
                (event_identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise AtomicRelativeValueExecutionError(
                        "atomic execution event already exists with different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=event_identifier,
                execution_identifier=attempt.identifier,
                occurred_at=occurred_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE}(sequence, event_identifier, execution_identifier, occurred_at, payload_json, previous_hash, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    event_identifier,
                    attempt.identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def latest(self, execution_identifier: str) -> AtomicRelativeValueExecutionAttempt | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE execution_identifier = ? ORDER BY sequence DESC LIMIT 1",
                (str(execution_identifier),),
            ).fetchone()
        return None if row is None else AtomicRelativeValueExecutionAttempt.from_dict(
            json.loads(str(row["payload_json"]))
        )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise AtomicRelativeValueExecutionError("atomic execution sequence is not contiguous")
            if str(row["previous_hash"]) != previous_hash:
                raise AtomicRelativeValueExecutionError("atomic execution hash chain is broken")
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                execution_identifier=str(row["execution_identifier"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise AtomicRelativeValueExecutionError("atomic execution content hash is invalid")
            previous_hash = expected_hash
        return True


class AtomicRelativeValuePaperExecutionOrchestrator:
    """Commit an all-or-nothing relative-value paper expression."""

    version = "atomic-relative-value-paper-execution.v1"

    def __init__(
        self,
        *,
        base_executor: MultiAssetPaperExecutionOrchestrator,
        store: SQLiteAtomicRelativeValueExecutionStore,
        weight_tolerance: float = 0.000001,
    ) -> None:
        if not isinstance(base_executor, MultiAssetPaperExecutionOrchestrator):
            raise TypeError("base_executor must be MultiAssetPaperExecutionOrchestrator")
        if not isinstance(store, SQLiteAtomicRelativeValueExecutionStore):
            raise TypeError("store must be SQLiteAtomicRelativeValueExecutionStore")
        self.base_executor = base_executor
        self.store = store
        self.weight_tolerance = float(weight_tolerance)
        if not 0.0 < self.weight_tolerance <= 0.001:
            raise ValueError("weight_tolerance must be positive and no more than 10 bps")

    def execute(
        self,
        *,
        expression: RelativeValueCandidateExpression,
        construction: PortfolioConstructionResult,
        decision_identifier: str,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        implementations: tuple[RelativeValuePaperLegImplementation, ...],
        as_of: datetime,
    ) -> AtomicRelativeValueExecutionAttempt:
        admission = RelativeValueAdmissionPolicy().assess(expression)
        if not admission.paper_execution_eligible:
            raise AtomicRelativeValueExecutionError(
                "relative-value expression is not paper-execution eligible: "
                + "; ".join(admission.reasons)
            )
        if expression.as_of > as_of:
            raise AtomicRelativeValueExecutionError("relative-value expression is future-known")
        if construction.as_of > as_of or portfolio.as_of > as_of:
            raise AtomicRelativeValueExecutionError("construction/portfolio cannot be future-known")
        if not construction.trades:
            raise AtomicRelativeValueExecutionError("relative-value execution requires construction trades")

        execution_identifier = (
            f"atomic-rv:{expression.identifier}:{construction.request_identifier}"
        )
        previous = self.store.latest(execution_identifier)
        if previous is not None and previous.status is AtomicRelativeValueExecutionStatus.COMPLETED:
            return previous
        if previous is not None and portfolio.identifier != previous.beginning_snapshot_identifier:
            raise AtomicRelativeValueExecutionError(
                "atomic retry must start from the exact unchanged beginning portfolio"
            )
        attempt_number = 1 if previous is None else previous.attempt + 1

        normalized_profiles = {str(key).upper(): value for key, value in profiles.items()}
        implementation_by_leg = {
            item.leg_instrument_identifier: item for item in implementations
        }
        if len(implementation_by_leg) != len(implementations):
            raise AtomicRelativeValueExecutionError("relative-value leg implementations must be unique")
        expected_leg_ids = {item.instrument_identifier for item in expression.legs}
        if set(implementation_by_leg) != expected_leg_ids:
            raise AtomicRelativeValueExecutionError(
                "atomic implementations must exactly cover relative-value legs"
            )
        implementation_by_symbol = {
            item.execution_symbol.upper(): item for item in implementations
        }
        if len(implementation_by_symbol) != len(implementations):
            raise AtomicRelativeValueExecutionError(
                "atomic implementations must use unique execution symbols"
            )
        trade_by_symbol = {item.symbol.upper(): item for item in construction.trades}
        if set(trade_by_symbol) != set(implementation_by_symbol):
            raise AtomicRelativeValueExecutionError(
                "construction trades must exactly match atomic implementation symbols"
            )
        if set(normalized_profiles) != set(trade_by_symbol):
            raise AtomicRelativeValueExecutionError(
                "execution profiles must exactly match atomic construction symbols"
            )

        # Preserve the expression's relative gross weights when construction scales the
        # complete structure up or down. This prevents an execution bridge from turning
        # a relative-value thesis into a different directional portfolio.
        expression_gross = sum(float(item.gross_weight) for item in expression.legs)
        construction_gross = sum(float(item.trade_weight) for item in construction.trades)
        if expression_gross <= 0.0 or construction_gross <= 0.0:
            raise AtomicRelativeValueExecutionError("relative-value gross exposure must be positive")
        owned = {item.symbol.upper(): item for item in portfolio.positions}
        for leg in expression.legs:
            implementation = implementation_by_leg[leg.instrument_identifier]
            trade = trade_by_symbol[implementation.execution_symbol.upper()]
            profile = normalized_profiles[implementation.execution_symbol.upper()]
            if implementation.leg_symbol.upper() != leg.symbol.upper():
                raise AtomicRelativeValueExecutionError("implementation leg symbol does not match expression")
            if implementation.economic_side is not leg.side:
                raise AtomicRelativeValueExecutionError("implementation economic side does not match expression")
            if trade.side is not implementation.execution_side:
                raise AtomicRelativeValueExecutionError("construction side does not match certified implementation")
            if profile.instrument_identifier != implementation.execution_instrument_identifier:
                raise AtomicRelativeValueExecutionError("profile instrument does not match certified implementation")
            expected_ratio = float(leg.gross_weight) / expression_gross
            actual_ratio = float(trade.trade_weight) / construction_gross
            if abs(expected_ratio - actual_ratio) > self.weight_tolerance:
                raise AtomicRelativeValueExecutionError(
                    f"{leg.symbol} construction distorts relative-value leg proportions"
                )
            if leg.side is RelativeValueLegSide.SHORT:
                if implementation.execution_side is TradeSide.SELL:
                    position = owned.get(implementation.execution_symbol.upper())
                    if position is None:
                        raise AtomicRelativeValueExecutionError(
                            "short economic leg cannot open a naked paper short; SELL is allowed only against an existing canonical position"
                        )
                else:
                    if not implementation.defined_risk_short_implementation:
                        raise AtomicRelativeValueExecutionError(
                            "short economic BUY implementation lacks defined-risk/inverse certification"
                        )
                    if not bool(profile.defined_risk):
                        raise AtomicRelativeValueExecutionError(
                            "short economic BUY implementation profile is not defined-risk"
                        )

        latest_before = self.base_executor.portfolio_store.latest(portfolio.portfolio_code)
        if latest_before is None or latest_before.identifier != portfolio.identifier:
            raise AtomicRelativeValueExecutionError(
                "canonical portfolio advanced before atomic simulation began"
            )

        with tempfile.TemporaryDirectory(prefix="capital-intelligence-atomic-rv-") as raw_tmp:
            tmp = Path(raw_tmp)
            temp_portfolio_store = SQLiteCanonicalPortfolioStore(tmp / "portfolio.db")
            temp_portfolio_store.append(portfolio)
            temp_execution_store = SQLiteMultiAssetPaperExecutionStore(tmp / "execution.db")
            simulator = MultiAssetPaperExecutionOrchestrator(
                session_provider=self.base_executor.session_provider,
                quote_provider=self.base_executor.quote_provider,
                store=temp_execution_store,
                portfolio_store=temp_portfolio_store,
                universe_store=self.base_executor.universe_store,
                policy=self.base_executor.policy,
            )
            try:
                batch = simulator.execute(
                    construction=construction,
                    decision_identifier=decision_identifier,
                    portfolio=portfolio,
                    profiles=normalized_profiles,
                    as_of=as_of,
                )
            except MultiAssetExecutionError as error:
                attempt = AtomicRelativeValueExecutionAttempt(
                    identifier=execution_identifier,
                    expression_identifier=expression.identifier,
                    decision_identifier=decision_identifier,
                    construction_identifier=construction.request_identifier,
                    attempted_at=as_of,
                    status=AtomicRelativeValueExecutionStatus.FAILED,
                    beginning_snapshot_identifier=portfolio.identifier,
                    ending_snapshot_identifier=portfolio.identifier,
                    underlying_batch_identifier=None,
                    implementation_identifiers=tuple(
                        item.implementation_certification_identifier
                        for item in implementations
                    ),
                    reasons=(str(error), "real canonical portfolio was not changed"),
                    attempt=attempt_number,
                    canonical_state_changed=False,
                )
                self.store.append(attempt)
                return attempt

            all_filled = bool(batch.order_results) and all(
                item.status is MultiAssetOrderStatus.FILLED
                and abs(item.requested_base_amount - item.filled_base_amount)
                <= self.base_executor.policy.reconciliation_tolerance
                for item in batch.order_results
            )
            fully_reconciled = bool(
                batch.reconciliation.reconciled
                and batch.reconciliation.accounting_reconciled
            )
            if (
                batch.status is not MultiAssetExecutionStatus.COMPLETED
                or not all_filled
                or not fully_reconciled
            ):
                reasons = tuple(
                    dict.fromkeys(
                        (
                            f"underlying batch status={batch.status.value}",
                            *(
                                f"{item.symbol}: {item.status.value}: {item.reason}"
                                for item in batch.order_results
                                if item.status is not MultiAssetOrderStatus.FILLED
                                or abs(item.requested_base_amount - item.filled_base_amount)
                                > self.base_executor.policy.reconciliation_tolerance
                            ),
                            "atomic requirement not satisfied; provisional fills were discarded",
                            "real canonical portfolio was not changed",
                        )
                    )
                )
                status = (
                    AtomicRelativeValueExecutionStatus.HELD
                    if batch.status is MultiAssetExecutionStatus.HELD
                    else AtomicRelativeValueExecutionStatus.FAILED
                )
                attempt = AtomicRelativeValueExecutionAttempt(
                    identifier=execution_identifier,
                    expression_identifier=expression.identifier,
                    decision_identifier=decision_identifier,
                    construction_identifier=construction.request_identifier,
                    attempted_at=as_of,
                    status=status,
                    beginning_snapshot_identifier=portfolio.identifier,
                    ending_snapshot_identifier=portfolio.identifier,
                    underlying_batch_identifier=batch.identifier,
                    implementation_identifiers=tuple(
                        item.implementation_certification_identifier
                        for item in implementations
                    ),
                    reasons=reasons,
                    attempt=attempt_number,
                    canonical_state_changed=False,
                )
                self.store.append(attempt)
                return attempt

            latest_after = self.base_executor.portfolio_store.latest(portfolio.portfolio_code)
            if latest_after is None or latest_after.identifier != portfolio.identifier:
                raise AtomicRelativeValueExecutionError(
                    "canonical portfolio advanced during atomic simulation; refusing commit"
                )

            committed_identifier = (
                f"{portfolio.identifier}:atomic-rv:{hashlib.sha256(execution_identifier.encode('utf-8')).hexdigest()[:16]}"
            )
            committed_snapshot = replace(
                batch.ending_snapshot,
                identifier=committed_identifier,
                source_identifiers=tuple(
                    dict.fromkeys(
                        (
                            *batch.ending_snapshot.source_identifiers,
                            expression.identifier,
                            construction.request_identifier,
                            self.version,
                            *(item.implementation_certification_identifier for item in implementations),
                            *expression.evidence_identifiers,
                            *expression.model_versions,
                        )
                    )
                ),
            )
            self.base_executor.portfolio_store.append(committed_snapshot)

        attempt = AtomicRelativeValueExecutionAttempt(
            identifier=execution_identifier,
            expression_identifier=expression.identifier,
            decision_identifier=decision_identifier,
            construction_identifier=construction.request_identifier,
            attempted_at=as_of,
            status=AtomicRelativeValueExecutionStatus.COMPLETED,
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot_identifier=committed_snapshot.identifier,
            underlying_batch_identifier=batch.identifier,
            implementation_identifiers=tuple(
                item.implementation_certification_identifier for item in implementations
            ),
            reasons=(
                "all relative-value legs were fully filled in the isolated canonical paper executor",
                "the complete simulated portfolio reconciled before one canonical snapshot was committed",
                "no naked-short authority was introduced",
            ),
            attempt=attempt_number,
            canonical_state_changed=True,
        )
        self.store.append(attempt)
        return attempt


__all__ = [
    "AtomicRelativeValueExecutionAttempt",
    "AtomicRelativeValueExecutionError",
    "AtomicRelativeValueExecutionStatus",
    "AtomicRelativeValuePaperExecutionOrchestrator",
    "RelativeValuePaperLegImplementation",
    "SQLiteAtomicRelativeValueExecutionStore",
]
