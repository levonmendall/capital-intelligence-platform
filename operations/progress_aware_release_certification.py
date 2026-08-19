"""Harden release certification around durable per-node progress.

Comprehensive-discovery DAG nodes can legitimately perform many independently bounded
provider operations. Treating the whole node as one fixed wall-clock call recreates the
aggregate timeout that DAG-native supervision was intended to remove. This module keeps
that node boundary fail-closed while changing its execution budget into a *stall* budget:
a node may continue past the ordinary timeout only while credential-safe child progress
continues, and every node still has the existing one-hour absolute hard cap.

Release prequalification can also resume a still-valid decision epoch. A current attempt
therefore owns a DAG journal when that journal was freshly updated after the attempt
started; the decision epoch itself does not need to be newer than the attempt. The
resume-aware projection below preserves that distinction and merges a validated per-node
progress sidecar without granting the sidecar any decision authority.

Nothing in this module changes market membership, evidence completeness/freshness,
screening, specialist or CIO authority, construction, execution, or paper-only controls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations import release_evidence_prequalification as _release_state


_NODE_PROGRESS_SCHEMA = "persistent-certification-node-progress.v1"
_SAFE_STAGE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_DURABLE_PROGRESS_INTERVAL_SECONDS = 2.0
_NODE_LAST_PROGRESS: dict[int, float] = {}


def _aware(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
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


def _safe_stage(value: object) -> str:
    candidate = str(value or "progress").strip()[:160]
    if _SAFE_STAGE.fullmatch(candidate):
        return candidate
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", candidate).strip("-")
    return normalized[:160] or "progress"


def _safe_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    metrics: dict[str, int] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name or "").strip()[:120]
        if not name or isinstance(raw_value, bool) or not isinstance(raw_value, int):
            continue
        if raw_value < 0:
            continue
        metrics[name] = raw_value
    return metrics


def _node_progress_path(
    values: Mapping[str, str],
    *,
    release_sha: str,
    epoch: datetime,
    node_id: str,
) -> Path:
    from operations import persistent_certification_scheduler as scheduler

    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
    return (
        scheduler._root(values)
        / scheduler._SCHEMA_VERSION
        / release_sha
        / scheduler._epoch_key(epoch)
        / "node-progress"
        / f"{digest}.json"
    )


def _publish_node_progress(
    values: Mapping[str, str],
    *,
    release_sha: str,
    epoch: datetime,
    node: object,
    stage: str,
    metrics: Mapping[str, int],
) -> None:
    from operations import persistent_certification_scheduler as scheduler

    node_id = str(getattr(node, "node_id", "certification-node")).strip()
    asset_class = str(getattr(node, "asset_class", "other")).strip() or "other"
    body: dict[str, object] = {
        "schema_version": _NODE_PROGRESS_SCHEMA,
        "release_sha": release_sha,
        "decision_epoch": epoch.isoformat(),
        "node_id": node_id,
        "asset_class": asset_class,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stage": _safe_stage(stage),
        "metrics": dict(metrics),
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    scheduler._atomic_json(
        _node_progress_path(
            values,
            release_sha=release_sha,
            epoch=epoch,
            node_id=node_id,
        ),
        body,
    )


def _install_child_progress_emitters(connection, runner: object, node: object) -> None:
    """Mirror safe child progress to the parent pipe and a durable sidecar."""

    from operations import manual_cio_diagnostic as diagnostic
    from operations import persistent_certification_scheduler as scheduler

    values = os.environ
    release_sha = scheduler._release(values)
    epoch = _aware(getattr(runner, "timestamp", None))
    lock = threading.Lock()
    durable_clock = [0.0]
    request_count = [0]

    def emit(stage: object, metrics: object = None) -> None:
        safe_stage = _safe_stage(stage)
        safe_metrics = _safe_metrics(metrics)
        with lock:
            try:
                connection.send(("progress", safe_stage, safe_metrics))
            except (BrokenPipeError, EOFError, OSError):
                pass

            now = time.monotonic()
            if (
                epoch is None
                or not release_sha
                or release_sha == "unknown"
                or now - durable_clock[0] < _DURABLE_PROGRESS_INTERVAL_SECONDS
            ):
                return
            try:
                _publish_node_progress(
                    values,
                    release_sha=release_sha,
                    epoch=epoch,
                    node=node,
                    stage=safe_stage,
                    metrics=safe_metrics,
                )
            except (OSError, TypeError, ValueError):
                # Durable progress is observability only. If it cannot be written, the
                # unchanged parent stall boundary will eventually fail the run closed.
                return
            durable_clock[0] = now

    original_record = diagnostic.record_manual_cio_diagnostic_progress

    def record_progress(stage, *args, **kwargs):
        result = original_record(stage, *args, **kwargs)
        emit(stage, kwargs.get("metrics"))
        return result

    diagnostic.record_manual_cio_diagnostic_progress = record_progress

    # Most provider adapters ultimately use requests. A completed request is meaningful
    # I/O progress, but no URL, payload, header, symbol, or credential is persisted.
    try:
        import requests
    except ImportError:
        return

    original_request = requests.sessions.Session.request

    def request_with_progress(session, *args, **kwargs):
        try:
            return original_request(session, *args, **kwargs)
        finally:
            request_count[0] += 1
            emit(
                "provider_io_progress",
                {"provider_calls_completed": request_count[0]},
            )

    requests.sessions.Session.request = request_with_progress


def _progress_node_worker(connection, runner, node) -> None:
    """Run one DAG node while reporting only bounded credential-safe progress."""

    from operations import dag_native_comprehensive_supervision as dag

    process_group_ready = False
    try:
        if os.name == "posix":
            os.setsid()
            process_group_ready = True
        connection.send(("ready", process_group_ready))
        _install_child_progress_emitters(connection, runner, node)
        try:
            result = int(runner(node))
        except BaseException as error:  # noqa: BLE001 - child transports safe failure.
            retry_after = getattr(error, "retry_after_seconds", None)
            try:
                retry_seconds = float(retry_after) if retry_after is not None else None
            except (TypeError, ValueError):
                retry_seconds = None
            if retry_seconds is not None and retry_seconds <= 0.0:
                retry_seconds = None
            connection.send(
                (
                    "error",
                    type(error).__name__,
                    dag._supervision._safe_error(error),
                    retry_seconds,
                )
            )
            return
        connection.send(("ok", result))
    except BaseException:
        # Missing terminal transport remains a fail-closed worker failure in the parent.
        return
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _progress_aware_poll(item, *, timeout_seconds: float):
    """Treat the configured node timeout as a no-progress budget, not total runtime."""

    from operations import dag_native_comprehensive_supervision as dag

    now = time.monotonic()
    key = id(item)
    if item.ready_at is None:
        if item.connection.poll(0.0):
            try:
                message = item.connection.recv()
            except (EOFError, OSError):
                return dag._supervision.SupervisedComponentExecutionError(
                    f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                    "before becoming ready"
                )
            if not isinstance(message, tuple) or len(message) != 2 or message[0] != "ready":
                return dag._supervision.SupervisedComponentExecutionError(
                    f"{getattr(item.node, 'node_id', 'certification-node')} returned an "
                    "invalid readiness message"
                )
            item.process_group_ready = bool(message[1])
            item.ready_at = time.monotonic()
            _NODE_LAST_PROGRESS[key] = item.ready_at
            return None
        if now - item.launched_at >= dag._supervision._STARTUP_TIMEOUT_SECONDS:
            dag._supervision._stop_process(item.process, process_group_ready=False)
            _NODE_LAST_PROGRESS.pop(key, None)
            return dag._supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker did not "
                "establish its isolation boundary"
            )
        if not item.process.is_alive():
            _NODE_LAST_PROGRESS.pop(key, None)
            return dag._supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                "before becoming ready"
            )
        return None

    while item.connection.poll(0.0):
        try:
            message = item.connection.recv()
        except (EOFError, OSError):
            _NODE_LAST_PROGRESS.pop(key, None)
            return dag._supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                "without a terminal result"
            )
        if isinstance(message, tuple) and len(message) == 3 and message[0] == "progress":
            _NODE_LAST_PROGRESS[key] = time.monotonic()
            continue
        _NODE_LAST_PROGRESS.pop(key, None)
        return dag._terminal_result(item, message)

    assert item.ready_at is not None
    hard_limit_seconds = dag._MAX_NODE_TIMEOUT_SECONDS
    if now - item.ready_at >= hard_limit_seconds:
        dag._supervision._stop_process(
            item.process,
            process_group_ready=item.process_group_ready,
        )
        _NODE_LAST_PROGRESS.pop(key, None)
        return dag._supervision.SupervisedComponentTimeout(
            f"{getattr(item.node, 'node_id', 'certification-node')} exceeded its "
            f"{hard_limit_seconds:g}s absolute execution cap"
        )

    last_progress = _NODE_LAST_PROGRESS.get(key, item.ready_at)
    if now - last_progress >= timeout_seconds:
        dag._supervision._stop_process(
            item.process,
            process_group_ready=item.process_group_ready,
        )
        _NODE_LAST_PROGRESS.pop(key, None)
        return dag._supervision.SupervisedComponentTimeout(
            f"{getattr(item.node, 'node_id', 'certification-node')} made no child progress "
            f"for {timeout_seconds:g}s"
        )
    if not item.process.is_alive():
        _NODE_LAST_PROGRESS.pop(key, None)
        return dag._supervision.SupervisedComponentExecutionError(
            f"{getattr(item.node, 'node_id', 'certification-node')} worker exited without "
            "a terminal result"
        )
    return None


def _safe_node_progress(
    raw: object,
    *,
    release_sha: str,
    decision_epoch: datetime,
) -> dict[str, object] | None:
    if not isinstance(raw, Mapping) or raw.get("schema_version") != _NODE_PROGRESS_SCHEMA:
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
    if str(raw.get("release_sha") or "").strip() != release_sha:
        return None
    observed_epoch = _aware(raw.get("decision_epoch"))
    updated_at = _aware(raw.get("updated_at"))
    if observed_epoch != decision_epoch or updated_at is None:
        return None
    node_id = _release_state._safe_token(raw.get("node_id"))
    asset_class = _release_state._safe_token(raw.get("asset_class"))
    stage = _safe_stage(raw.get("stage"))
    if node_id is None:
        return None
    return {
        "schema_version": _NODE_PROGRESS_SCHEMA,
        "release_sha": release_sha,
        "decision_epoch": decision_epoch.isoformat(),
        "node_id": node_id,
        "asset_class": asset_class,
        "updated_at": updated_at.isoformat(),
        "stage": stage,
        "metrics": _safe_metrics(raw.get("metrics")),
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _overlay_node_progress(
    progress: Mapping[str, object],
    *,
    values: Mapping[str, str],
) -> Mapping[str, object]:
    from operations import persistent_certification_scheduler as scheduler

    release_sha = str(progress.get("release_sha") or "").strip()
    epoch = _aware(progress.get("decision_epoch"))
    base_updated = _aware(progress.get("updated_at"))
    node_states = progress.get("node_states")
    if (
        not release_sha
        or epoch is None
        or base_updated is None
        or not isinstance(node_states, Mapping)
        or progress.get("blocking_node")
    ):
        return progress

    root = (
        _release_state._dag_runtime_root(values)
        / scheduler._epoch_key(epoch)
        / "node-progress"
    )
    try:
        candidates = tuple(root.glob("*.json"))
    except OSError:
        return progress

    newest: tuple[datetime, dict[str, object]] | None = None
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        safe = _safe_node_progress(
            raw,
            release_sha=release_sha,
            decision_epoch=epoch,
        )
        if safe is None:
            continue
        node_id = str(safe["node_id"])
        node_state = node_states.get(node_id)
        if not isinstance(node_state, Mapping):
            continue
        if str(node_state.get("state") or "").strip().lower() != "running":
            continue
        updated_at = _aware(safe.get("updated_at"))
        if updated_at is None or updated_at <= base_updated:
            continue
        if newest is None or updated_at > newest[0]:
            newest = (updated_at, safe)

    if newest is None:
        return progress

    safe = newest[1]
    node_id = str(safe["node_id"])
    node_state = node_states[node_id]
    projected = dict(progress)
    projected.update(
        {
            "updated_at": safe["updated_at"],
            "active_node": node_id,
            "focus_node": node_id,
            "asset_class": (
                safe.get("asset_class")
                or (node_state.get("asset_class") if isinstance(node_state, Mapping) else None)
            ),
            "provider_groups": (
                list(node_state.get("provider_groups") or [])
                if isinstance(node_state, Mapping)
                else []
            ),
            "failure_type": None,
            "node_progress": safe,
        }
    )
    return projected


def install_resume_aware_release_dag_projection() -> None:
    """Accept a resumed epoch only when its current-release journal is freshly updated."""

    current = _release_state.load_release_certification_dag_progress
    if getattr(current, "_resume_aware_dag_projection", False):
        return

    def load(values: Mapping[str, str], *, started_at: datetime | None = None):
        # The canonical loader already validates release identity, paper-only state,
        # authority flags, node payloads, and journal integrity shape. Calling it without
        # an attempt boundary intentionally allows a resumable older decision epoch.
        progress = current(values, started_at=None)
        if progress is None:
            return None
        progress = _overlay_node_progress(progress, values=values)
        if started_at is not None:
            boundary = _aware(started_at)
            if boundary is None:
                raise ValueError(
                    "release prequalification started_at must be timezone-aware"
                )
            updated_at = _aware(progress.get("updated_at"))
            if updated_at is None or updated_at < boundary:
                return None
        return progress

    load._resume_aware_dag_projection = True  # type: ignore[attr-defined]
    _release_state.load_release_certification_dag_progress = load


def install_progress_aware_dag_node_supervision() -> None:
    """Install per-node stall supervision after the canonical DAG runtime is installed."""

    from operations import dag_native_comprehensive_supervision as dag

    if getattr(dag._poll_running, "_progress_aware_node_supervision", False):
        return

    original_close = dag._close_running

    def close_running(item) -> None:
        _NODE_LAST_PROGRESS.pop(id(item), None)
        original_close(item)

    _progress_aware_poll._progress_aware_node_supervision = True  # type: ignore[attr-defined]
    _progress_node_worker._progress_aware_node_supervision = True  # type: ignore[attr-defined]
    close_running._progress_aware_node_supervision = True  # type: ignore[attr-defined]
    dag._node_worker = _progress_node_worker
    dag._poll_running = _progress_aware_poll
    dag._close_running = close_running


__all__ = [
    "install_progress_aware_dag_node_supervision",
    "install_resume_aware_release_dag_projection",
]
