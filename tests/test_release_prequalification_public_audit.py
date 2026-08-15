from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import publish_cio_diagnostic_audit as audit


def test_prequalification_is_visible_without_manufacturing_cio_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(timezone.utc)
    values = {"CAPITAL_INTELLIGENCE_RELEASE": "release-123"}
    canonical = {
        "request_id": "old-cio",
        "requested_at": (started - timedelta(minutes=5)).isoformat(),
        "active_release": "release-old",
        "release_matches": False,
        "state": "pending",
    }
    monkeypatch.setattr(
        audit,
        "load_release_evidence_prequalification",
        lambda _values: {
            "prequalification_id": "prequal-1",
            "release": "release-123",
            "state": "in_progress",
            "stage": "evidence_prequalifying",
            "started_at": started.isoformat(),
            "updated_at": started.isoformat(),
            "completed_at": None,
            "detail": "validating components",
            "metrics": {"components_current": 12},
            "generation_id": "",
        },
    )
    monkeypatch.setattr(
        audit,
        "load_reference_readiness_progress",
        lambda _values: {
            "stage": "reference_futures_contracts",
            "updated_at": (started + timedelta(seconds=1)).isoformat(),
            "progress_metrics": {"configured_futures_roots": 13, "reused": 1},
        },
    )

    published = audit._with_release_prequalification(canonical, values=values)

    assert published["request_id"] == "prequal-1"
    assert published["request_kind"] == "evidence_prequalification"
    assert published["state"] == "prequalifying"
    assert published["stage"] == "evidence_prequalifying"
    assert published["prequalification_component_stage"] == "reference_futures_contracts"
    assert published["prequalification_component_metrics"]["reused"] == 1
    assert published["all_market_evaluation_complete"] is False
    assert published["paper_only"] is True
    assert published["real_money_authorized"] is False


def test_newer_cio_request_supersedes_prequalification_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(timezone.utc)
    values = {"CAPITAL_INTELLIGENCE_RELEASE": "release-123"}
    canonical = {
        "request_id": "cio-new",
        "requested_at": (started + timedelta(seconds=5)).isoformat(),
        "active_release": "release-123",
        "release_matches": True,
        "state": "pending",
        "stage": "reference_manifest_ready",
    }
    monkeypatch.setattr(
        audit,
        "load_release_evidence_prequalification",
        lambda _values: {
            "prequalification_id": "prequal-1",
            "release": "release-123",
            "state": "completed",
            "stage": "evidence_generation_ready",
            "started_at": started.isoformat(),
            "updated_at": started.isoformat(),
            "completed_at": started.isoformat(),
            "detail": "ready",
            "metrics": {},
            "generation_id": "generation-1",
        },
    )

    assert audit._with_release_prequalification(canonical, values=values) == canonical
