"""Extended paper-operation evidence and governance-readiness assessment.

This module measures whether the governed investment process has accumulated
sufficient, intact, and operationally credible paper evidence for a formal human
governance review.  It never authorizes real-money execution and never permits
performance marketing claims.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping


_EPSILON = 1e-12


def _required_text(value: object, *, field_name: str) -> str:
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


def _integer(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
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


def _ratio(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _return(value: object, *, field_name: str) -> float:
    normalized = _number(value, field_name=field_name)
    if normalized <= -1.0:
        raise ValueError(f"{field_name} must be greater than -1")
    return normalized


def _text_tuple(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_required_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("paper-operation payload must be finite JSON") from error


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 12)


def _compound(returns: Iterable[float]) -> float:
    wealth = 1.0
    for value in returns:
        wealth *= 1.0 + value
    return round(wealth - 1.0, 12)


def _maximum_drawdown(returns: Iterable[float]) -> float:
    wealth = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        if peak > 0:
            drawdown = max(drawdown, (peak - wealth) / peak)
    return round(drawdown, 12)


class PaperOperationReadiness(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"
    READY_FOR_GOVERNANCE_REVIEW = "ready_for_governance_review"


@dataclass(frozen=True, slots=True)
class PaperOperationPolicy:
    """Versioned minimum evidence and operational-quality requirements."""

    version: str = "paper-operation-evidence.v1"
    minimum_observation_days: int = 60
    minimum_distinct_regimes: int = 2
    minimum_completed_cycles: int = 40
    minimum_decisions: int = 20
    minimum_confidence_samples: int = 20
    minimum_paper_execution_batches: int = 10
    minimum_alert_feedback_samples: int = 10
    minimum_cycle_completion_rate: float = 0.98
    minimum_evaluation_coverage: float = 0.95
    minimum_thesis_review_coverage: float = 0.95
    minimum_implementation_completion_rate: float = 0.95
    minimum_reconciliation_rate: float = 1.0
    maximum_alert_false_positive_rate: float = 0.20
    maximum_mean_brier_score: float = 0.25
    maximum_calibration_error: float = 0.10
    maximum_critical_slo_breaches: int = 0
    maximum_unresolved_incidents: int = 0
    maximum_data_integrity_failures: int = 0
    maximum_reconciliation_failures: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _required_text(self.version, field_name="version"))
        for field_name in (
            "minimum_observation_days",
            "minimum_distinct_regimes",
            "minimum_completed_cycles",
            "minimum_decisions",
            "minimum_confidence_samples",
            "minimum_paper_execution_batches",
            "minimum_alert_feedback_samples",
        ):
            object.__setattr__(
                self,
                field_name,
                _integer(getattr(self, field_name), field_name=field_name, minimum=1),
            )
        for field_name in (
            "minimum_cycle_completion_rate",
            "minimum_evaluation_coverage",
            "minimum_thesis_review_coverage",
            "minimum_implementation_completion_rate",
            "minimum_reconciliation_rate",
            "maximum_alert_false_positive_rate",
            "maximum_mean_brier_score",
            "maximum_calibration_error",
        ):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        for field_name in (
            "maximum_critical_slo_breaches",
            "maximum_unresolved_incidents",
            "maximum_data_integrity_failures",
            "maximum_reconciliation_failures",
        ):
            object.__setattr__(
                self,
                field_name,
                _integer(getattr(self, field_name), field_name=field_name),
            )

    def to_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperOperationPolicy":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown paper-operation policy fields: {sorted(unknown)}")
        return cls(**dict(payload))


@dataclass(frozen=True, slots=True)
class PaperOperationObservation:
    """One immutable period of point-in-time paper-operation evidence."""

    identifier: str
    period_start: datetime
    period_end: datetime
    observed_at: datetime
    regime: str
    expected_full_universe_cycles: int
    completed_full_universe_cycles: int
    decision_count: int
    action_decision_count: int
    abstention_decision_count: int
    evaluations_due: int
    evaluations_completed: int
    confidence_sample_count: int
    brier_score_sum: float
    calibration_absolute_error_sum: float
    paper_execution_batches: int
    paper_execution_completed: int
    paper_execution_reconciled: int
    paper_execution_failed: int
    turnover: float
    transaction_cost_return: float
    thesis_reviews_due: int
    thesis_reviews_completed: int
    theses_strengthening: int
    theses_stable: int
    theses_weakening: int
    theses_invalidated: int
    alerts_generated: int
    alerts_sent: int
    alerts_suppressed: int
    alerts_acknowledged: int
    alerts_useful: int
    alerts_false_positive: int
    portfolio_return: float
    benchmark_return: float
    cash_return: float
    passive_return: float
    critical_slo_breaches: int = 0
    unresolved_incidents: int = 0
    data_integrity_failures: int = 0
    reconciliation_failures: int = 0
    evidence_identifiers: tuple[str, ...] = ()
    schema_version: str = "paper-operation-observation.v1"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "regime", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("period_start", "period_end", "observed_at"):
            object.__setattr__(self, field_name, _aware(getattr(self, field_name), field_name=field_name))
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot predate period_start")
        if self.observed_at < self.period_end:
            raise ValueError("observed_at cannot predate period_end")
        integer_fields = (
            "expected_full_universe_cycles",
            "completed_full_universe_cycles",
            "decision_count",
            "action_decision_count",
            "abstention_decision_count",
            "evaluations_due",
            "evaluations_completed",
            "confidence_sample_count",
            "paper_execution_batches",
            "paper_execution_completed",
            "paper_execution_reconciled",
            "paper_execution_failed",
            "thesis_reviews_due",
            "thesis_reviews_completed",
            "theses_strengthening",
            "theses_stable",
            "theses_weakening",
            "theses_invalidated",
            "alerts_generated",
            "alerts_sent",
            "alerts_suppressed",
            "alerts_acknowledged",
            "alerts_useful",
            "alerts_false_positive",
            "critical_slo_breaches",
            "unresolved_incidents",
            "data_integrity_failures",
            "reconciliation_failures",
        )
        for field_name in integer_fields:
            object.__setattr__(self, field_name, _integer(getattr(self, field_name), field_name=field_name))
        if self.completed_full_universe_cycles > self.expected_full_universe_cycles:
            raise ValueError("completed cycles cannot exceed expected cycles")
        if self.action_decision_count + self.abstention_decision_count != self.decision_count:
            raise ValueError("action and abstention counts must equal decision_count")
        if self.evaluations_completed > self.evaluations_due:
            raise ValueError("evaluations_completed cannot exceed evaluations_due")
        if self.paper_execution_completed > self.paper_execution_batches:
            raise ValueError("paper_execution_completed cannot exceed paper_execution_batches")
        if self.paper_execution_reconciled > self.paper_execution_completed:
            raise ValueError("paper_execution_reconciled cannot exceed completed executions")
        if self.paper_execution_failed > self.paper_execution_batches:
            raise ValueError("paper_execution_failed cannot exceed paper execution batches")
        if self.thesis_reviews_completed > self.thesis_reviews_due:
            raise ValueError("thesis_reviews_completed cannot exceed thesis_reviews_due")
        if self.alerts_sent + self.alerts_suppressed > self.alerts_generated:
            raise ValueError("sent and suppressed alerts cannot exceed generated alerts")
        if self.alerts_acknowledged > self.alerts_sent:
            raise ValueError("acknowledged alerts cannot exceed sent alerts")
        if self.alerts_useful + self.alerts_false_positive > self.alerts_acknowledged:
            raise ValueError("alert feedback counts cannot exceed acknowledged alerts")
        object.__setattr__(self, "brier_score_sum", _number(self.brier_score_sum, field_name="brier_score_sum", minimum=0.0))
        object.__setattr__(
            self,
            "calibration_absolute_error_sum",
            _number(self.calibration_absolute_error_sum, field_name="calibration_absolute_error_sum", minimum=0.0),
        )
        if self.confidence_sample_count == 0 and (
            self.brier_score_sum > _EPSILON or self.calibration_absolute_error_sum > _EPSILON
        ):
            raise ValueError("calibration sums require confidence samples")
        if self.confidence_sample_count > 0:
            if self.brier_score_sum > self.confidence_sample_count + _EPSILON:
                raise ValueError("brier_score_sum cannot exceed sample count")
            if self.calibration_absolute_error_sum > self.confidence_sample_count + _EPSILON:
                raise ValueError("calibration error sum cannot exceed sample count")
        object.__setattr__(self, "turnover", _number(self.turnover, field_name="turnover", minimum=0.0))
        object.__setattr__(
            self,
            "transaction_cost_return",
            _number(self.transaction_cost_return, field_name="transaction_cost_return", minimum=0.0),
        )
        for field_name in ("portfolio_return", "benchmark_return", "cash_return", "passive_return"):
            object.__setattr__(self, field_name, _return(getattr(self, field_name), field_name=field_name))
        object.__setattr__(
            self,
            "evidence_identifiers",
            _text_tuple(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )

    @property
    def alert_feedback_count(self) -> int:
        return self.alerts_useful + self.alerts_false_positive

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, datetime):
                payload[field_name] = value.isoformat()
            elif isinstance(value, tuple):
                payload[field_name] = list(value)
            else:
                payload[field_name] = value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperOperationObservation":
        values = dict(payload)
        for field_name in ("period_start", "period_end", "observed_at"):
            values[field_name] = datetime.fromisoformat(str(values[field_name]))
        values["evidence_identifiers"] = tuple(str(item) for item in values.get("evidence_identifiers", ()))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class PaperOperationEvidenceReport:
    identifier: str
    evaluated_at: datetime
    policy_version: str
    status: PaperOperationReadiness
    period_start: datetime | None
    period_end: datetime | None
    observation_count: int
    observation_days: int
    regimes: tuple[str, ...]
    expected_full_universe_cycles: int
    completed_full_universe_cycles: int
    cycle_completion_rate: float | None
    decision_count: int
    action_decision_count: int
    abstention_decision_count: int
    evaluations_due: int
    evaluations_completed: int
    evaluation_coverage: float | None
    confidence_sample_count: int
    mean_brier_score: float | None
    calibration_error: float | None
    paper_execution_batches: int
    paper_execution_completed: int
    implementation_completion_rate: float | None
    paper_execution_reconciled: int
    reconciliation_rate: float | None
    paper_execution_failed: int
    thesis_reviews_due: int
    thesis_reviews_completed: int
    thesis_review_coverage: float | None
    alert_feedback_count: int
    alert_useful_rate: float | None
    alert_false_positive_rate: float | None
    compounded_portfolio_return: float
    compounded_benchmark_return: float
    compounded_cash_return: float
    compounded_passive_return: float
    portfolio_return_vs_benchmark: float
    portfolio_return_vs_cash: float
    portfolio_return_vs_passive: float
    maximum_drawdown: float
    total_turnover: float
    total_transaction_cost_return: float
    critical_slo_breaches: int
    unresolved_incidents: int
    data_integrity_failures: int
    reconciliation_failures: int
    blockers: tuple[str, ...]
    insufficiencies: tuple[str, ...]
    diagnostics: tuple[str, ...]
    real_money_authorized: bool = False
    performance_claims_permitted: bool = False
    schema_version: str = "paper-operation-evidence-report.v1"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "policy_version", "schema_version"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "evaluated_at", _aware(self.evaluated_at, field_name="evaluated_at"))
        if not isinstance(self.status, PaperOperationReadiness):
            raise TypeError("status must be PaperOperationReadiness")
        if self.real_money_authorized or self.performance_claims_permitted:
            raise ValueError("paper evidence cannot authorize live money or performance claims")
        for field_name in ("regimes", "blockers", "insufficiencies", "diagnostics"):
            object.__setattr__(self, field_name, _text_tuple(getattr(self, field_name), field_name=field_name))

    @property
    def ready_for_governance_review(self) -> bool:
        return self.status is PaperOperationReadiness.READY_FOR_GOVERNANCE_REVIEW

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, datetime):
                payload[field_name] = value.isoformat()
            elif isinstance(value, Enum):
                payload[field_name] = value.value
            elif isinstance(value, tuple):
                payload[field_name] = list(value)
            else:
                payload[field_name] = value
        payload["ready_for_governance_review"] = self.ready_for_governance_review
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PaperOperationEvidenceReport":
        values = dict(payload)
        values.pop("ready_for_governance_review", None)
        values["evaluated_at"] = datetime.fromisoformat(str(values["evaluated_at"]))
        values["period_start"] = None if values.get("period_start") is None else datetime.fromisoformat(str(values["period_start"]))
        values["period_end"] = None if values.get("period_end") is None else datetime.fromisoformat(str(values["period_end"]))
        values["status"] = PaperOperationReadiness(str(values["status"]))
        for field_name in ("regimes", "blockers", "insufficiencies", "diagnostics"):
            values[field_name] = tuple(str(item) for item in values.get(field_name, ()))
        return cls(**values)


class PaperOperationEvidenceEvaluator:
    """Aggregate immutable observations under one versioned release policy."""

    def __init__(self, policy: PaperOperationPolicy | None = None) -> None:
        self.policy = policy or PaperOperationPolicy()

    def evaluate(
        self,
        observations: Iterable[PaperOperationObservation],
        *,
        evaluated_at: datetime | None = None,
    ) -> PaperOperationEvidenceReport:
        now = _aware(evaluated_at or datetime.now(timezone.utc), field_name="evaluated_at")
        ordered = tuple(sorted(observations, key=lambda item: (item.period_start, item.identifier)))
        identifiers = [item.identifier for item in ordered]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("paper-operation observation identifiers must be unique")
        if any(item.observed_at > now for item in ordered):
            raise ValueError("observations cannot be known after evaluated_at")
        self._validate_periods(ordered)

        sums = self._sums(ordered)
        days = len({day for item in ordered for day in self._days(item.period_start, item.period_end)})
        regimes = tuple(sorted({item.regime for item in ordered}))
        cycle_rate = _safe_rate(sums["completed_full_universe_cycles"], sums["expected_full_universe_cycles"])
        evaluation_coverage = _safe_rate(sums["evaluations_completed"], sums["evaluations_due"])
        implementation_rate = _safe_rate(sums["paper_execution_completed"], sums["paper_execution_batches"])
        reconciliation_rate = _safe_rate(sums["paper_execution_reconciled"], sums["paper_execution_completed"])
        thesis_coverage = _safe_rate(sums["thesis_reviews_completed"], sums["thesis_reviews_due"])
        feedback_count = sums["alerts_useful"] + sums["alerts_false_positive"]
        useful_rate = _safe_rate(sums["alerts_useful"], feedback_count)
        false_positive_rate = _safe_rate(sums["alerts_false_positive"], feedback_count)
        mean_brier = (
            None
            if sums["confidence_sample_count"] == 0
            else round(sums["brier_score_sum"] / sums["confidence_sample_count"], 12)
        )
        calibration_error = (
            None
            if sums["confidence_sample_count"] == 0
            else round(sums["calibration_absolute_error_sum"] / sums["confidence_sample_count"], 12)
        )

        blockers = self._blockers(
            sums=sums,
            cycle_rate=cycle_rate,
            evaluation_coverage=evaluation_coverage,
            implementation_rate=implementation_rate,
            reconciliation_rate=reconciliation_rate,
            thesis_coverage=thesis_coverage,
            false_positive_rate=false_positive_rate,
            feedback_count=feedback_count,
            mean_brier=mean_brier,
            calibration_error=calibration_error,
        )
        insufficiencies = self._insufficiencies(
            days=days,
            regimes=regimes,
            sums=sums,
            feedback_count=feedback_count,
        )
        if blockers:
            status = PaperOperationReadiness.BLOCKED
        elif insufficiencies:
            status = PaperOperationReadiness.INSUFFICIENT_EVIDENCE
        else:
            status = PaperOperationReadiness.READY_FOR_GOVERNANCE_REVIEW

        portfolio_return = _compound(item.portfolio_return for item in ordered)
        benchmark_return = _compound(item.benchmark_return for item in ordered)
        cash_return = _compound(item.cash_return for item in ordered)
        passive_return = _compound(item.passive_return for item in ordered)
        diagnostics = (
            "Benchmark and cash comparisons are diagnostic evidence, not automatic approval criteria.",
            "Ready for governance review does not authorize real-money execution.",
            "Performance claims remain prohibited until independent governance and disclosure review.",
        )
        period_start = None if not ordered else min(item.period_start for item in ordered)
        period_end = None if not ordered else max(item.period_end for item in ordered)
        report_identifier = self._report_identifier(now, ordered)
        return PaperOperationEvidenceReport(
            identifier=report_identifier,
            evaluated_at=now,
            policy_version=self.policy.version,
            status=status,
            period_start=period_start,
            period_end=period_end,
            observation_count=len(ordered),
            observation_days=days,
            regimes=regimes,
            expected_full_universe_cycles=sums["expected_full_universe_cycles"],
            completed_full_universe_cycles=sums["completed_full_universe_cycles"],
            cycle_completion_rate=cycle_rate,
            decision_count=sums["decision_count"],
            action_decision_count=sums["action_decision_count"],
            abstention_decision_count=sums["abstention_decision_count"],
            evaluations_due=sums["evaluations_due"],
            evaluations_completed=sums["evaluations_completed"],
            evaluation_coverage=evaluation_coverage,
            confidence_sample_count=sums["confidence_sample_count"],
            mean_brier_score=mean_brier,
            calibration_error=calibration_error,
            paper_execution_batches=sums["paper_execution_batches"],
            paper_execution_completed=sums["paper_execution_completed"],
            implementation_completion_rate=implementation_rate,
            paper_execution_reconciled=sums["paper_execution_reconciled"],
            reconciliation_rate=reconciliation_rate,
            paper_execution_failed=sums["paper_execution_failed"],
            thesis_reviews_due=sums["thesis_reviews_due"],
            thesis_reviews_completed=sums["thesis_reviews_completed"],
            thesis_review_coverage=thesis_coverage,
            alert_feedback_count=feedback_count,
            alert_useful_rate=useful_rate,
            alert_false_positive_rate=false_positive_rate,
            compounded_portfolio_return=portfolio_return,
            compounded_benchmark_return=benchmark_return,
            compounded_cash_return=cash_return,
            compounded_passive_return=passive_return,
            portfolio_return_vs_benchmark=round(portfolio_return - benchmark_return, 12),
            portfolio_return_vs_cash=round(portfolio_return - cash_return, 12),
            portfolio_return_vs_passive=round(portfolio_return - passive_return, 12),
            maximum_drawdown=_maximum_drawdown(item.portfolio_return for item in ordered),
            total_turnover=round(sum(item.turnover for item in ordered), 12),
            total_transaction_cost_return=round(sum(item.transaction_cost_return for item in ordered), 12),
            critical_slo_breaches=sums["critical_slo_breaches"],
            unresolved_incidents=sums["unresolved_incidents"],
            data_integrity_failures=sums["data_integrity_failures"],
            reconciliation_failures=sums["reconciliation_failures"],
            blockers=tuple(blockers),
            insufficiencies=tuple(insufficiencies),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _days(start: datetime, end: datetime) -> tuple[date, ...]:
        result: list[date] = []
        current = start.date()
        terminal = end.date()
        while current <= terminal:
            result.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return tuple(result)

    @staticmethod
    def _validate_periods(observations: tuple[PaperOperationObservation, ...]) -> None:
        previous_end: datetime | None = None
        for item in observations:
            if previous_end is not None and item.period_start <= previous_end:
                raise ValueError("paper-operation observation periods cannot overlap")
            previous_end = item.period_end

    @staticmethod
    def _sums(observations: tuple[PaperOperationObservation, ...]) -> dict[str, Any]:
        fields = (
            "expected_full_universe_cycles", "completed_full_universe_cycles",
            "decision_count", "action_decision_count", "abstention_decision_count",
            "evaluations_due", "evaluations_completed", "confidence_sample_count",
            "brier_score_sum", "calibration_absolute_error_sum",
            "paper_execution_batches", "paper_execution_completed",
            "paper_execution_reconciled", "paper_execution_failed",
            "thesis_reviews_due", "thesis_reviews_completed",
            "alerts_useful", "alerts_false_positive", "critical_slo_breaches",
            "unresolved_incidents", "data_integrity_failures", "reconciliation_failures",
        )
        return {field_name: sum(getattr(item, field_name) for item in observations) for field_name in fields}

    def _blockers(
        self,
        *,
        sums: Mapping[str, Any],
        cycle_rate: float | None,
        evaluation_coverage: float | None,
        implementation_rate: float | None,
        reconciliation_rate: float | None,
        thesis_coverage: float | None,
        false_positive_rate: float | None,
        feedback_count: int,
        mean_brier: float | None,
        calibration_error: float | None,
    ) -> list[str]:
        policy = self.policy
        blockers: list[str] = []
        count_checks = (
            ("critical SLO breaches", sums["critical_slo_breaches"], policy.maximum_critical_slo_breaches),
            ("unresolved incidents", sums["unresolved_incidents"], policy.maximum_unresolved_incidents),
            ("data-integrity failures", sums["data_integrity_failures"], policy.maximum_data_integrity_failures),
            ("paper-ledger reconciliation failures", sums["reconciliation_failures"], policy.maximum_reconciliation_failures),
        )
        for label, actual, maximum in count_checks:
            if actual > maximum:
                blockers.append(f"{label} {actual} exceed policy maximum {maximum}")
        rate_checks = (
            ("full-universe cycle completion", cycle_rate, policy.minimum_cycle_completion_rate),
            ("decision evaluation coverage", evaluation_coverage, policy.minimum_evaluation_coverage),
            ("thesis review coverage", thesis_coverage, policy.minimum_thesis_review_coverage),
            ("paper implementation completion", implementation_rate, policy.minimum_implementation_completion_rate),
            ("paper reconciliation", reconciliation_rate, policy.minimum_reconciliation_rate),
        )
        for label, actual, minimum in rate_checks:
            if actual is not None and actual + _EPSILON < minimum:
                blockers.append(f"{label} {actual:.4f} is below policy minimum {minimum:.4f}")
        if feedback_count >= policy.minimum_alert_feedback_samples and false_positive_rate is not None:
            if false_positive_rate - _EPSILON > policy.maximum_alert_false_positive_rate:
                blockers.append(
                    f"alert false-positive rate {false_positive_rate:.4f} exceeds policy maximum "
                    f"{policy.maximum_alert_false_positive_rate:.4f}"
                )
        if sums["confidence_sample_count"] >= policy.minimum_confidence_samples:
            if mean_brier is not None and mean_brier - _EPSILON > policy.maximum_mean_brier_score:
                blockers.append(
                    f"mean Brier score {mean_brier:.4f} exceeds policy maximum "
                    f"{policy.maximum_mean_brier_score:.4f}"
                )
            if calibration_error is not None and calibration_error - _EPSILON > policy.maximum_calibration_error:
                blockers.append(
                    f"calibration error {calibration_error:.4f} exceeds policy maximum "
                    f"{policy.maximum_calibration_error:.4f}"
                )
        return blockers

    def _insufficiencies(
        self,
        *,
        days: int,
        regimes: tuple[str, ...],
        sums: Mapping[str, Any],
        feedback_count: int,
    ) -> list[str]:
        policy = self.policy
        checks = (
            ("observation days", days, policy.minimum_observation_days),
            ("distinct regimes", len(regimes), policy.minimum_distinct_regimes),
            ("completed full-universe cycles", sums["completed_full_universe_cycles"], policy.minimum_completed_cycles),
            ("CIO decisions", sums["decision_count"], policy.minimum_decisions),
            ("confidence samples", sums["confidence_sample_count"], policy.minimum_confidence_samples),
            ("paper execution batches", sums["paper_execution_batches"], policy.minimum_paper_execution_batches),
            ("alert feedback samples", feedback_count, policy.minimum_alert_feedback_samples),
        )
        return [f"{label} {actual} are below required minimum {minimum}" for label, actual, minimum in checks if actual < minimum]

    def _report_identifier(
        self,
        evaluated_at: datetime,
        observations: tuple[PaperOperationObservation, ...],
    ) -> str:
        content = {
            "evaluated_at": evaluated_at.isoformat(),
            "policy_version": self.policy.version,
            "observations": [item.identifier for item in observations],
        }
        digest = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()[:24]
        return f"paper-operation-report:{digest}"


class PaperOperationEvidenceIntegrityError(RuntimeError):
    """Raised when append-only paper-operation history fails verification."""


class SQLitePaperOperationEvidenceStore:
    """Independent append-only chains for observations and assessments."""

    _GENESIS_HASH = "0" * 64
    _OBSERVATION_TABLE = "paper_operation_observations"
    _REPORT_TABLE = "paper_operation_reports"

    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        self.path = Path(path)
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._OBSERVATION_TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_operation_observed_at
                ON {self._OBSERVATION_TABLE} (occurred_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._OBSERVATION_TABLE}_no_update
                BEFORE UPDATE ON {self._OBSERVATION_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'paper-operation observation history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._OBSERVATION_TABLE}_no_delete
                BEFORE DELETE ON {self._OBSERVATION_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'paper-operation observation history is append-only');
                END;

                CREATE TABLE IF NOT EXISTS {self._REPORT_TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_operation_report_at
                ON {self._REPORT_TABLE} (occurred_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._REPORT_TABLE}_no_update
                BEFORE UPDATE ON {self._REPORT_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'paper-operation report history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._REPORT_TABLE}_no_delete
                BEFORE DELETE ON {self._REPORT_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'paper-operation report history is append-only');
                END;
                """
            )

    def append_observation(self, observation: PaperOperationObservation) -> PaperOperationObservation:
        if not isinstance(observation, PaperOperationObservation):
            raise TypeError("observation must be PaperOperationObservation")
        self._append(
            table=self._OBSERVATION_TABLE,
            identifier=observation.identifier,
            occurred_at=observation.observed_at,
            payload=observation.to_dict(),
        )
        return observation

    def append_report(self, report: PaperOperationEvidenceReport) -> PaperOperationEvidenceReport:
        if not isinstance(report, PaperOperationEvidenceReport):
            raise TypeError("report must be PaperOperationEvidenceReport")
        self._append(
            table=self._REPORT_TABLE,
            identifier=report.identifier,
            occurred_at=report.evaluated_at,
            payload=report.to_dict(),
        )
        return report

    def observations(self, *, limit: int = 10000) -> tuple[PaperOperationObservation, ...]:
        rows = self._rows(self._OBSERVATION_TABLE, limit=limit)
        return tuple(PaperOperationObservation.from_dict(json.loads(str(row["payload_json"]))) for row in rows)

    def reports(self, *, limit: int = 1000) -> tuple[PaperOperationEvidenceReport, ...]:
        rows = self._rows(self._REPORT_TABLE, limit=limit)
        return tuple(PaperOperationEvidenceReport.from_dict(json.loads(str(row["payload_json"]))) for row in rows)

    def latest_report(self) -> PaperOperationEvidenceReport | None:
        reports = self.reports(limit=1)
        return None if not reports else reports[0]

    def verify_integrity(self) -> bool:
        if not self.path.exists():
            return True
        with self._connect() as connection:
            for table in (self._OBSERVATION_TABLE, self._REPORT_TABLE):
                if not self._has_table(connection, table):
                    continue
                previous_hash = self._GENESIS_HASH
                expected_sequence = 1
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY sequence ASC").fetchall():
                    if int(row["sequence"]) != expected_sequence:
                        raise PaperOperationEvidenceIntegrityError(f"{table} sequence is not contiguous")
                    if str(row["previous_hash"]) != previous_hash:
                        raise PaperOperationEvidenceIntegrityError(f"{table} previous hash does not match")
                    expected_hash = self._hash(
                        str(row["identifier"]),
                        datetime.fromisoformat(str(row["occurred_at"])),
                        str(row["payload_json"]),
                        previous_hash,
                    )
                    if str(row["content_hash"]) != expected_hash:
                        raise PaperOperationEvidenceIntegrityError(f"{table} content hash does not match")
                    previous_hash = expected_hash
                    expected_sequence += 1
        return True

    def _append(
        self,
        *,
        table: str,
        identifier: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        self._initialize()
        self.verify_integrity()
        payload_json = _canonical_json(payload)
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {table} WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError("paper-operation identifier cannot be reused for different content")
                return
            previous = connection.execute(
                f"SELECT content_hash FROM {table} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = self._GENESIS_HASH if previous is None else str(previous["content_hash"])
            content_hash = self._hash(identifier, occurred_at, payload_json, previous_hash)
            connection.execute(
                f"""
                INSERT INTO {table} (
                    identifier, occurred_at, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (identifier, occurred_at.isoformat(), payload_json, previous_hash, content_hash),
            )

    def _rows(self, table: str, *, limit: int) -> tuple[sqlite3.Row, ...]:
        _integer(limit, field_name="limit", minimum=1)
        if not self.path.exists():
            return ()
        with self._connect() as connection:
            if not self._has_table(connection, table):
                return ()
            rows = connection.execute(
                f"SELECT payload_json FROM {table} ORDER BY occurred_at DESC, sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(rows)

    @staticmethod
    def _has_table(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _hash(identifier: str, occurred_at: datetime, payload_json: str, previous_hash: str) -> str:
        content = "|".join((identifier, occurred_at.isoformat(), payload_json, previous_hash))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def observation_from_payload(payload: Mapping[str, Any]) -> PaperOperationObservation:
    return PaperOperationObservation.from_dict(payload)


def policy_from_payload(payload: Mapping[str, Any]) -> PaperOperationPolicy:
    return PaperOperationPolicy.from_dict(payload)


__all__ = [
    "PaperOperationEvidenceEvaluator",
    "PaperOperationEvidenceIntegrityError",
    "PaperOperationEvidenceReport",
    "PaperOperationObservation",
    "PaperOperationPolicy",
    "PaperOperationReadiness",
    "SQLitePaperOperationEvidenceStore",
    "observation_from_payload",
    "policy_from_payload",
]
