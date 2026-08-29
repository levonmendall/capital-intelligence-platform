"""Durable terminal transport for spawn-safe certification lane subprocesses.

A provider-facing lane is already isolated in a finite interpreter. This module closes the
remaining observability gap by persisting a bounded credential-safe terminal failure record
inside that child and making the parent raise from that exact child failure instead of
flattening every nonzero exit into ``return_code=2``.

This is transport and supervision only. It does not change evidence freshness, provider
budgets, market scope, screening, CIO authority, construction, execution, or paper-only
governance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from operations import comprehensive_discovery_input_spool as _spool
from operations import persistent_certification_scheduler as _scheduler
from operations import spawn_safe_authoritative_acquisition as _spawn_safe
from operations import supervised_component_execution as _supervision

_MODULE = "operations.spawn_safe_lane_terminal_transport"
_FAILURE_SCHEMA = "spawn-safe-certification-lane-failure.v1"
_SAFE_FAILURE_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")


def _failure_path(manifest_path: str | Path, node_id: str) -> Path:
    directory = Path(manifest_path).expanduser().parent
    return directory / f"lane-failure-{_spool._safe_release(node_id)}.json"


def _retry_after_seconds(error: BaseException) -> float | None:
    raw = getattr(error, "retry_after_seconds", None)
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(value) or value <= 0.0:
        return None
    return min(value, 3600.0)


def _safe_detail(error: BaseException | None) -> str | None:
    if error is None:
        return None
    detail = _supervision._safe_error(error)
    text = " ".join(str(detail).split())
    if not text:
        return None
    return text[:1600]


def _write_failure(
    manifest_path: str | Path,
    *,
    node_id: str,
    input_fingerprint: str,
    error: BaseException,
) -> Path:
    cause = error.__cause__
    if cause is None and not error.__suppress_context__:
        cause = error.__context__
    body: dict[str, object] = {
        "schema_version": _FAILURE_SCHEMA,
        "node_id": node_id,
        "input_fingerprint": input_fingerprint,
        "failure_type": type(error).__name__,
        "failure_message": _safe_detail(error),
        "failure_cause_type": type(cause).__name__ if cause is not None else None,
        "failure_cause_message": _safe_detail(cause),
        "retry_after_seconds": _retry_after_seconds(error),
        **_spool._authority_fields(),
    }
    path = _failure_path(manifest_path, node_id)
    _spool._atomic_json(path, body)
    return path


def _load_failure(
    manifest_path: str | Path,
    *,
    node: _scheduler.CertificationNode,
) -> dict[str, object]:
    body = _spool._load_json(_failure_path(manifest_path, node.node_id), schema=_FAILURE_SCHEMA)
    if str(body.get("node_id") or "") != node.node_id:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure node identity changed for {node.node_id}"
        )
    if str(body.get("input_fingerprint") or "") != node.input_fingerprint:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure fingerprint changed for {node.node_id}"
        )
    return body


def _remote_child_error(body: dict[str, object]) -> BaseException:
    type_name = str(body.get("failure_type") or "RemoteLaneExecutionError").strip()
    if _SAFE_FAILURE_TYPE.fullmatch(type_name) is None:
        type_name = "RemoteLaneExecutionError"
    error_type = type(type_name, (RuntimeError,), {})
    detail = str(body.get("failure_message") or "provider-facing certification lane failed")
    error = error_type(detail)
    retry = body.get("retry_after_seconds")
    try:
        retry_seconds = float(retry) if retry is not None else None
    except (TypeError, ValueError):
        retry_seconds = None
    if retry_seconds is not None and math.isfinite(retry_seconds) and retry_seconds > 0.0:
        setattr(error, "retry_after_seconds", min(retry_seconds, 3600.0))
    return error


def _call_with_terminal_truth(
    self: _spawn_safe.SpawnSafeSingleLaneRunner,
    node: _scheduler.CertificationNode,
) -> int:
    if node.node_id != self.node_id:
        raise _scheduler.CertificationSchedulerError(
            "spool-backed lane runner node identity changed across process boundary"
        )

    result_path = _spawn_safe._lane_result_path(self.manifest_path, node.node_id)
    failure_path = _failure_path(self.manifest_path, node.node_id)
    for path in (result_path, failure_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    repository_root = Path(__file__).resolve().parents[1]
    command = (
        sys.executable,
        "-m",
        _MODULE,
        "run-lane",
        "--manifest",
        self.manifest_path,
        "--node-id",
        node.node_id,
        "--input-fingerprint",
        node.input_fingerprint,
        "--timestamp",
        self.timestamp.isoformat(),
        "--policy-version",
        self.policy_version,
    )
    environment = dict(os.environ)
    environment.update(dict(self.environment))
    process = subprocess.Popen(
        command,
        cwd=str(repository_root),
        env=environment,
        start_new_session=False,
    )
    return_code = int(process.wait())
    if return_code != 0:
        try:
            body = _load_failure(self.manifest_path, node=node)
        except Exception as transport_error:
            raise _scheduler.CertificationSchedulerError(
                f"provider-facing certification lane subprocess failed without durable terminal truth "
                f"for {node.node_id}; return_code={return_code}; "
                f"pid={getattr(process, 'pid', 'unknown')}; "
                f"transport_error={type(transport_error).__name__}:{transport_error}"
            ) from transport_error
        child_error = _remote_child_error(body)
        cause_type = str(body.get("failure_cause_type") or "none")
        cause_message = str(body.get("failure_cause_message") or "none")
        raise _scheduler.CertificationSchedulerError(
            f"provider-facing certification lane failed for {node.node_id}; "
            f"child_failure_type={type(child_error).__name__}; "
            f"child_failure_message={child_error}; "
            f"child_cause_type={cause_type}; child_cause_message={cause_message}; "
            f"return_code={return_code}; pid={getattr(process, 'pid', 'unknown')}"
        ) from child_error
    return _spawn_safe._load_lane_result(self.manifest_path, node=node)


def install_spawn_safe_lane_terminal_transport() -> None:
    current = _spawn_safe.SpawnSafeSingleLaneRunner.__call__
    if getattr(current, "_durable_lane_terminal_truth", False):
        return
    _call_with_terminal_truth._durable_lane_terminal_truth = True  # type: ignore[attr-defined]
    _spawn_safe.SpawnSafeSingleLaneRunner.__call__ = _call_with_terminal_truth


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run-lane",))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--input-fingerprint", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--policy-version", required=True)
    args = parser.parse_args(argv)
    try:
        timestamp = _spawn_safe.datetime.fromisoformat(str(args.timestamp).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("lane timestamp must be timezone-aware")
        count = _spawn_safe._run_lane_cli(
            manifest_path=args.manifest,
            node_id=args.node_id,
            timestamp=timestamp,
            policy_version=args.policy_version,
        )
    except BaseException as error:  # noqa: BLE001 - finite child must fail closed.
        try:
            _write_failure(
                args.manifest,
                node_id=args.node_id,
                input_fingerprint=args.input_fingerprint,
                error=error,
            )
        except BaseException as persistence_error:  # noqa: BLE001
            print(
                json.dumps(
                    {
                        "event": "spawn_safe_certification_lane_failure_persistence_failed",
                        "node_id": args.node_id,
                        "error_type": type(error).__name__,
                        "persistence_error_type": type(persistence_error).__name__,
                        "credential_safe": True,
                        "paper_only": True,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(
            json.dumps(
                {
                    "event": "spawn_safe_certification_lane_failed",
                    "node_id": args.node_id,
                    "error_type": type(error).__name__,
                    "terminal_truth_persisted": True,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "spawn_safe_certification_lane_complete",
                "node_id": args.node_id,
                "evidence_complete_count": count,
                "credential_safe": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["install_spawn_safe_lane_terminal_transport"]
