from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import operations.manual_cio_diagnostic as manual_diagnostic
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)


NOW = datetime(2026, 8, 4, 21, 36, tzinfo=timezone.utc)


def _values(tmp_path):
    return {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}


def test_request_claim_and_finish_are_durable(tmp_path) -> None:
    values = _values(tmp_path)
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:abc123", now=NOW, values=values
    )
    assert created is True
    assert request.state == "pending"
    assert request.trigger_key.startswith("manual-diagnostic-")
    assert request.to_dict()["real_money_authorized"] is False

    duplicate, duplicate_created = request_manual_cio_diagnostic(
        requested_by="another-admin", now=NOW + timedelta(seconds=1), values=values
    )
    assert duplicate_created is False
    assert duplicate.request_id == request.request_id

    claimed = claim_manual_cio_diagnostic(now=NOW + timedelta(seconds=2), values=values)
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
    assert latest_manual_cio_diagnostic(values=values) == finished


def test_final_request_allows_a_new_diagnostic(tmp_path) -> None:
    values = _values(tmp_path)
    first, _ = request_manual_cio_diagnostic(
        requested_by="render-release:first", now=NOW, values=values
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
        requested_by="render-release:second", now=NOW + timedelta(minutes=1), values=values
    )
    assert created is True
    assert second.request_id != first.request_id
    assert second.state == "pending"


def test_progress_is_release_scoped_and_credential_safe(tmp_path) -> None:
    values = _values(tmp_path)
    request_manual_cio_diagnostic(
        requested_by="render-release:progress", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None
    assert record_manual_cio_diagnostic_progress(
        "catalog_eodhd_directories", metrics={"configured_exchanges": 19}, values=values
    ) is None
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
    assert updated.progress_stage == "deep_market_evidence:international_equity"
    assert dict(updated.progress_metrics) == {
        "catalog_records": 1200,
        "decision_eligible_records": 417,
    }
    assert updated.progress_recorded_at is not None
    assert updated.to_dict()["paper_only"] is True
    assert updated.to_dict()["real_money_authorized"] is False
    assert "symbol" not in updated.detail
    assert "provider" not in updated.detail

    with pytest.raises(ValueError, match="stage is invalid"):
        record_manual_cio_diagnostic_progress("provider key leaked", values=enabled)
    with pytest.raises(ValueError, match="stage is invalid"):
        record_manual_cio_diagnostic_progress("deep_market_evidence:secret", values=enabled)
    with pytest.raises(ValueError, match="metric name is invalid"):
        record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directories", metrics={"api_key": 1}, values=enabled
        )
    with pytest.raises(ValueError, match="nonnegative integers"):
        record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directories", metrics={"catalog_records": True}, values=enabled
        )


def test_terminal_screening_metrics_survive_terminal_finalization(tmp_path, monkeypatch) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    recorded_at = NOW + timedelta(minutes=7)
    monkeypatch.setattr(manual_diagnostic, "_utc_now", lambda: recorded_at)
    monkeypatch.setattr(
        manual_diagnostic,
        "_terminal_screening_resource_metrics",
        lambda _values: {
            "rss_kib": 321000,
            "hwm_kib": 330000,
            "container_current_kib": 1400000,
            "container_limit_kib": 2097152,
            "memory_reserve_kib": 655360,
            "governed_boundary_kib": 1441792,
            "governed_headroom_kib": 41792,
        },
    )
    request_manual_cio_diagnostic(
        requested_by="render-release:screening", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    progressed = record_manual_cio_diagnostic_progress(
        "terminal_screening_chunk:international_equity",
        metrics={
            "processed_records": 20480,
            "total_records": 45286,
            "chunk_records": 512,
        },
        values=values,
    )
    assert progressed is not None
    assert progressed.progress_stage == "terminal_screening_chunk:international_equity"
    assert progressed.progress_recorded_at == recorded_at
    assert dict(progressed.progress_metrics) == {
        "chunk_records": 512,
        "container_current_kib": 1400000,
        "container_limit_kib": 2097152,
        "governed_boundary_kib": 1441792,
        "governed_headroom_kib": 41792,
        "hwm_kib": 330000,
        "memory_reserve_kib": 655360,
        "processed_records": 20480,
        "rss_kib": 321000,
        "total_records": 45286,
    }

    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key=None,
        snapshot_identifier=None,
        detail="Resource Governor memory pressure",
        now=NOW + timedelta(minutes=8),
        values=values,
    )
    reloaded = latest_manual_cio_diagnostic(values=values)
    assert reloaded == finished
    assert reloaded is not None
    assert reloaded.detail == "Resource Governor memory pressure"
    assert reloaded.progress_stage == "terminal_screening_chunk:international_equity"
    assert reloaded.progress_recorded_at == recorded_at
    assert dict(reloaded.progress_metrics)["processed_records"] == 20480
    assert dict(reloaded.progress_metrics)["governed_headroom_kib"] == 41792


def test_context_cycle_and_last_stage_survive_watchdog_style_finalization(tmp_path) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:lineage", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps({"cycle_key": "daily-cio:2026-08-04:context"}), encoding="utf-8"
    )
    progressed = record_manual_cio_diagnostic_progress(
        "six_specialist_committee_cio_cycle", values=values
    )
    assert progressed is not None
    assert progressed.cycle_key == "daily-cio:2026-08-04:context"
    assert progressed.progress_stage == "six_specialist_committee_cio_cycle"

    # The watchdog holds the original claimed object. Finalization must reload the latest
    # durable state rather than erasing the cycle and stage with that stale object.
    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key=None,
        snapshot_identifier=None,
        detail="bounded child terminated fail-closed",
        now=NOW + timedelta(minutes=20),
        values=values,
    )
    assert finished.state == "failed"
    assert finished.cycle_key == "daily-cio:2026-08-04:context"
    assert finished.progress_stage == "six_specialist_committee_cio_cycle"
    assert latest_manual_cio_diagnostic(values=values) == finished


def test_finalization_rejects_context_cycle_rebinding(tmp_path) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:lineage", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None
    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps({"cycle_key": "context:one"}), encoding="utf-8"
    )
    record_manual_cio_diagnostic_progress(
        "six_specialist_committee_cio_cycle", values=values
    )
    with pytest.raises(ValueError, match="cannot be rebound"):
        finish_manual_cio_diagnostic(
            claimed,
            succeeded=False,
            cycle_key="context:two",
            snapshot_identifier=None,
            detail="failed",
            values=values,
        )

def test_resumable_option_progress_stages_are_registered(tmp_path) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    request_manual_cio_diagnostic(
        requested_by="render-release:resumable-options", now=NOW, values=values
    )
    claimed = claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    stages = (
        ("catalog_options_partitioned", {"configured_underlyings": 1}),
        (
            "catalog_options_expiration_partition",
            {"processed_records": 1, "total_records": 3},
        ),
        (
            "catalog_options_partitioned_complete",
            {"configured_underlyings": 1, "catalog_records": 2},
        ),
    )
    for stage, metrics in stages:
        updated = record_manual_cio_diagnostic_progress(
            stage, metrics=metrics, values=values
        )
        assert updated is not None
        assert updated.progress_stage == stage
        assert dict(updated.progress_metrics) == metrics
