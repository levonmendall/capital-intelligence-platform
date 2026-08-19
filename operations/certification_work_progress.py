"""Credential-safe work progress reporting for paper-only certification lanes.

This module has no market, evidence, ranking, sizing, CIO, construction, execution, or
real-money authority. It reports nonnegative work counters only through the progress-aware
spawn worker's child-to-parent transport and durable node sidecar.
"""

from __future__ import annotations

from operations import manual_cio_diagnostic as diagnostic


_TRANSPORT_ONLY_VALUES = {
    # The progress-aware child worker wraps ``record_manual_cio_diagnostic_progress`` and
    # forwards every call to its parent pipe after invoking the original recorder. Passing
    # an explicitly disabled recorder mapping makes that original call a no-op, so multiple
    # spawned lanes never contend for the shared manual-diagnostic file. The wrapper still
    # emits the credential-safe stage/metrics to the parent and node sidecar.
    "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "false",
}


def record_certification_work_progress(
    asset_class: str,
    *,
    processed_records: int,
    total_records: int,
    chunk_records: int = 1,
) -> None:
    """Publish completed-work counters without child ownership of diagnostic state."""

    lane = str(asset_class).strip().lower()
    metrics = {
        "processed_records": max(0, int(processed_records)),
        "total_records": max(0, int(total_records)),
        "chunk_records": max(0, int(chunk_records)),
    }
    try:
        diagnostic.record_manual_cio_diagnostic_progress(
            f"deep_market_evidence:{lane}",
            metrics=metrics,
            values=_TRANSPORT_ONLY_VALUES,
        )
    except (OSError, TypeError, ValueError):
        # Observability cannot authorize or invalidate evidence. If the child transport is
        # unavailable, the unchanged fail-closed stall supervisor remains authoritative.
        return


__all__ = ["record_certification_work_progress"]
