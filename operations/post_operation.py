"""Publish operational-readiness evidence after a daily operation is terminal.

The canonical daily workflow cannot evaluate itself from inside one of its own
stages.  This publisher runs only after ``CanonicalDailyOperationsOrchestrator``
returns a terminal result.  It binds the operation to one explicit test baseline
and delegates factual assembly to ``OperationalReadinessAssembler``.  It cannot
approve a readiness gate or alter the completed operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from operations.daily_orchestration import (
    CanonicalDailyOperationRequest,
    CanonicalDailyOperationResult,
    DailyOperationStatus,
)
from operations.readiness import (
    OperationalReadinessAssembler,
    OperationalReadinessAssemblyResult,
)


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


@dataclass(frozen=True, slots=True)
class PostOperationReadinessPublication:
    """One immutable publication result linked to one terminal daily operation."""

    operation_identifier: str
    operation_status: DailyOperationStatus
    baseline_identifier: str
    published_at: datetime
    assembly: OperationalReadinessAssemblyResult
    schema_version: str = "post-operation-readiness-publication.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "operation_identifier",
            "baseline_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.operation_status, DailyOperationStatus):
            raise TypeError("operation_status must be DailyOperationStatus")
        if self.operation_status not in {
            DailyOperationStatus.COMPLETED,
            DailyOperationStatus.FAILED,
        }:
            raise ValueError("post-operation publication requires a terminal status")
        _aware(self.published_at, field_name="published_at")
        if not isinstance(self.assembly, OperationalReadinessAssemblyResult):
            raise TypeError(
                "assembly must be OperationalReadinessAssemblyResult"
            )
        if (
            self.assembly.daily_operation_identifier
            != self.operation_identifier
        ):
            raise ValueError(
                "operational readiness must resolve the same daily operation"
            )
        if (
            self.assembly.snapshot.baseline_identifier
            != self.baseline_identifier
        ):
            raise ValueError(
                "operational readiness baseline does not match publication"
            )

    @property
    def clean(self) -> bool:
        return not self.assembly.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_identifier": self.operation_identifier,
            "operation_status": self.operation_status.value,
            "baseline_identifier": self.baseline_identifier,
            "published_at": self.published_at.isoformat(),
            "clean": self.clean,
            "assembly": self.assembly.to_dict(),
            "schema_version": self.schema_version,
            "real_money_authorized": False,
        }


class PostOperationReadinessPublisher:
    """Publish factual operational evidence after a terminal operation."""

    def __init__(
        self,
        *,
        assembler: OperationalReadinessAssembler,
        baseline_identifier: str,
    ) -> None:
        if not isinstance(assembler, OperationalReadinessAssembler):
            raise TypeError("assembler must be OperationalReadinessAssembler")
        self.assembler = assembler
        self.baseline_identifier = _text(
            baseline_identifier,
            field_name="baseline_identifier",
        )

    def publish(
        self,
        request: CanonicalDailyOperationRequest,
        result: CanonicalDailyOperationResult,
        *,
        published_at: datetime,
    ) -> PostOperationReadinessPublication:
        if not isinstance(request, CanonicalDailyOperationRequest):
            raise TypeError("request must be CanonicalDailyOperationRequest")
        if not isinstance(result, CanonicalDailyOperationResult):
            raise TypeError("result must be CanonicalDailyOperationResult")
        timestamp = _aware(published_at, field_name="published_at")
        if result.identifier != request.identifier:
            raise ValueError("operation result does not match request")
        if result.status not in {
            DailyOperationStatus.COMPLETED,
            DailyOperationStatus.FAILED,
        }:
            raise ValueError("operation result is not terminal")
        if self.baseline_identifier not in request.input_identifiers:
            raise ValueError(
                "test baseline must be an immutable daily-operation input"
            )
        assembly = self.assembler.assemble(
            assessed_at=timestamp,
            baseline_identifier=self.baseline_identifier,
            process_version=request.process_version,
            code_version=request.code_version,
        )
        return PostOperationReadinessPublication(
            operation_identifier=request.identifier,
            operation_status=result.status,
            baseline_identifier=self.baseline_identifier,
            published_at=timestamp,
            assembly=assembly,
        )


__all__ = [
    "PostOperationReadinessPublication",
    "PostOperationReadinessPublisher",
]
