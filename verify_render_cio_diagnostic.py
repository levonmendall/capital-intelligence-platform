"""Retry-aware entrypoint for exact-release Render CIO verification.

Deployment-triggered verification also enforces a request freshness boundary supplied by
``CIO_DIAGNOSTIC_FRESH_AFTER``. This prevents an old exact-release diagnostic snapshot
from being adopted after a redeploy of the same commit while preserving scheduled/manual
verification behavior. All verifier paths remain fail-closed.

The exact-release gate proves the complete analytical path through portfolio construction.
Paper implementation is a separate terminal operational state: a scheduled or held paper
transaction cannot invalidate evidence, screening, committee, CIO, or construction that
already completed under the same immutable certification input.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import verify_render_cio_diagnostic_core as _core


_original_poll_render_audit = _core.poll_render_audit
_original_verify_complete_all_market_evaluation = (
    _core.verify_complete_all_market_evaluation
)
_SERVER_REPLACEMENT_GRACE_ATTEMPTS = 45
_MAX_ADOPTED_FAILURES = 4
_FRESH_AFTER_ENV = "CIO_DIAGNOSTIC_FRESH_AFTER"
_PREQUALIFICATION_FAILURE_STAGE = "evidence_prequalification_failed"


def _parse_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_boundary() -> datetime | None:
    return _parse_utc(os.getenv(_FRESH_AFTER_ENV))


def _request_is_fresh(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
    boundary: datetime,
) -> bool:
    request_id = str(payload.get("request_id") or "").strip()
    requested_at = _parse_utc(payload.get("requested_at"))
    return bool(
        request_id
        and requested_at is not None
        and requested_at >= boundary
        and str(payload.get("active_release") or "") == expected_release
        and payload.get("release_matches") is True
    )


def _terminal_prequalification_failure(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> bool:
    """Return true when evidence failed before a new CIO request may lawfully exist."""

    return bool(
        str(payload.get("state") or "") == "failed"
        and _core._progress_stage(payload) == _PREQUALIFICATION_FAILURE_STAGE
        and _core.audit_is_current_and_final(
            payload,
            expected_release=expected_release,
        )
    )


def _freshness_detail(
    payload: Mapping[str, Any],
    *,
    boundary: datetime,
) -> str:
    return (
        "stale_diagnostic_snapshot: exact-release verification did not observe a "
        "post-deployment diagnostic request; "
        f"request_id={str(payload.get('request_id') or '').strip() or 'unavailable'}; "
        f"requested_at={str(payload.get('requested_at') or '').strip() or 'unavailable'}; "
        f"fresh_after={boundary.isoformat()}; "
        f"state={payload.get('state')!r}; stage={_core._progress_stage(payload)}"
    )


def _await_fresh_deployment_request(
    *,
    url: str,
    expected_release: str,
    output_path: Path,
    fetcher: Callable[[str], Mapping[str, Any]],
    sleeper: Callable[[float], None],
    progress_writer: Callable[[str], None] | None,
    interval_seconds: float,
    boundary: datetime,
) -> tuple[Mapping[str, Any], int]:
    last_payload: Mapping[str, Any] | None = None
    last_fetch_error: BaseException | None = None
    for attempt in range(1, _SERVER_REPLACEMENT_GRACE_ATTEMPTS + 1):
        try:
            payload = fetcher(url)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
            _core.RenderAuditVerificationError,
        ) as error:
            last_fetch_error = error
            if progress_writer is not None and (attempt == 1 or attempt % 2 == 0):
                progress_writer(
                    json.dumps(
                        {
                            "event": "render_cio_diagnostic_freshness_unavailable",
                            "attempt": attempt,
                            "error_type": type(error).__name__,
                            "fresh_after": boundary.isoformat(),
                            "release_match": "unknown",
                        },
                        sort_keys=True,
                    )
                )
            if attempt < _SERVER_REPLACEMENT_GRACE_ATTEMPTS:
                sleeper(interval_seconds)
            continue

        last_payload = payload
        _core._write_json(output_path, payload)
        # Evidence prequalification intentionally happens before a fresh CIO request is
        # created. If it terminates fail-closed, freshness must not mask that root cause as
        # a stale request. The verifier reports the current release's terminal evidence
        # failure immediately and still requires freshness for every actual CIO request.
        if _terminal_prequalification_failure(
            payload,
            expected_release=expected_release,
        ):
            raise _core.RenderAuditVerificationError(
                _core._terminal_failure_detail(payload)
            )
        if _request_is_fresh(
            payload,
            expected_release=expected_release,
            boundary=boundary,
        ):
            if progress_writer is not None:
                progress_writer(
                    json.dumps(
                        {
                            "event": "render_cio_diagnostic_fresh_request_observed",
                            "attempt": attempt,
                            "request_id": str(payload.get("request_id") or ""),
                            "requested_at": str(payload.get("requested_at") or ""),
                            "release_match": "yes",
                        },
                        sort_keys=True,
                    )
                )
            return payload, attempt

        if progress_writer is not None and (attempt == 1 or attempt % 2 == 0):
            progress_writer(
                json.dumps(
                    {
                        "event": "render_cio_diagnostic_freshness_wait",
                        "attempt": attempt,
                        "request_id": str(payload.get("request_id") or "") or None,
                        "requested_at": str(payload.get("requested_at") or "") or None,
                        "fresh_after": boundary.isoformat(),
                        "release_match": (
                            "yes"
                            if str(payload.get("active_release") or "") == expected_release
                            and payload.get("release_matches") is True
                            else "no"
                        ),
                    },
                    sort_keys=True,
                )
            )
        if attempt < _SERVER_REPLACEMENT_GRACE_ATTEMPTS:
            sleeper(interval_seconds)

    if last_payload is not None:
        raise _core.RenderAuditVerificationError(
            _freshness_detail(last_payload, boundary=boundary)
        )
    raise _core.RenderAuditVerificationError(
        "stale_diagnostic_snapshot: exact-release verification could not read a "
        "post-deployment diagnostic request; "
        f"fresh_after={boundary.isoformat()}; state='unavailable'; "
        "stage=audit_unavailable; "
        f"last_error={type(last_fetch_error).__name__ if last_fetch_error else 'unknown'}"
    )


def _replacement_wait_detail(
    primary_failure_detail: str,
    secondary_detail: str,
) -> str:
    return (
        f"{primary_failure_detail}; "
        "secondary_context=replacement_attempt_not_observed; "
        f"replacement_wait_detail={secondary_detail}"
    )


def _retry_aware_poll_render_audit(
    *,
    url: str,
    expected_release: str,
    output_path: Path,
    maximum_attempts: int = 120,
    interval_seconds: float = 15.0,
    fresh_attempt_grace_attempts: int = _core._DEFAULT_FRESH_ATTEMPT_GRACE_ATTEMPTS,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    sleeper: Callable[[float], None] = _core.time.sleep,
    clock: Callable[[], float] = _core.time.monotonic,
    progress_writer: Callable[[str], None] | None = print,
) -> Mapping[str, Any]:
    active_fetcher = fetcher or (lambda target: _core._fetch_json(target))
    boundary = _freshness_boundary()
    prefetched: Mapping[str, Any] | None = None
    freshness_attempts = 0
    if boundary is not None:
        prefetched, freshness_attempts = _await_fresh_deployment_request(
            url=url,
            expected_release=expected_release,
            output_path=output_path,
            fetcher=active_fetcher,
            sleeper=sleeper,
            progress_writer=progress_writer,
            interval_seconds=interval_seconds,
            boundary=boundary,
        )
    else:
        # Scheduled/manual verification has no deployment freshness timestamp. Prefetch one
        # snapshot so a release-level prequalification failure is still terminal immediately
        # instead of becoming the baseline failed request that the core later relabels stale.
        try:
            candidate = active_fetcher(url)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
            _core.RenderAuditVerificationError,
        ):
            candidate = None
        if candidate is not None:
            prefetched = candidate
            freshness_attempts = 1
            _core._write_json(output_path, candidate)
            if _terminal_prequalification_failure(
                candidate,
                expected_release=expected_release,
            ):
                raise _core.RenderAuditVerificationError(
                    _core._terminal_failure_detail(candidate)
                )

    if prefetched is not None and _terminal_prequalification_failure(
        prefetched,
        expected_release=expected_release,
    ):
        raise _core.RenderAuditVerificationError(
            _core._terminal_failure_detail(prefetched)
        )

    def next_fetch(target: str) -> Mapping[str, Any]:
        nonlocal prefetched
        if prefetched is not None:
            payload = prefetched
            prefetched = None
            return payload
        return active_fetcher(target)

    adopted_failures = 0
    awaiting_replacement = False
    primary_failure_detail: str | None = None
    remaining_attempts = max(1, maximum_attempts - max(0, freshness_attempts - 1))
    while True:
        active_grace_attempts = (
            max(
                fresh_attempt_grace_attempts,
                _SERVER_REPLACEMENT_GRACE_ATTEMPTS,
            )
            if awaiting_replacement
            else fresh_attempt_grace_attempts
        )
        try:
            return _original_poll_render_audit(
                url=url,
                expected_release=expected_release,
                output_path=output_path,
                maximum_attempts=remaining_attempts,
                interval_seconds=interval_seconds,
                fresh_attempt_grace_attempts=active_grace_attempts,
                fetcher=next_fetch,
                sleeper=sleeper,
                clock=clock,
                progress_writer=progress_writer,
            )
        except _core.RenderAuditVerificationError as error:
            detail = str(error)
            if not detail.startswith("current_diagnostic_failed:"):
                if (
                    awaiting_replacement
                    and primary_failure_detail is not None
                    and (
                        detail.startswith("stale_diagnostic:")
                        or detail.startswith(
                            "Render CIO diagnostic did not publish a current successful aggregate audit"
                        )
                    )
                ):
                    raise _core.RenderAuditVerificationError(
                        _replacement_wait_detail(primary_failure_detail, detail)
                    ) from error
                raise
            if f"stage={_PREQUALIFICATION_FAILURE_STAGE}" in detail:
                raise
            if primary_failure_detail is None:
                primary_failure_detail = detail
            adopted_failures += 1
            if adopted_failures >= _MAX_ADOPTED_FAILURES:
                raise
            awaiting_replacement = True
            if progress_writer is not None:
                progress_writer(
                    json.dumps(
                        {
                            "event": "render_cio_diagnostic_replacement_expected",
                            "failed_server_attempt": adopted_failures,
                            "stage": "awaiting_replacement_attempt",
                            "state": "pending",
                            "release_match": "yes",
                        },
                        sort_keys=True,
                    )
                )
                progress_writer(
                    "::notice title=Render CIO diagnostic replacement::"
                    f"failed_server_attempt={adopted_failures} "
                    "state=awaiting_replacement_attempt release_match=yes"
                )


def _verify_end_to_end_all_market_evaluation(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> None:
    """Verify the exact-release analytical path through canonical construction.

    Terminal paper implementation is intentionally reported but not required here. The
    release gate proves that qualified all-market evidence reached screening, the six-
    specialist committee, CIO authority, and portfolio construction under one immutable
    certification input. A pending launch/session boundary therefore cannot manufacture
    an analytical failure after construction has already completed.
    """

    _original_verify_complete_all_market_evaluation(
        payload,
        expected_release=expected_release,
    )
    failed: list[str] = []

    # Preserve the existing compositional market-lane proof. Certification v2 adds the
    # downstream deterministic lineage; it does not weaken the lane aggregate contract.
    for name in (
        "all_market_runtime_certified",
        "all_market_certification_integrity_valid",
        "all_market_certification_release_matches",
        "all_market_certification_context_matches",
    ):
        if payload.get(name) is not True:
            failed.append(name)
    for name in (
        "all_market_certification_id",
        "all_market_certification_epoch",
        "all_market_certification_aggregate_sha256",
        "all_market_certification_discovery_manifest_fingerprint",
    ):
        if not str(payload.get(name) or "").strip():
            failed.append(name)

    # Certification v2 is the authoritative release/evidence/decision handoff. Require
    # every analytical stage through construction and every immutable component identity.
    for name in (
        "all_market_certification_v2_available",
        "all_market_certification_v2_input_integrity_valid",
        "all_market_certification_v2_state_integrity_valid",
        "all_market_certification_v2_release_matches",
        "all_market_evidence_certified",
        "all_market_screening_certified",
        "all_market_committee_certified",
        "all_market_cio_certified",
        "all_market_construction_certified",
    ):
        if payload.get(name) is not True:
            failed.append(name)
    for name in (
        "all_market_certification_v2_id",
        "all_market_evidence_generation_id",
        "all_market_point_in_time_snapshot_id",
        "all_market_global_discovery_snapshot_id",
        "all_market_us_equity_discovery_snapshot_id",
        "all_market_paper_evidence_snapshot_id",
        "all_market_policy_compatibility_hash",
        "all_market_certification_v2_state",
    ):
        if not str(payload.get(name) or "").strip():
            failed.append(name)

    # Operational certification is a separate truth. If it is complete, the audit must
    # prove a terminal no-action or paper-implemented branch. If it is pending, the
    # analytical gate still succeeds only because CONSTRUCTION_COMPLETE was proven above.
    if payload.get("all_market_operational_certified") is True:
        if str(payload.get("all_market_certification_v2_state") or "") != "CERTIFIED":
            failed.append("all_market_operational_state")
        if not (
            payload.get("all_market_paper_implementation_certified") is True
            or payload.get("all_market_no_action_certified") is True
        ):
            failed.append("all_market_terminal_outcome")

    if str(payload.get("schema_version") or "") != (
        "public-cio-diagnostic-audit.v2-end-to-end"
    ):
        failed.append("end_to_end_audit_schema")
    if failed:
        raise _core.RenderAuditVerificationError(
            "end-to-end all-market analytical certification failed closed; failed="
            + ", ".join(failed)
            + f"; detail={str(payload.get('detail') or '')[:1000]}"
        )


_core.poll_render_audit = _retry_aware_poll_render_audit
_core.verify_complete_all_market_evaluation = _verify_end_to_end_all_market_evaluation


if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
