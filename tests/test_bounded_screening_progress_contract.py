from datetime import datetime, timezone

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


def test_bounded_terminal_screening_chunk_progress_is_accepted_and_persisted(tmp_path):
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH": str(
            tmp_path / "manual-cio-diagnostic.json"
        ),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "1",
    }
    now = datetime(2026, 8, 11, 3, 15, tzinfo=timezone.utc)

    request, created = request_manual_cio_diagnostic(
        requested_by="release-certification",
        now=now,
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(now=now, values=values)
    assert claimed is not None
    assert claimed.request_id == request.request_id

    updated = record_manual_cio_diagnostic_progress(
        "terminal_screening_chunk:international_equity",
        metrics={
            "processed_records": 512,
            "total_records": 45_243,
            "chunk_records": 512,
        },
        values=values,
    )

    assert updated is not None
    assert updated.detail == (
        "governed_progress=terminal_screening_chunk:international_equity; "
        "chunk_records=512; processed_records=512; total_records=45243"
    )
    persisted = latest_manual_cio_diagnostic(values=values)
    assert persisted is not None
    assert persisted.detail == updated.detail
