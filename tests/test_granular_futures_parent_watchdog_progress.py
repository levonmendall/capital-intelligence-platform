"""Regressions for root-level futures liveness in release prequalification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations import granular_futures_parent_watchdog_progress as adapter
from operations import release_prequalification_parent_watchdog as watchdog


def _coarse(updated_at: datetime, *, component: str = "reference-futures-contracts"):
    return watchdog.PrequalificationProgress(
        phase="reference_acquisition",
        component=component,
        updated_at=updated_at,
        state="qualifying",
        stall_limit_seconds=180.0,
        metrics={"qualified_count": 1, "required_count": 2},
        progress_token="coarse-reference",
    )


def _granular(updated_at: datetime, *, active_unit: str = "massive-root-NQ"):
    return {
        "cutoff": "2026-08-26T16:44:05+00:00",
        "updated_at": updated_at.isoformat(),
        "state": "qualifying",
        "required_root_count": 13,
        "qualified_root_count": 3,
        "unresolved_root_count": 10,
        "required_roots": ["6B", "6E", "6J", "CL", "ES", "GC", "HG", "NG", "NQ", "RTY", "SI", "ZB", "ZN"],
        "qualified_roots": ["6B", "6J", "ES"],
        "unresolved_roots": ["6E", "CL", "GC", "HG", "NG", "NQ", "RTY", "SI", "ZB", "ZN"],
        "active_unit": active_unit,
        "units": [
            {
                "unit": "massive-root-6E",
                "provider": "massive",
                "state": "timed-out",
                "root": "6E",
            },
            {
                "unit": active_unit,
                "provider": "massive",
                "state": "running",
                "root": "NQ",
            },
        ],
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_current_granular_root_advances_coarse_reference_progress(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    coarse_at = boundary + timedelta(seconds=1)
    granular_at = boundary + timedelta(seconds=40)
    monkeypatch.setattr(adapter, "load_futures_reference_progress", lambda _values: _granular(granular_at))

    projected = adapter._project_granular_futures_progress(
        watchdog,
        _coarse(coarse_at),
        {},
        boundary=boundary,
    )

    assert projected.component == "massive-root-NQ"
    assert projected.updated_at == granular_at
    assert projected.stall_limit_seconds == 180.0
    assert projected.metrics["futures_required_root_count"] == 13
    assert projected.metrics["futures_qualified_root_count"] == 3
    assert projected.metrics["futures_unresolved_root_count"] == 10
    assert "granular-futures" in projected.progress_token


def test_granular_projection_preserves_existing_finite_stall_budget(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    granular_at = boundary + timedelta(seconds=2)
    monkeypatch.setattr(adapter, "load_futures_reference_progress", lambda _values: _granular(granular_at))
    coarse = _coarse(boundary + timedelta(seconds=1))

    projected = adapter._project_granular_futures_progress(
        watchdog,
        coarse,
        {},
        boundary=boundary,
    )

    assert projected.stall_limit_seconds == coarse.stall_limit_seconds


def test_timestamp_only_rewrite_cannot_manufacture_new_liveness(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    first_at = boundary + timedelta(seconds=2)
    second_at = boundary + timedelta(seconds=30)
    coarse = _coarse(boundary + timedelta(seconds=1))

    monkeypatch.setattr(adapter, "load_futures_reference_progress", lambda _values: _granular(first_at))
    first = adapter._project_granular_futures_progress(
        watchdog,
        coarse,
        {},
        boundary=boundary,
    )
    monkeypatch.setattr(adapter, "load_futures_reference_progress", lambda _values: _granular(second_at))
    second = adapter._project_granular_futures_progress(
        watchdog,
        coarse,
        {},
        boundary=boundary,
    )

    assert first.updated_at != second.updated_at
    assert first.progress_token == second.progress_token


def test_stale_or_unrelated_granular_progress_is_ignored(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    coarse = _coarse(boundary + timedelta(seconds=1))
    monkeypatch.setattr(
        adapter,
        "load_futures_reference_progress",
        lambda _values: _granular(boundary - timedelta(seconds=1)),
    )
    assert adapter._project_granular_futures_progress(
        watchdog, coarse, {}, boundary=boundary
    ) is coarse

    unrelated = _coarse(boundary + timedelta(seconds=1), component="reference-directories")
    monkeypatch.setattr(
        adapter,
        "load_futures_reference_progress",
        lambda _values: _granular(boundary + timedelta(seconds=3)),
    )
    assert adapter._project_granular_futures_progress(
        watchdog, unrelated, {}, boundary=boundary
    ) is unrelated


def test_completed_unit_is_visible_between_active_roots(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    granular_at = boundary + timedelta(seconds=3)
    payload = _granular(granular_at, active_unit="")
    payload["units"] = [
        {
            "unit": "massive-root-NQ",
            "provider": "massive",
            "state": "timed-out",
            "root": "NQ",
        }
    ]
    monkeypatch.setattr(adapter, "load_futures_reference_progress", lambda _values: payload)

    projected = adapter._project_granular_futures_progress(
        watchdog,
        _coarse(boundary + timedelta(seconds=1)),
        {},
        boundary=boundary,
    )

    assert projected.component == "massive-root-NQ"
