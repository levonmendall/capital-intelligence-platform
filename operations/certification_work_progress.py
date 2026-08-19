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
    evidence_complete_records: int | None = None,
) -> None:
    """Publish completed-work counters without child ownership of diagnostic state."""

    lane = str(asset_class).strip().lower()
    metrics = {
        "processed_records": max(0, int(processed_records)),
        "total_records": max(0, int(total_records)),
        "chunk_records": max(0, int(chunk_records)),
    }
    if evidence_complete_records is not None:
        metrics["evidence_complete_records"] = max(0, int(evidence_complete_records))
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


def install_spawn_child_transport_only_progress() -> None:
    """Prevent spawned fallback progress from becoming a second diagnostic file writer."""

    from operations import redundant_market_probe as probe

    current = probe._record_deep_progress
    if getattr(current, "_spawn_child_transport_only", False):
        return
    last_processed: dict[str, int] = {}

    def transport_only(
        lane: str | None,
        *,
        decision_eligible_records: int,
        processed_records: int,
        evidence_complete_records: int,
        callback,
    ) -> None:
        del callback
        if lane is None:
            return
        normalized_lane = str(lane).strip().lower()
        prior = last_processed.get(normalized_lane, 0)
        current_processed = max(0, int(processed_records))
        delta = max(1, current_processed - prior)
        last_processed[normalized_lane] = max(prior, current_processed)
        record_certification_work_progress(
            normalized_lane,
            processed_records=current_processed,
            total_records=max(0, int(decision_eligible_records)),
            chunk_records=delta,
            evidence_complete_records=max(0, int(evidence_complete_records)),
        )

    transport_only._spawn_child_transport_only = True  # type: ignore[attr-defined]
    probe._record_deep_progress = transport_only


__all__ = [
    "install_spawn_child_transport_only_progress",
    "record_certification_work_progress",
]
