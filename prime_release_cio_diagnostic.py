"""Prime the durable paper-only CIO diagnostic record for the current release.

This startup boundary exists only to make exact-release certification state truthful
while a comprehensive discovery run is still in progress. It creates the current
release's pending diagnostic request before the web service publishes its first public
audit. It does not claim the request, run analysis, authorize a candidate, size a
portfolio, execute an order, or grant real-money authority.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)

_OWNER_LEASE_FILENAME = "manual-cio-diagnostic-owner.json"


def _boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-release-diagnostic-primer",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "paper_only": True,
                "real_money_authorized": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _owner_lease_path(values: Mapping[str, str]) -> Path:
    """Resolve the same owner-lease path used by the governed diagnostic runner."""

    configured = values.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().parent / _OWNER_LEASE_FILENAME
    data_root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_root / _OWNER_LEASE_FILENAME


def _lease_payload(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _process_alive(pid: object) -> bool:
    if isinstance(pid, bool):
        return False
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    return value > 0 and Path(f"/proc/{value}").exists()


def _active_owner_exists(request_id: str, values: Mapping[str, str]) -> bool:
    """Honor an in-progress request only while its exact owner lease is still live."""

    payload = _lease_payload(_owner_lease_path(values))
    return bool(
        payload is not None
        and str(payload.get("request_id") or "") == request_id
        and _process_alive(payload.get("pid"))
    )


def _supersede_stale_pending_request(
    *,
    existing,
    requester: str,
    release: str,
    values: MutableMapping[str, str],
) -> None:
    """Close one orphaned prior-release pending request before current promotion.

    Pending coordination has never been claimed and therefore has no CIO, construction,
    or execution authority. Claiming it only so it can be durably closed preserves the
    existing append-only terminal semantics while allowing the exact current release to
    own the single coordination slot.
    """

    claimed = claim_manual_cio_diagnostic(values=values)
    if claimed is None or claimed.request_id != existing.request_id:
        _log(
            "release_diagnostic_primer_stale_pending_claim_failed",
            release=release,
            requested_by=requester,
            stale_request_id=existing.request_id,
            stale_requested_by=existing.requested_by,
            handoff_complete=False,
            decision_authority=False,
            execution_authority=False,
        )
        raise RuntimeError("stale pending diagnostic could not be closed fail-closed")

    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key=None,
        snapshot_identifier=None,
        detail=(
            "Pending diagnostic belonged to a prior release and was superseded before "
            "execution so exact-release post-prequalification coordination could proceed."
        ),
        values=values,
    )
    _log(
        "release_diagnostic_primer_stale_pending_superseded",
        release=release,
        requested_by=requester,
        stale_request_id=finished.request_id,
        stale_requested_by=finished.requested_by,
        stale_state=finished.state,
        handoff_complete=False,
        decision_authority=False,
        execution_authority=False,
    )


def _supersede_interrupted_prior_release_request(
    *,
    existing,
    requester: str,
    release: str,
    values: MutableMapping[str, str],
) -> None:
    """Close prior-release claimed work only after proving its owner lease is gone.

    The diagnostic runner already uses this owner lease as the durable/liveness boundary
    when recovering an interrupted request. Reusing the same rule here prevents a dead
    prior deployment from permanently occupying the single coordination slot while still
    preserving any genuinely live owner. The stale request is closed fail-closed; it is
    never reclassified as successful and cannot contribute decision or execution authority.
    """

    if _active_owner_exists(existing.request_id, values):
        raise RuntimeError("live prior-release diagnostic owner cannot be superseded")

    finished = finish_manual_cio_diagnostic(
        existing,
        succeeded=False,
        cycle_key=existing.cycle_key,
        snapshot_identifier=existing.snapshot_identifier,
        detail=(
            "In-progress diagnostic belonged to a prior release and no live owner lease "
            "remained; the interrupted request was closed fail-closed so exact-release "
            "post-prequalification coordination could proceed."
        ),
        values=values,
    )
    _log(
        "release_diagnostic_primer_stale_in_progress_superseded",
        release=release,
        requested_by=requester,
        stale_request_id=finished.request_id,
        stale_requested_by=finished.requested_by,
        stale_state=finished.state,
        live_owner_observed=False,
        handoff_complete=False,
        decision_authority=False,
        execution_authority=False,
    )


def prime_release_diagnostic_request(
    values: MutableMapping[str, str] | None = None,
) -> int:
    resolved = os.environ if values is None else values
    if not _boolean(
        resolved.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE"),
        default=False,
    ):
        _log("release_diagnostic_primer_disabled")
        return 0

    release = _release(resolved)
    requester = f"render-release:{release}"
    existing = latest_manual_cio_diagnostic(values=resolved)

    # A current-release in-progress request is already a valid handoff. For a prior
    # release, preserve it only while its exact process owner is still alive. An orphaned
    # prior-release claim otherwise blocks current-release activation forever because the
    # single-slot request store refuses a new pending request.
    if existing is not None and existing.state == "in_progress":
        if existing.requested_by == requester:
            _log(
                "release_diagnostic_primer_active_request_preserved",
                release=release,
                request_id=existing.request_id,
                requested_by=existing.requested_by,
                state=existing.state,
                exact_release=True,
                live_owner_required=False,
            )
            return 0
        if _active_owner_exists(existing.request_id, resolved):
            _log(
                "release_diagnostic_primer_prior_release_live_owner_preserved",
                release=release,
                request_id=existing.request_id,
                requested_by=existing.requested_by,
                state=existing.state,
                exact_release=False,
                live_owner_observed=True,
                handoff_complete=False,
            )
            return 0
        _supersede_interrupted_prior_release_request(
            existing=existing,
            requester=requester,
            release=release,
            values=resolved,
        )
        existing = latest_manual_cio_diagnostic(values=resolved)

    if (
        existing is not None
        and existing.state == "pending"
        and existing.requested_by == requester
    ):
        _log(
            "release_diagnostic_primer_current_pending_preserved",
            release=release,
            request_id=existing.request_id,
            requested_by=existing.requested_by,
            state=existing.state,
        )
        return 0

    # A prior release can leave an unclaimed pending coordination record on persistent
    # storage. Preserving that record forever blocks request_manual_cio_diagnostic(), so a
    # completed exact-release evidence qualification can remain publicly "prequalifying"
    # even though all six stages are done. Close only that unclaimed stale record
    # fail-closed, then create the current release's request below.
    if (
        existing is not None
        and existing.state == "pending"
        and existing.requested_by != requester
    ):
        _supersede_stale_pending_request(
            existing=existing,
            requester=requester,
            release=release,
            values=resolved,
        )
        existing = latest_manual_cio_diagnostic(values=resolved)

    # A restart of the same exact release must not manufacture a second terminal record.
    if (
        existing is not None
        and existing.requested_by == requester
        and existing.state in {"completed", "failed"}
    ):
        _log(
            "release_diagnostic_primer_exact_release_already_terminal",
            release=release,
            request_id=existing.request_id,
            state=existing.state,
        )
        return 0

    request, created = request_manual_cio_diagnostic(
        requested_by=requester,
        values=resolved,
    )
    if not created and request.requested_by != requester:
        _log(
            "release_diagnostic_primer_handoff_failed",
            release=release,
            request_id=request.request_id,
            requested_by=request.requested_by,
            state=request.state,
            expected_requested_by=requester,
            handoff_complete=False,
            decision_authority=False,
            execution_authority=False,
        )
        raise RuntimeError("current release diagnostic coordination was not established")

    _log(
        "release_diagnostic_primer_created"
        if created
        else "release_diagnostic_primer_not_created",
        release=release,
        request_id=request.request_id,
        requested_by=request.requested_by,
        state=request.state,
        handoff_complete=request.requested_by == requester and request.state == "pending",
        decision_authority=False,
        execution_authority=False,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("prime_release_cio_diagnostic.py accepts no arguments")
    try:
        return prime_release_diagnostic_request()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        _log(
            "release_diagnostic_primer_failed",
            error_type=type(error).__name__,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
