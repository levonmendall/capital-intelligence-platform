"""Exact-release durable production-state snapshots for read-only presentation.

The manual CIO diagnostic request is a single mutable coordination file. That global file is
useful for single-flight ownership, but it is not a safe canonical presentation pointer:
a later diagnostic can overwrite it even though an earlier exact-release diagnostic remains
the production truth for the release currently serving the UI.

This module keeps a release-scoped copy of the diagnostic state. It adds no decision,
construction, execution, or real-money authority. Invalid, missing, or mismatched state is
ignored so readers remain fail-closed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from operations.manual_cio_diagnostic import (
    ManualCIODiagnosticRequest,
    diagnostic_request_path,
)

_SAFE_RELEASE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_RELEASE_STATE_DIRECTORY = "manual-cio-diagnostic-by-release"


def _normalized_release(release: object) -> str | None:
    value = str(release or "").strip()
    if not value or value == "unknown" or not _SAFE_RELEASE.fullmatch(value):
        return None
    return value


def release_production_state_path(
    release: object,
    *,
    values: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the deterministic exact-release state path, or None for an invalid release."""

    normalized = _normalized_release(release)
    if normalized is None:
        return None
    return (
        diagnostic_request_path(values).parent
        / _RELEASE_STATE_DIRECTORY
        / normalized
        / "latest.json"
    )


def publish_release_production_state(
    release: object,
    request: ManualCIODiagnosticRequest,
    *,
    values: Mapping[str, str] | None = None,
) -> Path:
    """Atomically publish diagnostic truth only when it belongs to the exact release."""

    normalized = _normalized_release(release)
    if normalized is None:
        raise ValueError("release production state requires a valid release identifier")
    expected_requester = f"render-release:{normalized}"
    if request.requested_by != expected_requester:
        raise ValueError("release production state requester does not match release")

    path = release_production_state_path(normalized, values=values)
    if path is None:  # pragma: no cover - normalized above makes this unreachable.
        raise ValueError("release production state path is unavailable")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_release_production_state(
    release: object,
    *,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest | None:
    """Load only a valid diagnostic bound to the requested exact release."""

    normalized = _normalized_release(release)
    if normalized is None:
        return None
    path = release_production_state_path(normalized, values=values)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    try:
        request = ManualCIODiagnosticRequest.from_dict(payload)
    except (TypeError, ValueError):
        return None
    if request.requested_by != f"render-release:{normalized}":
        return None
    return request


__all__ = [
    "load_release_production_state",
    "publish_release_production_state",
    "release_production_state_path",
]
