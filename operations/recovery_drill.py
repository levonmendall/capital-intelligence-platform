"""Isolated encrypted recovery drills for the complete canonical authority set."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from operations.backup import BackupError, SQLiteBackupManager


class RecoveryDrillError(RuntimeError):
    pass


class RecoveryDrillIntegrityError(RecoveryDrillError):
    pass


class RecoveryDrillStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _non_negative(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class RecoveryLineageProbe:
    authority: str
    table: str
    column: str
    expected_value: str

    def __post_init__(self) -> None:
        for field_name in ("authority", "table", "column", "expected_value"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("table", "column"):
            value = getattr(self, field_name)
            if not value.replace("_", "").isalnum():
                raise ValueError(f"{field_name} must be a safe SQLite identifier")

    def to_dict(self) -> dict[str, str]:
        return {
            "authority": self.authority,
            "table": self.table,
            "column": self.column,
            "expected_value": self.expected_value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryLineageProbe":
        return cls(
            authority=str(value["authority"]),
            table=str(value["table"]),
            column=str(value["column"]),
            expected_value=str(value["expected_value"]),
        )


@dataclass(frozen=True, slots=True)
class RecoveryDrillExpectation:
    identifier: str
    baseline_identifier: str
    process_version: str
    code_version: str
    required_authorities: tuple[str, ...]
    lineage_probes: tuple[RecoveryLineageProbe, ...]
    maximum_recovery_seconds: int
    maximum_data_loss_seconds: int
    schema_version: str = "canonical-recovery-drill-expectation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.required_authorities, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.required_authorities
        ):
            raise TypeError("required_authorities must contain non-empty strings")
        if len(self.required_authorities) != len(set(self.required_authorities)):
            raise ValueError("required_authorities cannot contain duplicates")
        if not self.required_authorities:
            raise ValueError("required_authorities cannot be empty")
        if not isinstance(self.lineage_probes, tuple) or not all(
            isinstance(item, RecoveryLineageProbe) for item in self.lineage_probes
        ):
            raise TypeError("lineage_probes must contain RecoveryLineageProbe values")
        if not self.lineage_probes:
            raise ValueError("lineage_probes cannot be empty")
        unknown = {
            item.authority for item in self.lineage_probes
        } - set(self.required_authorities)
        if unknown:
            raise ValueError(
                f"lineage probes reference unknown authorities: {sorted(unknown)}"
            )
        object.__setattr__(
            self,
            "maximum_recovery_seconds",
            _non_negative(
                self.maximum_recovery_seconds,
                field_name="maximum_recovery_seconds",
            ),
        )
        object.__setattr__(
            self,
            "maximum_data_loss_seconds",
            _non_negative(
                self.maximum_data_loss_seconds,
                field_name="maximum_data_loss_seconds",
            ),
        )
        if self.maximum_recovery_seconds < 1:
            raise ValueError("maximum_recovery_seconds must be positive")
        if self.schema_version != "canonical-recovery-drill-expectation.v1":
            raise ValueError("unsupported recovery expectation schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "required_authorities": list(self.required_authorities),
            "lineage_probes": [item.to_dict() for item in self.lineage_probes],
            "maximum_recovery_seconds": self.maximum_recovery_seconds,
            "maximum_data_loss_seconds": self.maximum_data_loss_seconds,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryDrillExpectation":
        return cls(
            identifier=str(value["identifier"]),
            baseline_identifier=str(value["baseline_identifier"]),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            required_authorities=tuple(
                str(item) for item in value["required_authorities"]
            ),
            lineage_probes=tuple(
                RecoveryLineageProbe.from_dict(item)
                for item in value["lineage_probes"]
            ),
            maximum_recovery_seconds=int(value["maximum_recovery_seconds"]),
            maximum_data_loss_seconds=int(value["maximum_data_loss_seconds"]),
            schema_version=str(
                value.get(
                    "schema_version",
                    "canonical-recovery-drill-expectation.v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class RecoveryDrillReport:
    identifier: str
    expectation_identifier: str
    archive_identifier: str
    executed_at: datetime
    status: RecoveryDrillStatus
    baseline_identifier: str
    process_version: str
    code_version: str
    restored_authorities: tuple[str, ...]
    integrity_verified_authorities: tuple[str, ...]
    passed_probe_identifiers: tuple[str, ...]
    failed_probe_identifiers: tuple[str, ...]
    recovery_seconds: int
    data_loss_seconds: int
    production_mutation_count: int
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "canonical-recovery-drill-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "expectation_identifier",
            "archive_identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.executed_at, field_name="executed_at")
        if not isinstance(self.status, RecoveryDrillStatus):
            raise TypeError("status must be RecoveryDrillStatus")
        for field_name in (
            "restored_authorities",
            "integrity_verified_authorities",
            "passed_probe_identifiers",
            "failed_probe_identifiers",
            "blockers",
            "evidence_identifiers",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(value) != len(set(value)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        for field_name in (
            "recovery_seconds",
            "data_loss_seconds",
            "production_mutation_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative(getattr(self, field_name), field_name=field_name),
            )
        if self.status is RecoveryDrillStatus.PASSED:
            if self.blockers or self.failed_probe_identifiers:
                raise ValueError("passed recovery drill cannot contain blockers")
            if self.production_mutation_count != 0:
                raise ValueError("passed recovery drill cannot mutate production")
        if self.schema_version != "canonical-recovery-drill-report.v1":
            raise ValueError("unsupported recovery report schema")

    @property
    def paper_test_authorized(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "expectation_identifier": self.expectation_identifier,
            "archive_identifier": self.archive_identifier,
            "executed_at": self.executed_at.isoformat(),
            "status": self.status.value,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "restored_authorities": list(self.restored_authorities),
            "integrity_verified_authorities": list(
                self.integrity_verified_authorities
            ),
            "passed_probe_identifiers": list(self.passed_probe_identifiers),
            "failed_probe_identifiers": list(self.failed_probe_identifiers),
            "recovery_seconds": self.recovery_seconds,
            "data_loss_seconds": self.data_loss_seconds,
            "production_mutation_count": self.production_mutation_count,
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }


class SQLiteRecoveryDrillStore:
    _TABLE = "canonical_recovery_drill_reports"
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
                    executed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'recovery drill reports are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'recovery drill reports are append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        sequence: int,
        identifier: str,
        executed_at: str,
        payload: str,
        previous: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (str(sequence), identifier, executed_at, payload, previous)
            ).encode("utf-8")
        ).hexdigest()

    def append(self, report: RecoveryDrillReport) -> int:
        payload = _canonical_json(report.to_dict())
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,payload_json FROM {self._TABLE} WHERE identifier=?",
                (report.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise RecoveryDrillError(
                        "recovery report identifier has conflicting content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            executed_at = report.executed_at.isoformat()
            content_hash = self._hash(
                sequence,
                report.identifier,
                executed_at,
                payload,
                previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?)",
                (
                    sequence,
                    report.identifier,
                    executed_at,
                    payload,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise RecoveryDrillIntegrityError(
                    "recovery drill sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous:
                raise RecoveryDrillIntegrityError(
                    "recovery drill previous hash is invalid"
                )
            actual = self._hash(
                expected,
                str(row["identifier"]),
                str(row["executed_at"]),
                str(row["payload_json"]),
                previous,
            )
            if str(row["content_hash"]) != actual:
                raise RecoveryDrillIntegrityError(
                    "recovery drill content hash is invalid"
                )
            previous = actual
        return True


class CanonicalRecoveryDrill:
    def __init__(self, manager: SQLiteBackupManager) -> None:
        if not isinstance(manager, SQLiteBackupManager):
            raise TypeError("manager must be SQLiteBackupManager")
        self.manager = manager

    @staticmethod
    def _integrity(path: Path) -> bool:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return row is not None and row[0] == "ok"

    def run(
        self,
        *,
        archive: str | Path,
        expectation: RecoveryDrillExpectation,
        executed_at: datetime,
    ) -> RecoveryDrillReport:
        timestamp = _aware(executed_at, field_name="executed_at")
        started = time.monotonic()
        source = Path(archive)
        manifest = self.manager.verify_archive(source)
        blockers: list[str] = []
        for field_name in ("baseline_identifier", "process_version", "code_version"):
            if manifest.get(field_name) != getattr(expectation, field_name):
                blockers.append(f"backup manifest {field_name} does not match expectation")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise RecoveryDrillError("backup manifest files are unavailable")
        entry_by_name = {
            str(item["logical_name"]): item
            for item in entries
            if isinstance(item, Mapping)
        }
        missing = set(expectation.required_authorities) - set(entry_by_name)
        if missing:
            blockers.append(
                "backup is missing required drill authorities: "
                + ", ".join(sorted(missing))
            )
        passed_probes: list[str] = []
        failed_probes: list[str] = []
        restored_names: list[str] = []
        integrity_names: list[str] = []
        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-recovery-drill-"
        ) as temporary:
            restored = self.manager.restore(source, temporary)
            restored_by_filename = {item.name: item for item in restored}
            for logical_name, entry in entry_by_name.items():
                filename = str(entry["filename"])
                database = restored_by_filename.get(filename)
                if database is None:
                    continue
                restored_names.append(logical_name)
                if self._integrity(database):
                    integrity_names.append(logical_name)
                else:
                    blockers.append(
                        f"restored authority failed integrity: {logical_name}"
                    )
            for index, probe in enumerate(expectation.lineage_probes, start=1):
                probe_identifier = (
                    f"probe:{index}:{probe.authority}:{probe.table}:{probe.column}"
                )
                entry = entry_by_name.get(probe.authority)
                if entry is None:
                    failed_probes.append(probe_identifier)
                    continue
                database = restored_by_filename.get(str(entry["filename"]))
                if database is None:
                    failed_probes.append(probe_identifier)
                    continue
                try:
                    with sqlite3.connect(
                        f"file:{database}?mode=ro",
                        uri=True,
                    ) as connection:
                        row = connection.execute(
                            f'SELECT 1 FROM "{probe.table}" '
                            f'WHERE CAST("{probe.column}" AS TEXT)=? LIMIT 1',
                            (probe.expected_value,),
                        ).fetchone()
                except sqlite3.Error:
                    row = None
                if row is None:
                    failed_probes.append(probe_identifier)
                else:
                    passed_probes.append(probe_identifier)
        if failed_probes:
            blockers.append(
                "one or more decision-lineage probes did not reconstruct"
            )
        recovery_seconds = int(round(time.monotonic() - started))
        if recovery_seconds > expectation.maximum_recovery_seconds:
            blockers.append("recovery exceeded the approved recovery-time objective")
        created_at = manifest.get("created_at")
        try:
            backup_time = datetime.fromisoformat(str(created_at))
            data_loss_seconds = max(0, int((timestamp - backup_time).total_seconds()))
        except (TypeError, ValueError):
            data_loss_seconds = expectation.maximum_data_loss_seconds + 1
            blockers.append("backup creation time cannot be used for recovery-point evidence")
        if data_loss_seconds > expectation.maximum_data_loss_seconds:
            blockers.append("recovery exceeded the approved recovery-point objective")
        status = (
            RecoveryDrillStatus.PASSED
            if not blockers
            else RecoveryDrillStatus.FAILED
        )
        archive_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return RecoveryDrillReport(
            identifier=(
                f"recovery-drill:{expectation.identifier}:{timestamp.isoformat()}"
            ),
            expectation_identifier=expectation.identifier,
            archive_identifier=f"backup-sha256:{archive_digest}",
            executed_at=timestamp,
            status=status,
            baseline_identifier=expectation.baseline_identifier,
            process_version=expectation.process_version,
            code_version=expectation.code_version,
            restored_authorities=tuple(sorted(restored_names)),
            integrity_verified_authorities=tuple(sorted(integrity_names)),
            passed_probe_identifiers=tuple(passed_probes),
            failed_probe_identifiers=tuple(failed_probes),
            recovery_seconds=recovery_seconds,
            data_loss_seconds=data_loss_seconds,
            production_mutation_count=0,
            blockers=tuple(blockers),
            evidence_identifiers=(
                expectation.identifier,
                f"backup-sha256:{archive_digest}",
                *tuple(passed_probes),
            ),
        )


__all__ = [
    "CanonicalRecoveryDrill",
    "RecoveryDrillError",
    "RecoveryDrillExpectation",
    "RecoveryDrillIntegrityError",
    "RecoveryDrillReport",
    "RecoveryDrillStatus",
    "RecoveryLineageProbe",
    "SQLiteRecoveryDrillStore",
]
