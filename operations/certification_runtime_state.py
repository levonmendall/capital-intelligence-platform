"""Cross-process resolver for the durable all-market certification state machine.

Downstream owners never trust process-local environment variables for certification
identity. They resolve the immutable input ledger from disk, require its point-in-time
cutoff to match the authoritative artifact timestamp exactly, verify pointer integrity,
and then advance only the state they can prove. Non-production tests and rehearsals do
not require a production certification ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations.certification_state_machine import (
    CertificationState,
    CertificationStateError,
    CertificationStateRecord,
    advance_certification_state,
)
from operations.continuous_evidence_plane import evidence_plane_enabled


class CertificationRuntimeStateError(RuntimeError):
    """Raised when cross-process certification identity cannot be proven."""


@dataclass(frozen=True, slots=True)
class CertificationRuntimeBinding:
    certification_id: str
    release: str
    cutoff: datetime
    evidence_generation_id: str
    snapshot_id: str
    current_state: CertificationState
    current_source_id: str


def certification_runtime_enabled(values: Mapping[str, str] | None = None) -> bool:
    resolved = os.environ if values is None else values
    production = (
        str(resolved.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "")).strip().lower()
        == "production"
        or str(resolved.get("RENDER", "")).strip().lower() == "true"
    )
    return production and evidence_plane_enabled(resolved)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise CertificationRuntimeStateError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for certification runtime state"
        )
    return Path(raw).expanduser() / "all-market-certification-v2"


def _read_integrity_json(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CertificationRuntimeStateError(f"{label} is unavailable") from error
    if not isinstance(payload, Mapping):
        raise CertificationRuntimeStateError(f"{label} is malformed")
    body = dict(payload)
    integrity = body.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(body):
        raise CertificationRuntimeStateError(f"{label} integrity mismatch")
    return body


def resolve_certification_for_cutoff(
    cutoff: datetime,
    *,
    values: Mapping[str, str] | None = None,
) -> CertificationRuntimeBinding:
    """Resolve the latest release input only when its exact cutoff matches ``cutoff``."""

    resolved = dict(os.environ if values is None else values)
    requested = _aware(cutoff, field_name="certification_cutoff")
    release = _release(resolved)
    root = _root(resolved)
    ledger = _read_integrity_json(
        root / "ledger" / _safe(release) / "latest-input.json",
        label="certification input ledger",
    )
    if str(ledger.get("release") or "") != release:
        raise CertificationRuntimeStateError("certification input release mismatch")
    raw_cutoff = ledger.get("snapshot_cutoff")
    if not isinstance(raw_cutoff, str):
        raise CertificationRuntimeStateError("certification input cutoff is missing")
    try:
        recorded_cutoff = _aware(
            datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00")),
            field_name="recorded_certification_cutoff",
        )
    except ValueError as error:
        raise CertificationRuntimeStateError("certification input cutoff is invalid") from error
    if recorded_cutoff != requested:
        raise CertificationRuntimeStateError(
            "certification input cutoff does not match the authoritative artifact timestamp"
        )
    certification_id = str(ledger.get("record_id") or "").strip()
    evidence_generation_id = str(ledger.get("evidence_generation_id") or "").strip()
    snapshot_id = str(ledger.get("snapshot_id") or "").strip()
    if not certification_id or not evidence_generation_id or not snapshot_id:
        raise CertificationRuntimeStateError("certification input identity is incomplete")

    state = _read_integrity_json(
        root / "state" / certification_id / "latest.json",
        label="certification state pointer",
    )
    if str(state.get("certification_id") or "") != certification_id:
        raise CertificationRuntimeStateError("certification state identity mismatch")
    try:
        current_state = CertificationState(str(state["state"]))
    except (KeyError, ValueError) as error:
        raise CertificationRuntimeStateError("certification state value is invalid") from error
    current_source = str(state.get("source_id") or "").strip()
    if not current_source:
        raise CertificationRuntimeStateError("certification state source is missing")
    return CertificationRuntimeBinding(
        certification_id=certification_id,
        release=release,
        cutoff=requested,
        evidence_generation_id=evidence_generation_id,
        snapshot_id=snapshot_id,
        current_state=current_state,
        current_source_id=current_source,
    )


_LINEAR_ORDER = (
    CertificationState.EVIDENCE_READY,
    CertificationState.SNAPSHOT_FROZEN,
    CertificationState.SCREENING_COMPLETE,
    CertificationState.COMMITTEE_COMPLETE,
    CertificationState.CIO_COMPLETE,
    CertificationState.CONSTRUCTION_COMPLETE,
)
_LINEAR_RANK = {state: index for index, state in enumerate(_LINEAR_ORDER)}


def advance_linear_state_for_cutoff(
    *,
    cutoff: datetime,
    target: CertificationState,
    source_id: str,
    values: Mapping[str, str] | None = None,
    detail: str = "",
    metadata: Mapping[str, object] | None = None,
) -> CertificationStateRecord | None:
    """Advance one pre-implementation stage, tolerating only proven prior completion."""

    if target not in _LINEAR_RANK:
        raise ValueError("target must be a pre-implementation linear certification state")
    resolved = dict(os.environ if values is None else values)
    if not certification_runtime_enabled(resolved):
        return None
    binding = resolve_certification_for_cutoff(cutoff, values=resolved)
    current_rank = _LINEAR_RANK.get(binding.current_state)
    target_rank = _LINEAR_RANK[target]
    normalized_source = str(source_id).strip()
    if not normalized_source:
        raise ValueError("source_id is required")
    if current_rank is None:
        return None
    if current_rank > target_rank:
        return None
    if current_rank == target_rank:
        if binding.current_source_id != normalized_source:
            raise CertificationRuntimeStateError(
                "certification stage replay changed its authoritative source"
            )
        return None
    if current_rank + 1 != target_rank:
        raise CertificationRuntimeStateError(
            f"certification prerequisite is incomplete: current={binding.current_state.value}, target={target.value}"
        )
    try:
        return advance_certification_state(
            certification_id=binding.certification_id,
            target=target,
            source_id=normalized_source,
            values=resolved,
            detail=detail,
            metadata=metadata,
        )
    except CertificationStateError as error:
        raise CertificationRuntimeStateError(str(error)) from error


__all__ = [
    "CertificationRuntimeBinding",
    "CertificationRuntimeStateError",
    "advance_linear_state_for_cutoff",
    "certification_runtime_enabled",
    "resolve_certification_for_cutoff",
]
