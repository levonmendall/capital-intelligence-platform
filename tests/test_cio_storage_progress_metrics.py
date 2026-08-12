from __future__ import annotations

from datetime import datetime, timezone

import operations.manual_cio_diagnostic as manual_diagnostic
from operations.bounded_terminal_screening import _storage_metrics
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


NOW = datetime(2026, 8, 12, 21, 52, tzinfo=timezone.utc)
_STORAGE_METRIC_NAMES = {
    "publication_bytes",
    "publication_index_bytes",
    "screening_spool_bytes",
    "chunk_file_bytes",
    "storage_reserve_bytes",
    "storage_total_bytes",
    "storage_used_bytes",
    "storage_free_bytes",
}


def test_real_storage_metrics_are_accepted_by_manual_progress_contract(
    tmp_path, monkeypatch
) -> None:
    publication_path = tmp_path / "provider-preselection.json"
    publication_index_path = tmp_path / "signals.sqlite3"
    screening_spool_path = tmp_path / "screening.sqlite3"
    chunk_path = tmp_path / "provider-preselection-chunk.json"
    publication_path.write_bytes(b"publication")
    publication_index_path.write_bytes(b"index")
    screening_spool_path.write_bytes(b"screening")
    chunk_path.write_bytes(b"chunk")

    storage_metrics = _storage_metrics(
        publication_path=publication_path,
        publication_index_path=publication_index_path,
        screening_spool_path=screening_spool_path,
        chunk_path=chunk_path,
    )
    assert set(storage_metrics) == _STORAGE_METRIC_NAMES

    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "diagnostic"),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:storage-telemetry", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    monkeypatch.setattr(
        manual_diagnostic,
        "_terminal_screening_resource_metrics",
        lambda _values: {},
    )
    updated = record_manual_cio_diagnostic_progress(
        "terminal_screening_chunk:international_equity",
        metrics=storage_metrics,
        values=values,
    )

    assert updated is not None
    persisted = dict(updated.progress_metrics)
    assert {name: persisted[name] for name in _STORAGE_METRIC_NAMES} == storage_metrics
