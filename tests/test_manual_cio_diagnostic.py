from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


NOW = datetime(2026, 8, 4, 21, 36, tzinfo=timezone.utc)


def _values(tmp_path):
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }


def test_request_claim_and_finish_are_durable(tmp_path) -> None:
    values = _values(tmp_path)
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:abc123",
        now=NOW,
        values=values,
    )

    assert created is True
    assert request.state == "pending"
    assert request.trigger_key.startswith("manual-diagnostic-")
    assert request.to_dict()["real_money_authorized"] is False

    duplicate, duplicate_created = request_manual_cio_diagnostic(
        requested_by="another-admin",
        now=NOW + timedelta(seconds=1),
        values=values,
    )
    assert duplicate_created is False
    assert duplicate.request_id == request.request_id

    claimed = claim_manual_cio_diagnostic(
        now=NOW + timedelta(seconds=2),
        values=values,
    )
    assert claimed is not None
    assert claimed.state == "in_progress"
    assert claimed.started_at == NOW + timedelta(seconds=2)
    assert claim_manual_cio_diagnostic(values=values) is None

    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key="canonical-cio:America/Los_Angeles:2026-08-04:event:test",
        snapshot_identifier=None,
        detail="provider failed closed",
        now=NOW + timedelta(seconds=3),
        values=values,
    )
    assert finished.state == "failed"
    assert finished.completed_at == NOW + timedelta(seconds=3)

    reloaded = latest_manual_cio_diagnostic(values=values)
    assert reloaded == finished


def test_final_request_allows_a_new_diagnostic(tmp_path) -> None:
    values = _values(tmp_path)
    first, _ = request_manual_cio_diagnostic(
        requested_by="render-release:first",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None
    finish_manual_cio_diagnostic(
        claimed,
        succeeded=True,
        cycle_key="cycle-one",
        snapshot_identifier="briefing-one",
        detail="completed",
        now=NOW,
        values=values,
    )

    second, created = request_manual_cio_diagnostic(
        requested_by="render-release:second",
        now=NOW + timedelta(minutes=1),
        values=values,
    )
    assert created is True
    assert second.request_id != first.request_id
    assert second.state == "pending"


def test_progress_is_release_scoped_and_credential_safe(tmp_path) -> None:
    values = _values(tmp_path)
    request_manual_cio_diagnostic(
        requested_by="render-release:progress",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    assert (
        record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directories",
            metrics={"configured_exchanges": 19},
            values=values,
        )
        is None
    )
    assert latest_manual_cio_diagnostic(values=values) == claimed

    enabled = {
        **values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    updated = record_manual_cio_diagnostic_progress(
        "deep_market_evidence:international_equity",
        metrics={"decision_eligible_records": 417, "catalog_records": 1200},
        values=enabled,
    )

    assert updated is not None
    assert updated.detail == (
        "governed_progress=deep_market_evidence:international_equity; "
        "catalog_records=1200; decision_eligible_records=417"
    )
    assert updated.to_dict()["paper_only"] is True
    assert updated.to_dict()["real_money_authorized"] is False
    assert "symbol" not in updated.detail
    assert "provider" not in updated.detail

    with pytest.raises(ValueError, match="stage is invalid"):
        record_manual_cio_diagnostic_progress(
            "provider key leaked",
            values=enabled,
        )
    with pytest.raises(ValueError, match="stage is invalid"):
        record_manual_cio_diagnostic_progress(
            "deep_market_evidence:secret",
            values=enabled,
        )
    with pytest.raises(ValueError, match="metric name is invalid"):
        record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directories",
            metrics={"api_key": 1},
            values=enabled,
        )
    with pytest.raises(ValueError, match="nonnegative integers"):
        record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directories",
            metrics={"catalog_records": True},
            values=enabled,
        )
