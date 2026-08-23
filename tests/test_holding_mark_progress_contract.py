from __future__ import annotations

from operations import manual_cio_diagnostic as diagnostic


def test_bounded_runtime_registers_holding_mark_progress_stages() -> None:
    # Importing the bounded production wrapper installs its telemetry contract before any
    # production-context preparation can emit progress. The import intentionally preserves
    # the historical core-module surface after installing these runtime-only extensions.
    import run_bounded_manual_cio_diagnostic  # noqa: F401

    assert "production_context_holding_marks_started" in diagnostic._PROGRESS_STAGES
    assert "production_context_holding_marks_failed" in diagnostic._PROGRESS_STAGES
