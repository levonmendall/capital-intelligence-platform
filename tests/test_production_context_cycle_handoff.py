from __future__ import annotations

import json
from datetime import datetime, timezone

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


NOW = datetime(2026, 8, 22, 19, 0, tzinfo=timezone.utc)


def test_portfolio_mark_adopts_published_production_context_cycle(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:cycle-handoff",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None
    assert claimed.cycle_key is None

    published_cycle = "canonical-cio:America/Los_Angeles:2026-08-22:event:context"
    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps({"cycle_key": published_cycle}),
        encoding="utf-8",
    )

    finalized = record_manual_cio_diagnostic_progress(
        "production_context_portfolio_finalized",
        values=values,
    )
    assert finalized is not None
    assert finalized.cycle_key is None

    marked = record_manual_cio_diagnostic_progress(
        "production_context_portfolio_marked",
        values=values,
    )
    assert marked is not None
    assert marked.progress_stage == "production_context_portfolio_marked"
    assert marked.cycle_key == published_cycle


def test_portfolio_mark_does_not_adopt_refresh_required_context(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:cycle-handoff",
        now=NOW,
        values=values,
    )
    assert claim_manual_cio_diagnostic(now=NOW, values=values) is not None
    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps({"cycle_key": "refresh-required:stale-context"}),
        encoding="utf-8",
    )

    marked = record_manual_cio_diagnostic_progress(
        "production_context_portfolio_marked",
        values=values,
    )
    assert marked is not None
    assert marked.cycle_key is None
