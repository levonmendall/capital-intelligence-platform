"""Retry-aware entrypoint for exact-release Render CIO verification.

The verifier core remains unchanged. This shim treats a terminal failure from an adopted
server-side attempt as provisional because the Render release bootstrap can issue a
bounded replacement attempt for the same exact release. A diagnostic that is already
failed when polling begins keeps the caller's normal stale-failure grace. All verifier
paths remain fail-closed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import verify_render_cio_diagnostic_core as _core


_original_poll_render_audit = _core.poll_render_audit
_SERVER_REPLACEMENT_GRACE_ATTEMPTS = 45
_MAX_ADOPTED_FAILURES = 4


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
    adopted_failures = 0
    awaiting_replacement = False
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
                maximum_attempts=maximum_attempts,
                interval_seconds=interval_seconds,
                fresh_attempt_grace_attempts=active_grace_attempts,
                fetcher=fetcher,
                sleeper=sleeper,
                clock=clock,
                progress_writer=progress_writer,
            )
        except _core.RenderAuditVerificationError as error:
            detail = str(error)
            if not detail.startswith("current_diagnostic_failed:"):
                raise
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
            # Re-enter the core verifier. The failed adopted request is now the baseline,
            # so the extended grace applies only while waiting for its replacement. If no
            # new request_id appears, the core still terminates fail-closed.


_core.poll_render_audit = _retry_aware_poll_render_audit


if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve historical imports and test monkeypatch behavior while exposing the patched
# poller through the canonical module name.
sys.modules[__name__] = _core
