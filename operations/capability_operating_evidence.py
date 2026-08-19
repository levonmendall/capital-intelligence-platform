"""Independent fresh evidence plane for the currently operable CIO universe.

This plane is deliberately smaller than comprehensive all-market discovery.  It refreshes
raw market/fundamental/cash evidence for instruments that already possess operating
membership, then publishes the same immutable paper-evidence snapshot format used by the
broader research plane.  Comprehensive discovery remains free to expand future coverage in
parallel; its failure cannot invalidate this plane.

This module owns evidence only.  It cannot authorize investment, construction, execution,
or real money.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from operations.capability_operating_universe import build_capability_operating_universe
from operations.evidence_state_scope import load_evidence_state_scope
from operations.free_paper_pilot import (
    FreePaperPilotUniverse,
    _free_paper_pilot_universe_from_payload,
    free_paper_pilot_universe_payload,
)
from operations.owned_paper_evidence_collection import collect_owned_paper_evidence
from operations.paper_evidence_snapshot import (
    PaperEvidenceSnapshot,
    PaperEvidenceSnapshotError,
    load_paper_evidence_snapshot,
    publish_paper_evidence_snapshot,
)
from operations.paper_evidence_spool_concurrent import close_spooled_paper_evidence

_SCHEMA = "capability-operating-evidence.v1"
_DEFAULT_MAX_AGE_SECONDS = 900.0


class CapabilityOperatingEvidenceError(RuntimeError):
    """Raised when current operating evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CapabilityOperatingEvidence:
    as_of: datetime
    completed_at: datetime
    snapshot: PaperEvidenceSnapshot
    universe: FreePaperPilotUniverse
    held_symbols: tuple[str, ...]
    holding_only_symbols: tuple[str, ...]
    state_path: Path

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _digest(payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _root(values: Mapping[str, str]) -> Path:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not raw:
        raise CapabilityOperatingEvidenceError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for capability operating evidence"
        )
    return Path(raw).expanduser() / "capability_operating_evidence"


def _state_path(values: Mapping[str, str]) -> Path:
    return _root(values) / "latest.json"


def _max_age_seconds(values: Mapping[str, str]) -> float:
    raw = str(
        values.get("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS") or ""
    ).strip()
    if not raw:
        return _DEFAULT_MAX_AGE_SECONDS
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS must be numeric"
        ) from error
    if value <= 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS must be positive"
        )
    return value


def _atomic_state(path: Path, payload: Mapping[str, object]) -> None:
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(body, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_state(values: Mapping[str, str]) -> Mapping[str, object]:
    path = _state_path(values)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence state is unavailable"
        ) from error
    if not isinstance(payload, Mapping):
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence state is malformed"
        )
    integrity = str(payload.get("integrity_sha256") or "").strip()
    material = {str(key): value for key, value in payload.items() if key != "integrity_sha256"}
    if not integrity or integrity != _digest(material):
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence state integrity mismatch"
        )
    if payload.get("schema_version") != _SCHEMA:
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence state schema is invalid"
        )
    return payload


def refresh_capability_operating_evidence(
    *,
    as_of: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> CapabilityOperatingEvidence:
    """Acquire and immutably publish fresh evidence for the current operating universe."""

    resolved = dict(os.environ if values is None else values)
    timestamp = _aware(
        datetime.now(timezone.utc) if as_of is None else as_of,
        field_name="operating_evidence_as_of",
    )
    if timestamp > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence cannot prepare a future cutoff"
        )

    scope = load_evidence_state_scope(as_of=timestamp, values=resolved)
    try:
        universe, holding_only = build_capability_operating_universe(
            as_of=timestamp,
            held_symbols=scope.held_symbols,
        )
        payload = collect_owned_paper_evidence(
            universe,
            timestamp,
            required_holding_symbols=scope.held_symbols,
            values=resolved,
        )
        try:
            snapshot = publish_paper_evidence_snapshot(
                payload,
                universe=universe,
                evidence_as_of=timestamp,
                values=resolved,
                requested_history_days=365 * 10 + 20,
            )
        finally:
            close_spooled_paper_evidence(payload)
    except CapabilityOperatingEvidenceError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError, PaperEvidenceSnapshotError) as error:
        raise CapabilityOperatingEvidenceError(
            f"capability operating evidence refresh failed: {type(error).__name__}: {error}"
        ) from error

    completed = datetime.now(timezone.utc)
    state: dict[str, object] = {
        "schema_version": _SCHEMA,
        "as_of": timestamp.isoformat(),
        "completed_at": completed.isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "universe": free_paper_pilot_universe_payload(universe),
        "held_symbols": list(scope.held_symbols),
        "holding_only_symbols": list(holding_only),
        "instrument_count": len(universe.instruments),
        "comprehensive_discovery_required": False,
        "provider_refresh_owned_here": True,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    path = _state_path(resolved)
    _atomic_state(path, state)
    return CapabilityOperatingEvidence(
        as_of=timestamp,
        completed_at=completed,
        snapshot=snapshot,
        universe=universe,
        held_symbols=tuple(scope.held_symbols),
        holding_only_symbols=holding_only,
        state_path=path,
    )


def load_capability_operating_evidence(
    *,
    cutoff: datetime,
    values: Mapping[str, str] | None = None,
) -> CapabilityOperatingEvidence:
    """Load a fresh operating snapshot without provider calls or global discovery."""

    resolved = dict(os.environ if values is None else values)
    requested = _aware(cutoff, field_name="operating_evidence_cutoff")
    payload = _read_state(resolved)
    try:
        as_of = _aware(
            datetime.fromisoformat(str(payload["as_of"]).replace("Z", "+00:00")),
            field_name="operating_evidence_as_of",
        )
        completed = _aware(
            datetime.fromisoformat(str(payload["completed_at"]).replace("Z", "+00:00")),
            field_name="operating_evidence_completed_at",
        )
        raw_universe = payload["universe"]
        held_raw = payload["held_symbols"]
        holding_only_raw = payload["holding_only_symbols"]
        if not isinstance(raw_universe, Mapping):
            raise TypeError("operating evidence universe is malformed")
        if not isinstance(held_raw, list) or not isinstance(holding_only_raw, list):
            raise TypeError("operating evidence holding scope is malformed")
        universe = _free_paper_pilot_universe_from_payload(raw_universe)
    except (KeyError, TypeError, ValueError) as error:
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence state cannot be reconstructed"
        ) from error

    age = requested - as_of
    if age < timedelta(0) or age > timedelta(seconds=_max_age_seconds(resolved)):
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence is missing or stale for the CIO cutoff"
        )
    if completed < as_of:
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence completion precedes its evidence timestamp"
        )

    try:
        snapshot = load_paper_evidence_snapshot(
            evidence_as_of=as_of,
            universe=universe,
            values=resolved,
        )
    except PaperEvidenceSnapshotError as error:
        raise CapabilityOperatingEvidenceError(
            f"capability operating paper snapshot is invalid: {error}"
        ) from error
    expected_snapshot = str(payload.get("snapshot_id") or "").strip()
    if not expected_snapshot or snapshot.snapshot_id != expected_snapshot:
        raise CapabilityOperatingEvidenceError(
            "capability operating evidence snapshot identifier changed"
        )

    return CapabilityOperatingEvidence(
        as_of=as_of,
        completed_at=completed,
        snapshot=snapshot,
        universe=universe,
        held_symbols=tuple(str(item).strip().upper() for item in held_raw if str(item).strip()),
        holding_only_symbols=tuple(
            str(item).strip().upper() for item in holding_only_raw if str(item).strip()
        ),
        state_path=_state_path(resolved),
    )


__all__ = [
    "CapabilityOperatingEvidence",
    "CapabilityOperatingEvidenceError",
    "load_capability_operating_evidence",
    "refresh_capability_operating_evidence",
]
