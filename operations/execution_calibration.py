"""Calibrate paper-execution prices against representative market evidence.

Calibration compares the execution model's fill price with an independently
observed benchmark for the same instrument, side, venue, and timestamp. The
result is evidence only: it cannot authorize trading or upgrade a data license.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ExecutionCalibrationError(RuntimeError):
    """Raised when calibration evidence is invalid."""


class ExecutionCalibrationState(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class ExecutionSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(value: object, *, field_name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if positive and normalized <= 0:
        raise ValueError(f"{field_name} must be positive")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class ExecutionCalibrationPolicy:
    version: str = "paper-execution-calibration-policy.v1"
    minimum_samples: int = 12
    minimum_asset_classes: int = 3
    maximum_mean_absolute_error_bps: float = 15.0
    maximum_p95_absolute_error_bps: float = 25.0
    maximum_single_sample_error_bps: float = 50.0
    maximum_quote_age_seconds: int = 60

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        for field_name in (
            "minimum_samples",
            "minimum_asset_classes",
            "maximum_quote_age_seconds",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in (
            "maximum_mean_absolute_error_bps",
            "maximum_p95_absolute_error_bps",
            "maximum_single_sample_error_bps",
        ):
            value = _number(getattr(self, field_name), field_name=field_name)
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")
            object.__setattr__(self, field_name, value)
        if self.maximum_mean_absolute_error_bps > self.maximum_p95_absolute_error_bps:
            raise ValueError("mean error threshold cannot exceed p95 threshold")
        if self.maximum_p95_absolute_error_bps > self.maximum_single_sample_error_bps:
            raise ValueError("p95 threshold cannot exceed single-sample threshold")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionCalibrationPolicy":
        unknown = sorted(set(value) - set(cls.__dataclass_fields__))
        if unknown:
            raise ValueError(f"unknown execution calibration policy fields: {unknown}")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ExecutionCalibrationSample:
    identifier: str
    instrument_identifier: str
    asset_class: str
    venue: str
    provider: str
    observed_at: datetime
    modeled_at: datetime
    side: ExecutionSide
    bid: float
    ask: float
    benchmark_fill_price: float
    modeled_fill_price: float
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "instrument_identifier",
            "asset_class",
            "venue",
            "provider",
            "source_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.observed_at, field_name="observed_at")
        _aware(self.modeled_at, field_name="modeled_at")
        if self.modeled_at < self.observed_at:
            raise ValueError("modeled_at cannot predate observed_at")
        if not isinstance(self.side, ExecutionSide):
            raise TypeError("side must be ExecutionSide")
        for field_name in (
            "bid",
            "ask",
            "benchmark_fill_price",
            "modeled_fill_price",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name, positive=True),
            )
        if self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def benchmark_cost_bps(self) -> float:
        direction = 1.0 if self.side is ExecutionSide.BUY else -1.0
        return direction * (self.benchmark_fill_price - self.midpoint) / self.midpoint * 10_000

    @property
    def modeled_cost_bps(self) -> float:
        direction = 1.0 if self.side is ExecutionSide.BUY else -1.0
        return direction * (self.modeled_fill_price - self.midpoint) / self.midpoint * 10_000

    @property
    def absolute_error_bps(self) -> float:
        return abs(self.modeled_cost_bps - self.benchmark_cost_bps)

    @property
    def quote_age_seconds(self) -> int:
        return max(0, int((self.modeled_at - self.observed_at).total_seconds()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "instrument_identifier": self.instrument_identifier,
            "asset_class": self.asset_class,
            "venue": self.venue,
            "provider": self.provider,
            "observed_at": self.observed_at.isoformat(),
            "modeled_at": self.modeled_at.isoformat(),
            "side": self.side.value,
            "bid": self.bid,
            "ask": self.ask,
            "benchmark_fill_price": self.benchmark_fill_price,
            "modeled_fill_price": self.modeled_fill_price,
            "benchmark_cost_bps": round(self.benchmark_cost_bps, 12),
            "modeled_cost_bps": round(self.modeled_cost_bps, 12),
            "absolute_error_bps": round(self.absolute_error_bps, 12),
            "quote_age_seconds": self.quote_age_seconds,
            "source_identifier": self.source_identifier,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionCalibrationSample":
        return cls(
            identifier=str(value["identifier"]),
            instrument_identifier=str(value["instrument_identifier"]),
            asset_class=str(value["asset_class"]),
            venue=str(value["venue"]),
            provider=str(value["provider"]),
            observed_at=datetime.fromisoformat(str(value["observed_at"])),
            modeled_at=datetime.fromisoformat(str(value["modeled_at"])),
            side=ExecutionSide(str(value["side"])),
            bid=float(value["bid"]),
            ask=float(value["ask"]),
            benchmark_fill_price=float(value["benchmark_fill_price"]),
            modeled_fill_price=float(value["modeled_fill_price"]),
            source_identifier=str(value["source_identifier"]),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCalibrationReport:
    identifier: str
    evaluated_at: datetime
    state: ExecutionCalibrationState
    policy_version: str
    execution_policy_version: str
    sample_count: int
    asset_class_count: int
    reconciled_sample_count: int
    stale_sample_count: int
    mean_absolute_error_bps: float
    p95_absolute_error_bps: float
    maximum_absolute_error_bps: float
    blockers: tuple[str, ...]
    sample_identifiers: tuple[str, ...]
    source_identifiers: tuple[str, ...]
    schema_version: str = "paper-execution-calibration-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "policy_version",
            "execution_policy_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.state, ExecutionCalibrationState):
            raise TypeError("state must be ExecutionCalibrationState")
        for field_name in (
            "sample_count",
            "asset_class_count",
            "reconciled_sample_count",
            "stale_sample_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        for field_name in (
            "mean_absolute_error_bps",
            "p95_absolute_error_bps",
            "maximum_absolute_error_bps",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("blockers", "sample_identifiers", "source_identifiers"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(value) != len(set(value)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        if self.state is ExecutionCalibrationState.PASSED and self.blockers:
            raise ValueError("passed calibration cannot contain blockers")
        if self.state is ExecutionCalibrationState.BLOCKED and not self.blockers:
            raise ValueError("blocked calibration requires blockers")
        if self.schema_version != "paper-execution-calibration-report.v1":
            raise ValueError("unsupported execution calibration report schema")

    @property
    def passed(self) -> bool:
        return self.state is ExecutionCalibrationState.PASSED

    @property
    def execution_cost_error_bps(self) -> float:
        return self.p95_absolute_error_bps

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "state": self.state.value,
            "policy_version": self.policy_version,
            "execution_policy_version": self.execution_policy_version,
            "sample_count": self.sample_count,
            "asset_class_count": self.asset_class_count,
            "reconciled_sample_count": self.reconciled_sample_count,
            "stale_sample_count": self.stale_sample_count,
            "mean_absolute_error_bps": round(self.mean_absolute_error_bps, 12),
            "p95_absolute_error_bps": round(self.p95_absolute_error_bps, 12),
            "maximum_absolute_error_bps": round(self.maximum_absolute_error_bps, 12),
            "execution_cost_error_bps": round(self.execution_cost_error_bps, 12),
            "blockers": list(self.blockers),
            "sample_identifiers": list(self.sample_identifiers),
            "source_identifiers": list(self.source_identifiers),
            "passed": self.passed,
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }
        payload["content_sha256"] = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionCalibrationReport":
        return cls(
            identifier=str(value["identifier"]),
            evaluated_at=datetime.fromisoformat(str(value["evaluated_at"])),
            state=ExecutionCalibrationState(str(value["state"])),
            policy_version=str(value["policy_version"]),
            execution_policy_version=str(value["execution_policy_version"]),
            sample_count=int(value["sample_count"]),
            asset_class_count=int(value["asset_class_count"]),
            reconciled_sample_count=int(value["reconciled_sample_count"]),
            stale_sample_count=int(value["stale_sample_count"]),
            mean_absolute_error_bps=float(value["mean_absolute_error_bps"]),
            p95_absolute_error_bps=float(value["p95_absolute_error_bps"]),
            maximum_absolute_error_bps=float(value["maximum_absolute_error_bps"]),
            blockers=tuple(str(item) for item in value.get("blockers", ())),
            sample_identifiers=tuple(str(item) for item in value["sample_identifiers"]),
            source_identifiers=tuple(str(item) for item in value["source_identifiers"]),
            schema_version=str(
                value.get("schema_version", "paper-execution-calibration-report.v1")
            ),
        )


class ExecutionCalibrationEvaluator:
    def __init__(self, policy: ExecutionCalibrationPolicy | None = None) -> None:
        self.policy = policy or ExecutionCalibrationPolicy()

    def evaluate(
        self,
        *,
        identifier: str,
        execution_policy_version: str,
        samples: tuple[ExecutionCalibrationSample, ...],
        evaluated_at: datetime,
    ) -> ExecutionCalibrationReport:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        report_identifier = _text(identifier, field_name="identifier")
        policy_version = _text(
            execution_policy_version,
            field_name="execution_policy_version",
        )
        if not isinstance(samples, tuple) or not all(
            isinstance(item, ExecutionCalibrationSample) for item in samples
        ):
            raise TypeError("samples must contain ExecutionCalibrationSample values")
        identifiers = tuple(item.identifier for item in samples)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("calibration sample identifiers cannot contain duplicates")

        blockers: list[str] = []
        stale = tuple(
            item
            for item in samples
            if item.quote_age_seconds > self.policy.maximum_quote_age_seconds
        )
        valid = tuple(item for item in samples if item not in stale)
        asset_classes = tuple(sorted({item.asset_class for item in valid}))
        errors = tuple(item.absolute_error_bps for item in valid)
        mean_error = sum(errors) / len(errors) if errors else 0.0
        p95_error = _percentile(errors, 0.95)
        maximum_error = max(errors, default=0.0)

        if len(samples) < self.policy.minimum_samples:
            blockers.append(
                f"sample_count={len(samples)} is below {self.policy.minimum_samples}"
            )
        if stale:
            blockers.append(f"stale_sample_count={len(stale)}")
        if len(asset_classes) < self.policy.minimum_asset_classes:
            blockers.append(
                f"asset_class_count={len(asset_classes)} is below "
                f"{self.policy.minimum_asset_classes}"
            )
        if mean_error > self.policy.maximum_mean_absolute_error_bps:
            blockers.append(
                f"mean_absolute_error_bps={mean_error:.6f} exceeds "
                f"{self.policy.maximum_mean_absolute_error_bps}"
            )
        if p95_error > self.policy.maximum_p95_absolute_error_bps:
            blockers.append(
                f"p95_absolute_error_bps={p95_error:.6f} exceeds "
                f"{self.policy.maximum_p95_absolute_error_bps}"
            )
        if maximum_error > self.policy.maximum_single_sample_error_bps:
            blockers.append(
                f"maximum_absolute_error_bps={maximum_error:.6f} exceeds "
                f"{self.policy.maximum_single_sample_error_bps}"
            )

        state = (
            ExecutionCalibrationState.PASSED
            if not blockers
            else ExecutionCalibrationState.BLOCKED
        )
        return ExecutionCalibrationReport(
            identifier=report_identifier,
            evaluated_at=timestamp,
            state=state,
            policy_version=self.policy.version,
            execution_policy_version=policy_version,
            sample_count=len(samples),
            asset_class_count=len(asset_classes),
            reconciled_sample_count=len(valid),
            stale_sample_count=len(stale),
            mean_absolute_error_bps=mean_error,
            p95_absolute_error_bps=p95_error,
            maximum_absolute_error_bps=maximum_error,
            blockers=tuple(blockers),
            sample_identifiers=identifiers,
            source_identifiers=tuple(
                dict.fromkeys(item.source_identifier for item in samples)
            ),
        )


def load_execution_calibration_input(
    path: str | Path,
) -> tuple[str, str, tuple[ExecutionCalibrationSample, ...]]:
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExecutionCalibrationError(
            f"cannot read execution calibration input {source}"
        ) from error
    if not isinstance(value, Mapping):
        raise ExecutionCalibrationError("execution calibration input must be an object")
    schema = value.get("schema_version", "paper-execution-calibration-input.v1")
    if schema != "paper-execution-calibration-input.v1":
        raise ExecutionCalibrationError("unsupported execution calibration input schema")
    samples_value = value.get("samples")
    if not isinstance(samples_value, list):
        raise ExecutionCalibrationError("execution calibration samples must be a list")
    return (
        str(value["identifier"]),
        str(value["execution_policy_version"]),
        tuple(ExecutionCalibrationSample.from_dict(item) for item in samples_value),
    )


__all__ = [
    "ExecutionCalibrationError",
    "ExecutionCalibrationEvaluator",
    "ExecutionCalibrationPolicy",
    "ExecutionCalibrationReport",
    "ExecutionCalibrationSample",
    "ExecutionCalibrationState",
    "ExecutionSide",
    "load_execution_calibration_input",
]
