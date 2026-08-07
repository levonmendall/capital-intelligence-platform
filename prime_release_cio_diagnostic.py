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
from typing import Mapping, MutableMapping, Sequence

from operations.manual_cio_diagnostic import (
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)


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

    # Never overwrite an active request. The governed diagnostic runner owns recovery of
    # interrupted in-progress state and will replace it truthfully if that process died.
    if existing is not None and existing.state in {"pending", "in_progress"}:
        _log(
            "release_diagnostic_primer_active_request_preserved",
            release=release,
            request_id=existing.request_id,
            requested_by=existing.requested_by,
            state=existing.state,
        )
        return 0

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
    _log(
        "release_diagnostic_primer_created" if created else "release_diagnostic_primer_not_created",
        release=release,
        request_id=request.request_id,
        requested_by=request.requested_by,
        state=request.state,
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
