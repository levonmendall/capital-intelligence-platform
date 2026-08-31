from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import operations.production_state_envelope as state


_RELEASE = "release-current"
_EPOCH = "2026-08-31T03:31:00+00:00"
_NOW = datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc)


def _current() -> dict[str, object]:
    return {
        "schema_version": "current-asset-class-evaluation-status.v1",
        "successful": 1,
        "attempted": 13,
        "total": 13,
        "reached": 13,
        "as_of": _EPOCH,
        "source": "Current all-market evaluation",
        "rows": [],
        "release_sha": _RELEASE,
        "decision_epoch": _EPOCH,
        "exact_release": True,
        "historical": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _previous() -> dict[str, object]:
    return {
        "source": "Latest completed global evaluation",
        "as_of": "2026-08-30T20:00:00+00:00",
        "historical": True,
        "rows": [],
    }


def _diagnostic(requested_by: str = f"render-release:{_RELEASE}") -> SimpleNamespace:
    return SimpleNamespace(
        state="in_progress",
        requested_by=requested_by,
        request_id="diag-1",
        cycle_key="cycle-1",
        started_at=datetime(2026, 8, 31, 3, 30, tzinfo=timezone.utc),
        completed_at=None,
        progress_stage="production_context_screening_graph_released",
        progress_recorded_at=datetime(2026, 8, 31, 3, 59, tzinfo=timezone.utc),
        detail="screening graph active",
    )


def test_envelope_aligns_diagnostic_lane_state_and_certification_on_one_release(monkeypatch):
    monkeypatch.setattr(state, "load_current_asset_class_evaluation_status", lambda **_kwargs: _current())
    monkeypatch.setattr(state, "load_latest_completed_asset_class_evaluation", lambda **_kwargs: _previous())
    monkeypatch.setattr(
        state,
        "load_public_lane_telemetry",
        lambda _values: {
            "release": _RELEASE,
            "decision_epoch": _EPOCH,
            "lanes": [],
        },
    )
    monkeypatch.setattr(
        state,
        "load_all_market_certification_envelope",
        lambda **_kwargs: {
            "release_sha": _RELEASE,
            "certified": False,
            "coverage": {"represented_count": 1, "required_count": 13},
            "paper_only": True,
            "real_money_authorized": False,
        },
    )
    monkeypatch.setattr(state, "latest_manual_cio_diagnostic", lambda **_kwargs: _diagnostic())

    envelope = state.load_production_state_envelope(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE},
        now=_NOW,
    )

    assert envelope["schema_version"] == "production-state-envelope.v1"
    assert envelope["release_sha"] == _RELEASE
    assert envelope["decision_epoch"] == _EPOCH
    assert envelope["production"]["state"] == "in_progress"
    assert envelope["production"]["stage"] == "production_context_screening_graph_released"
    assert envelope["previous_completed_asset_class_evaluation"]["historical"] is True
    assert envelope["alignment"]["asset_release_matches"] is True
    assert envelope["alignment"]["diagnostic_release_matches"] is True
    assert envelope["alignment"]["telemetry_release_matches"] is True
    assert envelope["alignment"]["certification_release_matches"] is True
    assert envelope["alignment"]["asset_telemetry_decision_epoch_matches"] is True
    assert envelope["alignment"]["current_asset_state_coherent"] is True
    assert envelope["paper_only"] is True
    assert envelope["real_money_authorized"] is False
    assert envelope["decision_authority"] is False
    assert envelope["execution_authority"] is False


def test_stale_diagnostic_is_never_presented_as_current_release(monkeypatch):
    monkeypatch.setattr(state, "load_current_asset_class_evaluation_status", lambda **_kwargs: _current())
    monkeypatch.setattr(state, "load_latest_completed_asset_class_evaluation", lambda **_kwargs: None)
    monkeypatch.setattr(state, "load_public_lane_telemetry", lambda _values: None)
    monkeypatch.setattr(
        state,
        "load_all_market_certification_envelope",
        lambda **_kwargs: {"release_sha": _RELEASE, "certified": False},
    )
    monkeypatch.setattr(
        state,
        "latest_manual_cio_diagnostic",
        lambda **_kwargs: _diagnostic("render-release:old-release"),
    )

    envelope = state.load_production_state_envelope(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE},
        now=_NOW,
    )

    assert envelope["production"]["state"] == "stale_release"
    assert envelope["production"]["stage"] is None
    assert envelope["production"]["release_matches"] is False
    assert envelope["alignment"]["diagnostic_release_matches"] is False


def test_cross_epoch_lane_telemetry_is_reported_incoherent(monkeypatch):
    monkeypatch.setattr(state, "load_current_asset_class_evaluation_status", lambda **_kwargs: _current())
    monkeypatch.setattr(state, "load_latest_completed_asset_class_evaluation", lambda **_kwargs: None)
    monkeypatch.setattr(
        state,
        "load_public_lane_telemetry",
        lambda _values: {
            "release": _RELEASE,
            "decision_epoch": "2026-08-31T02:00:00+00:00",
            "lanes": [],
        },
    )
    monkeypatch.setattr(
        state,
        "load_all_market_certification_envelope",
        lambda **_kwargs: {"release_sha": _RELEASE, "certified": False},
    )
    monkeypatch.setattr(state, "latest_manual_cio_diagnostic", lambda **_kwargs: _diagnostic())

    envelope = state.load_production_state_envelope(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE},
        now=_NOW,
    )

    assert envelope["alignment"]["asset_telemetry_decision_epoch_matches"] is False
    assert envelope["alignment"]["current_asset_state_coherent"] is False
