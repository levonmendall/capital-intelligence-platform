"""Expose genuine provider progress between public qualification and the certification DAG.

Release prequalification has durable journals for reference acquisition, required public-live
qualification, and the certification DAG.  Broad discovery also performs provider work in
the evidence-owner process *between* the public-live gate and the first DAG journal.  This
module gives that otherwise invisible interval a credential-safe progress journal.

Only completed HTTP requests can advance the journal.  There is no timer heartbeat and no
investment, candidate, sizing, construction, execution, or real-money authority.  A silent
or stuck provider operation therefore remains subject to the unchanged parent stall budget.
"""

from __future__ import annotations

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


def record_evidence_preparation_progress(
    values: Mapping[str, str],
    *,
    completed_provider_calls: int,
) -> Mapping[str, object] | None:
    """Persist one real post-public provider completion without recording request data."""

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


def install_post_public_provider_progress(values: Mapping[str, str] | None = None) -> None:
    """Observe completed requests only after required public-live evidence has qualified.

    The hook is installed only in the disposable evidence-owner process.  Spawned DAG lane
    workers start fresh interpreters and retain their existing lane-native progress path.
    """

    import requests

    from operations.public_live_requirement_qualification import (
        load_public_live_requirement_progress,
    )

    resolved = dict(os.environ if values is None else values)
    current = requests.sessions.Session.request
    if getattr(current, "_post_public_provider_progress", False):
        return
    completed = [0]
    count_lock = threading.Lock()

    def request_with_progress(session, *args, **kwargs):
        try:
            return current(session, *args, **kwargs)
        finally:
            # Observability must never alter the provider call's own result or exception.
            try:
                public = load_public_live_requirement_progress(resolved)
                state = str(public.get("state") or "").strip().lower() if isinstance(public, Mapping) else ""
                pending = int(public.get("pending_count") or 0) if isinstance(public, Mapping) else 0
                failed = int(public.get("failed_count") or 0) if isinstance(public, Mapping) else 0
                if state != "qualified" or pending or failed:
                    return
                with count_lock:
                    completed[0] += 1
                    observed = completed[0]
                record_evidence_preparation_progress(
                    resolved,
                    completed_provider_calls=observed,
                )
            except Exception:
                # The journal is supervision-only.  If it cannot advance, the unchanged
                # parent watchdog remains fail-closed and will stop a genuinely silent run.
                return

    request_with_progress._post_public_provider_progress = True  # type: ignore[attr-defined]
    requests.sessions.Session.request = request_with_progress


__all__ = [
    "install_post_public_provider_progress",
    "load_evidence_preparation_progress",
    "record_evidence_preparation_progress",
]
