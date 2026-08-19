"""Credential-safe work progress reporting for paper-only certification lanes.

This module has no market, evidence, ranking, sizing, CIO, construction, execution, or
real-money authority. It only reports nonnegative work counters through the existing
manual diagnostic progress channel.
"""

from __future__ import annotations

from operations import manual_cio_diagnostic as diagnostic


def record_certification_work_progress(
    asset_class: str,
    *,
    processed_records: int,
    total_records: int,
    chunk_records: int = 1,
) -> None:
    """Publish credential-safe completed-work counters for one discovery lane."""

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
        )
    except (OSError, TypeError, ValueError):
        # Observability cannot authorize or invalidate evidence. The existing
        # fail-closed stall supervisor remains authoritative if progress cannot publish.
        return


__all__ = ["record_certification_work_progress"]
