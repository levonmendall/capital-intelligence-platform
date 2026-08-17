"""Durable, component-versioned qualified evidence checkpoints.

The ledger is an operational cache of already-qualified evidence components. Component
identity is deliberately independent of the running software release: a deployment may
reuse a component only when its explicit compatibility fingerprint and freshness
contract still qualify it. The observed release is retained for audit lineage but does
not itself invalidate otherwise compatible evidence.

Ledger entries have no investment, specialist, construction, execution, or real-money
authority. Missing, stale, incompatible, malformed, or integrity-invalid components are
not reusable and callers must refresh or fail closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping


_COMPONENT_SCHEMA = "qualified-evidence-component.v1"
_DEFAULT_MAX_AGE_SECONDS = 900.0


class QualifiedEvidenceLedgerError(RuntimeError):
    """Raised when qualified component persistence or validation is unsafe."""


@dataclass(frozen=True, slots=True)
class QualifiedEvidenceComponent:
    component_name: str
    component_id: str
    as_of: datetime
    completed_at: datetime
    valid_through: datetime
    compatibility_fingerprint: str
    observed_release: str
    payload: Mapping[str, object]
    path: Path


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise QualifiedEvidenceLedgerError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for qualified evidence components"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane" / "components"


def component_max_age_seconds(
    values: Mapping[str, str],
    component_name: str,
) -> float:
    token = re.sub(r"[^A-Za-z0-9]+", "_", component_name).strip("_").upper()
    names = (
        f"CAPITAL_INTELLIGENCE_EVIDENCE_COMPONENT_{token}_MAX_AGE_SECONDS",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS",
    )
    raw = ""
    for name in names:
        candidate = values.get(name, "").strip()
        if candidate:
            raw = candidate
            break
    if not raw:
        return _DEFAULT_MAX_AGE_SECONDS
    try:
        result = float(raw)
    except ValueError as error:
        raise ValueError(f"{names[0]} must be numeric") from error
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{names[0]} must be positive")
    return result


def compatibility_fingerprint(*parts: object) -> str:
    """Return a stable compatibility identity for a component contract."""

    return _digest(parts)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = dict(payload)
    material["integrity_sha256"] = _digest(payload)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component cannot be published: {path.name}"
        ) from error


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise QualifiedEvidenceLedgerError(f"{field_name} is invalid") from error
    return _aware(parsed, field_name=field_name)


def _read(path: Path) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component is unreadable: {path.name}"
        ) from error
    if not isinstance(raw, Mapping):
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component is not an object: {path.name}"
        )
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component integrity mismatch: {path.name}"
        )
    if payload.get("schema_version") != _COMPONENT_SCHEMA:
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component schema mismatch: {path.name}"
        )
    if (
        payload.get("investment_authority") is not False
        or payload.get("specialist_authority") is not False
        or payload.get("construction_authority") is not False
        or payload.get("execution_authority") is not False
        or payload.get("paper_only") is not True
        or payload.get("real_money_authorized") is not False
    ):
        raise QualifiedEvidenceLedgerError(
            f"qualified evidence component authority boundary is invalid: {path.name}"
        )
    return payload


def publish_qualified_component(
    *,
    values: Mapping[str, str],
    component_name: str,
    compatibility: str,
    completed_at: datetime | None = None,
    max_age_seconds: float | None = None,
    payload: Mapping[str, object] | None = None,
) -> QualifiedEvidenceComponent:
    name = str(component_name).strip()
    fingerprint = str(compatibility).strip()
    if not name or not fingerprint:
        raise ValueError("component_name and compatibility must be non-empty")
    completed = _aware(
        datetime.now(timezone.utc) if completed_at is None else completed_at,
        field_name="component_completed_at",
    )
    maximum_age = (
        component_max_age_seconds(values, name)
        if max_age_seconds is None
        else float(max_age_seconds)
    )
    if not math.isfinite(maximum_age) or maximum_age <= 0.0:
        raise ValueError("component max_age_seconds must be positive")
    valid_through = completed + timedelta(seconds=maximum_age)
    component_payload = dict(payload or {})
    material = {
        "schema_version": _COMPONENT_SCHEMA,
        "component_name": name,
        "as_of": completed.isoformat(),
        "completed_at": completed.isoformat(),
        "valid_through": valid_through.isoformat(),
        "compatibility_fingerprint": fingerprint,
        "observed_release": _release(values),
        "payload": component_payload,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    component_id = _digest(material)
    document = dict(material)
    document["component_id"] = component_id
    directory = _root(values) / _safe(name)
    immutable = directory / f"{component_id}.json"
    if immutable.exists():
        existing = _read(immutable)
        if existing is None or existing.get("component_id") != component_id:
            raise QualifiedEvidenceLedgerError(
                "qualified evidence immutable component content mismatch"
            )
    else:
        _atomic_json(immutable, document)
    _atomic_json(directory / "latest.json", document)
    return QualifiedEvidenceComponent(
        component_name=name,
        component_id=component_id,
        as_of=completed,
        completed_at=completed,
        valid_through=valid_through,
        compatibility_fingerprint=fingerprint,
        observed_release=_release(values),
        payload=component_payload,
        path=immutable,
    )


def load_qualified_component(
    *,
    values: Mapping[str, str],
    component_name: str,
    compatibility: str,
    cutoff: datetime | None = None,
) -> QualifiedEvidenceComponent | None:
    name = str(component_name).strip()
    fingerprint = str(compatibility).strip()
    if not name or not fingerprint:
        raise ValueError("component_name and compatibility must be non-empty")
    requested = _aware(
        datetime.now(timezone.utc) if cutoff is None else cutoff,
        field_name="component_cutoff",
    )
    latest = _root(values) / _safe(name) / "latest.json"
    raw = _read(latest)
    if raw is None:
        return None
    if str(raw.get("component_name") or "") != name:
        raise QualifiedEvidenceLedgerError("qualified evidence component name mismatch")
    if str(raw.get("compatibility_fingerprint") or "") != fingerprint:
        return None
    component_id = str(raw.get("component_id") or "")
    material = dict(raw)
    material.pop("component_id", None)
    if not component_id or component_id != _digest(material):
        raise QualifiedEvidenceLedgerError("qualified evidence component identifier mismatch")
    as_of = _parse_timestamp(raw.get("as_of"), field_name="component_as_of")
    completed = _parse_timestamp(
        raw.get("completed_at"), field_name="component_completed_at"
    )
    valid_through = _parse_timestamp(
        raw.get("valid_through"), field_name="component_valid_through"
    )
    if completed != as_of or not (as_of <= requested <= valid_through):
        return None
    immutable = latest.with_name(f"{component_id}.json")
    immutable_payload = _read(immutable)
    if immutable_payload is None or immutable_payload != raw:
        raise QualifiedEvidenceLedgerError(
            "qualified evidence immutable component is missing or mismatched"
        )
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        raise QualifiedEvidenceLedgerError("qualified evidence component payload is malformed")
    return QualifiedEvidenceComponent(
        component_name=name,
        component_id=component_id,
        as_of=as_of,
        completed_at=completed,
        valid_through=valid_through,
        compatibility_fingerprint=fingerprint,
        observed_release=str(raw.get("observed_release") or ""),
        payload=dict(payload),
        path=immutable,
    )


__all__ = [
    "QualifiedEvidenceComponent",
    "QualifiedEvidenceLedgerError",
    "compatibility_fingerprint",
    "component_max_age_seconds",
    "load_qualified_component",
    "publish_qualified_component",
]
