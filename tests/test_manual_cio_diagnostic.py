from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
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
