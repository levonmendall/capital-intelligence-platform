"""Human-governed approval for exact production stage-binding documents."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from operations.daily_orchestration import CANONICAL_DAILY_STAGE_ORDER


class StageBindingApprovalError(RuntimeError):
    pass


class StageBindingApprovalIntegrityError(StageBindingApprovalError):
    pass


class StageBindingApprovalState(str, Enum):
    APPROVED = "approved"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


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


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


def canonical_binding_payload(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StageBindingApprovalError(
            f"cannot load stage-binding document {source}"
        ) from error
    if not isinstance(value, Mapping):
        raise StageBindingApprovalError("stage bindings must encode an object")
    if value.get("schema_version") != "canonical-daily-stage-bindings.v1":
        raise StageBindingApprovalError(
            "stage bindings must use canonical-daily-stage-bindings.v1"
        )
    stages = value.get("stages")
    if not isinstance(stages, Mapping):
        raise StageBindingApprovalError("stage bindings require a stages object")
    expected = {item.value for item in CANONICAL_DAILY_STAGE_ORDER}
    if set(stages) != expected:
        raise StageBindingApprovalError(
            "stage-binding approval requires all twelve canonical stages"
        )
    return dict(value)


def stage_binding_sha256(path: str | Path) -> str:
    payload = canonical_binding_payload(path)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _looks_secret(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "api_key=",
        "password=",
        "secret=",
        "token=",
        "bearer ",
        "private_key",
    )
    return any(marker in lowered for marker in markers)


@dataclass(frozen=True, slots=True)
class StageBindingApproval:
    identifier: str
    binding_sha256: str
    baseline_identifier: str
    process_version: str
    code_version: str
    state: StageBindingApprovalState
    approved_at: datetime
    effective_at: datetime
    expires_at: datetime
    governance_identifier: str
    approver_role: str
    approved_modules: tuple[str, ...]
    required_secret_names: tuple[str, ...]
    rationale: str
    schema_version: str = "stage-binding-approval.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "binding_sha256",
            "baseline_identifier",
            "process_version",
            "code_version",
            "governance_identifier",
            "approver_role",
            "rationale",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if len(self.binding_sha256) != 64:
            raise ValueError("binding_sha256 must be a SHA-256 digest")
        if not isinstance(self.state, StageBindingApprovalState):
            raise TypeError("state must be StageBindingApprovalState")
        for field_name in ("approved_at", "effective_at", "expires_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.effective_at < self.approved_at:
            raise ValueError("effective_at cannot predate approved_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
        object.__setattr__(
            self,
            "approved_modules",
            _texts(self.approved_modules, field_name="approved_modules"),
        )
        object.__setattr__(
            self,
            "required_secret_names",
            _texts(self.required_secret_names, field_name="required_secret_names"),
        )
        if not self.approved_modules:
            raise ValueError("approved_modules cannot be empty")
        if any(_looks_secret(item) for item in self.required_secret_names):
            raise ValueError("required_secret_names may contain names, not values")
        if self.approver_role not in {
            "deployment_governance",
            "operations_governance",
        }:
            raise ValueError("stage bindings require a deployment or operations approver")
        if self.schema_version != "stage-binding-approval.v1":
            raise ValueError("unsupported stage-binding approval schema")

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return (
            self.state is StageBindingApprovalState.APPROVED
            and self.effective_at <= resolved < self.expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "binding_sha256": self.binding_sha256,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "state": self.state.value,
            "approved_at": self.approved_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "governance_identifier": self.governance_identifier,
            "approver_role": self.approver_role,
            "approved_modules": list(self.approved_modules),
            "required_secret_names": list(self.required_secret_names),
            "rationale": self.rationale,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageBindingApproval":
        if bool(value.get("real_money_authorized", False)):
            raise ValueError("stage-binding approval cannot authorize real money")
        return cls(
            identifier=str(value["identifier"]),
            binding_sha256=str(value["binding_sha256"]),
            baseline_identifier=str(value["baseline_identifier"]),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            state=StageBindingApprovalState(str(value["state"])),
            approved_at=datetime.fromisoformat(str(value["approved_at"])),
            effective_at=datetime.fromisoformat(str(value["effective_at"])),
            expires_at=datetime.fromisoformat(str(value["expires_at"])),
            governance_identifier=str(value["governance_identifier"]),
            approver_role=str(value["approver_role"]),
            approved_modules=tuple(str(item) for item in value["approved_modules"]),
            required_secret_names=tuple(
                str(item) for item in value.get("required_secret_names", ())
            ),
            rationale=str(value["rationale"]),
            schema_version=str(
                value.get("schema_version", "stage-binding-approval.v1")
            ),
        )


class SQLiteStageBindingApprovalStore:
    _TABLE = "stage_binding_approval_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    binding_sha256 TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS stage_binding_approval_lookup
                ON {self._TABLE}(binding_sha256, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'stage-binding approvals are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'stage-binding approvals are append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        *,
        sequence: int,
        identifier: str,
        binding_sha256: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    identifier,
                    binding_sha256,
                    occurred_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def append(self, approval: StageBindingApproval) -> int:
        payload = json.dumps(
            approval.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.verify_integrity()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,payload_json FROM {self._TABLE} WHERE event_identifier=?",
                (approval.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise StageBindingApprovalError(
                        "stage-binding approval identifier has conflicting content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            occurred_at = approval.approved_at.isoformat()
            content_hash = self._hash(
                sequence=sequence,
                identifier=approval.identifier,
                binding_sha256=approval.binding_sha256,
                occurred_at=occurred_at,
                payload_json=payload,
                previous_hash=previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?,?)",
                (
                    sequence,
                    approval.identifier,
                    approval.binding_sha256,
                    occurred_at,
                    payload,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def approvals(self, binding_sha256: str) -> tuple[StageBindingApproval, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE binding_sha256=? ORDER BY sequence",
                (binding_sha256,),
            ).fetchall()
        return tuple(
            StageBindingApproval.from_dict(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def active(
        self,
        binding_sha256: str,
        *,
        evaluated_at: datetime,
    ) -> StageBindingApproval | None:
        values = tuple(
            item
            for item in self.approvals(binding_sha256)
            if item.active_at(evaluated_at)
        )
        return None if not values else values[-1]

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise StageBindingApprovalIntegrityError(
                    "stage-binding approval sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous:
                raise StageBindingApprovalIntegrityError(
                    "stage-binding approval previous hash is invalid"
                )
            actual = self._hash(
                sequence=expected,
                identifier=str(row["event_identifier"]),
                binding_sha256=str(row["binding_sha256"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous,
            )
            if str(row["content_hash"]) != actual:
                raise StageBindingApprovalIntegrityError(
                    "stage-binding approval content hash is invalid"
                )
            previous = actual
        return True


def require_approved_stage_bindings(
    path: str | Path,
    *,
    approval_database: str | Path,
    baseline_identifier: str,
    process_version: str,
    code_version: str,
    evaluated_at: datetime,
    environ: Mapping[str, str],
) -> StageBindingApproval:
    payload = canonical_binding_payload(path)
    digest = stage_binding_sha256(path)
    approval = SQLiteStageBindingApprovalStore(approval_database).active(
        digest,
        evaluated_at=evaluated_at,
    )
    if approval is None:
        raise StageBindingApprovalError(
            "stage-binding document has no active exact approval"
        )
    expected = {
        "baseline_identifier": baseline_identifier,
        "process_version": process_version,
        "code_version": code_version,
    }
    for field_name, expected_value in expected.items():
        if getattr(approval, field_name) != expected_value:
            raise StageBindingApprovalError(
                f"stage-binding approval {field_name} does not match deployment"
            )
    stages = payload["stages"]
    assert isinstance(stages, Mapping)
    actual_modules = tuple(
        sorted(str(value["module"]) for value in stages.values())
    )
    if set(actual_modules) - set(approval.approved_modules):
        raise StageBindingApprovalError(
            "stage-binding document contains an unapproved command module"
        )
    missing_secret_names = tuple(
        name for name in approval.required_secret_names if not environ.get(name)
    )
    if missing_secret_names:
        raise StageBindingApprovalError(
            "stage-binding deployment is missing required secret variables: "
            + ", ".join(missing_secret_names)
        )
    for stage in stages.values():
        argv = stage.get("argv", ()) if isinstance(stage, Mapping) else ()
        if not isinstance(argv, list) or any(
            _looks_secret(item) for item in argv if isinstance(item, str)
        ):
            raise StageBindingApprovalError(
                "stage-binding arguments may reference secret names but cannot embed secret values"
            )
    return approval


__all__ = [
    "SQLiteStageBindingApprovalStore",
    "StageBindingApproval",
    "StageBindingApprovalError",
    "StageBindingApprovalIntegrityError",
    "StageBindingApprovalState",
    "canonical_binding_payload",
    "require_approved_stage_bindings",
    "stage_binding_sha256",
]
