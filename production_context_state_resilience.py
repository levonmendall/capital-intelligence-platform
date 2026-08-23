"""Resilient state lifecycle for governed production-context refreshes.

The canonical successful publication remains readable while a newer refresh is
attempted. Reuse is invalidated by changing only the cache key; the last successful
scan payload is never deleted before its replacement exists. A separate atomic
attempt record explains running, blocked, failed, ready, and reused refreshes.

Every attempt owns its production-context cycle before expensive preparation begins.
The attempt identifier and monotonically increasing fence version prevent a stale worker
from replacing the state of a newer owner after that worker has been superseded.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

try:  # POSIX production and GitHub Actions use flock; other platforms stay best-effort.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX compatibility only.
    fcntl = None

SUCCESS_STATE_FILENAME = "production-context-publication-state.json"
ATTEMPT_STATE_FILENAME = "production-context-publication-attempt-state.json"
ATTEMPT_LOCK_FILENAME = "production-context-publication-attempt-state.lock"
ATTEMPT_SCHEMA = "production-context-publication-attempt-state.v2-cycle-owned"


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


def _attempt_lock_path(settings: object) -> Path:
    return _state_root(settings) / ATTEMPT_LOCK_FILENAME


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


@contextmanager
def _attempt_guard(settings: object) -> Iterator[None]:
    """Serialize read/replace ownership transitions for the single latest-attempt file."""

    path = _attempt_lock_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _attempt_cycle_key(settings: object, scheduled_for: object) -> str | None:
    """Derive the same immutable calendar-cycle identity as the governed publisher."""

    if not isinstance(scheduled_for, datetime):
        return None
    if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
        return None
    timezone_name = str(getattr(settings, "scheduler_timezone", "")).strip()
    if not timezone_name:
        return None
    local_date = scheduled_for.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return f"canonical-cio:{timezone_name}:{local_date}"


def _attempt_payload(
    *,
    state: str,
    scheduled_for: object,
    started_at: datetime,
    completed_at: datetime | None,
    detail: str,
    attempt_id: str,
    fence_version: int,
    cycle_key: str | None,
    supersedes_attempt_id: str | None = None,
    result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    scheduled_text = (
        scheduled_for.isoformat()
        if isinstance(scheduled_for, datetime)
        else str(scheduled_for or "")
    )
    payload: dict[str, object] = {
        "schema_version": ATTEMPT_SCHEMA,
        "attempt_id": attempt_id,
        "fence_version": fence_version,
        "state": state,
        "cycle_key": cycle_key,
        "scheduled_for": scheduled_text,
        "started_at": started_at.isoformat(),
        "completed_at": None if completed_at is None else completed_at.isoformat(),
        "detail": detail,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if supersedes_attempt_id:
        payload["supersedes_attempt_id"] = supersedes_attempt_id
    if result is not None:
        for key in (
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


def _begin_attempt(
    *,
    settings: object,
    scheduled_for: object,
    started_at: datetime,
) -> tuple[str, int, str | None]:
    attempt_id = uuid4().hex
    cycle_key = _attempt_cycle_key(settings, scheduled_for)
    path = attempt_state_path(settings)
    with _attempt_guard(settings):
        previous = _read_json(path) or {}
        raw_fence = previous.get("fence_version", 0)
        fence_version = (
            int(raw_fence) + 1
            if isinstance(raw_fence, int)
            and not isinstance(raw_fence, bool)
            and raw_fence >= 0
            else 1
        )
        previous_id = str(previous.get("attempt_id") or "").strip() or None
        _atomic_json(
            path,
            _attempt_payload(
                state="running",
                scheduled_for=scheduled_for,
                started_at=started_at,
                completed_at=None,
                detail=(
                    "A governed production-context refresh is in progress. The last "
                    "successful opportunity scan remains available until replacement."
                ),
                attempt_id=attempt_id,
                fence_version=fence_version,
                cycle_key=cycle_key,
                supersedes_attempt_id=previous_id,
            ),
        )
    return attempt_id, fence_version, cycle_key


def _finish_attempt_if_owned(
    *,
    settings: object,
    attempt_id: str,
    fence_version: int,
    payload: Mapping[str, object],
) -> bool:
    """Compare-and-replace only while this worker still owns the current fence."""

    path = attempt_state_path(settings)
    with _attempt_guard(settings):
        current = _read_json(path)
        if not isinstance(current, Mapping):
            return False
        if str(current.get("attempt_id") or "") != attempt_id:
            return False
        if current.get("fence_version") != fence_version:
            return False
        final_payload = dict(payload)
        supersedes_attempt_id = str(
            current.get("supersedes_attempt_id") or ""
        ).strip()
        if supersedes_attempt_id:
            final_payload.setdefault("supersedes_attempt_id", supersedes_attempt_id)
        _atomic_json(path, final_payload)
        return True


def recording_context_preparer(preparer: Callable[..., object]) -> Callable[..., object]:
    """Wrap a context preparer with cycle-owned, fenced, presentation-safe state."""

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
        attempt_id, fence_version, owned_cycle_key = _begin_attempt(
            settings=settings,
            scheduled_for=scheduled_for,
            started_at=started_at,
        )
        try:
            result = preparer(*args, **kwargs)
        except Exception as error:
            completed_at = _utc_now()
            detail = f"{type(error).__name__}: {error}"[:1200]
            _finish_attempt_if_owned(
                settings=settings,
                attempt_id=attempt_id,
                fence_version=fence_version,
                payload=_attempt_payload(
                    state="failed",
                    scheduled_for=scheduled_for,
                    started_at=started_at,
                    completed_at=completed_at,
                    detail=detail,
                    attempt_id=attempt_id,
                    fence_version=fence_version,
                    cycle_key=owned_cycle_key,
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
        result_cycle_key = str(
            result_payload.get("cycle_key") or getattr(result, "cycle_key", "") or ""
        ).strip() or None
        if (
            owned_cycle_key is not None
            and result_cycle_key is not None
            and result_cycle_key != owned_cycle_key
        ):
            mismatch = (
                "Production context result cycle does not match the fenced attempt cycle."
            )
            _finish_attempt_if_owned(
                settings=settings,
                attempt_id=attempt_id,
                fence_version=fence_version,
                payload=_attempt_payload(
                    state="failed",
                    scheduled_for=scheduled_for,
                    started_at=started_at,
                    completed_at=_utc_now(),
                    detail=mismatch,
                    attempt_id=attempt_id,
                    fence_version=fence_version,
                    cycle_key=owned_cycle_key,
                ),
            )
            raise RuntimeError(mismatch)

        terminal_cycle_key = owned_cycle_key or result_cycle_key
        _finish_attempt_if_owned(
            settings=settings,
            attempt_id=attempt_id,
            fence_version=fence_version,
            payload=_attempt_payload(
                state=result_state or "unknown",
                scheduled_for=scheduled_for,
                started_at=started_at,
                completed_at=_utc_now(),
                detail=detail,
                attempt_id=attempt_id,
                fence_version=fence_version,
                cycle_key=terminal_cycle_key,
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
