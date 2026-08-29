"""Project bounded certification failure cause through the parent runtime journal.

The certification DAG already preserves credential-safe failure message/cause metadata in
``CertificationNodeResult``. The parent runtime journal historically retained only the
failure type, which made the release prequalification diagnostic lose the exact terminal
cause. This module is observability-only: it copies the already-bounded terminal metadata
into the parent-owned runtime journal and validates it again before public projection.
Scheduling, evidence requirements, provider behavior, market scope, authority, and
paper-only controls are unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from operations import dag_native_comprehensive_supervision as _dag
from operations import persistent_certification_scheduler as _scheduler
from operations import release_evidence_prequalification as _release


def _bounded_optional_failure_text(value: object) -> str | None:
    if value is None:
        return None
    return _scheduler._bounded_failure_text(value)


def _result_failure_fields(result: object) -> dict[str, object]:
    """Return only bounded scheduler-owned terminal failure metadata."""

    failure_type = _release._safe_token(getattr(result, "failure_type", None))
    if failure_type is None:
        return {}
    retry_after = getattr(result, "retry_after", None)
    retry_after_value = (
        retry_after.isoformat()
        if isinstance(retry_after, datetime)
        and retry_after.tzinfo is not None
        and retry_after.utcoffset() is not None
        else None
    )
    return {
        "failure_message": _bounded_optional_failure_text(
            getattr(result, "failure_message", None)
        ),
        "failure_cause_type": _release._safe_token(
            getattr(result, "failure_cause_type", None)
        ),
        "failure_cause_message": _bounded_optional_failure_text(
            getattr(result, "failure_cause_message", None)
        ),
        "retryable": getattr(result, "retryable", False) is True,
        "retry_after": retry_after_value,
    }


def _augment_runtime_body(
    body: Mapping[str, object],
    *,
    results: Mapping[str, object],
) -> dict[str, object]:
    """Add causal metadata only to already-terminal failed node states."""

    projected = dict(body)
    raw_states = body.get("node_states")
    if not isinstance(raw_states, Mapping):
        return projected
    node_states: dict[str, object] = {}
    for raw_node_id, raw_state in raw_states.items():
        node_id = str(raw_node_id)
        item = dict(raw_state) if isinstance(raw_state, Mapping) else raw_state
        if isinstance(item, dict) and str(item.get("state") or "").lower() == "failed":
            result = results.get(node_id)
            if result is not None:
                item.update(_result_failure_fields(result))
        node_states[node_id] = item
    projected["node_states"] = node_states
    return projected


def _safe_projected_failure_fields(raw_state: Mapping[str, object]) -> dict[str, object]:
    """Revalidate bounded terminal metadata before release-diagnostic projection."""

    if str(raw_state.get("state") or "").strip().lower() != "failed":
        return {}
    failure_message = _bounded_optional_failure_text(raw_state.get("failure_message"))
    failure_cause_type = _release._safe_token(raw_state.get("failure_cause_type"))
    failure_cause_message = _bounded_optional_failure_text(
        raw_state.get("failure_cause_message")
    )
    retry_after = _release._parse_aware(raw_state.get("retry_after"))
    return {
        "failure_message": failure_message,
        "failure_cause_type": failure_cause_type,
        "failure_cause_message": failure_cause_message,
        "retryable": raw_state.get("retryable") is True,
        "retry_after": None if retry_after is None else retry_after.isoformat(),
    }


def _install_runtime_journal_projection() -> None:
    current = _dag._publish_runtime_journal
    if getattr(current, "_bounded_failure_cause_projection", False):
        return

    def publish_runtime_journal(self, *, nodes, results, pending, running) -> None:
        current(
            self,
            nodes=nodes,
            results=results,
            pending=pending,
            running=running,
        )
        path = (
            _scheduler._root(self.values)
            / _scheduler._SCHEMA_VERSION
            / self.release_sha
            / _scheduler._epoch_key(self.epoch)
            / "runtime-latest.json"
        )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, Mapping):
            return
        if raw.get("schema_version") != _dag._RUNTIME_JOURNAL_SCHEMA:
            return
        if raw.get("release_sha") != self.release_sha:
            return
        if raw.get("paper_only") is not True or raw.get("real_money_authorized") is not False:
            return
        projected = _augment_runtime_body(raw, results=results)
        if projected != raw:
            _scheduler._atomic_json(path, projected)

    publish_runtime_journal.__dict__.update(getattr(current, "__dict__", {}))
    publish_runtime_journal._bounded_failure_cause_projection = True  # type: ignore[attr-defined]
    _dag._publish_runtime_journal = publish_runtime_journal


def _install_release_projection() -> None:
    current = _release._safe_dag_runtime_payload
    if getattr(current, "_bounded_failure_cause_projection", False):
        return

    def safe_dag_runtime_payload(raw: object) -> dict[str, object] | None:
        safe = current(raw)
        if safe is None or not isinstance(raw, Mapping):
            return safe
        raw_states = raw.get("node_states")
        safe_states = safe.get("node_states")
        if not isinstance(raw_states, Mapping) or not isinstance(safe_states, Mapping):
            return safe

        node_states: dict[str, object] = {}
        for node_id, safe_state in safe_states.items():
            item = dict(safe_state) if isinstance(safe_state, Mapping) else safe_state
            raw_state = raw_states.get(node_id)
            if isinstance(item, dict) and isinstance(raw_state, Mapping):
                item.update(_safe_projected_failure_fields(raw_state))
            node_states[str(node_id)] = item

        projected = dict(safe)
        projected["node_states"] = node_states
        focus_node = str(projected.get("blocking_node") or projected.get("focus_node") or "")
        focus_state = node_states.get(focus_node)
        if isinstance(focus_state, Mapping):
            for name in (
                "failure_message",
                "failure_cause_type",
                "failure_cause_message",
                "retryable",
                "retry_after",
            ):
                projected[name] = focus_state.get(name)
        return projected

    safe_dag_runtime_payload.__dict__.update(getattr(current, "__dict__", {}))
    safe_dag_runtime_payload._bounded_failure_cause_projection = True  # type: ignore[attr-defined]
    _release._safe_dag_runtime_payload = safe_dag_runtime_payload


def install_certification_failure_projection() -> None:
    """Install bounded causal observability without changing certification behavior."""

    _install_runtime_journal_projection()
    _install_release_projection()


__all__ = ["install_certification_failure_projection"]
