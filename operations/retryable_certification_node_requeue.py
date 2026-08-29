"""Honor bounded retry hints inside the persistent certification DAG.

The scheduler already persists exact-release/epoch node success and failure state. This
runtime wrapper uses only that durable manifest to retry failures that are explicitly
marked retryable, waiting outside provider leases and never past the node's existing
deadline. Malformed, non-retryable, or deadline-exhausted failures remain terminal and
fail closed.

No evidence freshness, provider capacity, worker count, memory boundary, market scope,
canonical publication, investment authority, or paper-only control is changed.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from operations import persistent_certification_scheduler as _scheduler


def _exact_retry_not_before(
    instance: object,
    nodes: Sequence[object],
) -> datetime | None:
    """Return the durable retry boundary only when every failed node is retryable."""

    values = getattr(instance, "values", None)
    release_sha = str(getattr(instance, "release_sha", "") or "").strip()
    epoch = getattr(instance, "epoch", None)
    policy_version = str(getattr(instance, "policy_version", "") or "")
    if not isinstance(values, Mapping) or not release_sha or epoch is None:
        return None

    try:
        path = (
            _scheduler._root(values)
            / _scheduler._SCHEMA_VERSION
            / release_sha
            / _scheduler._epoch_key(epoch)
            / "latest.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None

    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _scheduler._digest(body):
        return None
    expected = {
        "schema_version": _scheduler._MANIFEST_SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": _scheduler._aware(
            epoch,
            field_name="scheduler_epoch",
        ).isoformat(),
        "policy_version": policy_version,
    }
    if any(body.get(key) != value for key, value in expected.items()):
        return None

    failed_nodes = body.get("failed_nodes")
    node_results = body.get("node_results")
    if not isinstance(failed_nodes, list) or not failed_nodes or not isinstance(node_results, Mapping):
        return None

    node_by_id = {
        str(getattr(node, "node_id", "") or "").strip(): node
        for node in nodes
        if str(getattr(node, "node_id", "") or "").strip()
    }
    retry_times: list[datetime] = []
    deadlines: list[datetime] = []
    for raw_node_id in failed_nodes:
        node_id = str(raw_node_id or "").strip()
        node = node_by_id.get(node_id)
        result = node_results.get(node_id)
        if node is None or not isinstance(result, Mapping):
            return None
        if result.get("status") != "failed" or result.get("retryable") is not True:
            return None
        raw_retry_after = str(result.get("retry_after") or "").strip()
        if not raw_retry_after:
            return None
        try:
            retry_after = _scheduler._aware(
                datetime.fromisoformat(raw_retry_after.replace("Z", "+00:00")),
                field_name="retry_after",
            )
            deadline = _scheduler._aware(
                getattr(node, "deadline"),
                field_name="node_deadline",
            )
        except (TypeError, ValueError):
            return None
        if retry_after >= deadline:
            return None
        retry_times.append(retry_after)
        deadlines.append(deadline)

    retry_not_before = max(retry_times)
    earliest_deadline = min(deadlines)
    now = datetime.now(timezone.utc)
    if now >= earliest_deadline or retry_not_before >= earliest_deadline:
        return None
    return retry_not_before


def install_retryable_certification_node_requeue() -> None:
    """Retry explicit transient failures within the existing exact-epoch deadline."""

    current = _scheduler.PersistentCertificationScheduler.run
    if getattr(current, "_retryable_certification_node_requeue", False):
        return

    def run(self: Any, nodes: Sequence[object], runner: Any):
        ordered_nodes = tuple(nodes)
        while True:
            try:
                return current(self, ordered_nodes, runner)
            except _scheduler.CertificationSchedulerError:
                retry_not_before = _exact_retry_not_before(self, ordered_nodes)
                if retry_not_before is None:
                    raise
                delay = (retry_not_before - datetime.now(timezone.utc)).total_seconds()
                if delay > 0.0:
                    time.sleep(delay)

    run._retryable_certification_node_requeue = True  # type: ignore[attr-defined]
    _scheduler.PersistentCertificationScheduler.run = run


__all__ = ["install_retryable_certification_node_requeue"]
