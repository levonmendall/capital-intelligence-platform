"""Crash-safe atomic paper implementation for governed relative-value expressions.

This composes the existing multi-asset paper executor. It adds no new quote, session,
eligibility, cost, fill, reconciliation, shorting, construction, or investment
authority. The complete expression is simulated in isolated SQLite stores. Only a
fully filled and reconciled simulation may enter a two-phase PREPARED -> canonical
portfolio append -> COMPLETED commit.

If a process dies after portfolio append but before COMPLETED, a retry recognizes the
deterministic committed snapshot and finalizes the same attempt without duplicating
portfolio state. Any held, rejected, partial, stale, or ambiguous state fails closed.
Naked paper shorts remain unsupported.
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
from portfolio.construction_models import PortfolioConstructionResult, TradeSide
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetOrderStatus,
    MultiAssetPaperExecutionOrchestrator,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore


class AtomicRelativeValueExecutionError(RuntimeError):
    pass


class AtomicRelativeValueExecutionStatus(str, Enum):
    PREPARED = "prepared"
    COMPLETED = "completed"
    HELD = "held"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RelativeValuePaperLegImplementation:
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
            raise ValueError("implementation requires evidence lineage")
        if self.economic_side is RelativeValueLegSide.LONG:
            if self.execution_side is not TradeSide.BUY:
                raise ValueError("long economic legs must use BUY implementations")
            if self.defined_risk_short_implementation:
                raise ValueError("long legs cannot be marked short implementations")
        elif self.execution_side is TradeSide.BUY and not self.defined_risk_short_implementation:
            raise ValueError(
                "short economic BUY implementation must be explicitly certified as defined-risk/inverse"
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
    schema_version: str = "atomic-relative-value-paper-execution-attempt.v2"

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
            raise ValueError("paper execution cannot authorize capital or real money")
        if self.status is AtomicRelativeValueExecutionStatus.COMPLETED:
            if not self.canonical_state_changed:
                raise ValueError("completed attempt must publish canonical state")
            if self.ending_snapshot_identifier == self.beginning_snapshot_identifier:
                raise ValueError("completed attempt must change snapshot identity")
        elif self.canonical_state_changed:
            raise ValueError("only COMPLETED may report canonical state change")

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
            underlying_batch_identifier=(None if payload.get("underlying_batch_identifier") is None else str(payload["underlying_batch_identifier"])),
            implementation_identifiers=tuple(str(item) for item in payload.get("implementation_identifiers", ())),
            reasons=tuple(str(item) for item in payload.get("reasons", ())),
            attempt=int(payload["attempt"]),
            canonical_state_changed=bool(payload["canonical_state_changed"]),
        )


class SQLiteAtomicRelativeValueExecutionStore:
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
                CREATE INDEX IF NOT EXISTS atomic_rv_execution_lookup
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
    def _content_hash(
        cls,
        sequence: int,
        event_identifier: str,
        execution_identifier: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    event_identifier,
                    execution_identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def append(self, attempt: AtomicRelativeValueExecutionAttempt) -> int:
        payload_json = self._canonical(attempt.to_dict())
        event_identifier = (
            f"event:{attempt.identifier}:attempt:{attempt.attempt}:{attempt.status.value}"
        )
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
                        "atomic event identifier already exists with different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._content_hash(
                sequence,
                event_identifier,
                attempt.identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE}(sequence,event_identifier,execution_identifier,occurred_at,payload_json,previous_hash,content_hash) VALUES (?,?,?,?,?,?,?)",
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
                f"SELECT payload_json FROM {self._TABLE} WHERE execution_identifier=? ORDER BY sequence DESC LIMIT 1",
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
        for expected, row in enumerate(rows, 1):
            if int(row["sequence"]) != expected or str(row["previous_hash"]) != previous_hash:
                raise AtomicRelativeValueExecutionError("atomic execution hash chain is invalid")
            expected_hash = self._content_hash(
                expected,
                str(row["event_identifier"]),
                str(row["execution_identifier"]),
                str(row["occurred_at"]),
                str(row["payload_json"]),
                previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise AtomicRelativeValueExecutionError("atomic execution content hash is invalid")
            previous_hash = expected_hash
        return True


class AtomicRelativeValuePaperExecutionOrchestrator:
    version = "atomic-relative-value-paper-execution.v2-two-phase"

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
            raise ValueError("weight_tolerance must be positive and <= 10 bps")

    @staticmethod
    def _execution_identifier(
        expression: RelativeValueCandidateExpression,
        construction: PortfolioConstructionResult,
    ) -> str:
        return f"atomic-rv:{expression.identifier}:{construction.request_identifier}"

    @staticmethod
    def _committed_identifier(beginning_identifier: str, execution_identifier: str) -> str:
        digest = hashlib.sha256(execution_identifier.encode("utf-8")).hexdigest()[:16]
        return f"{beginning_identifier}:atomic-rv:{digest}"

    def _recover_or_validate_retry(
        self,
        *,
        previous: AtomicRelativeValueExecutionAttempt | None,
        latest_real: CanonicalPortfolioSnapshot | None,
        portfolio: CanonicalPortfolioSnapshot,
        as_of: datetime,
    ) -> AtomicRelativeValueExecutionAttempt | None:
        if previous is None:
            return None
        if previous.status is AtomicRelativeValueExecutionStatus.COMPLETED:
            return previous
        if previous.status is AtomicRelativeValueExecutionStatus.PREPARED:
            if latest_real is not None and latest_real.identifier == previous.ending_snapshot_identifier:
                completed = replace(
                    previous,
                    attempted_at=as_of,
                    status=AtomicRelativeValueExecutionStatus.COMPLETED,
                    reasons=tuple(
                        dict.fromkeys(
                            (
                                *previous.reasons,
                                "recovered completed canonical commit after PREPARED state",
                            )
                        )
                    ),
                    canonical_state_changed=True,
                )
                self.store.append(completed)
                return completed
            if latest_real is None or latest_real.identifier != previous.beginning_snapshot_identifier:
                raise AtomicRelativeValueExecutionError(
                    "ambiguous canonical portfolio after PREPARED atomic execution; refusing retry"
                )
            if portfolio.identifier != previous.beginning_snapshot_identifier:
                raise AtomicRelativeValueExecutionError(
                    "PREPARED retry must use the unchanged beginning portfolio"
                )
            return None
        if portfolio.identifier != previous.beginning_snapshot_identifier:
            raise AtomicRelativeValueExecutionError(
                "atomic retry must start from the exact unchanged beginning portfolio"
            )
        return None

    def _validate_structure(
        self,
        *,
        expression: RelativeValueCandidateExpression,
        construction: PortfolioConstructionResult,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        implementations: tuple[RelativeValuePaperLegImplementation, ...],
    ) -> dict[str, MultiAssetInstrumentProfile]:
        normalized_profiles = {str(key).upper(): value for key, value in profiles.items()}
        implementation_by_leg = {
            item.leg_instrument_identifier: item for item in implementations
        }
        if len(implementation_by_leg) != len(implementations):
            raise AtomicRelativeValueExecutionError("leg implementations must be unique")
        if set(implementation_by_leg) != {
            item.instrument_identifier for item in expression.legs
        }:
            raise AtomicRelativeValueExecutionError(
                "implementations must exactly cover expression legs"
            )
        implementation_by_symbol = {
            item.execution_symbol.upper(): item for item in implementations
        }
        if len(implementation_by_symbol) != len(implementations):
            raise AtomicRelativeValueExecutionError(
                "implementation execution symbols must be unique"
            )
        trade_by_symbol = {
            item.symbol.upper(): item for item in construction.trades
        }
        if set(trade_by_symbol) != set(implementation_by_symbol) or set(normalized_profiles) != set(trade_by_symbol):
            raise AtomicRelativeValueExecutionError(
                "construction trades, implementations, and profiles must exactly match"
            )
        expression_gross = sum(float(item.gross_weight) for item in expression.legs)
        construction_gross = sum(float(item.trade_weight) for item in construction.trades)
        if expression_gross <= 0.0 or construction_gross <= 0.0:
            raise AtomicRelativeValueExecutionError(
                "relative-value gross exposure must be positive"
            )
        owned = {item.symbol.upper(): item for item in portfolio.positions}
        for leg in expression.legs:
            implementation = implementation_by_leg[leg.instrument_identifier]
            trade = trade_by_symbol[implementation.execution_symbol.upper()]
            profile = normalized_profiles[implementation.execution_symbol.upper()]
            if implementation.leg_symbol.upper() != leg.symbol.upper() or implementation.economic_side is not leg.side:
                raise AtomicRelativeValueExecutionError(
                    "implementation does not match expression leg"
                )
            if trade.side is not implementation.execution_side or profile.instrument_identifier != implementation.execution_instrument_identifier:
                raise AtomicRelativeValueExecutionError(
                    "construction/profile does not match certified implementation"
                )
            expected_ratio = float(leg.gross_weight) / expression_gross
            actual_ratio = float(trade.trade_weight) / construction_gross
            if abs(expected_ratio - actual_ratio) > self.weight_tolerance:
                raise AtomicRelativeValueExecutionError(
                    f"{leg.symbol} construction distorts relative-value proportions"
                )
            if leg.side is RelativeValueLegSide.SHORT:
                if implementation.execution_side is TradeSide.SELL:
                    if implementation.execution_symbol.upper() not in owned:
                        raise AtomicRelativeValueExecutionError(
                            "naked paper shorts are unsupported; SELL short leg must reduce an owned position"
                        )
                elif not (
                    implementation.defined_risk_short_implementation
                    and bool(profile.defined_risk)
                ):
                    raise AtomicRelativeValueExecutionError(
                        "short economic BUY leg requires certified defined-risk/inverse implementation"
                    )
        return normalized_profiles

    def _record_noncommit(
        self,
        *,
        execution_identifier: str,
        expression: RelativeValueCandidateExpression,
        decision_identifier: str,
        construction: PortfolioConstructionResult,
        portfolio: CanonicalPortfolioSnapshot,
        as_of: datetime,
        implementations: tuple[RelativeValuePaperLegImplementation, ...],
        attempt: int,
        status: AtomicRelativeValueExecutionStatus,
        reasons: tuple[str, ...],
        batch_identifier: str | None,
    ) -> AtomicRelativeValueExecutionAttempt:
        result = AtomicRelativeValueExecutionAttempt(
            identifier=execution_identifier,
            expression_identifier=expression.identifier,
            decision_identifier=decision_identifier,
            construction_identifier=construction.request_identifier,
            attempted_at=as_of,
            status=status,
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot_identifier=portfolio.identifier,
            underlying_batch_identifier=batch_identifier,
            implementation_identifiers=tuple(
                item.implementation_certification_identifier for item in implementations
            ),
            reasons=reasons,
            attempt=attempt,
            canonical_state_changed=False,
        )
        self.store.append(result)
        return result

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
        if expression.as_of > as_of or construction.as_of > as_of or portfolio.as_of > as_of:
            raise AtomicRelativeValueExecutionError(
                "relative-value execution cannot use future-known state"
            )
        if not construction.trades:
            raise AtomicRelativeValueExecutionError(
                "relative-value execution requires construction trades"
            )

        execution_identifier = self._execution_identifier(expression, construction)
        latest_real = self.base_executor.portfolio_store.latest(portfolio.portfolio_code)
        previous = self.store.latest(execution_identifier)
        terminal = self._recover_or_validate_retry(
            previous=previous,
            latest_real=latest_real,
            portfolio=portfolio,
            as_of=as_of,
        )
        if terminal is not None:
            return terminal
        if latest_real is None or latest_real.identifier != portfolio.identifier:
            raise AtomicRelativeValueExecutionError(
                "canonical portfolio advanced before atomic simulation"
            )
        attempt = 1 if previous is None else previous.attempt + 1
        normalized_profiles = self._validate_structure(
            expression=expression,
            construction=construction,
            portfolio=portfolio,
            profiles=profiles,
            implementations=implementations,
        )

        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-atomic-rv-"
        ) as raw_tmp:
            tmp = Path(raw_tmp)
            temporary_portfolio_store = SQLiteCanonicalPortfolioStore(
                tmp / "portfolio.db"
            )
            temporary_portfolio_store.append(portfolio)
            simulator = MultiAssetPaperExecutionOrchestrator(
                session_provider=self.base_executor.session_provider,
                quote_provider=self.base_executor.quote_provider,
                store=SQLiteMultiAssetPaperExecutionStore(tmp / "execution.db"),
                portfolio_store=temporary_portfolio_store,
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
                return self._record_noncommit(
                    execution_identifier=execution_identifier,
                    expression=expression,
                    decision_identifier=decision_identifier,
                    construction=construction,
                    portfolio=portfolio,
                    as_of=as_of,
                    implementations=implementations,
                    attempt=attempt,
                    status=AtomicRelativeValueExecutionStatus.FAILED,
                    reasons=(str(error), "real canonical portfolio unchanged"),
                    batch_identifier=None,
                )

            all_filled = bool(batch.order_results) and all(
                item.status is MultiAssetOrderStatus.FILLED
                and abs(item.requested_base_amount - item.filled_base_amount)
                <= self.base_executor.policy.reconciliation_tolerance
                for item in batch.order_results
            )
            reconciled = bool(
                batch.reconciliation.reconciled
                and batch.reconciliation.accounting_reconciled
            )
            if (
                batch.status is not MultiAssetExecutionStatus.COMPLETED
                or not all_filled
                or not reconciled
            ):
                status = (
                    AtomicRelativeValueExecutionStatus.HELD
                    if batch.status is MultiAssetExecutionStatus.HELD
                    else AtomicRelativeValueExecutionStatus.FAILED
                )
                return self._record_noncommit(
                    execution_identifier=execution_identifier,
                    expression=expression,
                    decision_identifier=decision_identifier,
                    construction=construction,
                    portfolio=portfolio,
                    as_of=as_of,
                    implementations=implementations,
                    attempt=attempt,
                    status=status,
                    reasons=(
                        f"underlying batch status={batch.status.value}",
                        "atomic requirement not satisfied; all provisional fills discarded",
                        "real canonical portfolio unchanged",
                    ),
                    batch_identifier=batch.identifier,
                )

            committed_identifier = self._committed_identifier(
                portfolio.identifier, execution_identifier
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
                            *(
                                item.implementation_certification_identifier
                                for item in implementations
                            ),
                            *expression.evidence_identifiers,
                            *expression.model_versions,
                        )
                    )
                ),
            )

        prepared = AtomicRelativeValueExecutionAttempt(
            identifier=execution_identifier,
            expression_identifier=expression.identifier,
            decision_identifier=decision_identifier,
            construction_identifier=construction.request_identifier,
            attempted_at=as_of,
            status=AtomicRelativeValueExecutionStatus.PREPARED,
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot_identifier=committed_snapshot.identifier,
            underlying_batch_identifier=batch.identifier,
            implementation_identifiers=tuple(
                item.implementation_certification_identifier for item in implementations
            ),
            reasons=(
                "all legs fully filled and reconciled in isolated canonical paper executor",
                "canonical commit prepared but not yet published",
            ),
            attempt=attempt,
            canonical_state_changed=False,
        )
        self.store.append(prepared)

        latest_before_commit = self.base_executor.portfolio_store.latest(
            portfolio.portfolio_code
        )
        if latest_before_commit is None or latest_before_commit.identifier != portfolio.identifier:
            raise AtomicRelativeValueExecutionError(
                "canonical portfolio advanced after PREPARED; refusing atomic commit"
            )
        self.base_executor.portfolio_store.append(committed_snapshot)
        completed = replace(
            prepared,
            status=AtomicRelativeValueExecutionStatus.COMPLETED,
            reasons=(
                *prepared.reasons,
                "one reconciled canonical portfolio snapshot committed atomically",
                "no naked-short authority introduced",
            ),
            canonical_state_changed=True,
        )
        self.store.append(completed)
        return completed


__all__ = [
    "AtomicRelativeValueExecutionAttempt",
    "AtomicRelativeValueExecutionError",
    "AtomicRelativeValueExecutionStatus",
    "AtomicRelativeValuePaperExecutionOrchestrator",
    "RelativeValuePaperLegImplementation",
    "SQLiteAtomicRelativeValueExecutionStore",
]
