"""Durable, paper-only requests for an administrator-triggered CIO diagnostic cycle.

The request file is operational coordination state. It cannot authorize candidates,
portfolio changes, paper execution, or real money. The autonomous paper operator claims
at most one pending request and then runs the existing fully governed context, specialist,
CIO, construction, and paper-execution path with a unique material-event cycle key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


_SCHEMA_VERSION = "manual-cio-diagnostic.v1"
_ACTIVE_STATES = frozenset({"pending", "in_progress"})
_FINAL_STATES = frozenset({"completed", "failed"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("diagnostic timestamps must be non-empty strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware(parsed, field_name="diagnostic timestamp")


@dataclass(frozen=True, slots=True)
class ManualCIODiagnosticRequest:
    request_id: str
    requested_at: datetime
    requested_by: str
    state: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cycle_key: str | None = None
    snapshot_identifier: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id cannot be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by cannot be empty")
        _aware(self.requested_at, field_name="requested_at")
        if self.started_at is not None:
            _aware(self.started_at, field_name="started_at")
        if self.completed_at is not None:
            _aware(self.completed_at, field_name="completed_at")
        if self.state not in _ACTIVE_STATES | _FINAL_STATES:
            raise ValueError("unsupported manual diagnostic state")
        if self.state == "in_progress" and self.started_at is None:
            raise ValueError("in-progress diagnostics require started_at")
        if self.state in _FINAL_STATES and self.completed_at is None:
            raise ValueError("final diagnostics require completed_at")

    @property
    def trigger_key(self) -> str:
        return f"manual-diagnostic-{self.request_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "request_id": self.request_id,
            "requested_at": self.requested_at.astimezone(timezone.utc).isoformat(),
            "requested_by": self.requested_by,
            "state": self.state,
            "started_at": (
                None
                if self.started_at is None
                else self.started_at.astimezone(timezone.utc).isoformat()
            ),
            "completed_at": (
                None
                if self.completed_at is None
                else self.completed_at.astimezone(timezone.utc).isoformat()
            ),
            "cycle_key": self.cycle_key,
            "snapshot_identifier": self.snapshot_identifier,
            "detail": self.detail,
            "paper_only": True,
            "real_money_authorized": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ManualCIODiagnosticRequest":
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported manual CIO diagnostic schema")
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            requested_at=_optional_datetime(payload.get("requested_at"))
            or (_ for _ in ()).throw(ValueError("requested_at is required")),
            requested_by=str(payload.get("requested_by") or "").strip(),
            state=str(payload.get("state") or "").strip(),
            started_at=_optional_datetime(payload.get("started_at")),
            completed_at=_optional_datetime(payload.get("completed_at")),
            cycle_key=(
                None
                if payload.get("cycle_key") is None
                else str(payload.get("cycle_key")).strip() or None
            ),
            snapshot_identifier=(
                None
                if payload.get("snapshot_identifier") is None
                else str(payload.get("snapshot_identifier")).strip() or None
            ),
            detail=(
                None
                if payload.get("detail") is None
                else str(payload.get("detail"))[:2000]
            ),
        )


def diagnostic_request_path(
    values: Mapping[str, str] | None = None,
) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH",
        "",
    ).strip()
    if configured:
        return Path(configured).expanduser()
    data_root = Path(
        resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_root / "manual-cio-diagnostic.json"


def _read(path: Path) -> ManualCIODiagnosticRequest | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"manual CIO diagnostic state is invalid: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("manual CIO diagnostic state must be an object")
    return ManualCIODiagnosticRequest.from_dict(payload)


def _write(path: Path, request: ManualCIODiagnosticRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def latest_manual_cio_diagnostic(
    *,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest | None:
    return _read(diagnostic_request_path(values))


def request_manual_cio_diagnostic(
    *,
    requested_by: str,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> tuple[ManualCIODiagnosticRequest, bool]:
    requester = requested_by.strip()
    if not requester:
        raise ValueError("requested_by cannot be empty")
    path = diagnostic_request_path(values)
    existing = _read(path)
    if existing is not None and existing.state in _ACTIVE_STATES:
        return existing, False
    requested_at = _aware(now or _utc_now(), field_name="now")
    request = ManualCIODiagnosticRequest(
        request_id=uuid4().hex,
        requested_at=requested_at,
        requested_by=requester,
    )
    _write(path, request)
    return request, True


def claim_manual_cio_diagnostic(
    *,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest | None:
    path = diagnostic_request_path(values)
    request = _read(path)
    if request is None or request.state != "pending":
        return None
    claimed = replace(
        request,
        state="in_progress",
        started_at=_aware(now or _utc_now(), field_name="now"),
        detail="The autonomous paper operator claimed the diagnostic request.",
    )
    _write(path, claimed)
    return claimed


def finish_manual_cio_diagnostic(
    request: ManualCIODiagnosticRequest,
    *,
    succeeded: bool,
    cycle_key: str | None,
    snapshot_identifier: str | None,
    detail: str | None,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest:
    if request.state != "in_progress":
        raise ValueError("only an in-progress diagnostic can be finished")
    finished = replace(
        request,
        state="completed" if succeeded else "failed",
        completed_at=_aware(now or _utc_now(), field_name="now"),
        cycle_key=cycle_key,
        snapshot_identifier=snapshot_identifier,
        detail=None if detail is None else detail[:2000],
    )
    _write(diagnostic_request_path(values), finished)
    return finished


__all__ = [
    "ManualCIODiagnosticRequest",
    "claim_manual_cio_diagnostic",
    "diagnostic_request_path",
    "finish_manual_cio_diagnostic",
    "latest_manual_cio_diagnostic",
    "request_manual_cio_diagnostic",
]
