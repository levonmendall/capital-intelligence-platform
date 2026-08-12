"""Poll and verify the public, redacted Render CIO diagnostic audit."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


_FINAL_STATES = frozenset({"completed", "failed"})
_SUCCESS_STATE = "completed"
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
        "secret",
    }
)
_SAFE_PROGRESS_TOKEN = re.compile(r"^[A-Za-z0-9_:-]{1,120}$")
_PROGRESS_HEARTBEAT_SECONDS = 30.0
_STALE_PROGRESS_WARNING_SECONDS = 300.0
_DEFAULT_FRESH_ATTEMPT_GRACE_ATTEMPTS = 8


class RenderAuditVerificationError(RuntimeError):
    """Raised when the deployed audit is unavailable, stale, or incomplete."""


def _fetch_json(url: str, *, timeout_seconds: float = 20.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-render-audit-verifier/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RenderAuditVerificationError("Render audit must encode a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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


def _safe_progress_token(value: object, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_PROGRESS_TOKEN.fullmatch(candidate) else fallback


def _progress_stage(payload: Mapping[str, Any]) -> str:
    durable = _safe_progress_token(payload.get("stage"), fallback="")
    if durable:
        return durable
    raw = str(payload.get("detail") or "").strip()
    prefix = "governed_progress="
    if not raw.startswith(prefix):
        return "awaiting_progress"
    stage = raw[len(prefix) :].split(";", 1)[0].strip()
    return _safe_progress_token(stage, fallback="awaiting_progress")


def _progress_fields(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> tuple[str, str, str]:
    state = _safe_progress_token(payload.get("state"), fallback="unknown")
    stage = _progress_stage(payload)
    active_release = str(payload.get("active_release") or "")
    if active_release:
        release_match = (
            "yes"
            if active_release == expected_release and payload.get("release_matches") is True
            else "no"
        )
    else:
        release_match = "unknown"
    return stage, state, release_match


def _emit_progress(
    *,
    writer: Callable[[str], None],
    attempt: int,
    elapsed_seconds: float,
    stage: str,
    state: str,
    release_match: str,
    stale_seconds: float | None = None,
) -> None:
    event = {
        "event": "render_cio_diagnostic_progress",
        "attempt": attempt,
        "verification_elapsed_seconds": int(max(0.0, elapsed_seconds)),
        "stage": stage,
        "state": state,
        "release_match": release_match,
    }
    writer(json.dumps(event, sort_keys=True))
    writer(
        "::notice title=Render CIO diagnostic progress::"
        f"stage={stage} state={state} elapsed={event['verification_elapsed_seconds']}s "
        f"release_match={release_match} attempt={attempt}"
    )
    if stale_seconds is not None:
        stale = int(max(0.0, stale_seconds))
        writer(
            "::warning title=Render CIO diagnostic phase unchanged::"
            f"stage={stage} state={state} unchanged_for={stale}s "
            f"release_match={release_match}"
        )


def audit_is_current_and_final(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> bool:
    return all(
        (
            str(payload.get("active_release") or "") == expected_release,
            payload.get("release_matches") is True,
            str(payload.get("state") or "") in _FINAL_STATES,
            bool(payload.get("completed_at")),
            payload.get("credential_safe") is True,
            payload.get("paper_only") is True,
            payload.get("real_money_authorized") is False,
        )
    )


def audit_is_current_success(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> bool:
    """Return true only for a current successful aggregate release audit.

    A current failed audit can be an intermediate result while the release bootstrap is
    performing its next bounded cache-resume attempt. The verifier therefore keeps
    polling until a completed audit appears or its own finite polling budget expires.
    """

    return (
        audit_is_current_and_final(payload, expected_release=expected_release)
        and str(payload.get("state") or "") == _SUCCESS_STATE
    )


def poll_render_audit(
    *,
    url: str,
    expected_release: str,
    output_path: Path,
    maximum_attempts: int = 120,
    interval_seconds: float = 15.0,
    fresh_attempt_grace_attempts: int = _DEFAULT_FRESH_ATTEMPT_GRACE_ATTEMPTS,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    progress_writer: Callable[[str], None] | None = print,
) -> Mapping[str, Any]:
    if not url.strip():
        raise ValueError("url cannot be empty")
    if not expected_release.strip():
        raise ValueError("expected_release cannot be empty")
    if maximum_attempts < 1:
        raise ValueError("maximum_attempts must be positive")
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative")
    if fresh_attempt_grace_attempts < 1:
        raise ValueError("fresh_attempt_grace_attempts must be positive")
    active_fetcher = fetcher or (lambda target: _fetch_json(target))
    last_detail = "the audit endpoint did not return a current release record"
    started_at = clock()
    last_progress_key: tuple[str, str, str] | None = None
    last_progress_change_at = started_at
    last_heartbeat_at: float | None = None
    last_stale_warning_at: float | None = None
    baseline_failed_request_id: str | None = None
    baseline_failed_attempt: int | None = None
    fresh_attempt_observed = False

    for attempt in range(1, maximum_attempts + 1):
        try:
            payload = active_fetcher(url)
            _write_json(output_path, payload)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
            RenderAuditVerificationError,
        ) as error:
            last_detail = f"{type(error).__name__}: {error}"
            now = clock()
            if progress_writer is not None and (
                last_heartbeat_at is None
                or now - last_heartbeat_at >= _PROGRESS_HEARTBEAT_SECONDS
            ):
                _emit_progress(
                    writer=progress_writer,
                    attempt=attempt,
                    elapsed_seconds=now - started_at,
                    stage="audit_unavailable",
                    state="unavailable",
                    release_match="unknown",
                )
                last_heartbeat_at = now
        else:
            now = clock()
            progress_key = _progress_fields(payload, expected_release=expected_release)
            progress_changed = progress_key != last_progress_key
            if progress_changed:
                last_progress_key = progress_key
                last_progress_change_at = now
                last_stale_warning_at = None

            stale_for = now - last_progress_change_at
            stale_warning_due = bool(
                not progress_changed
                and stale_for >= _STALE_PROGRESS_WARNING_SECONDS
                and (
                    last_stale_warning_at is None
                    or now - last_stale_warning_at >= _STALE_PROGRESS_WARNING_SECONDS
                )
            )
            heartbeat_due = bool(
                progress_writer is not None
                and (
                    progress_changed
                    or last_heartbeat_at is None
                    or now - last_heartbeat_at >= _PROGRESS_HEARTBEAT_SECONDS
                    or stale_warning_due
                )
            )
            if heartbeat_due and progress_writer is not None:
                stage, state, release_match = progress_key
                _emit_progress(
                    writer=progress_writer,
                    attempt=attempt,
                    elapsed_seconds=now - started_at,
                    stage=stage,
                    state=state,
                    release_match=release_match,
                    stale_seconds=stale_for if stale_warning_due else None,
                )
                last_heartbeat_at = now
                if stale_warning_due:
                    last_stale_warning_at = now

            request_id = str(payload.get("request_id") or "").strip()
            current_failed = bool(
                audit_is_current_and_final(payload, expected_release=expected_release)
                and str(payload.get("state") or "") == "failed"
            )
            if baseline_failed_attempt is None and current_failed:
                baseline_failed_request_id = request_id
                baseline_failed_attempt = attempt
            elif baseline_failed_attempt is not None and not fresh_attempt_observed:
                if request_id and request_id != baseline_failed_request_id:
                    fresh_attempt_observed = True
                elif attempt - baseline_failed_attempt >= fresh_attempt_grace_attempts:
                    stage = _progress_stage(payload)
                    raise RenderAuditVerificationError(
                        "stale_diagnostic: exact-release certification did not observe a fresh "
                        f"diagnostic request within {fresh_attempt_grace_attempts} polling attempts; "
                        f"request_id={baseline_failed_request_id or 'unavailable'}; "
                        f"state={payload.get('state')!r}; stage={stage}"
                    )

            if audit_is_current_success(
                payload,
                expected_release=expected_release,
            ):
                return payload
            last_detail = (
                "audit is not a current successful aggregate result: "
                f"active_release={payload.get('active_release')!r}, "
                f"release_matches={payload.get('release_matches')!r}, "
                f"state={payload.get('state')!r}, "
                f"detail={str(payload.get('detail') or '')[:1000]!r}"
            )
        if attempt < maximum_attempts:
            sleeper(interval_seconds)
    raise RenderAuditVerificationError(
        "Render CIO diagnostic did not publish a current successful aggregate audit "
        f"after {maximum_attempts} attempts; last_detail={last_detail}"
    )


def verify_complete_all_market_evaluation(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> None:
    if not audit_is_current_and_final(payload, expected_release=expected_release):
        raise RenderAuditVerificationError(
            "audit does not belong to the expected final deployed release"
        )
    forbidden = sorted(_FORBIDDEN_KEYS.intersection(_walk_keys(payload)))
    if forbidden:
        raise RenderAuditVerificationError(
            "public audit contains forbidden fields: " + ", ".join(forbidden)
        )
    required_true = (
        "ready",
        "context_cycle_matches",
        "comprehensive_discovery_required",
        "comprehensive_discovery_complete",
        "scheduled_market_coverage_complete",
        "terminal_screening_complete",
        "all_market_evaluation_complete",
    )
    failed = tuple(name for name in required_true if payload.get(name) is not True)
    lanes = payload.get("market_lanes")
    scheduled_lanes = (
        tuple(
            item
            for item in lanes
            if isinstance(item, Mapping) and item.get("scheduled") is True
        )
        if isinstance(lanes, list)
        else ()
    )
    unrepresented = tuple(
        str(item.get("asset_class") or "unknown")
        for item in scheduled_lanes
        if item.get("represented") is not True
    )
    if not scheduled_lanes:
        failed = (*failed, "scheduled_market_lanes_present")
    if unrepresented:
        failed = (*failed, "unrepresented_market_lanes=" + ",".join(unrepresented))
    if failed:
        detail = str(payload.get("detail") or "no diagnostic detail was published")
        limitations = payload.get("comprehensive_discovery_limitations")
        raise RenderAuditVerificationError(
            "all-market CIO evaluation failed closed; failed="
            + ", ".join(failed)
            + f"; detail={detail}; limitations={limitations!r}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-attempts", type=int, default=120)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument(
        "--fresh-attempt-grace-attempts",
        type=int,
        default=_DEFAULT_FRESH_ATTEMPT_GRACE_ATTEMPTS,
    )
    args = parser.parse_args(argv)
    try:
        payload = poll_render_audit(
            url=args.url,
            expected_release=args.expected_release,
            output_path=args.output,
            maximum_attempts=args.maximum_attempts,
            interval_seconds=args.interval_seconds,
            fresh_attempt_grace_attempts=args.fresh_attempt_grace_attempts,
        )
        verify_complete_all_market_evaluation(
            payload,
            expected_release=args.expected_release,
        )
    except (OSError, TypeError, ValueError, RenderAuditVerificationError) as error:
        print(
            json.dumps(
                {
                    "event": "render_cio_diagnostic_verification_failed",
                    "error_type": type(error).__name__,
                    "detail": str(error)[:4000],
                    "expected_release": args.expected_release,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 3
    print(
        json.dumps(
            {
                "event": "render_cio_diagnostic_verified",
                "expected_release": args.expected_release,
                "all_market_evaluation_complete": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
