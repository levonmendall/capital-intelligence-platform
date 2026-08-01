"""Resilient state lifecycle for governed production-context refreshes.

The canonical successful publication remains readable while a newer refresh is
attempted. Reuse is invalidated by changing only the cache key; the last successful
scan payload is never deleted before its replacement exists. A separate atomic
attempt record explains running, blocked, failed, ready, and reused refreshes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping

SUCCESS_STATE_FILENAME = "production-context-publication-state.json"
ATTEMPT_STATE_FILENAME = "production-context-publication-attempt-state.json"
ATTEMPT_SCHEMA = "production-context-publication-attempt-state.v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _state_root(settings: object) -> Path:
    portfolio_database = getattr(settings, "portfolio_database", None)
    if portfolio_database is None:
        raise TypeError("settings.portfolio_database is required")
    return Path(portfolio_database).expanduser().parent


def successful_state_path(settings: object) -> Path:
    return _state_root(settings) / SUCCESS_STATE_FILENAME


def attempt_state_path(settings: object) -> Path:
    return _state_root(settings) / ATTEMPT_STATE_FILENAME


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def invalidate_reuse_preserving_success(settings: object) -> None:
    """Prevent same-slot reuse without removing the last successful UI snapshot."""

    path = successful_state_path(settings)
    payload = _read_json(path)
    if payload is None:
        return

    current_cycle_key = str(payload.get("cycle_key") or "").strip()
    last_successful_cycle_key = str(
        payload.get("last_successful_cycle_key") or current_cycle_key
    ).strip()
    invalidated_at = _utc_now()
    preserved = dict(payload)
    preserved["last_successful_cycle_key"] = last_successful_cycle_key
    preserved["cycle_key"] = (
        f"refresh-required:{invalidated_at.strftime('%Y%m%dT%H%M%S%fZ')}:"
        f"{last_successful_cycle_key or 'unknown'}"
    )
    preserved["reuse_invalidated_at"] = invalidated_at.isoformat()
    preserved["last_successful_state_preserved"] = True
    _atomic_json(path, preserved)


def latest_attempt(settings: object) -> dict[str, Any] | None:
    return _read_json(attempt_state_path(settings))


def _attempt_payload(
    *,
    state: str,
    scheduled_for: object,
    started_at: datetime,
    completed_at: datetime | None,
    detail: str,
    result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    scheduled_text = (
        scheduled_for.isoformat()
        if isinstance(scheduled_for, datetime)
        else str(scheduled_for or "")
    )
    payload: dict[str, object] = {
        "schema_version": ATTEMPT_SCHEMA,
        "state": state,
        "scheduled_for": scheduled_text,
        "started_at": started_at.isoformat(),
        "completed_at": None if completed_at is None else completed_at.isoformat(),
        "detail": detail,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if result is not None:
        for key in (
            "cycle_key",
            "decision_as_of",
            "eligible_universe_identifier",
            "screening_publication_identifier",
            "context_identifier",
            "instrument_count",
            "candidate_count",
            "exclusion_count",
        ):
            if key in result:
                payload[key] = result[key]
    return payload


def recording_context_preparer(preparer: Callable[..., object]) -> Callable[..., object]:
    """Wrap a context preparer with an atomic, presentation-safe attempt record."""

    if getattr(preparer, "_records_production_context_attempts", False):
        return preparer

    @wraps(preparer)
    def wrapped(*args: object, **kwargs: object) -> object:
        settings = kwargs.get("settings") or (args[0] if args else None)
        scheduled_for = kwargs.get("scheduled_for") or (
            args[1] if len(args) > 1 else None
        )
        if settings is None:
            raise TypeError("context preparer requires settings")

        started_at = _utc_now()
        _atomic_json(
            attempt_state_path(settings),
            _attempt_payload(
                state="running",
                scheduled_for=scheduled_for,
                started_at=started_at,
                completed_at=None,
                detail=(
                    "A governed production-context refresh is in progress. The last "
                    "successful opportunity scan remains available until replacement."
                ),
            ),
        )
        try:
            result = preparer(*args, **kwargs)
        except Exception as error:
            completed_at = _utc_now()
            detail = f"{type(error).__name__}: {error}"[:1200]
            _atomic_json(
                attempt_state_path(settings),
                _attempt_payload(
                    state="failed",
                    scheduled_for=scheduled_for,
                    started_at=started_at,
                    completed_at=completed_at,
                    detail=detail,
                ),
            )
            raise

        to_dict = getattr(result, "to_dict", None)
        serialized = to_dict() if callable(to_dict) else {}
        result_payload = serialized if isinstance(serialized, Mapping) else {}
        result_state = str(
            result_payload.get("state") or getattr(result, "state", "unknown")
        ).strip().lower()
        detail = str(
            result_payload.get("detail") or getattr(result, "detail", "")
        ).strip()
        _atomic_json(
            attempt_state_path(settings),
            _attempt_payload(
                state=result_state or "unknown",
                scheduled_for=scheduled_for,
                started_at=started_at,
                completed_at=_utc_now(),
                detail=detail,
                result=result_payload,
            ),
        )
        return result

    wrapped._records_production_context_attempts = True  # type: ignore[attr-defined]
    return wrapped


__all__ = [
    "ATTEMPT_STATE_FILENAME",
    "SUCCESS_STATE_FILENAME",
    "attempt_state_path",
    "invalidate_reuse_preserving_success",
    "latest_attempt",
    "recording_context_preparer",
    "successful_state_path",
]
