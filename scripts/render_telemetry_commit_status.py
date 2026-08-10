"""Format credential-safe Render telemetry as a compact GitHub commit status.

This module never receives a GitHub or Render credential. It accepts only the already-allowlisted
telemetry snapshot and emits a tiny status state/description suitable for a GitHub commit status.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

_ALLOWED_CAPTURE_STATES = frozenset({"ok", "unavailable", "unsafe_payload"})
_FAILURE_STATES = frozenset(
    {"failed", "error", "timed_out", "timeout", "cancelled", "canceled", "terminated"}
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MAX_DESCRIPTION_LENGTH = 140


class InvalidTelemetrySnapshot(RuntimeError):
    """Raised when the supplied snapshot is not the credential-safe telemetry contract."""


def _safe_token(value: object, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_TOKEN.fullmatch(candidate) else fallback


def _elapsed_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unknown"
    return f"{max(0, int(round(float(value))))}s"


def status_for_snapshot(snapshot: Mapping[str, Any]) -> tuple[str, str]:
    """Return GitHub status state and a strictly allowlisted live description."""

    if snapshot.get("credential_safe") is not True:
        raise InvalidTelemetrySnapshot("snapshot is not marked credential-safe")
    if snapshot.get("paper_only") is not True:
        raise InvalidTelemetrySnapshot("snapshot is not marked paper-only")
    if snapshot.get("real_money_authorized") is not False:
        raise InvalidTelemetrySnapshot("snapshot does not deny real-money authority")

    capture_state = str(snapshot.get("capture_state") or "")
    if capture_state not in _ALLOWED_CAPTURE_STATES:
        raise InvalidTelemetrySnapshot("snapshot has an unknown capture state")

    diagnostic = snapshot.get("diagnostic")
    if capture_state == "ok" and not isinstance(diagnostic, Mapping):
        raise InvalidTelemetrySnapshot("ok snapshot is missing diagnostic telemetry")

    if not isinstance(diagnostic, Mapping):
        status_state = "error" if capture_state == "unsafe_payload" else "pending"
        description = f"telemetry={capture_state} stage=unavailable state=unknown elapsed=unknown"
        return status_state, description[:_MAX_DESCRIPTION_LENGTH]

    state = _safe_token(diagnostic.get("state"), fallback="unknown")
    stage = _safe_token(diagnostic.get("stage"), fallback="awaiting_progress")
    elapsed = _elapsed_text(diagnostic.get("elapsed_seconds"))
    release_match = diagnostic.get("release_matches_expected")
    release_text = "yes" if release_match is True else "no" if release_match is False else "unknown"

    complete = bool(
        capture_state == "ok"
        and release_match is True
        and state == "completed"
        and diagnostic.get("all_market_evaluation_complete") is True
    )
    if complete:
        status_state = "success"
    elif capture_state == "unsafe_payload" or state in _FAILURE_STATES:
        status_state = "error"
    else:
        status_state = "pending"

    description = (
        f"stage={stage} state={state} elapsed={elapsed} release_match={release_text}"
    )
    return status_state, description[:_MAX_DESCRIPTION_LENGTH]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 2
    if not isinstance(payload, Mapping):
        return 2
    try:
        state, description = status_for_snapshot(payload)
    except InvalidTelemetrySnapshot:
        return 2
    print(state)
    print(description)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
