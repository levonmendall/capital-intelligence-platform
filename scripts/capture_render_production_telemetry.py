"""Capture credential-safe Render production progress for GitHub operational telemetry.

This collector is deliberately read-only. It reads the already-public redacted CIO diagnostic
surface, rejects payloads containing forbidden fields, and writes only a small allowlisted
operational snapshot. It never accepts Render credentials and cannot authorize investment or
execution activity.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "render-production-telemetry.v1"
_FINAL_SUCCESS_STATE = "completed"
_FINAL_FAILURE_STATE = "failed"
_EXIT_UNSAFE = 4
_EXIT_RELEASE_MISMATCH = 5
_EXIT_DIAGNOSTIC_FAILED = 6
_EXIT_TIMEOUT = 7
_FORBIDDEN_KEYS = frozenset(
    {
        "holdings",
        "positions",
        "target_weights",
        "candidate_symbols",
        "recommendations",
        "provider_payloads",
        "provider_records",
        "api_key",
        "api_token",
        "access_token",
        "authorization",
        "cookie",
        "password",
        "secret",
    }
)
_MARKET_LANE_KEYS = (
    "asset_class",
    "scheduled",
    "represented",
    "catalog_count",
    "deep_analyzed_count",
    "selected_count",
)
_DIAGNOSTIC_BOOLEAN_KEYS = (
    "ready",
    "release_matches",
    "credential_safe",
    "paper_only",
    "real_money_authorized",
    "context_cycle_matches",
    "comprehensive_discovery_required",
    "comprehensive_discovery_complete",
    "scheduled_market_coverage_complete",
    "terminal_screening_complete",
    "all_market_evaluation_complete",
)
_PROGRESS_BOOLEAN_KEYS = (
    "comprehensive_discovery_complete",
    "scheduled_market_coverage_complete",
    "terminal_screening_complete",
    "all_market_evaluation_complete",
)


class UnsafeTelemetryPayload(RuntimeError):
    """Raised when a supposedly redacted public audit contains forbidden fields."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _walk_keys(value: object) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key).strip().lower())
            keys.extend(_walk_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            keys.extend(_walk_keys(item))
    return tuple(keys)


def _assert_credential_safe_source(payload: Mapping[str, Any]) -> None:
    forbidden = sorted(_FORBIDDEN_KEYS.intersection(_walk_keys(payload)))
    if forbidden:
        raise UnsafeTelemetryPayload(
            "public audit contains forbidden operational fields"
        )
    if payload.get("credential_safe") is not True:
        raise UnsafeTelemetryPayload("public audit is not marked credential-safe")
    if payload.get("paper_only") is not True:
        raise UnsafeTelemetryPayload("public audit is not marked paper-only")
    if payload.get("real_money_authorized") is not False:
        raise UnsafeTelemetryPayload("public audit does not explicitly deny real-money authority")


def _parse_progress_stage(detail: object) -> str | None:
    raw = str(detail or "").strip()
    prefix = "governed_progress="
    if not raw.startswith(prefix):
        return None
    stage = raw[len(prefix) :].split(";", 1)[0].strip()
    if not stage or len(stage) > 80:
        return None
    if not all(character.isalnum() or character in {"_", "-"} for character in stage):
        return None
    return stage


def _safe_market_lanes(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        lane: dict[str, object] = {}
        for key in _MARKET_LANE_KEYS:
            candidate = item.get(key)
            if isinstance(candidate, bool | int | float | str) or candidate is None:
                lane[key] = candidate
        safe.append(lane)
    return safe


def _elapsed_seconds(
    payload: Mapping[str, Any],
    *,
    captured_at: datetime,
) -> float | None:
    requested_at = _parse_datetime(payload.get("requested_at"))
    if requested_at is None:
        return None
    completed_at = _parse_datetime(payload.get("completed_at"))
    endpoint = completed_at or captured_at
    elapsed = (endpoint - requested_at).total_seconds()
    return round(max(0.0, elapsed), 3)


def build_snapshot(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
    captured_at: datetime | None = None,
    http_status: int | None = None,
    latency_ms: float | None = None,
) -> dict[str, object]:
    """Build an allowlisted production snapshot from the public diagnostic audit."""

    _assert_credential_safe_source(payload)
    now = (captured_at or _utc_now()).astimezone(timezone.utc)
    active_release = str(payload.get("active_release") or "")
    release_matches_expected = bool(
        active_release == expected_release and payload.get("release_matches") is True
    )
    diagnostic: dict[str, object] = {
        "state": str(payload.get("state") or "unknown"),
        "active_release": active_release,
        "release_matches_expected": release_matches_expected,
        "requested_at": str(payload.get("requested_at") or "") or None,
        "completed_at": str(payload.get("completed_at") or "") or None,
        "elapsed_seconds": _elapsed_seconds(payload, captured_at=now),
        "stage": _parse_progress_stage(payload.get("detail")),
        "limitation_count": (
            len(payload.get("comprehensive_discovery_limitations"))
            if isinstance(payload.get("comprehensive_discovery_limitations"), list)
            else 0
        ),
        "market_lanes": _safe_market_lanes(payload.get("market_lanes")),
    }
    for key in _DIAGNOSTIC_BOOLEAN_KEYS:
        value = payload.get(key)
        diagnostic[key] = value if isinstance(value, bool) else None

    http: dict[str, object] = {}
    if http_status is not None:
        http["status"] = int(http_status)
    if latency_ms is not None:
        http["latency_ms"] = round(max(0.0, float(latency_ms)), 3)

    return {
        "schema_version": _SCHEMA_VERSION,
        "captured_at": _iso_z(now),
        "expected_release": expected_release,
        "capture_state": "ok",
        "http": http,
        "diagnostic": diagnostic,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


def unavailable_snapshot(
    *,
    expected_release: str,
    error_type: str,
    captured_at: datetime | None = None,
    http_status: int | None = None,
) -> dict[str, object]:
    now = (captured_at or _utc_now()).astimezone(timezone.utc)
    http: dict[str, object] = {}
    if http_status is not None:
        http["status"] = int(http_status)
    return {
        "schema_version": _SCHEMA_VERSION,
        "captured_at": _iso_z(now),
        "expected_release": expected_release,
        "capture_state": "unavailable",
        "error_type": error_type,
        "http": http,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


def unsafe_snapshot(
    *,
    expected_release: str,
    captured_at: datetime | None = None,
) -> dict[str, object]:
    now = (captured_at or _utc_now()).astimezone(timezone.utc)
    return {
        "schema_version": _SCHEMA_VERSION,
        "captured_at": _iso_z(now),
        "expected_release": expected_release,
        "capture_state": "unsafe_payload",
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


def fetch_public_audit(
    url: str,
    *,
    timeout_seconds: float = 10.0,
) -> tuple[Mapping[str, Any], int, float]:
    """GET the public audit without credentials, cookies, or mutation-capable methods."""

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-render-telemetry/1.0",
        },
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 200))
        payload = json.loads(response.read().decode("utf-8"))
    latency_ms = (time.monotonic() - started) * 1000.0
    if not isinstance(payload, Mapping):
        raise ValueError("public audit must encode a JSON object")
    return payload, status, latency_ms


def capture_once(
    *,
    url: str,
    expected_release: str,
    fetcher: Callable[[str], tuple[Mapping[str, Any], int, float]] | None = None,
    captured_at: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    active_fetcher = fetcher or (lambda target: fetch_public_audit(target))
    try:
        payload, status, latency_ms = active_fetcher(url)
        snapshot = build_snapshot(
            payload,
            expected_release=expected_release,
            captured_at=captured_at,
            http_status=status,
            latency_ms=latency_ms,
        )
    except UnsafeTelemetryPayload:
        return unsafe_snapshot(
            expected_release=expected_release,
            captured_at=captured_at,
        ), True
    except (OSError, TypeError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        status = int(error.code) if isinstance(error, urllib.error.HTTPError) else None
        return unavailable_snapshot(
            expected_release=expected_release,
            error_type=type(error).__name__,
            captured_at=captured_at,
            http_status=status,
        ), False
    return snapshot, False


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _diagnostic(snapshot: Mapping[str, object]) -> Mapping[str, object] | None:
    diagnostic = snapshot.get("diagnostic")
    return diagnostic if isinstance(diagnostic, Mapping) else None


def _progress_started(snapshot: Mapping[str, object]) -> bool:
    diagnostic = _diagnostic(snapshot)
    if diagnostic is None:
        return False
    if diagnostic.get("stage") is not None:
        return True
    lanes = diagnostic.get("market_lanes")
    if isinstance(lanes, list) and lanes:
        return True
    return any(diagnostic.get(key) is True for key in _PROGRESS_BOOLEAN_KEYS)


def _current_success(snapshot: Mapping[str, object]) -> bool:
    diagnostic = _diagnostic(snapshot)
    return bool(
        snapshot.get("capture_state") == "ok"
        and diagnostic is not None
        and diagnostic.get("release_matches_expected") is True
        and diagnostic.get("state") == _FINAL_SUCCESS_STATE
        and diagnostic.get("all_market_evaluation_complete") is True
    )


def _terminal_failure(snapshot: Mapping[str, object]) -> bool:
    diagnostic = _diagnostic(snapshot)
    return bool(
        snapshot.get("capture_state") == "ok"
        and diagnostic is not None
        and diagnostic.get("release_matches_expected") is True
        and diagnostic.get("state") == _FINAL_FAILURE_STATE
    )


def _failure_class(snapshot: Mapping[str, object], *, timed_out: bool = False) -> str:
    diagnostic = _diagnostic(snapshot)
    if (
        snapshot.get("capture_state") == "ok"
        and diagnostic is not None
        and diagnostic.get("release_matches_expected") is not True
    ):
        return "release_mismatch"
    if _terminal_failure(snapshot):
        return "terminal_failure" if _progress_started(snapshot) else "startup_failure"
    if timed_out:
        return "timeout"
    return "none"


def _annotate_observation(
    snapshot: Mapping[str, object],
    *,
    observation_count: int,
    observed_duration_seconds: float,
    timed_out: bool = False,
) -> dict[str, object]:
    annotated = dict(snapshot)
    annotated["progress_started"] = _progress_started(snapshot)
    annotated["failure_class"] = _failure_class(snapshot, timed_out=timed_out)
    annotated["observation_count"] = max(1, int(observation_count))
    annotated["observed_duration_seconds"] = round(
        max(0.0, float(observed_duration_seconds)), 3
    )
    return annotated


def _exit_code(snapshot: Mapping[str, object], *, unsafe: bool) -> int:
    if unsafe:
        return _EXIT_UNSAFE
    if _current_success(snapshot):
        return 0
    failure_class = str(snapshot.get("failure_class") or "")
    if failure_class == "release_mismatch":
        return _EXIT_RELEASE_MISMATCH
    if failure_class in {"startup_failure", "terminal_failure"}:
        return _EXIT_DIAGNOSTIC_FAILED
    return _EXIT_TIMEOUT


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeline-output", type=Path)
    parser.add_argument("--watch-seconds", type=float, default=0.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if not args.url.strip() or not args.expected_release.strip():
        raise SystemExit("url and expected-release are required")
    if args.watch_seconds < 0 or args.interval_seconds <= 0:
        raise SystemExit("watch-seconds cannot be negative and interval-seconds must be positive")

    started = time.monotonic()
    deadline = started + args.watch_seconds
    timeline: list[dict[str, object]] = []
    unsafe = False
    final_snapshot: dict[str, object] | None = None
    while True:
        snapshot, unsafe = capture_once(
            url=args.url,
            expected_release=args.expected_release,
        )
        now = time.monotonic()
        terminal_failure = _terminal_failure(snapshot)
        success = _current_success(snapshot)
        timed_out = not (unsafe or terminal_failure or success) and now >= deadline
        final_snapshot = _annotate_observation(
            snapshot,
            observation_count=len(timeline) + 1,
            observed_duration_seconds=now - started,
            timed_out=timed_out,
        )
        timeline.append(final_snapshot)
        _write_json(args.output, final_snapshot)
        if args.timeline_output is not None:
            _write_json(args.timeline_output, timeline)
        print(json.dumps(final_snapshot, sort_keys=True, allow_nan=False), flush=True)
        if unsafe or terminal_failure or success or timed_out:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, remaining))

    if final_snapshot is None:
        return _EXIT_TIMEOUT
    return _exit_code(final_snapshot, unsafe=unsafe)


if __name__ == "__main__":
    raise SystemExit(main())
