"""Regressions for reference-controller startup liveness ownership."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import run_stage_isolated_evidence_pipeline as coordinator
from operations import release_prequalification_parent_watchdog as watchdog


def _stage_state(updated_at: datetime):
    return SimpleNamespace(
        current_stage="reference",
        next_stage="reference",
        completed_stages=(),
        updated_at=updated_at,
        state="running",
        pipeline_id="pipeline-reference-startup",
    )


def test_reference_stage_marker_is_controller_startup_with_short_budget(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    updated = started + timedelta(seconds=1)
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: _stage_state(updated),
    )

    progress = watchdog._stage_pipeline_progress({}, boundary=started)

    assert progress is not None
    assert progress.phase == "reference"
    assert progress.component == "reference-controller-startup"
    assert progress.state == "running"
    assert progress.stall_limit_seconds == 45.0
    assert progress.metrics == {
        "stage_completed_count": 0,
        "stage_required_count": 6,
    }


def test_reference_startup_budget_can_be_governed_without_changing_component_timeout(
    monkeypatch,
) -> None:
    started = datetime.now(timezone.utc)
    updated = started + timedelta(seconds=1)
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: _stage_state(updated),
    )
    values = {
        "CAPITAL_INTELLIGENCE_RELEASE_REFERENCE_CONTROLLER_STARTUP_STALL_SECONDS": "30",
        "CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_COMPONENT_TIMEOUT_SECONDS": "120",
    }

    startup = watchdog._stage_pipeline_progress(values, boundary=started)
    component = watchdog.PrequalificationProgress(
        phase="reference_acquisition",
        component="reference-directories",
        updated_at=updated + timedelta(seconds=1),
        state="qualifying",
        stall_limit_seconds=180.0,
        metrics={"qualified_count": 0, "pending_count": 2},
    )
    nested = watchdog._progress_nested_under_stage(startup, component)  # type: ignore[arg-type]

    assert startup is not None
    assert startup.stall_limit_seconds == 30.0
    assert nested is not None
    assert nested.component == "reference-directories"
    assert nested.stall_limit_seconds == 180.0


def test_reference_boundary_is_persisted_before_child_interpreter_launch() -> None:
    source = inspect.getsource(coordinator.run_pipeline)
    reference_claim = source.index('if stage == "reference"')
    begin = source.index("begin_evidence_stage(", reference_claim)
    launch = source.index("subprocess.Popen(", reference_claim)

    assert reference_claim < begin < launch


def test_startup_marker_has_no_investment_or_execution_authority() -> None:
    source = inspect.getsource(coordinator.run_pipeline)
    reference_claim = source.index('if stage == "reference"')
    launch = source.index("subprocess.Popen(", reference_claim)
    handoff = source[reference_claim:launch]

    assert "decision" not in handoff.lower()
    assert "candidate" not in handoff.lower()
    assert "sizing" not in handoff.lower()
    assert "construction" not in handoff.lower()
    assert "execution" not in handoff.lower()
