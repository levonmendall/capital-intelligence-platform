"""Expose genuine provider progress between public qualification and the certification DAG.

Release prequalification has durable journals for reference acquisition, required public-live
qualification, and the certification DAG. Broad discovery also performs provider work in
the evidence-owner process *between* the public-live gate and the first DAG journal. This
module gives that otherwise invisible interval a credential-safe progress journal.

Progress is work-unit native: only a newly completed provider request signature can advance
the journal. Repeated retries of the same request therefore cannot act as a synthetic
heartbeat and keep release certification alive indefinitely. Request material is never
persisted; only an in-memory SHA-256 fingerprint is used for deduplication. A silent, stuck,
or endlessly replayed provider operation remains subject to the unchanged parent stall
budget.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


_SCHEMA_VERSION = "evidence-preparation-progress.v1"
_STAGE = "post-public-provider-io"
_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")
_LOCK = threading.Lock()
_STRUCTURAL_PREWARM_LOCK = threading.Lock()
_STRUCTURAL_PREWARM_STARTED = False


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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path(values: Mapping[str, str]) -> Path | None:
    data_dir = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    release_sha = _release(values)
    if not data_dir or not release_sha or release_sha == "unknown":
        return None
    return (
        Path(data_dir).expanduser()
        / "release_prequalification_progress"
        / _safe_release(release_sha)
        / "evidence-preparation-latest.json"
    )


def _safe_metrics(value: Mapping[str, int] | None) -> dict[str, int]:
    if value is None:
        return {}
    return {
        str(name): int(item)
        for name, item in value.items()
        if isinstance(name, str)
        and name.strip()
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _request_fingerprint(args: tuple[object, ...], kwargs: Mapping[str, object]) -> str:
    """Return an in-memory-only identity for one provider request work unit.

    The fingerprint deliberately includes request targeting/payload material so legitimate
    pagination or instrument-specific calls remain distinct. The material itself is never
    written to disk or telemetry; only the digest lives in the disposable evidence-owner
    process.
    """

    method = str(args[0] if args else kwargs.get("method") or "").strip().upper()
    url = str(args[1] if len(args) > 1 else kwargs.get("url") or "").strip()
    material = {
        "method": method,
        "url": url,
        "params": repr(kwargs.get("params")),
        "data": repr(kwargs.get("data")),
        "json": repr(kwargs.get("json")),
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


def record_evidence_preparation_progress(
    values: Mapping[str, str],
    *,
    completed_provider_calls: int,
) -> Mapping[str, object] | None:
    """Persist the count of distinct completed post-public provider work units."""

    if (
        isinstance(completed_provider_calls, bool)
        or not isinstance(completed_provider_calls, int)
        or completed_provider_calls < 1
    ):
        raise ValueError("completed_provider_calls must be a positive integer")
    path = _path(values)
    if path is None:
        return None
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "release_sha": _release(values),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stage": _STAGE,
        "progress_semantics": "distinct-provider-request-work-units",
        "metrics": {"provider_calls_completed": completed_provider_calls},
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    material = dict(payload)
    material["integrity_sha256"] = _digest(payload)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        temporary.write_text(
            json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    return payload


def load_evidence_preparation_progress(
    values: Mapping[str, str],
) -> Mapping[str, object] | None:
    """Load only exact-release, integrity-valid, non-authoritative progress."""

    path = _path(values)
    if path is None or not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        return None
    if payload.get("schema_version") != _SCHEMA_VERSION:
        return None
    if str(payload.get("release_sha") or "").strip() != _release(values):
        return None
    semantics = str(payload.get("progress_semantics") or "").strip()
    if semantics and semantics != "distinct-provider-request-work-units":
        return None
    if payload.get("credential_safe") is not True:
        return None
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        return None
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if payload.get(authority) is not False:
            return None
    if str(payload.get("stage") or "") != _STAGE:
        return None
    try:
        updated_at = datetime.fromisoformat(
            str(payload.get("updated_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if updated_at.tzinfo is None or updated_at.utcoffset() is None:
        return None
    metrics = _safe_metrics(
        payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else None
    )
    if "provider_calls_completed" not in metrics:
        return None
    return {
        **payload,
        "updated_at": updated_at.astimezone(timezone.utc).isoformat(),
        "metrics": metrics,
    }


def _start_us_equity_structural_prewarm(values: Mapping[str, str]) -> None:
    """Start structural-only comprehensive work iff this is the active Render equity stage."""

    global _STRUCTURAL_PREWARM_STARTED
    if str(values.get("RENDER") or "").strip().lower() != "true":
        return
    with _STRUCTURAL_PREWARM_LOCK:
        if _STRUCTURAL_PREWARM_STARTED:
            return
        try:
            from operations.stage_isolated_evidence_pipeline import (
                load_stage_isolated_evidence_state,
            )

            state = load_stage_isolated_evidence_state(values)
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        if state is None or state.state != "running" or state.current_stage != "us_equity_discovery":
            return
        try:
            from operations.comprehensive_discovery_structural_prewarm import (
                start_render_structural_prewarm,
            )

            handle = start_render_structural_prewarm(
                evidence_as_of=state.evidence_as_of,
                values=values,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        if handle.process is None:
            return
        # The stage process does not exit until atexit handlers finish.  Reap the sidecar
        # before the coordinator can launch comprehensive discovery, preserving the existing
        # exclusive heavy/publication lane.  Any failure remains advisory and non-authoritative.
        atexit.register(handle.stop)
        _STRUCTURAL_PREWARM_STARTED = True


def install_post_public_provider_progress(values: Mapping[str, str] | None = None) -> None:
    """Observe distinct completed requests only after required public-live qualification.

    The hook is installed only in the disposable evidence-owner process. Spawned DAG lane
    workers start fresh interpreters and retain their existing lane-native progress path.
    Replaying the same request cannot advance the journal a second time.
    """

    # The exact epoch provider child already calls this observer before provider acquisition.
    # Install the child-local durable exchange checkpoint at that same narrow handoff.  The
    # bootstrap self-checks sys.orig_argv, so normal evidence-owner calls remain observational.
    from provider_preselection_checkpoint_bootstrap import install_for_epoch_provider_child

    install_for_epoch_provider_child()

    import requests

    from operations.public_live_requirement_qualification import (
        load_public_live_requirement_progress,
    )

    resolved = dict(os.environ if values is None else values)
    current = requests.sessions.Session.request
    if getattr(current, "_post_public_provider_progress", False):
        return
    completed = [0]
    seen_work_units: set[str] = set()
    count_lock = threading.Lock()

    def request_with_progress(session, *args, **kwargs):
        fingerprint = _request_fingerprint(tuple(args), kwargs)
        try:
            return current(session, *args, **kwargs)
        finally:
            # Observability must never alter the provider call's own result or exception.
            try:
                public = load_public_live_requirement_progress(resolved)
                state = (
                    str(public.get("state") or "").strip().lower()
                    if isinstance(public, Mapping)
                    else ""
                )
                pending = (
                    int(public.get("pending_count") or 0)
                    if isinstance(public, Mapping)
                    else 0
                )
                failed = (
                    int(public.get("failed_count") or 0)
                    if isinstance(public, Mapping)
                    else 0
                )
                if state == "qualified" and not pending and not failed:
                    should_record = False
                    observed = 0
                    with count_lock:
                        if fingerprint not in seen_work_units:
                            seen_work_units.add(fingerprint)
                            completed[0] += 1
                            observed = completed[0]
                            should_record = True
                    if should_record:
                        record_evidence_preparation_progress(
                            resolved,
                            completed_provider_calls=observed,
                        )
            except Exception:
                # The journal is supervision-only. If it cannot advance, the unchanged
                # parent watchdog remains fail-closed and will stop a genuinely silent run.
                pass

    request_with_progress._post_public_provider_progress = True  # type: ignore[attr-defined]
    requests.sessions.Session.request = request_with_progress
    # Structural prewarm has one explicit owner in the U.S.-equity stage runner. Progress
    # instrumentation must remain observational and must not start a second sidecar.


__all__ = [
    "install_post_public_provider_progress",
    "load_evidence_preparation_progress",
    "record_evidence_preparation_progress",
]
