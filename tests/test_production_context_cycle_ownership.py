from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)
from production_context_state_resilience import (
    ATTEMPT_STATE_FILENAME,
    latest_attempt,
    recording_context_preparer,
)


NOW = datetime(2026, 8, 23, 14, 30, tzinfo=timezone.utc)
SCHEDULED = datetime(2026, 8, 23, 14, 45, tzinfo=timezone.utc)
EXPECTED_CYCLE = "canonical-cio:America/New_York:2026-08-23"
ATTEMPT_SCHEMA = "production-context-publication-attempt-state.v2-cycle-owned"


@dataclass(frozen=True)
class _Result:
    state: str
    cycle_key: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "cycle_key": self.cycle_key,
            "detail": self.detail,
            "instrument_count": 1,
            "candidate_count": 0,
            "exclusion_count": 1,
        }


def _settings(tmp_path: Path):
    return SimpleNamespace(
        portfolio_database=tmp_path / "canonical_portfolio.db",
        scheduler_timezone="America/New_York",
    )


def _diagnostic_values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }


def test_running_context_attempt_owns_cycle_before_preparer_progress(tmp_path) -> None:
    settings = _settings(tmp_path)
    observed: dict[str, object] = {}

    def preparer(*, settings, scheduled_for):
        attempt = latest_attempt(settings)
        assert attempt is not None
        observed.update(attempt)
        return _Result("ready", EXPECTED_CYCLE, "ready")

    result = recording_context_preparer(preparer)(
        settings=settings,
        scheduled_for=SCHEDULED,
    )

    assert result.cycle_key == EXPECTED_CYCLE
    assert observed["state"] == "running"
    assert observed["cycle_key"] == EXPECTED_CYCLE
    assert isinstance(observed["attempt_id"], str) and observed["attempt_id"]
    assert observed["fence_version"] == 1

    terminal = latest_attempt(settings)
    assert terminal is not None
    assert terminal["attempt_id"] == observed["attempt_id"]
    assert terminal["fence_version"] == 1
    assert terminal["cycle_key"] == EXPECTED_CYCLE
    assert terminal["state"] == "ready"


def test_superseded_context_worker_cannot_overwrite_newer_attempt(tmp_path) -> None:
    settings = _settings(tmp_path)
    outer_owner: dict[str, object] = {}

    def inner(*, settings, scheduled_for):
        return _Result("ready", EXPECTED_CYCLE, "inner-owner")

    inner_wrapped = recording_context_preparer(inner)

    def outer(*, settings, scheduled_for):
        current = latest_attempt(settings)
        assert current is not None
        outer_owner.update(current)
        inner_wrapped(settings=settings, scheduled_for=scheduled_for)
        return _Result("ready", EXPECTED_CYCLE, "stale-outer")

    recording_context_preparer(outer)(settings=settings, scheduled_for=SCHEDULED)

    terminal = latest_attempt(settings)
    assert terminal is not None
    assert terminal["state"] == "ready"
    assert terminal["detail"] == "inner-owner"
    assert terminal["fence_version"] == 2
    assert terminal["attempt_id"] != outer_owner["attempt_id"]
    assert terminal["supersedes_attempt_id"] == outer_owner["attempt_id"]


def test_context_result_with_wrong_cycle_fails_closed(tmp_path) -> None:
    settings = _settings(tmp_path)

    def preparer(*, settings, scheduled_for):
        return _Result(
            "ready",
            "canonical-cio:America/New_York:2026-08-24",
            "wrong-cycle",
        )

    with pytest.raises(RuntimeError, match="fenced attempt cycle"):
        recording_context_preparer(preparer)(
            settings=settings,
            scheduled_for=SCHEDULED,
        )

    terminal = latest_attempt(settings)
    assert terminal is not None
    assert terminal["state"] == "failed"
    assert terminal["cycle_key"] == EXPECTED_CYCLE


def test_diagnostic_adopts_current_running_attempt_cycle_before_final_publication(
    tmp_path,
) -> None:
    values = _diagnostic_values(tmp_path)
    request_manual_cio_diagnostic(
        requested_by="render-release:test",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW + timedelta(seconds=1), values=values)
    assert claimed is not None

    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps({"cycle_key": "refresh-required:old-cycle"}),
        encoding="utf-8",
    )
    (tmp_path / ATTEMPT_STATE_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": ATTEMPT_SCHEMA,
                "attempt_id": "current-attempt",
                "fence_version": 9,
                "state": "running",
                "cycle_key": EXPECTED_CYCLE,
                "scheduled_for": SCHEDULED.isoformat(),
                "started_at": (NOW + timedelta(seconds=2)).isoformat(),
                "completed_at": None,
                "detail": "running",
                "paper_only": True,
                "real_money_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    progressed = record_manual_cio_diagnostic_progress(
        "production_context_portfolio_finalized",
        values=values,
    )

    assert progressed is not None
    assert progressed.cycle_key == EXPECTED_CYCLE
    assert latest_manual_cio_diagnostic(values=values) == progressed


def test_diagnostic_rejects_attempt_that_predates_its_claim(tmp_path) -> None:
    values = _diagnostic_values(tmp_path)
    request_manual_cio_diagnostic(
        requested_by="render-release:test",
        now=NOW,
        values=values,
    )
    claimed = claim_manual_cio_diagnostic(now=NOW + timedelta(seconds=10), values=values)
    assert claimed is not None

    (tmp_path / ATTEMPT_STATE_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": ATTEMPT_SCHEMA,
                "attempt_id": "stale-attempt",
                "fence_version": 2,
                "state": "running",
                "cycle_key": EXPECTED_CYCLE,
                "scheduled_for": SCHEDULED.isoformat(),
                "started_at": (NOW + timedelta(seconds=5)).isoformat(),
                "completed_at": None,
                "detail": "stale",
                "paper_only": True,
                "real_money_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    progressed = record_manual_cio_diagnostic_progress(
        "production_context_base_universe_ready",
        values=values,
    )

    assert progressed is not None
    assert progressed.cycle_key is None
