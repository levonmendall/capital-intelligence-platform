"""Credential-safe release evidence prequalification state.

This state is deliberately distinct from a CIO diagnostic request. Deployment may spend
several minutes validating or selectively refreshing evidence, but the CIO request is not
created until an immutable exact-release generation is ready.

Comprehensive-discovery certification runs before that CIO request exists. Its parent-owned
runtime journal is therefore projected through release prequalification, not through manual
CIO state. Live journal data remains a separately validated operational projection; terminal
failure snapshots the exact blocker into this integrity-protected record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations.evidence_prequalification_attribution import (
    failed_prequalification_attribution,
)

_SCHEMA = "release-evidence-prequalification.v1"
_DAG_RUNTIME_SCHEMA = "persistent-certification-runtime.v1"
_DAG_SCHEDULER_SCHEMA = "persistent-certification-dag.v1"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
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


def _parse_aware(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_token(value: object, *, limit: int = 160) -> str | None:
    candidate = str(value or "").strip()[:limit]
    return candidate if _SAFE_TOKEN.fullmatch(candidate) else None


def _safe_nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0


def _safe_provider_groups(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    providers: list[str] = []
    for item in value:
        provider = _safe_token(item)
        if provider and provider not in providers:
            providers.append(provider)
        if len(providers) >= 12:
            break
    return providers


def _dag_runtime_root(values: Mapping[str, str]) -> Path:
    root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return root / "certification-dag" / _DAG_SCHEDULER_SCHEMA / _release(values)


def _safe_dag_runtime_payload(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    if raw.get("schema_version") != _DAG_RUNTIME_SCHEMA:
        return None
    if raw.get("paper_only") is not True or raw.get("real_money_authorized") is not False:
        return None
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "execution_authority",
    ):
        if raw.get(authority) is not False:
            return None

    release_sha = _safe_token(raw.get("release_sha"))
    decision_epoch = _parse_aware(raw.get("decision_epoch"))
    updated_at = _parse_aware(raw.get("updated_at"))
    if not release_sha or decision_epoch is None or updated_at is None:
        return None

    raw_nodes = raw.get("node_states")
    if not isinstance(raw_nodes, Mapping):
        return None
    node_states: dict[str, dict[str, object]] = {}
    for raw_node_id, raw_state in sorted(raw_nodes.items(), key=lambda item: str(item[0])):
        node_id = _safe_token(raw_node_id)
        if node_id is None or not isinstance(raw_state, Mapping):
            continue
        state = _safe_token(raw_state.get("state")) or "unknown"
        asset_class = _safe_token(raw_state.get("asset_class"))
        failure_type = _safe_token(raw_state.get("failure_type"))
        node_states[node_id] = {
            "state": state,
            "asset_class": asset_class,
            "provider_groups": _safe_provider_groups(raw_state.get("provider_groups")),
            "decision_eligible_count": _safe_nonnegative_int(
                raw_state.get("decision_eligible_count")
            ),
            "reused": raw_state.get("reused") is True,
            "failure_type": failure_type,
        }

    raw_required = raw.get("required_nodes")
    required_nodes = [
        node_id
        for item in (raw_required if isinstance(raw_required, list | tuple) else ())
        if (node_id := _safe_token(item)) is not None
    ]
    counts_source = raw.get("counts")
    counts_raw = counts_source if isinstance(counts_source, Mapping) else {}
    counts = {
        "required_nodes": len(required_nodes),
        "completed_nodes": _safe_nonnegative_int(counts_raw.get("completed_nodes")),
        "reused_nodes": _safe_nonnegative_int(counts_raw.get("reused_nodes")),
        "failed_nodes": _safe_nonnegative_int(counts_raw.get("failed_nodes")),
        "running_nodes": _safe_nonnegative_int(counts_raw.get("running_nodes")),
        "pending_nodes": _safe_nonnegative_int(counts_raw.get("pending_nodes")),
    }

    def first_node(states: set[str]) -> tuple[str, Mapping[str, object]] | None:
        for node_id, item in node_states.items():
            if str(item.get("state") or "").lower() in states:
                return node_id, item
        return None

    blocking = first_node({"failed", "timed-out", "timed_out", "invalid"})
    active = first_node({"running"})
    pending = first_node({"pending"})
    focus = blocking or active or pending
    focus_node = None if focus is None else focus[0]
    focus_state = {} if focus is None else focus[1]

    return {
        "schema_version": _DAG_RUNTIME_SCHEMA,
        "release_sha": release_sha,
        "decision_epoch": decision_epoch.isoformat(),
        "updated_at": updated_at.isoformat(),
        "counts": counts,
        "required_nodes": required_nodes,
        "node_states": node_states,
        "active_node": None if active is None else active[0],
        "blocking_node": None if blocking is None else blocking[0],
        "focus_node": focus_node,
        "asset_class": focus_state.get("asset_class"),
        "provider_groups": list(focus_state.get("provider_groups") or []),
        "failure_type": focus_state.get("failure_type"),
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def load_release_certification_dag_progress(
    values: Mapping[str, str],
    *,
    started_at: datetime | None = None,
) -> Mapping[str, object] | None:
    """Load the newest current-release DAG journal that belongs to this attempt.

    Runtime journals have no decision authority. This loader is deliberately strict about
    release identity, timestamps, credential safety, paper-only state, and all authority
    flags before allowing a journal to explain release prequalification progress.
    """

    release = _release(values)
    if not release or release == "unknown":
        return None
    boundary = None
    if started_at is not None:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("release prequalification started_at must be timezone-aware")
        boundary = started_at.astimezone(timezone.utc)

    newest: tuple[datetime, dict[str, object]] | None = None
    root = _dag_runtime_root(values)
    try:
        candidates = tuple(root.glob("*/runtime-latest.json"))
    except OSError:
        return None
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        safe = _safe_dag_runtime_payload(raw)
        if safe is None or safe.get("release_sha") != release:
            continue
        updated_at = _parse_aware(safe.get("updated_at"))
        decision_epoch = _parse_aware(safe.get("decision_epoch"))
        if updated_at is None or decision_epoch is None:
            continue
        if boundary is not None and (updated_at < boundary or decision_epoch < boundary):
            continue
        if newest is None or updated_at > newest[0]:
            newest = (updated_at, safe)
    return None if newest is None else newest[1]


def _dag_failure_detail(progress: Mapping[str, object]) -> str:
    counts = progress.get("counts")
    safe_counts = counts if isinstance(counts, Mapping) else {}
    node = _safe_token(progress.get("blocking_node") or progress.get("focus_node"))
    asset_class = _safe_token(progress.get("asset_class"))
    failure_type = _safe_token(progress.get("failure_type"))
    providers = _safe_provider_groups(progress.get("provider_groups"))
    parts = [
        "certification_dag_failure",
        f"node={node or 'unknown'}",
        f"asset_class={asset_class or 'unknown'}",
        f"failure_type={failure_type or 'unknown'}",
        f"completed_nodes={_safe_nonnegative_int(safe_counts.get('completed_nodes'))}",
        f"required_nodes={_safe_nonnegative_int(safe_counts.get('required_nodes'))}",
        f"reused_nodes={_safe_nonnegative_int(safe_counts.get('reused_nodes'))}",
        f"failed_nodes={_safe_nonnegative_int(safe_counts.get('failed_nodes'))}",
        f"running_nodes={_safe_nonnegative_int(safe_counts.get('running_nodes'))}",
        f"pending_nodes={_safe_nonnegative_int(safe_counts.get('pending_nodes'))}",
    ]
    if providers:
        parts.append("providers=" + ",".join(providers))
    return "; ".join(parts)


def _project_live_dag_progress(
    raw: Mapping[str, object],
    *,
    values: Mapping[str, str],
) -> Mapping[str, object]:
    """Overlay validated live DAG progress after the stored integrity check succeeds.

    This projection never rewrites the signed prequalification file. It exists so the
    already-established public prequalification publisher can expose pre-CIO DAG progress
    while the evidence child is still running. Terminal state always uses its signed DAG
    snapshot instead of mutable live state.
    """

    if str(raw.get("state") or "").strip().lower() not in {"pending", "in_progress"}:
        return raw
    started_at = _parse_aware(raw.get("started_at"))
    if started_at is None:
        return raw
    dag_progress = load_release_certification_dag_progress(values, started_at=started_at)
    if dag_progress is None:
        return raw

    counts = dag_progress.get("counts")
    safe_counts = counts if isinstance(counts, Mapping) else {}
    metrics = dict(raw.get("metrics") or {}) if isinstance(raw.get("metrics"), Mapping) else {}
    for name in (
        "required_nodes",
        "completed_nodes",
        "reused_nodes",
        "failed_nodes",
        "running_nodes",
        "pending_nodes",
    ):
        metrics[name] = _safe_nonnegative_int(safe_counts.get(name))

    blocking_node = _safe_token(dag_progress.get("blocking_node"))
    focus_node = _safe_token(dag_progress.get("focus_node"))
    asset_class = _safe_token(dag_progress.get("asset_class"))
    failure_type = _safe_token(dag_progress.get("failure_type"))
    if blocking_node:
        stage = f"certification_dag_failed:{asset_class or 'other'}"
    elif focus_node:
        stage = f"certification_dag:{asset_class or 'other'}"
    else:
        stage = str(raw.get("stage") or "evidence_refresh")

    projected = dict(raw)
    projected.update(
        {
            "stage": stage,
            "detail": (
                "governed_prequalification_dag_progress; "
                f"node={blocking_node or focus_node or 'unknown'}; "
                f"asset_class={asset_class or 'unknown'}; "
                f"failure_type={failure_type or 'none'}"
            )[:1000],
            "metrics": metrics,
            "dag_progress": dag_progress,
            "runtime_projection": True,
        }
    )
    return projected


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

    dag_progress: Mapping[str, object] | None = None
    failure_context: Mapping[str, object] | None = None
    persisted_detail = str(detail)[:1000]
    if normalized_state == "failed":
        dag_progress = load_release_certification_dag_progress(values, started_at=start)
        if dag_progress is not None:
            dag_detail = _dag_failure_detail(dag_progress)
            persisted_detail = (persisted_detail + "; " + dag_detail).strip("; ")[:1000]
        attribution = failed_prequalification_attribution(
            detail=persisted_detail,
            metrics=normalized_metrics,
        ).as_dict()
        if dag_progress is not None:
            attribution = dict(attribution)
            blocking_node = _safe_token(
                dag_progress.get("blocking_node") or dag_progress.get("focus_node")
            )
            asset_class = _safe_token(dag_progress.get("asset_class"))
            failure_type = _safe_token(dag_progress.get("failure_type"))
            providers = _safe_provider_groups(dag_progress.get("provider_groups"))
            attribution.update(
                {
                    "capability": "comprehensive_discovery",
                    "failure_stage": (
                        f"certification_dag:{asset_class}"
                        if asset_class
                        else "certification_dag"
                    ),
                    "blocking_node": blocking_node,
                    "asset_class": asset_class,
                    "failure_type": failure_type,
                    "provider_groups": providers,
                    "certification_dag": dag_progress,
                }
            )
            if failure_type and any(
                token in failure_type.lower()
                for token in ("timeout", "timedout", "deadline")
            ):
                attribution["reason"] = "deadline_exceeded"
                attribution["error_type"] = failure_type
        failure_context = attribution

    material: dict[str, object] = {
        "schema_version": _SCHEMA,
        "prequalification_id": prequalification_id or uuid.uuid4().hex,
        "release": _release(values),
        "state": normalized_state,
        "stage": normalized_stage,
        "started_at": start.astimezone(timezone.utc).isoformat(),
        "updated_at": now.isoformat(),
        "completed_at": now.isoformat() if normalized_state in {"completed", "failed"} else None,
        "detail": persisted_detail,
        "metrics": normalized_metrics,
        "generation_id": str(generation_id or ""),
        "dag_progress": dag_progress,
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
    return _project_live_dag_progress(raw, values=values)


__all__ = [
    "load_release_certification_dag_progress",
    "load_release_evidence_prequalification",
    "write_release_evidence_prequalification",
]
