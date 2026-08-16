from __future__ import annotations

from datetime import datetime, timezone

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


NOW = datetime(2026, 8, 16, 20, 58, tzinfo=timezone.utc)


def test_qualified_evidence_consumption_progress_stage_is_registered(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:qualified-evidence-progress",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    updated = record_manual_cio_diagnostic_progress(
        "qualified_evidence_consumption",
        values=values,
    )

    assert updated is not None
    assert updated.progress_stage == "qualified_evidence_consumption"
    assert updated.detail == "governed_progress=qualified_evidence_consumption"
    assert updated.to_dict()["paper_only"] is True
    assert updated.to_dict()["real_money_authorized"] is False
