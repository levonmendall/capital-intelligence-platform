"""Durable coordination for stage-isolated all-market evidence preparation.

The evidence plane is deliberately split into fresh short-lived interpreters so provider,
discovery, and paper-evidence working sets are returned to the operating system between
major phases. This module is coordination-only: it persists the exact evidence epoch,
reference binding, completed-stage prefix, and final generation identity. It performs no
provider acquisition and has no investment, candidate, sizing, construction, execution, or
real-money authority.

A failed or interrupted pipeline can resume only while its evidence epoch remains fresh.
Every stage completion is durable before the next stage starts. The immutable evidence and
snapshot stores remain the substantive authority; this journal is only a restart-safe
operational checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping


_SCHEMA_VERSION = "stage-isolated-evidence-pipeline.v1"
_STAGES = (
    "reference",
    "public_live",
    "us_equity_discovery",
    "comprehensive_discovery",
    "paper_evidence",
    "finalize",
)
_DEFAULT_MAX_AGE_SECONDS = 900.0
_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")
_ALLOWED_STATES = frozenset({"running", "failed", "completed"})


class StageIsolatedEvidencePipelineError(RuntimeError):
    """Raised when the stage-isolated coordination journal is invalid."""


@dataclass(frozen=True, slots=True)
class StageIsolatedEvidenceState:
    pipeline_id: str
    release: str
    state: str
    requested_at: datetime
    evidence_as_of: datetime
    updated_at: datetime
    completed_stages: tuple[str, ...]
    current_stage: str | None
    stage_started_at: datetime | None
    reference_manifest_id: str | None
    reference_manifest_path: str | None
    generation_id: str | None
    error_type: str | None
    error_detail: str | None
    path: Path

    @property
    def next_stage(self) -> str | None:
        if len(self.completed_stages) >= len(_STAGES):
            return None
        return _STAGES[len(self.completed_stages)]


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise StageIsolatedEvidencePipelineError(
            f"{field_name} is not a valid timestamp"
        ) from error
    return _aware(parsed, field_name=field_name)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe_release(value: str) -> str:
    normalized = _SAFE_RELEASE.sub("-", str(value or "").strip()).strip("-.")
    return normalized or "unknown"


def _path(values: Mapping[str, str]) -> Path:
    data_dir = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    release = _release(values)
    if not data_dir:
        raise StageIsolatedEvidencePipelineError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for stage-isolated evidence state"
        )
    if not release or release == "unknown":
        raise StageIsolatedEvidencePipelineError(
            "exact release identity is required for stage-isolated evidence state"
        )
    return (
        Path(data_dir).expanduser()
        / "release_prequalification_progress"
        / _safe_release(release)
        / "stage-isolated-evidence-latest.json"
    )


def _max_age_seconds(values: Mapping[str, str]) -> float:
    raw = str(values.get("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_MAX_AGE_SECONDS
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS must be numeric"
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS must be positive"
        )
    return value


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    material = dict(payload)
    material["integrity_sha256"] = _digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validated_payload(path: Path) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence state is unreadable"
        ) from error
    if not isinstance(raw, Mapping):
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence state is not an object"
        )
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence state integrity mismatch"
        )
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence state schema mismatch"
        )
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence state authority boundary is invalid"
        )
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if payload.get(authority) is not False:
            raise StageIsolatedEvidencePipelineError(
                "stage-isolated evidence state contains forbidden authority"
            )
    return payload


def _completed_prefix(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated completed stage collection is invalid"
        )
    completed = tuple(str(item) for item in value)
    if completed != _STAGES[: len(completed)]:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated completed stages are not a canonical prefix"
        )
    return completed


def _optional_text(value: object, *, limit: int = 1600) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def _state_from_payload(path: Path, payload: Mapping[str, object]) -> StageIsolatedEvidenceState:
    state = str(payload.get("state") or "").strip().lower()
    if state not in _ALLOWED_STATES:
        raise StageIsolatedEvidencePipelineError("stage-isolated state is invalid")
    completed = _completed_prefix(payload.get("completed_stages"))
    current_stage = _optional_text(payload.get("current_stage"), limit=80)
    if current_stage is not None and current_stage not in _STAGES:
        raise StageIsolatedEvidencePipelineError("stage-isolated current stage is invalid")
    if current_stage is not None and current_stage in completed:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated current stage is already completed"
        )
    stage_started_raw = payload.get("stage_started_at")
    stage_started_at = (
        None
        if stage_started_raw in (None, "")
        else _parse_timestamp(stage_started_raw, field_name="stage_started_at")
    )
    release = str(payload.get("release") or "").strip()
    pipeline_id = str(payload.get("pipeline_id") or "").strip()
    if not pipeline_id or not release:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated state identity is incomplete"
        )
    if state == "completed" and completed != _STAGES:
        raise StageIsolatedEvidencePipelineError(
            "completed stage-isolated pipeline lacks all required stages"
        )
    return StageIsolatedEvidenceState(
        pipeline_id=pipeline_id,
        release=release,
        state=state,
        requested_at=_parse_timestamp(payload.get("requested_at"), field_name="requested_at"),
        evidence_as_of=_parse_timestamp(payload.get("evidence_as_of"), field_name="evidence_as_of"),
        updated_at=_parse_timestamp(payload.get("updated_at"), field_name="updated_at"),
        completed_stages=completed,
        current_stage=current_stage,
        stage_started_at=stage_started_at,
        reference_manifest_id=_optional_text(payload.get("reference_manifest_id"), limit=256),
        reference_manifest_path=_optional_text(payload.get("reference_manifest_path"), limit=1000),
        generation_id=_optional_text(payload.get("generation_id"), limit=256),
        error_type=_optional_text(payload.get("error_type"), limit=160),
        error_detail=_optional_text(payload.get("error_detail"), limit=1600),
        path=path,
    )


def load_stage_isolated_evidence_state(
    values: Mapping[str, str] | None = None,
) -> StageIsolatedEvidenceState | None:
    resolved = dict(os.environ if values is None else values)
    path = _path(resolved)
    payload = _validated_payload(path)
    if payload is None:
        return None
    state = _state_from_payload(path, payload)
    if state.release != _release(resolved):
        return None
    return state


def _payload_for(
    state: StageIsolatedEvidenceState,
    *,
    status: str | None = None,
    evidence_as_of: datetime | None = None,
    completed_stages: tuple[str, ...] | None = None,
    current_stage: str | None | object = ...,
    stage_started_at: datetime | None | object = ...,
    reference_manifest_id: str | None | object = ...,
    reference_manifest_path: str | None | object = ...,
    generation_id: str | None | object = ...,
    error_type: str | None | object = ...,
    error_detail: str | None | object = ...,
) -> dict[str, object]:
    def choose(candidate: object, existing: object) -> object:
        return existing if candidate is ... else candidate

    now = datetime.now(timezone.utc)
    resolved_as_of = state.evidence_as_of if evidence_as_of is None else _aware(
        evidence_as_of, field_name="evidence_as_of"
    )
    resolved_completed = state.completed_stages if completed_stages is None else completed_stages
    return {
        "schema_version": _SCHEMA_VERSION,
        "pipeline_id": state.pipeline_id,
        "release": state.release,
        "state": state.state if status is None else status,
        "requested_at": state.requested_at.isoformat(),
        "evidence_as_of": resolved_as_of.isoformat(),
        "updated_at": now.isoformat(),
        "completed_stages": list(resolved_completed),
        "current_stage": choose(current_stage, state.current_stage),
        "stage_started_at": (
            None
            if choose(stage_started_at, state.stage_started_at) is None
            else _aware(
                choose(stage_started_at, state.stage_started_at),  # type: ignore[arg-type]
                field_name="stage_started_at",
            ).isoformat()
        ),
        "reference_manifest_id": choose(reference_manifest_id, state.reference_manifest_id),
        "reference_manifest_path": choose(reference_manifest_path, state.reference_manifest_path),
        "generation_id": choose(generation_id, state.generation_id),
        "error_type": choose(error_type, state.error_type),
        "error_detail": choose(error_detail, state.error_detail),
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _new_state(values: Mapping[str, str], *, requested_at: datetime) -> StageIsolatedEvidenceState:
    path = _path(values)
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "pipeline_id": uuid.uuid4().hex,
        "release": _release(values),
        "state": "running",
        "requested_at": requested_at.isoformat(),
        "evidence_as_of": requested_at.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_stages": [],
        "current_stage": None,
        "stage_started_at": None,
        "reference_manifest_id": None,
        "reference_manifest_path": None,
        "generation_id": None,
        "error_type": None,
        "error_detail": None,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_write(path, payload)
    return _state_from_payload(path, payload)


def _qualified_generation_matches(
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
    *,
    cutoff: datetime,
) -> bool:
    if state.state != "completed" or not state.generation_id:
        return False
    path = (
        Path(values["CAPITAL_INTELLIGENCE_DATA_DIR"]).expanduser()
        / "continuous_evidence_plane"
        / "latest-qualified.json"
    )
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(raw, Mapping):
        return False
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        return False
    if payload.get("schema_version") != "continuous-evidence-plane.v1":
        return False
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        return False
    if str(payload.get("release") or "").strip() != state.release:
        return False
    if str(payload.get("generation_id") or "").strip() != state.generation_id:
        return False
    try:
        as_of = _parse_timestamp(payload.get("as_of"), field_name="generation_as_of")
    except StageIsolatedEvidencePipelineError:
        return False
    age = cutoff - as_of
    return timedelta(0) <= age <= timedelta(seconds=_max_age_seconds(values))


def ensure_stage_isolated_evidence_pipeline(
    values: Mapping[str, str] | None = None,
    *,
    requested_at: datetime | None = None,
) -> StageIsolatedEvidenceState:
    resolved = dict(os.environ if values is None else values)
    requested = _aware(
        datetime.now(timezone.utc) if requested_at is None else requested_at,
        field_name="requested_at",
    )
    existing = load_stage_isolated_evidence_state(resolved)
    if existing is not None:
        if _qualified_generation_matches(existing, resolved, cutoff=requested):
            return existing
        age = requested - existing.evidence_as_of
        resumable = bool(
            existing.state in {"running", "failed"}
            and timedelta(seconds=-5) <= age <= timedelta(seconds=_max_age_seconds(resolved))
            and existing.completed_stages == _STAGES[: len(existing.completed_stages)]
        )
        if resumable:
            return existing
    return _new_state(resolved, requested_at=requested)


def _require_pipeline(
    values: Mapping[str, str],
    *,
    pipeline_id: str,
) -> StageIsolatedEvidenceState:
    state = load_stage_isolated_evidence_state(values)
    if state is None or state.pipeline_id != str(pipeline_id).strip():
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence pipeline identity changed"
        )
    return state


def begin_evidence_stage(
    values: Mapping[str, str],
    *,
    pipeline_id: str,
    stage: str,
) -> StageIsolatedEvidenceState:
    state = _require_pipeline(values, pipeline_id=pipeline_id)
    normalized = str(stage).strip()
    if normalized not in _STAGES:
        raise ValueError("unsupported stage-isolated evidence stage")
    if normalized in state.completed_stages:
        return state
    if state.next_stage != normalized:
        raise StageIsolatedEvidencePipelineError(
            f"stage-isolated evidence stage order violation: expected={state.next_stage}; received={normalized}"
        )
    payload = _payload_for(
        state,
        status="running",
        current_stage=normalized,
        stage_started_at=datetime.now(timezone.utc),
        error_type=None,
        error_detail=None,
    )
    _atomic_write(state.path, payload)
    return _state_from_payload(state.path, payload)


def complete_evidence_stage(
    values: Mapping[str, str],
    *,
    pipeline_id: str,
    stage: str,
    evidence_as_of: datetime | None = None,
    reference_manifest_id: str | None = None,
    reference_manifest_path: str | None = None,
    generation_id: str | None = None,
) -> StageIsolatedEvidenceState:
    state = _require_pipeline(values, pipeline_id=pipeline_id)
    normalized = str(stage).strip()
    if normalized in state.completed_stages:
        return state
    if state.current_stage != normalized or state.next_stage != normalized:
        raise StageIsolatedEvidencePipelineError(
            "stage-isolated evidence stage completed without owning the current boundary"
        )
    completed = (*state.completed_stages, normalized)
    status = "completed" if completed == _STAGES else "running"
    if normalized == "finalize" and not generation_id:
        raise StageIsolatedEvidencePipelineError(
            "final stage must publish a qualified generation identifier"
        )
    payload = _payload_for(
        state,
        status=status,
        evidence_as_of=evidence_as_of,
        completed_stages=completed,
        current_stage=None,
        stage_started_at=None,
        reference_manifest_id=(
            state.reference_manifest_id
            if reference_manifest_id is None
            else str(reference_manifest_id).strip() or None
        ),
        reference_manifest_path=(
            state.reference_manifest_path
            if reference_manifest_path is None
            else str(reference_manifest_path).strip() or None
        ),
        generation_id=(state.generation_id if generation_id is None else generation_id),
        error_type=None,
        error_detail=None,
    )
    _atomic_write(state.path, payload)
    return _state_from_payload(state.path, payload)


def fail_evidence_stage(
    values: Mapping[str, str],
    *,
    pipeline_id: str,
    stage: str,
    error_type: str,
    error_detail: str,
) -> StageIsolatedEvidenceState:
    state = _require_pipeline(values, pipeline_id=pipeline_id)
    normalized = str(stage).strip()
    if normalized not in _STAGES:
        raise ValueError("unsupported stage-isolated evidence stage")
    payload = _payload_for(
        state,
        status="failed",
        current_stage=normalized,
        stage_started_at=(state.stage_started_at or datetime.now(timezone.utc)),
        error_type=str(error_type).strip()[:160] or "StageError",
        error_detail=str(error_detail).strip()[:1600] or "stage failed",
    )
    _atomic_write(state.path, payload)
    return _state_from_payload(state.path, payload)


__all__ = [
    "StageIsolatedEvidencePipelineError",
    "StageIsolatedEvidenceState",
    "_STAGES",
    "begin_evidence_stage",
    "complete_evidence_stage",
    "ensure_stage_isolated_evidence_pipeline",
    "fail_evidence_stage",
    "load_stage_isolated_evidence_state",
]
