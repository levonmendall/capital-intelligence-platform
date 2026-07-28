"""Reconcile immutable provider backfills before they can support paper testing.

The reconciler verifies the completed backfill manifest, every landed artifact,
provider/query identity, temporal lineage, raw-payload hash, and duplicate logical
windows. It never upgrades licensing or certification and never normalizes a
provider-native payload into investment authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ProviderReconciliationError(RuntimeError):
    """Raised when a backfill or reconciliation input is invalid."""


class ProviderReconciliationState(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProviderReconciliationError(f"cannot read JSON artifact {path}") from error
    if not isinstance(value, dict):
        raise ProviderReconciliationError(f"JSON artifact must encode an object: {path}")
    return value


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderReconciliationError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    return _aware(parsed, field_name=field_name)


def _payload_hash(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProviderReconciliationError("provider payload is not finite JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _payload_item_count(payload: object) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("data", "records", "results", "items", "prices", "symbols"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return len(payload)
    return 0


@dataclass(frozen=True, slots=True)
class ProviderReconciliationReport:
    identifier: str
    evaluated_at: datetime
    state: ProviderReconciliationState
    backfill_report_identifier: str
    plan_identifier: str
    artifact_count: int
    reconciled_artifact_count: int
    payload_item_count: int
    empty_artifact_count: int
    duplicate_logical_window_count: int
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    artifact_hashes: tuple[str, ...]
    schema_version: str = "provider-backfill-reconciliation-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "backfill_report_identifier",
            "plan_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.state, ProviderReconciliationState):
            raise TypeError("state must be ProviderReconciliationState")
        for field_name in (
            "artifact_count",
            "reconciled_artifact_count",
            "payload_item_count",
            "empty_artifact_count",
            "duplicate_logical_window_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        for field_name in ("blockers", "warnings", "artifact_hashes"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
        if len(self.artifact_hashes) != len(set(self.artifact_hashes)):
            raise ValueError("artifact_hashes cannot contain duplicates")
        if self.state is ProviderReconciliationState.PASSED and self.blockers:
            raise ValueError("passed reconciliation cannot contain blockers")
        if self.state is ProviderReconciliationState.BLOCKED and not self.blockers:
            raise ValueError("blocked reconciliation requires blockers")
        if self.schema_version != "provider-backfill-reconciliation-report.v1":
            raise ValueError("unsupported provider reconciliation schema")

    @property
    def passed(self) -> bool:
        return self.state is ProviderReconciliationState.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "state": self.state.value,
            "backfill_report_identifier": self.backfill_report_identifier,
            "plan_identifier": self.plan_identifier,
            "artifact_count": self.artifact_count,
            "reconciled_artifact_count": self.reconciled_artifact_count,
            "payload_item_count": self.payload_item_count,
            "empty_artifact_count": self.empty_artifact_count,
            "duplicate_logical_window_count": self.duplicate_logical_window_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "artifact_hashes": list(self.artifact_hashes),
            "passed": self.passed,
            "licensing_approved": False,
            "provider_certified": False,
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "secret_values_disclosed": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderReconciliationReport":
        return cls(
            identifier=str(value["identifier"]),
            evaluated_at=_parse_timestamp(value["evaluated_at"], field_name="evaluated_at"),
            state=ProviderReconciliationState(str(value["state"])),
            backfill_report_identifier=str(value["backfill_report_identifier"]),
            plan_identifier=str(value["plan_identifier"]),
            artifact_count=int(value["artifact_count"]),
            reconciled_artifact_count=int(value["reconciled_artifact_count"]),
            payload_item_count=int(value["payload_item_count"]),
            empty_artifact_count=int(value["empty_artifact_count"]),
            duplicate_logical_window_count=int(value["duplicate_logical_window_count"]),
            blockers=tuple(str(item) for item in value.get("blockers", ())),
            warnings=tuple(str(item) for item in value.get("warnings", ())),
            artifact_hashes=tuple(str(item) for item in value.get("artifact_hashes", ())),
            schema_version=str(
                value.get(
                    "schema_version",
                    "provider-backfill-reconciliation-report.v1",
                )
            ),
        )


class ProviderBackfillReconciler:
    """Verify one completed immutable backfill directory."""

    def reconcile(
        self,
        directory: str | Path,
        *,
        evaluated_at: datetime,
    ) -> ProviderReconciliationReport:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        root = Path(directory).expanduser().resolve()
        report_path = root / "backfill-report.json"
        report = _load_object(report_path)
        blockers: list[str] = []
        warnings: list[str] = []
        backfill_state = str(report.get("state", ""))
        required_failures = report.get("required_failures", [])
        if backfill_state != "completed":
            blockers.append(f"backfill state is {backfill_state or 'unavailable'}")
        if isinstance(required_failures, list) and required_failures:
            blockers.append("backfill contains required failures")
        artifacts = report.get("artifacts")
        if not isinstance(artifacts, list):
            raise ProviderReconciliationError("backfill report artifacts are unavailable")
        declared_count = report.get("artifact_count")
        if declared_count != len(artifacts):
            blockers.append("backfill artifact_count does not match artifact list")

        reconciled = 0
        payload_items = 0
        empty_count = 0
        hashes: list[str] = []
        logical_windows: set[tuple[str, str, str, str, str]] = set()
        duplicate_count = 0
        for index, artifact in enumerate(artifacts, start=1):
            if not isinstance(artifact, Mapping):
                blockers.append(f"artifact {index} metadata is invalid")
                continue
            relative = Path(str(artifact.get("relative_path", "")))
            destination = (root / relative).resolve()
            try:
                destination.relative_to(root)
            except ValueError:
                blockers.append(f"artifact {index} escapes the backfill directory")
                continue
            if not destination.is_file():
                blockers.append(f"artifact is missing: {relative.as_posix()}")
                continue
            encoded = destination.read_bytes()
            actual_file_hash = hashlib.sha256(encoded).hexdigest()
            expected_file_hash = str(artifact.get("content_hash", ""))
            if actual_file_hash != expected_file_hash:
                blockers.append(f"artifact file hash mismatch: {relative.as_posix()}")
                continue
            try:
                snapshot = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                blockers.append(f"artifact is not valid UTF-8 JSON: {relative.as_posix()}")
                continue
            if not isinstance(snapshot, dict):
                blockers.append(f"artifact snapshot must be an object: {relative.as_posix()}")
                continue

            expected = {
                "backfill_task_identifier": artifact.get("task_identifier"),
                "provider": artifact.get("provider"),
                "provider_symbol": artifact.get("provider_symbol"),
                "dataset_type": artifact.get("dataset_type"),
                "query_start_at": artifact.get("start_at"),
                "query_end_at": artifact.get("end_at"),
            }
            for field_name, expected_value in expected.items():
                if snapshot.get(field_name) != expected_value:
                    blockers.append(
                        f"artifact identity mismatch for {field_name}: "
                        f"{relative.as_posix()}"
                    )
            try:
                query_as_of = _parse_timestamp(
                    snapshot.get("query_as_of"), field_name="query_as_of"
                )
                available_at = _parse_timestamp(
                    snapshot.get("available_at"), field_name="available_at"
                )
                retrieved_at = _parse_timestamp(
                    snapshot.get("retrieved_at"), field_name="retrieved_at"
                )
                end_at = _parse_timestamp(
                    snapshot.get("query_end_at"), field_name="query_end_at"
                )
                if available_at > query_as_of:
                    blockers.append(
                        f"artifact was unavailable at its query cutoff: {relative.as_posix()}"
                    )
                if end_at > query_as_of:
                    blockers.append(
                        f"artifact query end follows its cutoff: {relative.as_posix()}"
                    )
                if retrieved_at < available_at:
                    blockers.append(
                        f"artifact retrieval predates availability: {relative.as_posix()}"
                    )
            except ProviderReconciliationError as error:
                blockers.append(f"{relative.as_posix()}: {error}")

            payload = snapshot.get("payload")
            declared_payload_hash = snapshot.get("content_hash")
            try:
                actual_payload_hash = _payload_hash(payload)
            except ProviderReconciliationError as error:
                blockers.append(f"{relative.as_posix()}: {error}")
                continue
            if actual_payload_hash != declared_payload_hash:
                blockers.append(f"raw payload hash mismatch: {relative.as_posix()}")
                continue
            item_count = _payload_item_count(payload)
            payload_items += item_count
            if item_count == 0:
                empty_count += 1
                warnings.append(f"empty provider payload: {relative.as_posix()}")

            logical_key = (
                str(artifact.get("task_identifier", "")),
                str(artifact.get("provider_symbol", "")),
                str(artifact.get("dataset_type", "")),
                str(artifact.get("start_at", "")),
                str(artifact.get("end_at", "")),
            )
            if logical_key in logical_windows:
                duplicate_count += 1
                blockers.append(f"duplicate logical backfill window: {logical_key}")
            else:
                logical_windows.add(logical_key)
            hashes.append(actual_file_hash)
            reconciled += 1

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        state = (
            ProviderReconciliationState.PASSED
            if not blockers and reconciled == len(artifacts)
            else ProviderReconciliationState.BLOCKED
        )
        report_identifier = _text(
            report.get("identifier"), field_name="backfill_report_identifier"
        )
        plan_identifier = _text(
            report.get("plan_identifier"), field_name="plan_identifier"
        )
        return ProviderReconciliationReport(
            identifier=f"provider-reconciliation:{report_identifier}:{timestamp.isoformat()}",
            evaluated_at=timestamp,
            state=state,
            backfill_report_identifier=report_identifier,
            plan_identifier=plan_identifier,
            artifact_count=len(artifacts),
            reconciled_artifact_count=reconciled,
            payload_item_count=payload_items,
            empty_artifact_count=empty_count,
            duplicate_logical_window_count=duplicate_count,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            artifact_hashes=tuple(dict.fromkeys(hashes)),
        )


__all__ = [
    "ProviderBackfillReconciler",
    "ProviderReconciliationError",
    "ProviderReconciliationReport",
    "ProviderReconciliationState",
]
