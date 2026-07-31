"""Pre-registered, immutable paper experiment and soak-test evidence.

Completion produces evidence for human review only. It cannot tune a threshold,
promote policy, authorize a portfolio change, or support a performance claim.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class PaperExperimentProtocol:
    version: str
    hypothesis: str
    portfolio_code: str
    starting_capital: float
    base_currency: str
    universe_identifiers: tuple[str, ...]
    provider_manifest_identifier: str
    cost_model_version: str
    benchmark_definition: str
    minimum_calendar_days: int
    minimum_operating_cycles: int
    maximum_missing_cycles: int
    observation_schedule: str
    metrics: tuple[str, ...]
    required_failure_scenarios: tuple[str, ...]
    change_control: str
    schema_version: str = "paper-experiment-protocol.v1"

    def __post_init__(self) -> None:
        for field in (
            "version", "hypothesis", "portfolio_code", "base_currency",
            "provider_manifest_identifier", "cost_model_version",
            "benchmark_definition", "observation_schedule", "change_control",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if self.portfolio_code != "COMPOUNDING" or self.starting_capital != 250_000.0:
            raise ValueError("experiment must govern one $250,000 COMPOUNDING portfolio")
        if self.base_currency != "USD":
            raise ValueError("experiment base currency must be USD")
        for field in ("universe_identifiers", "metrics", "required_failure_scenarios"):
            value = getattr(self, field)
            if not isinstance(value, tuple) or not value or len(value) != len(set(value)):
                raise ValueError(f"{field} must be a non-empty unique tuple")
        if self.minimum_calendar_days < 28 or self.minimum_operating_cycles < 20:
            raise ValueError("formal experiment must span multiple weeks and at least 20 cycles")
        if self.maximum_missing_cycles < 0 or self.maximum_missing_cycles >= self.minimum_operating_cycles:
            raise ValueError("maximum_missing_cycles is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "hypothesis": self.hypothesis,
            "portfolio_code": self.portfolio_code,
            "starting_capital": self.starting_capital,
            "base_currency": self.base_currency,
            "universe_identifiers": list(self.universe_identifiers),
            "provider_manifest_identifier": self.provider_manifest_identifier,
            "cost_model_version": self.cost_model_version,
            "benchmark_definition": self.benchmark_definition,
            "minimum_calendar_days": self.minimum_calendar_days,
            "minimum_operating_cycles": self.minimum_operating_cycles,
            "maximum_missing_cycles": self.maximum_missing_cycles,
            "observation_schedule": self.observation_schedule,
            "metrics": list(self.metrics),
            "required_failure_scenarios": list(self.required_failure_scenarios),
            "change_control": self.change_control,
            "schema_version": self.schema_version,
            "automatic_threshold_change_permitted": False,
            "policy_promotion_authorized": False,
            "performance_claims_permitted": False,
            "real_money_authorized": False,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode()).hexdigest()


REQUIRED_LAUNCH_GATES = (
    "pr1_public_access_safe",
    "pr2_single_execution_authority",
    "pr3_normal_application_composition",
    "pr4_composite_readiness",
    "pr5_canonical_topology",
    "pr6_deterministic_history",
    "pr7_restart_idempotency_reconciliation",
    "pr8_real_browser_gate",
    "pr9_golden_chaos_gate",
    "pr10_human_reviewed_event_benchmark",
    "pr11_scope_and_historical_certification",
    "render_exact_sha_verified",
)


@dataclass(frozen=True, slots=True)
class PaperExperimentRegistration:
    identifier: str
    protocol_version: str
    protocol_fingerprint: str
    registered_at: datetime
    start_date: date
    code_version: str
    deployed_git_sha: str
    launch_evidence_identifiers: tuple[str, ...]
    schema_version: str = "paper-experiment-registration.v1"

    def __post_init__(self) -> None:
        for field in ("identifier", "protocol_version", "protocol_fingerprint"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "registered_at", _aware(self.registered_at, "registered_at"))
        if self.start_date < self.registered_at.date():
            raise ValueError("start_date cannot predate registration")
        for field in ("code_version", "deployed_git_sha"):
            value = _text(getattr(self, field), field)
            if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value.lower()):
                raise ValueError(f"{field} must be an exact 40-character Git SHA")
            object.__setattr__(self, field, value.lower())
        if self.code_version != self.deployed_git_sha:
            raise ValueError("experiment code_version must equal the exact deployed Git SHA")
        if set(self.launch_evidence_identifiers) != set(REQUIRED_LAUNCH_GATES):
            raise ValueError("registration requires every PR1-PR11 and deployment gate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "protocol_version": self.protocol_version,
            "protocol_fingerprint": self.protocol_fingerprint,
            "registered_at": self.registered_at.isoformat(),
            "start_date": self.start_date.isoformat(),
            "code_version": self.code_version,
            "deployed_git_sha": self.deployed_git_sha,
            "launch_evidence_identifiers": list(self.launch_evidence_identifiers),
            "schema_version": self.schema_version,
            "paper_only": True,
            "automatic_threshold_change_permitted": False,
            "performance_claims_permitted": False,
            "real_money_authorized": False,
        }


def register_paper_experiment(
    protocol: PaperExperimentProtocol,
    *,
    registered_at: datetime,
    start_date: date,
    code_version: str,
    deployed_git_sha: str,
    launch_gates: Mapping[str, bool],
) -> PaperExperimentRegistration:
    missing = [gate for gate in REQUIRED_LAUNCH_GATES if launch_gates.get(gate) is not True]
    if missing:
        raise ValueError("paper experiment launch gates are not satisfied: " + ", ".join(missing))
    timestamp = _aware(registered_at, "registered_at")
    identifier = "paper-experiment:" + hashlib.sha256(
        f"{protocol.fingerprint}|{code_version}|{start_date.isoformat()}".encode()
    ).hexdigest()
    return PaperExperimentRegistration(
        identifier=identifier,
        protocol_version=protocol.version,
        protocol_fingerprint=protocol.fingerprint,
        registered_at=timestamp,
        start_date=start_date,
        code_version=code_version,
        deployed_git_sha=deployed_git_sha,
        launch_evidence_identifiers=tuple(REQUIRED_LAUNCH_GATES),
    )


@dataclass(frozen=True, slots=True)
class PaperExperimentObservation:
    identifier: str
    registration_identifier: str
    protocol_fingerprint: str
    code_version: str
    operation_date: date
    recorded_at: datetime
    ending_nav: float
    benchmark_nav: float
    transaction_cost: float
    turnover: float
    missing_data: bool
    reconciliation_passed: bool
    benchmark_reconstructable: bool
    source_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("identifier", "registration_identifier", "protocol_fingerprint", "code_version"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        if self.operation_date > self.recorded_at.date():
            raise ValueError("operation_date cannot be future-known")
        if self.ending_nav < 0 or self.benchmark_nav < 0 or self.transaction_cost < 0 or self.turnover < 0:
            raise ValueError("observation values cannot be negative")
        if not self.source_identifiers:
            raise ValueError("observation requires source lineage")


class PaperExperimentState(str, Enum):
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE_AWAITING_HUMAN_REVIEW = "complete_awaiting_human_review"


@dataclass(frozen=True, slots=True)
class PaperExperimentEvaluation:
    state: PaperExperimentState
    blockers: tuple[str, ...]
    credited_cycle_count: int
    elapsed_calendar_days: int
    missing_cycle_count: int
    ending_nav: float | None
    ending_benchmark_nav: float | None
    total_transaction_cost: float
    schema_version: str = "paper-experiment-evaluation.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "blockers": list(self.blockers),
            "credited_cycle_count": self.credited_cycle_count,
            "elapsed_calendar_days": self.elapsed_calendar_days,
            "missing_cycle_count": self.missing_cycle_count,
            "ending_nav": self.ending_nav,
            "ending_benchmark_nav": self.ending_benchmark_nav,
            "total_transaction_cost": self.total_transaction_cost,
            "schema_version": self.schema_version,
            "human_review_required": True,
            "automatic_threshold_change_permitted": False,
            "policy_promotion_authorized": False,
            "performance_claims_permitted": False,
            "real_money_authorized": False,
        }


def evaluate_paper_experiment(
    protocol: PaperExperimentProtocol,
    registration: PaperExperimentRegistration,
    observations: Iterable[PaperExperimentObservation],
    *,
    evaluated_at: datetime,
) -> PaperExperimentEvaluation:
    now = _aware(evaluated_at, "evaluated_at")
    items = tuple(sorted(observations, key=lambda item: (item.operation_date, item.identifier)))
    blockers = []
    if registration.protocol_fingerprint != protocol.fingerprint:
        blockers.append("protocol fingerprint drift")
    if any(item.registration_identifier != registration.identifier for item in items):
        blockers.append("observation belongs to another registration")
    if any(item.protocol_fingerprint != protocol.fingerprint for item in items):
        blockers.append("observation protocol drift")
    if any(item.code_version != registration.code_version for item in items):
        blockers.append("observation code-version drift")
    dates = [item.operation_date for item in items]
    if len(dates) != len(set(dates)):
        blockers.append("duplicate operating date")
    if any(not item.reconciliation_passed for item in items):
        blockers.append("unreconciled observation")
    if any(not item.benchmark_reconstructable for item in items):
        blockers.append("benchmark is not reconstructable")
    missing = sum(item.missing_data for item in items)
    if missing > protocol.maximum_missing_cycles:
        blockers.append("missing-data allowance exceeded")
    elapsed = max((now.date() - registration.start_date).days + 1, 0)
    credited = sum(not item.missing_data and item.reconciliation_passed for item in items)
    complete = elapsed >= protocol.minimum_calendar_days and credited >= protocol.minimum_operating_cycles
    if blockers:
        state = PaperExperimentState.BLOCKED
    elif complete:
        state = PaperExperimentState.COMPLETE_AWAITING_HUMAN_REVIEW
    else:
        state = PaperExperimentState.IN_PROGRESS
    return PaperExperimentEvaluation(
        state=state,
        blockers=tuple(sorted(set(blockers))),
        credited_cycle_count=credited,
        elapsed_calendar_days=elapsed,
        missing_cycle_count=missing,
        ending_nav=None if not items else items[-1].ending_nav,
        ending_benchmark_nav=None if not items else items[-1].benchmark_nav,
        total_transaction_cost=round(sum(item.transaction_cost for item in items), 8),
    )


def load_paper_experiment_protocol(path: str | Path) -> PaperExperimentProtocol:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "paper-experiment-protocol.v1":
        raise ValueError("unsupported paper experiment protocol")
    if any(payload.get(field) is not False for field in (
        "automatic_threshold_change_permitted", "policy_promotion_authorized",
        "performance_claims_permitted", "real_money_authorized",
    )):
        raise ValueError("paper experiment protocol cannot grant authority or claims")
    return PaperExperimentProtocol(
        version=payload["version"], hypothesis=payload["hypothesis"],
        portfolio_code=payload["portfolio_code"], starting_capital=float(payload["starting_capital"]),
        base_currency=payload["base_currency"], universe_identifiers=tuple(payload["universe_identifiers"]),
        provider_manifest_identifier=payload["provider_manifest_identifier"],
        cost_model_version=payload["cost_model_version"], benchmark_definition=payload["benchmark_definition"],
        minimum_calendar_days=int(payload["minimum_calendar_days"]),
        minimum_operating_cycles=int(payload["minimum_operating_cycles"]),
        maximum_missing_cycles=int(payload["maximum_missing_cycles"]),
        observation_schedule=payload["observation_schedule"], metrics=tuple(payload["metrics"]),
        required_failure_scenarios=tuple(payload["required_failure_scenarios"]),
        change_control=payload["change_control"],
    )


class SQLitePaperExperimentStore:
    """Hash-chained append-only registration, observation, and evaluation log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_experiment_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, identifier TEXT UNIQUE NOT NULL, event_type TEXT NOT NULL, recorded_at TEXT NOT NULL, payload_json TEXT NOT NULL, previous_hash TEXT NOT NULL, content_hash TEXT UNIQUE NOT NULL);
                CREATE TRIGGER IF NOT EXISTS experiment_no_update BEFORE UPDATE ON paper_experiment_events BEGIN SELECT RAISE(ABORT, 'paper experiment history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS experiment_no_delete BEFORE DELETE ON paper_experiment_events BEGIN SELECT RAISE(ABORT, 'paper experiment history is append-only'); END;
                """
            )

    def append(self, *, identifier: str, event_type: str, recorded_at: datetime, payload: Mapping[str, Any]) -> None:
        body = _canonical(payload)
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_json FROM paper_experiment_events WHERE identifier=?", (identifier,)).fetchone()
            if existing:
                if existing[0] != body:
                    raise ValueError("experiment event identifier already exists with different content")
                return
            tail = connection.execute("SELECT content_hash FROM paper_experiment_events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous = "0" * 64 if tail is None else tail[0]
            timestamp = _aware(recorded_at, "recorded_at").isoformat()
            digest = hashlib.sha256(f"{identifier}|{event_type}|{timestamp}|{body}|{previous}".encode()).hexdigest()
            connection.execute("INSERT INTO paper_experiment_events(identifier,event_type,recorded_at,payload_json,previous_hash,content_hash) VALUES(?,?,?,?,?,?)", (identifier, event_type, timestamp, body, previous, digest))


__all__ = [
    "PaperExperimentEvaluation", "PaperExperimentObservation", "PaperExperimentProtocol",
    "PaperExperimentRegistration", "PaperExperimentState", "REQUIRED_LAUNCH_GATES",
    "SQLitePaperExperimentStore", "evaluate_paper_experiment", "load_paper_experiment_protocol",
    "register_paper_experiment",
]
