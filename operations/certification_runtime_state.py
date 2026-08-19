"""Cross-process resolver and completion helpers for all-market certification v2.

The certification input is frozen by the provider-free evidence consumer. Downstream
screening, committee, CIO, construction, and paper-implementation processes may run in
separate processes, so they resolve the immutable input from disk by its exact point-in-
time cutoff rather than through process environment variables or a mutable "latest"
pointer.

This module is operational lineage only. It grants no investment, specialist,
construction, execution, or real-money authority.
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


_SCHEMA = "all-market-certification-input.v2"


class CertificationRuntimeStateError(RuntimeError):
    """Raised when persisted certification lineage cannot be trusted or advanced."""


@dataclass(frozen=True, slots=True)
class CertificationRuntimeBinding:
    certification_id: str
    release: str
    cutoff: datetime
    evidence_generation_id: str
    snapshot_id: str
    global_discovery_snapshot_id: str
    us_equity_discovery_snapshot_id: str
    paper_evidence_snapshot_id: str
    policy_compatibility_hash: str
    current_state: CertificationState
    current_source_id: str


def _capability_scoped_operation_enabled(values: Mapping[str, str]) -> bool:
    """Return whether this process is the independently governed operating CIO path.

    Capability-scoped operation and exhaustive all-market certification intentionally have
    separate readiness boundaries.  An explicit setting wins; Render defaults to the
    capability-scoped operating path in the same way as production-context publication.
    Setting the flag explicitly false preserves the strict all-market certification path
    for a comprehensive certification process running in production.
    """

    explicit = values.get("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip().lower() in {"1", "true", "yes", "on"}
    return str(values.get("RENDER", "")).strip().lower() == "true"


def certification_runtime_enabled(
    values: Mapping[str, str] | None = None,
) -> bool:
    """Return whether this process owns the exhaustive all-market lineage state machine.

    The capability-scoped CIO consumes a separately qualified immutable operating-evidence
    snapshot and must not advance or wait on all-market certification stages.  Full-market
    certification remains fail-closed and unchanged when capability-scoped operation is
    explicitly disabled.
    """

    resolved = os.environ if values is None else values
    production = (
        str(resolved.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "")).strip().lower()
        == "production"
        or str(resolved.get("RENDER", "")).strip().lower() == "true"
    )
    return (
        production
        and evidence_plane_enabled(resolved)
        and not _capability_scoped_operation_enabled(resolved)
    )


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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


def _stamp(value: datetime) -> str:
    return _aware(value, field_name="certification_cutoff").strftime(
        "%Y%m%dT%H%M%S%fZ"
    )


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


def _input_pointer_for_cutoff(
    *,
    cutoff: datetime,
    values: Mapping[str, str],
) -> Mapping[str, object]:
    release = _release(values)
    root = _root(values)
    exact_path = (
        root
        / "ledger"
        / _safe(release)
        / "by-cutoff"
        / f"{_stamp(cutoff)}.json"
    )
    if exact_path.exists():
        # If an exact index exists, any unreadable/corrupt content is authoritative
        # evidence of a lineage problem. Never hide it by falling back to a mutable
        # latest pointer.
        return _read_integrity_json(
            exact_path,
            label="certification input cutoff ledger",
        )

    # Compatibility only for inputs created before the exact-cutoff index existed. The
    # mutable latest pointer is accepted only when its own recorded cutoff exactly
    # matches the requested cutoff; it can never bind an older stage to a newer cycle.
    latest = _read_integrity_json(
        root / "ledger" / _safe(release) / "latest-input.json",
        label="certification input ledger",
    )
    raw_cutoff = latest.get("snapshot_cutoff")
    if not isinstance(raw_cutoff, str):
        raise CertificationRuntimeStateError(
            "certification input cutoff is missing"
        )
    try:
        recorded = _aware(
            datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00")),
            field_name="recorded_certification_cutoff",
        )
    except ValueError as error:
        raise CertificationRuntimeStateError(
            "certification input cutoff is invalid"
        ) from error
    if recorded != cutoff:
        raise CertificationRuntimeStateError(
            "certification input cutoff does not match the authoritative artifact timestamp"
        )
    return latest


def _binding_from_ledger(
    *,
    requested: datetime,
    release: str,
    ledger: Mapping[str, object],
    values: Mapping[str, str],
) -> CertificationRuntimeBinding:
    if ledger.get("schema_version") != _SCHEMA:
        raise CertificationRuntimeStateError("certification input schema mismatch")
    if str(ledger.get("release") or "") != release:
        raise CertificationRuntimeStateError("certification input release mismatch")

    raw_cutoff = ledger.get("snapshot_cutoff")
    if not isinstance(raw_cutoff, str):
        raise CertificationRuntimeStateError("certification input cutoff is missing")
    try:
        recorded = _aware(
            datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00")),
            field_name="recorded_certification_cutoff",
        )
    except ValueError as error:
        raise CertificationRuntimeStateError(
            "certification input cutoff is invalid"
        ) from error
    if recorded != requested:
        raise CertificationRuntimeStateError(
            "certification input cutoff does not match the authoritative artifact timestamp"
        )

    certification_id = str(ledger.get("record_id") or "").strip()
    generation_id = str(ledger.get("evidence_generation_id") or "").strip()
    snapshot_id = str(ledger.get("snapshot_id") or "").strip()
    global_snapshot_id = str(
        ledger.get("global_discovery_snapshot_id") or ""
    ).strip()
    equity_snapshot_id = str(
        ledger.get("us_equity_discovery_snapshot_id") or ""
    ).strip()
    paper_snapshot_id = str(
        ledger.get("paper_evidence_snapshot_id") or ""
    ).strip()
    policy_hash = str(ledger.get("policy_compatibility_hash") or "").strip()
    if not certification_id or not generation_id or not snapshot_id:
        raise CertificationRuntimeStateError(
            "certification input identity is incomplete"
        )

    state = _read_integrity_json(
        _root(values) / "state" / certification_id / "latest.json",
        label="certification state pointer",
    )
    if str(state.get("certification_id") or "") != certification_id:
        raise CertificationRuntimeStateError("certification state identity mismatch")
    try:
        current = CertificationState(str(state["state"]))
    except (KeyError, ValueError) as error:
        raise CertificationRuntimeStateError(
            "certification state value is invalid"
        ) from error
    source = str(state.get("source_id") or "").strip()
    if not source:
        raise CertificationRuntimeStateError("certification state source is missing")

    return CertificationRuntimeBinding(
        certification_id=certification_id,
        release=release,
        cutoff=requested,
        evidence_generation_id=generation_id,
        snapshot_id=snapshot_id,
        global_discovery_snapshot_id=global_snapshot_id,
        us_equity_discovery_snapshot_id=equity_snapshot_id,
        paper_evidence_snapshot_id=paper_snapshot_id,
        policy_compatibility_hash=policy_hash,
        current_state=current,
        current_source_id=source,
    )


def resolve_certification_for_cutoff(
    cutoff: datetime,
    *,
    values: Mapping[str, str] | None = None,
) -> CertificationRuntimeBinding:
    resolved = dict(os.environ if values is None else values)
    requested = _aware(cutoff, field_name="certification_cutoff")
    release = _release(resolved)
    ledger = _input_pointer_for_cutoff(cutoff=requested, values=resolved)
    return _binding_from_ledger(
        requested=requested,
        release=release,
        ledger=ledger,
        values=resolved,
    )


def resolve_latest_certification(
    *,
    values: Mapping[str, str] | None = None,
) -> CertificationRuntimeBinding | None:
    """Resolve the latest immutable input and its current durable certification state."""

    resolved = dict(os.environ if values is None else values)
    if not certification_runtime_enabled(resolved):
        return None
    release = _release(resolved)
    latest = _read_integrity_json(
        _root(resolved) / "ledger" / _safe(release) / "latest-input.json",
        label="certification input ledger",
    )
    raw_cutoff = latest.get("snapshot_cutoff")
    if not isinstance(raw_cutoff, str):
        raise CertificationRuntimeStateError("certification input cutoff is missing")
    try:
        requested = _aware(
            datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00")),
            field_name="recorded_certification_cutoff",
        )
    except ValueError as error:
        raise CertificationRuntimeStateError(
            "certification input cutoff is invalid"
        ) from error
    # Re-resolve through the exact-cutoff index so a corrupt exact ledger cannot be
    # hidden by the mutable latest pointer.
    return resolve_certification_for_cutoff(requested, values=resolved)


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
    """Advance exactly one pre-implementation stage for an exact CIO cutoff."""

    if target not in _LINEAR_RANK:
        raise ValueError(
            "target must be a pre-implementation linear certification state"
        )
    resolved = dict(os.environ if values is None else values)
    if not certification_runtime_enabled(resolved):
        return None
    source = str(source_id).strip()
    if not source:
        raise ValueError("source_id is required")

    binding = resolve_certification_for_cutoff(cutoff, values=resolved)
    current_rank = _LINEAR_RANK.get(binding.current_state)
    target_rank = _LINEAR_RANK[target]
    if current_rank is None:
        if binding.current_state in {
            CertificationState.PAPER_IMPLEMENTED,
            CertificationState.NO_ACTION,
            CertificationState.CERTIFIED,
        }:
            return None
        raise CertificationRuntimeStateError(
            f"unexpected certification state {binding.current_state.value}"
        )
    if current_rank > target_rank:
        return None
    if current_rank == target_rank:
        if binding.current_source_id != source:
            raise CertificationRuntimeStateError(
                "certification stage replay changed its authoritative source"
            )
        return None
    if current_rank + 1 != target_rank:
        raise CertificationRuntimeStateError(
            "certification prerequisite is incomplete: "
            f"current={binding.current_state.value}, target={target.value}"
        )
    try:
        return advance_certification_state(
            certification_id=binding.certification_id,
            target=target,
            source_id=source,
            values=resolved,
            detail=detail,
            metadata=metadata,
        )
    except CertificationStateError as error:
        raise CertificationRuntimeStateError(str(error)) from error


def complete_certification_for_cutoff(
    *,
    cutoff: datetime,
    outcome: CertificationState,
    source_id: str,
    values: Mapping[str, str] | None = None,
    detail: str = "",
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Advance construction to a truthful terminal paper/no-action outcome and certify."""

    if outcome not in {
        CertificationState.PAPER_IMPLEMENTED,
        CertificationState.NO_ACTION,
    }:
        raise ValueError("outcome must be PAPER_IMPLEMENTED or NO_ACTION")
    resolved = dict(os.environ if values is None else values)
    if not certification_runtime_enabled(resolved):
        return
    source = str(source_id).strip()
    if not source:
        raise ValueError("source_id is required")

    binding = resolve_certification_for_cutoff(cutoff, values=resolved)
    if binding.current_state is CertificationState.CERTIFIED:
        return
    if binding.current_state is CertificationState.CONSTRUCTION_COMPLETE:
        try:
            advance_certification_state(
                certification_id=binding.certification_id,
                target=outcome,
                source_id=source,
                values=resolved,
                detail=detail,
                metadata=metadata,
            )
        except CertificationStateError as error:
            raise CertificationRuntimeStateError(str(error)) from error
        binding = resolve_certification_for_cutoff(cutoff, values=resolved)
    if binding.current_state is not outcome:
        raise CertificationRuntimeStateError(
            f"cannot complete certification from {binding.current_state.value}"
        )
    try:
        advance_certification_state(
            certification_id=binding.certification_id,
            target=CertificationState.CERTIFIED,
            source_id=f"certified:{source}",
            values=resolved,
            detail="all-market certification completed",
            metadata={
                "implementation_outcome": outcome.value,
                **dict(metadata or {}),
            },
        )
    except CertificationStateError as error:
        raise CertificationRuntimeStateError(str(error)) from error


__all__ = [
    "CertificationRuntimeBinding",
    "CertificationRuntimeStateError",
    "advance_linear_state_for_cutoff",
    "certification_runtime_enabled",
    "complete_certification_for_cutoff",
    "resolve_certification_for_cutoff",
    "resolve_latest_certification",
]
