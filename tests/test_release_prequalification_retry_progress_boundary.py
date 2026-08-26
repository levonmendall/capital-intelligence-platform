"""Regressions for release-prequalification progress across wrapper retries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations import release_prequalification_parent_watchdog as watchdog
from operations import release_prequalification_retry_progress_boundary as boundary_adapter


def _status(started_at: datetime, *, state: str = "in_progress", prequalification_id: str = "preq-1"):
    return {
        "prequalification_id": prequalification_id,
        "started_at": started_at.isoformat(),
        "state": state,
    }


def test_active_retry_uses_persisted_generation_start(monkeypatch) -> None:
    generation_start = datetime.now(timezone.utc) - timedelta(minutes=20)
    retry_start = generation_start + timedelta(minutes=15)
    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: _status(generation_start),
    )

    observed = boundary_adapter._generation_boundary(
        watchdog,
        {},
        fallback=retry_start,
    )

    assert observed == generation_start


def test_terminal_or_unidentified_generation_keeps_retry_boundary(monkeypatch) -> None:
    generation_start = datetime.now(timezone.utc) - timedelta(minutes=20)
    retry_start = generation_start + timedelta(minutes=15)

    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: _status(generation_start, state="failed"),
    )
    assert boundary_adapter._generation_boundary(
        watchdog,
        {},
        fallback=retry_start,
    ) == retry_start

    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: _status(generation_start, prequalification_id=""),
    )
    assert boundary_adapter._generation_boundary(
        watchdog,
        {},
        fallback=retry_start,
    ) == retry_start


def test_generation_boundary_never_moves_observation_forward(monkeypatch) -> None:
    retry_start = datetime.now(timezone.utc)
    future_start = retry_start + timedelta(seconds=10)
    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: _status(future_start),
    )

    assert boundary_adapter._generation_boundary(
        watchdog,
        {},
        fallback=retry_start,
    ) == retry_start


def test_installed_observer_forwards_generation_start_and_preserves_stall_budget(monkeypatch) -> None:
    generation_start = datetime.now(timezone.utc) - timedelta(minutes=30)
    retry_start = generation_start + timedelta(minutes=25)
    captured: dict[str, datetime] = {}
    sentinel = watchdog.PrequalificationProgress(
        phase="reference_binding",
        component="release-reference-manifest",
        updated_at=generation_start + timedelta(minutes=10),
        state="qualified",
        stall_limit_seconds=180.0,
        metrics={"qualified_count": 2, "required_count": 2},
        progress_token="same-generation-progress",
    )

    def original(_values, *, started_at: datetime):
        captured["started_at"] = started_at
        return sentinel

    monkeypatch.setattr(watchdog, "observe_current_prequalification_progress", original)
    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: _status(generation_start),
    )

    boundary_adapter.install_release_prequalification_retry_progress_boundary()
    result = watchdog.observe_current_prequalification_progress({}, started_at=retry_start)

    assert captured["started_at"] == generation_start
    assert result is sentinel
    assert result.stall_limit_seconds == 180.0


def test_install_is_idempotent(monkeypatch) -> None:
    def original(_values, *, started_at: datetime):
        return started_at

    monkeypatch.setattr(watchdog, "observe_current_prequalification_progress", original)
    boundary_adapter.install_release_prequalification_retry_progress_boundary()
    first = watchdog.observe_current_prequalification_progress
    boundary_adapter.install_release_prequalification_retry_progress_boundary()

    assert watchdog.observe_current_prequalification_progress is first
