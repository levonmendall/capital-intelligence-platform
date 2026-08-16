"""Credential-safe release evidence prequalification state.

This state is deliberately distinct from a CIO diagnostic request. Deployment may spend
several minutes validating or selectively refreshing evidence, but the CIO request is not
created until an immutable exact-release generation is ready.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations.evidence_prequalification_attribution import (
    failed_prequalification_attribution,
)

_SCHEMA = "release-evidence-prequalification.v1"
_ALLOWED_STATES = frozenset({"pending", "in_progress", "completed", "failed"})
_ALLOWED_STAGES = frozenset(
    {
        "evidence_prequalifying",
        "reference_components",
        "evidence_refresh",
        "evidence_generation_ready",
        "evidence_prequalification_failed",
    }
)


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


def _path(values: Mapping[str, str]) -> Path:
    root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return root / "release_evidence" / "prequalification-latest.json"


def write_release_evidence_prequalification(
    values: Mapping[str, str],
    *,
    state: str,
    stage: str,
    prequalification_id: str | None = None,
    started_at: datetime | None = None,
    detail: str = "",
    metrics: Mapping[str, int] | None = None,
    generation_id: str | None = None,
) -> Mapping[str, object]:
    normalized_state = str(state).strip().lower()
    normalized_stage = str(stage).strip()
    if normalized_state not in _ALLOWED_STATES:
        raise ValueError("release evidence prequalification state is invalid")
    if normalized_stage not in _ALLOWED_STAGES:
        raise ValueError("release evidence prequalification stage is invalid")
    now = datetime.now(timezone.utc)
    start = started_at or now
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("release evidence prequalification started_at must be timezone-aware")
    normalized_metrics: dict[str, int] = {}
    for name, value in sorted((metrics or {}).items()):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("prequalification metric name is invalid")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("prequalification metrics must be nonnegative integers")
        normalized_metrics[name.strip()] = value

    failure_context: Mapping[str, object] | None = None
    if normalized_state == "failed":
        failure_context = failed_prequalification_attribution(
            detail=detail,
            metrics=normalized_metrics,
        ).as_dict()

    material: dict[str, object] = {
        "schema_version": _SCHEMA,
        "prequalification_id": prequalification_id or uuid.uuid4().hex,
        "release": _release(values),
        "state": normalized_state,
        "stage": normalized_stage,
        "started_at": start.astimezone(timezone.utc).isoformat(),
        "updated_at": now.isoformat(),
        "completed_at": now.isoformat() if normalized_state in {"completed", "failed"} else None,
        "detail": str(detail)[:1000],
        "metrics": normalized_metrics,
        "generation_id": str(generation_id or ""),
        "failure_context": failure_context,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    payload = {**material, "integrity_sha256": _digest(material)}
    path = _path(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return payload


def load_release_evidence_prequalification(
    values: Mapping[str, str],
) -> Mapping[str, object] | None:
    path = _path(values)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping) or raw.get("schema_version") != _SCHEMA:
        return None
    material = dict(raw)
    integrity = material.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(material):
        return None
    if str(raw.get("release") or "").strip() != _release(values):
        return None
    if raw.get("credential_safe") is not True:
        return None
    if raw.get("paper_only") is not True or raw.get("real_money_authorized") is not False:
        return None
    return raw


__all__ = [
    "load_release_evidence_prequalification",
    "write_release_evidence_prequalification",
]
