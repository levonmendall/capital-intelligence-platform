"""Durable monotonic retry floor for point-in-time historical evidence conflicts.

A paper-evidence attempt can discover that the only trustworthy persistent history for a
scope was refreshed after the attempt's frozen decision epoch. That attempt must remain
fail-closed. The next attempt, however, must not be rebound by reusable public evidence to
an epoch older than the historical snapshot that caused the failure.

This module persists only that coordination lower bound. It never certifies evidence and
has no investment, candidate, sizing, construction, execution, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

_SCHEMA_VERSION = "historical-evidence-epoch-floor.v1"
_FILENAME = "historical-evidence-epoch-floor.json"
_TIMESTAMP_MARKERS = (
    "earliest_available_requested_as_of",
    "latest_snapshot_requested_as_of",
)
_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("historical evidence epoch floor timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _path(values: Mapping[str, str]) -> Path:
    data_dir = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    release = _release(values)
    if not data_dir:
        raise ValueError("CAPITAL_INTELLIGENCE_DATA_DIR is required for historical epoch floor")
    if not release or release == "unknown":
        raise ValueError("exact release identity is required for historical epoch floor")
    safe_release = _SAFE_RELEASE.sub("-", release).strip("-.") or "unknown"
    return (
        Path(data_dir).expanduser()
        / "release_prequalification_progress"
        / safe_release
        / _FILENAME
    )


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _parse_timestamp(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _conflict_snapshot_timestamp(error_detail: str) -> datetime | None:
    text = str(error_detail or "")
    for marker in _TIMESTAMP_MARKERS:
        match = re.search(rf"(?:^|;)\s*{re.escape(marker)}=([^;]+)", text)
        if match is None:
            continue
        parsed = _parse_timestamp(match.group(1))
        if parsed is not None:
            return parsed
    return None


def load_historical_evidence_epoch_floor(
    values: Mapping[str, str] | None = None,
) -> datetime | None:
    resolved = dict(os.environ if values is None else values)
    path = _path(resolved)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("historical evidence epoch floor is unreadable") from error
    if not isinstance(raw, Mapping):
        raise RuntimeError("historical evidence epoch floor is not an object")
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        raise RuntimeError("historical evidence epoch floor integrity mismatch")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise RuntimeError("historical evidence epoch floor schema mismatch")
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise RuntimeError("historical evidence epoch floor authority boundary is invalid")
    floor = _parse_timestamp(str(payload.get("minimum_evidence_as_of") or ""))
    if floor is None:
        raise RuntimeError("historical evidence epoch floor timestamp is invalid")
    return floor


def record_historical_evidence_epoch_floor(
    error_detail: str,
    *,
    values: Mapping[str, str] | None = None,
    observed_at: datetime | None = None,
) -> datetime | None:
    """Persist a monotonic floor only for a recognized future-snapshot lineage conflict."""

    conflict = _conflict_snapshot_timestamp(error_detail)
    if conflict is None:
        return None
    resolved = dict(os.environ if values is None else values)
    observed = _aware(datetime.now(timezone.utc) if observed_at is None else observed_at)
    minimum = max(conflict, observed)
    existing = load_historical_evidence_epoch_floor(resolved)
    if existing is not None:
        minimum = max(minimum, existing)

    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "release": _release(resolved),
        "minimum_evidence_as_of": minimum.isoformat(),
        "conflict_snapshot_requested_as_of": conflict.isoformat(),
        "observed_at": observed.isoformat(),
        "reason": "future_historical_snapshot_for_frozen_decision_epoch",
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    path = _path(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    material = {**payload, "integrity_sha256": _digest(payload)}
    temporary.write_text(
        json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return minimum


__all__ = [
    "load_historical_evidence_epoch_floor",
    "record_historical_evidence_epoch_floor",
]
