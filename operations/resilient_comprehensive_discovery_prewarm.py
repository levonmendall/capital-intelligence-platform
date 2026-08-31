"""Retry failed comprehensive provider prerequisites inside the existing early window.

The canonical transactional lane is deliberately reuse-only: it may consume an exact-epoch
provider publication produced by the early acquisition owner but may not start a second late
network fallback.  A single transient early provider-child failure therefore used to leave a
valid structural cache with no reusable publication, making the later lane fail immediately.

This wrapper gives the existing early owner a bounded retry opportunity without changing its
resource contract.  All passes share the *original* fanout budget calculated at sidecar
start; each later pass is capped to the remaining portion of that same budget.  Existing
clean publications are reused, so retry passes spend provider time only on prerequisites that
remain absent.  The six-worker cap, 300-second acceleration ceiling, downstream reserve,
evidence freshness, market scope, screening, CIO authority, construction, paper-only
execution, and real-money prohibition remain unchanged.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Mapping, Sequence

from operations import comprehensive_discovery_structural_prewarm as _base
from operations import epoch_scoped_provider_acquisition as _acquisition


_MODULE = "operations.resilient_comprehensive_discovery_prewarm"
_MAX_PROVIDER_PASSES = 3
_INSTALLED_ATTR = "_resilient_comprehensive_provider_prewarm_installed"


def _needs_retry(report: Mapping[str, object]) -> bool:
    return int(report.get("failed", 0) or 0) > 0 or int(
        report.get("provider_skipped_budget", 0) or 0
    ) > 0


def _run_resilient_fanout(
    request_path,
    *,
    values: Mapping[str, str],
    decision_epoch: datetime,
    original,
) -> Mapping[str, object]:
    """Run up to three passes while sharing one immutable initial acquisition budget."""

    initial_budget = float(_acquisition._fanout_budget_seconds(decision_epoch, values))
    if initial_budget <= 0.0:
        return original(
            request_path,
            values=values,
            decision_epoch=decision_epoch,
        )

    started = time.monotonic()
    reports: list[Mapping[str, object]] = []
    original_budget = _acquisition._fanout_budget_seconds

    for _pass in range(1, _MAX_PROVIDER_PASSES + 1):
        remaining = max(0.0, initial_budget - (time.monotonic() - started))
        if remaining <= 0.0:
            break

        def remaining_budget(epoch, resolved, *, now=None, _remaining=remaining):
            canonical = float(original_budget(epoch, resolved, now=now))
            return max(0.0, min(_remaining, canonical))

        _acquisition._fanout_budget_seconds = remaining_budget
        try:
            report = original(
                request_path,
                values=values,
                decision_epoch=decision_epoch,
            )
        finally:
            _acquisition._fanout_budget_seconds = original_budget
        reports.append(dict(report))
        if not _needs_retry(report):
            break

    if not reports:
        return original(
            request_path,
            values=values,
            decision_epoch=decision_epoch,
        )

    result = dict(reports[-1])
    result.update(
        {
            "provider_retry_passes": len(reports),
            "provider_retry_performed": len(reports) > 1,
            "provider_retry_initial_budget_seconds": round(initial_budget, 3),
            "provider_retry_elapsed_seconds": round(
                max(0.0, time.monotonic() - started), 3
            ),
            "provider_retry_budget_extended": False,
            "provider_worker_limit_extended": False,
            "advisory_only": True,
            "evidence_certified": False,
            "decision_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    return result


def prewarm_epoch_provider_inputs(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    """Run the canonical prewarm with resilient provider retries inside its original budget."""

    original = _acquisition.run_provider_acquisition_fanout

    def resilient(request_path, *, values, decision_epoch, **_kwargs):
        return _run_resilient_fanout(
            request_path,
            values=values,
            decision_epoch=decision_epoch,
            original=original,
        )

    _acquisition.run_provider_acquisition_fanout = resilient
    try:
        return _base.prewarm_epoch_provider_inputs(
            evidence_as_of=evidence_as_of,
            values=values,
        )
    finally:
        _acquisition.run_provider_acquisition_fanout = original


def install() -> None:
    """Route future Render prewarm sidecars through this bounded retry wrapper."""

    if getattr(_base, _INSTALLED_ATTR, False):
        return
    _base._MODULE = _MODULE
    setattr(_base, _INSTALLED_ATTR, True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    try:
        timestamp = datetime.fromisoformat(str(args.as_of).replace("Z", "+00:00"))
        prewarm_epoch_provider_inputs(evidence_as_of=timestamp)
    except (OSError, RuntimeError, TypeError, ValueError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "_MAX_PROVIDER_PASSES",
    "_needs_retry",
    "_run_resilient_fanout",
    "install",
    "prewarm_epoch_provider_inputs",
]
