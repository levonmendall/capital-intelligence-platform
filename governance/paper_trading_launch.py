"""Govern launch readiness, authorization, and paper-only controls.

A successful unit or release test is not enough to start the controlled paper
portfolio. This authority requires one current validated operating cycle for an
exact baseline plus point-in-time data integrity, realistic execution
calibration, reconciliation, recovery, replay, and halt-control exercises. It
does not require an elapsed multi-day burn-in and does not authorize real money,
broker connectivity, or performance claims.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


class PaperTradingLaunchError(RuntimeError):
    """Raised when launch evidence or execution authorization is unavailable."""


class PaperTradingLaunchIntegrityError(PaperTradingLaunchError):
    """Raised when an append-only launch or control history is invalid."""


class PaperTradingLaunchState(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"


class PaperTradingControlState(str, Enum):
    HALTED = "halted"
    ACTIVE = "active"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _count(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")
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
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class PaperTradingLaunchPolicy:
    """Versioned minimum acceptance policy for a controlled paper launch."""

    version: str = "paper-trading-launch-policy.v2"
    minimum_burn_in_days: int = 0
    minimum_scheduled_cycles: int = 1
    minimum_successful_cycle_ratio: float = 1.0
    minimum_point_in_time_cycle_ratio: float = 1.0
    minimum_complete_universe_cycle_ratio: float = 1.0
    minimum_required_provider_success_ratio: float = 0.99
    minimum_shadow_execution_scenarios: int = 12
    minimum_reconciled_shadow_execution_ratio: float = 1.0
    maximum_execution_cost_error_bps: float = 25.0
    minimum_backup_restore_exercises: int = 1
    minimum_scheduler_replay_exercises: int = 1
    minimum_kill_switch_exercises: int = 2
    minimum_provider_failover_exercises: int = 1
    minimum_market_session_exercises: int = 3
    minimum_partial_fill_retry_exercises: int = 1
    minimum_corporate_action_replay_exercises: int = 1
    minimum_fx_revaluation_exercises: int = 1
    maximum_drawdown_fraction: float = 0.20
    maximum_single_batch_turnover: float = 0.35
    authorization_ttl_hours: int = 24
    required_portfolio_count: int = 1
    required_portfolio_code: str = "COMPOUNDING"
    required_starting_capital: float = 250_000.0
    required_base_currency: str = "USD"

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        object.__setattr__(
            self,
            "minimum_burn_in_days",
            _count(self.minimum_burn_in_days, field_name="minimum_burn_in_days"),
        )
        for field_name in (
            "minimum_scheduled_cycles",
            "minimum_shadow_execution_scenarios",
            "minimum_backup_restore_exercises",
            "minimum_scheduler_replay_exercises",
            "minimum_kill_switch_exercises",
            "minimum_provider_failover_exercises",
            "minimum_market_session_exercises",
            "minimum_partial_fill_retry_exercises",
            "minimum_corporate_action_replay_exercises",
            "minimum_fx_revaluation_exercises",
            "authorization_ttl_hours",
            "required_portfolio_count",
        ):
            value = _count(getattr(self, field_name), field_name=field_name)
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "minimum_successful_cycle_ratio",
            "minimum_point_in_time_cycle_ratio",
            "minimum_complete_universe_cycle_ratio",
            "minimum_required_provider_success_ratio",
            "minimum_reconciled_shadow_execution_ratio",
            "maximum_drawdown_fraction",
            "maximum_single_batch_turnover",
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
        object.__setattr__(
            self,
            "maximum_execution_cost_error_bps",
            _number(
                self.maximum_execution_cost_error_bps,
                field_name="maximum_execution_cost_error_bps",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "required_portfolio_code",
            _text(self.required_portfolio_code, field_name="required_portfolio_code").upper(),
        )
        object.__setattr__(
            self,
            "required_starting_capital",
            _number(
                self.required_starting_capital,
                field_name="required_starting_capital",
                minimum=0.01,
            ),
        )
        object.__setattr__(
            self,
            "required_base_currency",
            _text(self.required_base_currency, field_name="required_base_currency").upper(),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperTradingLaunchPolicy":
        allowed = {field for field in cls.__dataclass_fields__}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown launch policy fields: {unknown}")
        return cls(**dict(payload))


@dataclass(frozen=True, slots=True)
class PaperTradingLaunchEvidence:
    """Immutable operating evidence for one exact paper-test baseline."""

    identifier: str
    observed_at: datetime
    knowledge_cutoff: datetime
    window_start: datetime
    window_end: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    portfolio_count: int
    portfolio_code: str
    starting_capital: float
    base_currency: str
    paper_only_disclosures_verified: bool
    live_broker_credentials_present: bool
    canonical_portfolio_integrity_verified: bool
    eligible_universe_integrity_verified: bool
    execution_store_integrity_verified: bool
    scheduled_cycles: int
    successful_cycles: int
    point_in_time_cycles: int
    complete_universe_cycles: int
    required_provider_checks: int
    successful_required_provider_checks: int
    shadow_execution_scenarios: int
    reconciled_shadow_execution_scenarios: int
    execution_cost_error_bps: float
    unresolved_orders: int
    duplicate_fill_events: int
    negative_cash_events: int
    stale_quote_acceptances: int
    unresolved_critical_incidents: int
    data_integrity_failures: int
    reconciliation_failures: int
    backup_restore_exercises: int
    scheduler_replay_exercises: int
    kill_switch_exercises: int
    provider_failover_exercises: int
    market_session_exercises: int
    partial_fill_retry_exercises: int
    corporate_action_replay_exercises: int
    fx_revaluation_exercises: int
    production_binding_approval_identifier: str
    recovery_certification_identifier: str
    execution_calibration_identifier: str
    execution_policy_version: str
    data_readiness_identifier: str
    product_readiness_identifier: str
    evidence_identifiers: tuple[str, ...]
    source_identifiers: tuple[str, ...]
    schema_version: str = "paper-trading-launch-evidence.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "production_binding_approval_identifier",
            "recovery_certification_identifier",
            "execution_calibration_identifier",
            "execution_policy_version",
            "data_readiness_identifier",
            "product_readiness_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "observed_at",
            "knowledge_cutoff",
            "window_start",
            "window_end",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.window_end < self.window_start:
            raise ValueError("window_end cannot predate window_start")
        if self.observed_at < self.window_end:
            raise ValueError("observed_at cannot predate window_end")
        if self.knowledge_cutoff < self.observed_at:
            raise ValueError("knowledge_cutoff cannot predate observed_at")
        for field_name in (
            "portfolio_count",
            "scheduled_cycles",
            "successful_cycles",
            "point_in_time_cycles",
            "complete_universe_cycles",
            "required_provider_checks",
            "successful_required_provider_checks",
            "shadow_execution_scenarios",
            "reconciled_shadow_execution_scenarios",
            "unresolved_orders",
            "duplicate_fill_events",
            "negative_cash_events",
            "stale_quote_acceptances",
            "unresolved_critical_incidents",
            "data_integrity_failures",
            "reconciliation_failures",
            "backup_restore_exercises",
            "scheduler_replay_exercises",
            "kill_switch_exercises",
            "provider_failover_exercises",
            "market_session_exercises",
            "partial_fill_retry_exercises",
            "corporate_action_replay_exercises",
            "fx_revaluation_exercises",
        ):
            object.__setattr__(
                self,
                field_name,
                _count(getattr(self, field_name), field_name=field_name),
            )
        for numerator, denominator in (
            (self.successful_cycles, self.scheduled_cycles),
            (self.point_in_time_cycles, self.scheduled_cycles),
            (self.complete_universe_cycles, self.scheduled_cycles),
            (
                self.successful_required_provider_checks,
                self.required_provider_checks,
            ),
            (
                self.reconciled_shadow_execution_scenarios,
                self.shadow_execution_scenarios,
            ),
        ):
            if numerator > denominator:
                raise ValueError("successful evidence counts cannot exceed total counts")
        object.__setattr__(
            self,
            "portfolio_code",
            _text(self.portfolio_code, field_name="portfolio_code").upper(),
        )
        object.__setattr__(
            self,
            "starting_capital",
            _number(self.starting_capital, field_name="starting_capital", minimum=0.01),
        )
        object.__setattr__(
            self,
            "base_currency",
            _text(self.base_currency, field_name="base_currency").upper(),
        )
        object.__setattr__(
            self,
            "execution_cost_error_bps",
            _number(
                self.execution_cost_error_bps,
                field_name="execution_cost_error_bps",
                minimum=0.0,
            ),
        )
        for field_name in (
            "paper_only_disclosures_verified",
            "live_broker_credentials_present",
            "canonical_portfolio_integrity_verified",
            "eligible_universe_integrity_verified",
            "execution_store_integrity_verified",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(
                self.source_identifiers,
                field_name="source_identifiers",
                minimum=1,
            ),
        )

    @property
    def burn_in_days(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 86_400.0

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return 0.0 if denominator <= 0 else round(numerator / denominator, 12)

    @property
    def successful_cycle_ratio(self) -> float:
        return self._ratio(self.successful_cycles, self.scheduled_cycles)

    @property
    def point_in_time_cycle_ratio(self) -> float:
        return self._ratio(self.point_in_time_cycles, self.scheduled_cycles)

    @property
    def complete_universe_cycle_ratio(self) -> float:
        return self._ratio(self.complete_universe_cycles, self.scheduled_cycles)

    @property
    def required_provider_success_ratio(self) -> float:
        return self._ratio(
            self.successful_required_provider_checks,
            self.required_provider_checks,
        )

    @property
    def reconciled_shadow_execution_ratio(self) -> float:
        return self._ratio(
            self.reconciled_shadow_execution_scenarios,
            self.shadow_execution_scenarios,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "observed_at": self.observed_at.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "portfolio_count": self.portfolio_count,
            "portfolio_code": self.portfolio_code,
            "starting_capital": self.starting_capital,
            "base_currency": self.base_currency,
            "paper_only_disclosures_verified": self.paper_only_disclosures_verified,
            "live_broker_credentials_present": self.live_broker_credentials_present,
            "canonical_portfolio_integrity_verified": self.canonical_portfolio_integrity_verified,
            "eligible_universe_integrity_verified": self.eligible_universe_integrity_verified,
            "execution_store_integrity_verified": self.execution_store_integrity_verified,
            "scheduled_cycles": self.scheduled_cycles,
            "successful_cycles": self.successful_cycles,
            "point_in_time_cycles": self.point_in_time_cycles,
            "complete_universe_cycles": self.complete_universe_cycles,
            "required_provider_checks": self.required_provider_checks,
            "successful_required_provider_checks": self.successful_required_provider_checks,
            "shadow_execution_scenarios": self.shadow_execution_scenarios,
            "reconciled_shadow_execution_scenarios": self.reconciled_shadow_execution_scenarios,
            "execution_cost_error_bps": self.execution_cost_error_bps,
            "unresolved_orders": self.unresolved_orders,
            "duplicate_fill_events": self.duplicate_fill_events,
            "negative_cash_events": self.negative_cash_events,
            "stale_quote_acceptances": self.stale_quote_acceptances,
            "unresolved_critical_incidents": self.unresolved_critical_incidents,
            "data_integrity_failures": self.data_integrity_failures,
            "reconciliation_failures": self.reconciliation_failures,
            "backup_restore_exercises": self.backup_restore_exercises,
            "scheduler_replay_exercises": self.scheduler_replay_exercises,
            "kill_switch_exercises": self.kill_switch_exercises,
            "provider_failover_exercises": self.provider_failover_exercises,
            "market_session_exercises": self.market_session_exercises,
            "partial_fill_retry_exercises": self.partial_fill_retry_exercises,
            "corporate_action_replay_exercises": self.corporate_action_replay_exercises,
            "fx_revaluation_exercises": self.fx_revaluation_exercises,
            "production_binding_approval_identifier": self.production_binding_approval_identifier,
            "recovery_certification_identifier": self.recovery_certification_identifier,
            "execution_calibration_identifier": self.execution_calibration_identifier,
            "execution_policy_version": self.execution_policy_version,
            "data_readiness_identifier": self.data_readiness_identifier,
            "product_readiness_identifier": self.product_readiness_identifier,
            "evidence_identifiers": list(self.evidence_identifiers),
            "source_identifiers": list(self.source_identifiers),
            "successful_cycle_ratio": self.successful_cycle_ratio,
            "point_in_time_cycle_ratio": self.point_in_time_cycle_ratio,
            "complete_universe_cycle_ratio": self.complete_universe_cycle_ratio,
            "required_provider_success_ratio": self.required_provider_success_ratio,
            "reconciled_shadow_execution_ratio": self.reconciled_shadow_execution_ratio,
            "burn_in_days": round(self.burn_in_days, 8),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperTradingLaunchEvidence":
        values = dict(payload)
        for name in ("observed_at", "knowledge_cutoff", "window_start", "window_end"):
            values[name] = datetime.fromisoformat(str(payload[name]).replace("Z", "+00:00"))
        values["evidence_identifiers"] = tuple(payload["evidence_identifiers"])
        values["source_identifiers"] = tuple(payload["source_identifiers"])
        for derived in (
            "successful_cycle_ratio",
            "point_in_time_cycle_ratio",
            "complete_universe_cycle_ratio",
            "required_provider_success_ratio",
            "reconciled_shadow_execution_ratio",
            "burn_in_days",
        ):
            values.pop(derived, None)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class PaperTradingLaunchReport:
    identifier: str
    assessed_at: datetime
    valid_until: datetime
    state: PaperTradingLaunchState
    baseline_identifier: str
    process_version: str
    code_version: str
    policy_version: str
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    maximum_drawdown_fraction: float
    maximum_single_batch_turnover: float
    real_money_authorized: bool = False
    performance_claims_permitted: bool = False
    schema_version: str = "paper-trading-launch-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "policy_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.assessed_at, field_name="assessed_at")
        _aware(self.valid_until, field_name="valid_until")
        if self.valid_until <= self.assessed_at:
            raise ValueError("valid_until must follow assessed_at")
        if not isinstance(self.state, PaperTradingLaunchState):
            raise TypeError("state must be PaperTradingLaunchState")
        object.__setattr__(self, "blockers", _texts(self.blockers, field_name="blockers"))
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        for field_name in ("maximum_drawdown_fraction", "maximum_single_batch_turnover"):
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
        if self.real_money_authorized or self.performance_claims_permitted:
            raise ValueError("paper launch cannot authorize real money or performance claims")

    @property
    def ready(self) -> bool:
        return self.state is PaperTradingLaunchState.READY

    def active_at(
        self,
        *,
        as_of: datetime,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
    ) -> bool:
        timestamp = _aware(as_of, field_name="as_of")
        return (
            self.ready
            and self.assessed_at <= timestamp < self.valid_until
            and self.baseline_identifier == baseline_identifier
            and self.process_version == process_version
            and self.code_version == code_version
        )

    @property
    def evidence_identifier(self) -> str:
        return f"paper-launch:{self.identifier}:{self.state.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "state": self.state.value,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "policy_version": self.policy_version,
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "maximum_drawdown_fraction": self.maximum_drawdown_fraction,
            "maximum_single_batch_turnover": self.maximum_single_batch_turnover,
            "evidence_identifier": self.evidence_identifier,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperTradingLaunchReport":
        return cls(
            identifier=str(payload["identifier"]),
            assessed_at=datetime.fromisoformat(str(payload["assessed_at"])),
            valid_until=datetime.fromisoformat(str(payload["valid_until"])),
            state=PaperTradingLaunchState(str(payload["state"])),
            baseline_identifier=str(payload["baseline_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            policy_version=str(payload["policy_version"]),
            blockers=tuple(payload.get("blockers", ())),
            evidence_identifiers=tuple(payload["evidence_identifiers"]),
            maximum_drawdown_fraction=float(payload["maximum_drawdown_fraction"]),
            maximum_single_batch_turnover=float(payload["maximum_single_batch_turnover"]),
            real_money_authorized=bool(payload.get("real_money_authorized", False)),
            performance_claims_permitted=bool(
                payload.get("performance_claims_permitted", False)
            ),
            schema_version=str(
                payload.get("schema_version", "paper-trading-launch-report.v1")
            ),
        )


class PaperTradingLaunchEvaluator:
    def __init__(self, policy: PaperTradingLaunchPolicy | None = None) -> None:
        self.policy = policy or PaperTradingLaunchPolicy()

    def evaluate(self, evidence: PaperTradingLaunchEvidence) -> PaperTradingLaunchReport:
        if not isinstance(evidence, PaperTradingLaunchEvidence):
            raise TypeError("evidence must be PaperTradingLaunchEvidence")
        policy = self.policy
        blockers: list[str] = []

        def minimum(name: str, actual: float, required: float) -> None:
            if actual < required:
                blockers.append(f"{name}: {actual} < required {required}")

        def maximum(name: str, actual: float, allowed: float = 0.0) -> None:
            if actual > allowed:
                blockers.append(f"{name}: {actual} > allowed {allowed}")

        if policy.minimum_burn_in_days > 0:
            minimum(
                "burn_in_days",
                evidence.burn_in_days,
                policy.minimum_burn_in_days,
            )
        minimum("scheduled_cycles", evidence.scheduled_cycles, policy.minimum_scheduled_cycles)
        minimum(
            "successful_cycle_ratio",
            evidence.successful_cycle_ratio,
            policy.minimum_successful_cycle_ratio,
        )
        minimum(
            "point_in_time_cycle_ratio",
            evidence.point_in_time_cycle_ratio,
            policy.minimum_point_in_time_cycle_ratio,
        )
        minimum(
            "complete_universe_cycle_ratio",
            evidence.complete_universe_cycle_ratio,
            policy.minimum_complete_universe_cycle_ratio,
        )
        minimum(
            "required_provider_success_ratio",
            evidence.required_provider_success_ratio,
            policy.minimum_required_provider_success_ratio,
        )
        minimum(
            "shadow_execution_scenarios",
            evidence.shadow_execution_scenarios,
            policy.minimum_shadow_execution_scenarios,
        )
        minimum(
            "reconciled_shadow_execution_ratio",
            evidence.reconciled_shadow_execution_ratio,
            policy.minimum_reconciled_shadow_execution_ratio,
        )
        maximum(
            "execution_cost_error_bps",
            evidence.execution_cost_error_bps,
            policy.maximum_execution_cost_error_bps,
        )
        for field_name, required in (
            ("backup_restore_exercises", policy.minimum_backup_restore_exercises),
            ("scheduler_replay_exercises", policy.minimum_scheduler_replay_exercises),
            ("kill_switch_exercises", policy.minimum_kill_switch_exercises),
            ("provider_failover_exercises", policy.minimum_provider_failover_exercises),
            ("market_session_exercises", policy.minimum_market_session_exercises),
            ("partial_fill_retry_exercises", policy.minimum_partial_fill_retry_exercises),
            (
                "corporate_action_replay_exercises",
                policy.minimum_corporate_action_replay_exercises,
            ),
            ("fx_revaluation_exercises", policy.minimum_fx_revaluation_exercises),
        ):
            minimum(field_name, getattr(evidence, field_name), required)
        for field_name in (
            "unresolved_orders",
            "duplicate_fill_events",
            "negative_cash_events",
            "stale_quote_acceptances",
            "unresolved_critical_incidents",
            "data_integrity_failures",
            "reconciliation_failures",
        ):
            maximum(field_name, getattr(evidence, field_name))
        if evidence.portfolio_count != policy.required_portfolio_count:
            blockers.append(
                f"portfolio_count: {evidence.portfolio_count} != required "
                f"{policy.required_portfolio_count}"
            )
        if evidence.portfolio_code != policy.required_portfolio_code:
            blockers.append("portfolio_code does not match the canonical portfolio")
        if abs(evidence.starting_capital - policy.required_starting_capital) > 0.01:
            blockers.append("starting_capital does not equal the canonical $250,000")
        if evidence.base_currency != policy.required_base_currency:
            blockers.append("base_currency does not match the canonical portfolio")
        if not evidence.paper_only_disclosures_verified:
            blockers.append("paper_only_disclosures_verified is false")
        if evidence.live_broker_credentials_present:
            blockers.append("live broker credentials are present")
        for field_name in (
            "canonical_portfolio_integrity_verified",
            "eligible_universe_integrity_verified",
            "execution_store_integrity_verified",
        ):
            if not getattr(evidence, field_name):
                blockers.append(f"{field_name} is false")

        state = (
            PaperTradingLaunchState.READY
            if not blockers
            else PaperTradingLaunchState.BLOCKED
        )
        assessed_at = evidence.knowledge_cutoff
        return PaperTradingLaunchReport(
            identifier=f"paper-trading-launch:{evidence.identifier}",
            assessed_at=assessed_at,
            valid_until=assessed_at + timedelta(hours=policy.authorization_ttl_hours),
            state=state,
            baseline_identifier=evidence.baseline_identifier,
            process_version=evidence.process_version,
            code_version=evidence.code_version,
            policy_version=policy.version,
            blockers=tuple(sorted(set(blockers))),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    (
                        evidence.identifier,
                        evidence.production_binding_approval_identifier,
                        evidence.recovery_certification_identifier,
                        evidence.execution_calibration_identifier,
                        evidence.data_readiness_identifier,
                        evidence.product_readiness_identifier,
                        *evidence.evidence_identifiers,
                        *evidence.source_identifiers,
                    )
                )
            ),
            maximum_drawdown_fraction=policy.maximum_drawdown_fraction,
            maximum_single_batch_turnover=policy.maximum_single_batch_turnover,
        )


class SQLitePaperTradingLaunchStore:
    """Append-only, SHA-256-chained paper-launch report authority."""

    _TABLE = "paper_trading_launch_reports"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    assessed_at TEXT NOT NULL,
                    baseline_identifier TEXT NOT NULL,
                    process_version TEXT NOT NULL,
                    code_version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_launch_lookup
                ON {self._TABLE} (
                    baseline_identifier, process_version, code_version, sequence
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper launch history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper launch history is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        assessed_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            f"{sequence}|{identifier}|{assessed_at}|{payload_json}|{previous_hash}".encode()
        ).hexdigest()

    def append(self, report: PaperTradingLaunchReport) -> int:
        if not isinstance(report, PaperTradingLaunchReport):
            raise TypeError("report must be PaperTradingLaunchReport")
        self.verify_integrity()
        payload_json = _canonical_json(report.to_dict())
        assessed_at = report.assessed_at.isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} WHERE identifier = ?",
                (report.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != payload_json:
                    raise PaperTradingLaunchError(
                        "launch report identifier already exists with different content"
                    )
                return int(existing[0])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail[1])
            content_hash = self._hash(
                sequence=sequence,
                identifier=report.identifier,
                assessed_at=assessed_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, identifier, assessed_at, baseline_identifier,
                    process_version, code_version, state, valid_until,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    report.identifier,
                    assessed_at,
                    report.baseline_identifier,
                    report.process_version,
                    report.code_version,
                    report.state.value,
                    report.valid_until.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def latest_ready(
        self,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> PaperTradingLaunchReport | None:
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        process = _text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        timestamp = _aware(as_of, field_name="as_of")
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json FROM {self._TABLE}
                WHERE baseline_identifier = ? AND process_version = ?
                  AND code_version = ? AND assessed_at <= ?
                ORDER BY sequence DESC
                """,
                (baseline, process, code, timestamp.isoformat()),
            ).fetchall()
        for row in rows:
            report = PaperTradingLaunchReport.from_dict(json.loads(str(row[0])))
            if report.active_at(
                as_of=timestamp,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
            ):
                return report
        return None

    def verify_integrity(self) -> bool:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT sequence, identifier, assessed_at, payload_json, "
                f"previous_hash, content_hash FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row[0]) != expected or str(row[4]) != previous:
                raise PaperTradingLaunchIntegrityError(
                    "paper launch sequence or previous hash is invalid"
                )
            actual = self._hash(
                sequence=expected,
                identifier=str(row[1]),
                assessed_at=str(row[2]),
                payload_json=str(row[3]),
                previous_hash=previous,
            )
            if str(row[5]) != actual:
                raise PaperTradingLaunchIntegrityError(
                    "paper launch content hash is invalid"
                )
            previous = actual
        return True


@dataclass(frozen=True, slots=True)
class PaperTradingControlEvent:
    identifier: str
    state: PaperTradingControlState
    effective_at: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    reason: str
    authority_identifiers: tuple[str, ...]
    launch_report_identifier: str | None = None
    schema_version: str = "paper-trading-control-event.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "reason",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.state, PaperTradingControlState):
            raise TypeError("state must be PaperTradingControlState")
        _aware(self.effective_at, field_name="effective_at")
        object.__setattr__(
            self,
            "authority_identifiers",
            _texts(
                self.authority_identifiers,
                field_name="authority_identifiers",
                minimum=1,
            ),
        )
        if self.launch_report_identifier is not None:
            object.__setattr__(
                self,
                "launch_report_identifier",
                _text(
                    self.launch_report_identifier,
                    field_name="launch_report_identifier",
                ),
            )
        if (
            self.state is PaperTradingControlState.ACTIVE
            and self.launch_report_identifier is None
        ):
            raise ValueError("active control requires a launch report identifier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "state": self.state.value,
            "effective_at": self.effective_at.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "reason": self.reason,
            "authority_identifiers": list(self.authority_identifiers),
            "launch_report_identifier": self.launch_report_identifier,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperTradingControlEvent":
        return cls(
            identifier=str(payload["identifier"]),
            state=PaperTradingControlState(str(payload["state"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
            baseline_identifier=str(payload["baseline_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            reason=str(payload["reason"]),
            authority_identifiers=tuple(payload["authority_identifiers"]),
            launch_report_identifier=(
                None
                if payload.get("launch_report_identifier") is None
                else str(payload["launch_report_identifier"])
            ),
            schema_version=str(
                payload.get("schema_version", "paper-trading-control-event.v1")
            ),
        )


class SQLitePaperTradingControlStore:
    """Append-only paper-only halt/resume authority; missing state means halted."""

    _TABLE = "paper_trading_control_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    effective_at TEXT NOT NULL,
                    baseline_identifier TEXT NOT NULL,
                    process_version TEXT NOT NULL,
                    code_version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_control_lookup
                ON {self._TABLE} (
                    baseline_identifier, process_version, code_version, sequence
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper control history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper control history is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        effective_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            f"{sequence}|{identifier}|{effective_at}|{payload_json}|{previous_hash}".encode()
        ).hexdigest()

    def append(self, event: PaperTradingControlEvent) -> int:
        if not isinstance(event, PaperTradingControlEvent):
            raise TypeError("event must be PaperTradingControlEvent")
        self.verify_integrity()
        payload_json = _canonical_json(event.to_dict())
        effective_at = event.effective_at.isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} WHERE identifier = ?",
                (event.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != payload_json:
                    raise PaperTradingLaunchError(
                        "control event identifier already exists with different content"
                    )
                return int(existing[0])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail[1])
            content_hash = self._hash(
                sequence=sequence,
                identifier=event.identifier,
                effective_at=effective_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, identifier, effective_at, baseline_identifier,
                    process_version, code_version, state, payload_json,
                    previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event.identifier,
                    effective_at,
                    event.baseline_identifier,
                    event.process_version,
                    event.code_version,
                    event.state.value,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def active_event(
        self,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> PaperTradingControlEvent | None:
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        process = _text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        timestamp = _aware(as_of, field_name="as_of")
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"""
                SELECT payload_json FROM {self._TABLE}
                WHERE baseline_identifier = ? AND process_version = ?
                  AND code_version = ? AND effective_at <= ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (baseline, process, code, timestamp.isoformat()),
            ).fetchone()
        return None if row is None else PaperTradingControlEvent.from_dict(
            json.loads(str(row[0]))
        )

    def verify_integrity(self) -> bool:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT sequence, identifier, effective_at, payload_json, "
                f"previous_hash, content_hash FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row[0]) != expected or str(row[4]) != previous:
                raise PaperTradingLaunchIntegrityError(
                    "paper control sequence or previous hash is invalid"
                )
            actual = self._hash(
                sequence=expected,
                identifier=str(row[1]),
                effective_at=str(row[2]),
                payload_json=str(row[3]),
                previous_hash=previous,
            )
            if str(row[5]) != actual:
                raise PaperTradingLaunchIntegrityError(
                    "paper control content hash is invalid"
                )
            previous = actual
        return True


@dataclass(frozen=True, slots=True)
class PaperExecutionAuthorization:
    launch_report: PaperTradingLaunchReport
    control_event: PaperTradingControlEvent

    @property
    def source_identifiers(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.launch_report.identifier,
                    self.launch_report.evidence_identifier,
                    self.control_event.identifier,
                    *self.launch_report.evidence_identifiers,
                    *self.control_event.authority_identifiers,
                )
            )
        )


def require_paper_execution_authorization(
    *,
    launch_store: SQLitePaperTradingLaunchStore,
    control_store: SQLitePaperTradingControlStore,
    baseline_identifier: str,
    process_version: str,
    code_version: str,
    as_of: datetime,
) -> PaperExecutionAuthorization:
    launch = launch_store.latest_ready(
        baseline_identifier=baseline_identifier,
        process_version=process_version,
        code_version=code_version,
        as_of=as_of,
    )
    if launch is None:
        raise PaperTradingLaunchError(
            "active paper-trading launch authorization is unavailable"
        )
    control = control_store.active_event(
        baseline_identifier=baseline_identifier,
        process_version=process_version,
        code_version=code_version,
        as_of=as_of,
    )
    if control is None or control.state is not PaperTradingControlState.ACTIVE:
        raise PaperTradingLaunchError("paper trading is halted")
    if control.launch_report_identifier != launch.identifier:
        raise PaperTradingLaunchError(
            "active paper control does not reference the current launch report"
        )
    return PaperExecutionAuthorization(launch_report=launch, control_event=control)


__all__ = [
    "PaperExecutionAuthorization",
    "PaperTradingControlEvent",
    "PaperTradingControlState",
    "PaperTradingLaunchError",
    "PaperTradingLaunchEvidence",
    "PaperTradingLaunchEvaluator",
    "PaperTradingLaunchIntegrityError",
    "PaperTradingLaunchPolicy",
    "PaperTradingLaunchReport",
    "PaperTradingLaunchState",
    "SQLitePaperTradingControlStore",
    "SQLitePaperTradingLaunchStore",
    "require_paper_execution_authorization",
]
