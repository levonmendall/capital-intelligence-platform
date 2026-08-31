from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_stage_isolated_evidence_pipeline as coordinator
import run_stage_isolated_evidence_stage as worker


def _state(
    *,
    pipeline_id: str = "pipeline-a",
    status: str = "running",
    completed_stages: tuple[str, ...] = (),
    current_stage: str | None = None,
    generation_id: str | None = None,
) -> coordinator.StageIsolatedEvidenceState:
    now = datetime.now(timezone.utc)
    return coordinator.StageIsolatedEvidenceState(
        pipeline_id=pipeline_id,
        release="release-a",
        state=status,
        requested_at=now,
        evidence_as_of=now,
        updated_at=now,
        completed_stages=completed_stages,
        current_stage=current_stage,
        stage_started_at=now if current_stage else None,
        reference_manifest_id="manifest-a",
        reference_manifest_path="/tmp/reference-manifest.json",
        generation_id=generation_id,
        error_type=None,
        error_detail=None,
        path=Path("/tmp/stage-isolated-evidence-latest.json"),
    )


def _install_coordinator_child_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_code: int,
    latest: coordinator.StageIsolatedEvidenceState,
) -> list[dict[str, object]]:
    before = _state(
        completed_stages=coordinator._STAGES[:-1],
        current_stage="finalize",
    )
    terminal = latest
    # The coordinator first checks whether a failed comprehensive attempt still has a live
    # owner before ensuring/resuming the active attempt. Preserve the same running journal
    # through that preflight and the stage-loop read, then expose the child terminal state.
    states = iter((before, before, terminal, terminal))
    failures: list[dict[str, object]] = []

    monkeypatch.setattr(coordinator, "_ensure_active_attempt", lambda _values: before)
    monkeypatch.setattr(
        coordinator,
        "load_stage_isolated_evidence_state",
        lambda _values: next(states),
    )
    monkeypatch.setattr(coordinator.subprocess, "Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        coordinator,
        "_wait_for_stage_process",
        lambda _process, *, state, values: (return_code, False),
    )
    monkeypatch.setattr(
        coordinator,
        "_safe_failure",
        lambda **payload: failures.append(payload),
    )
    return failures


def test_worker_completion_telemetry_cannot_revoke_durable_completion(monkeypatch):
    now = datetime.now(timezone.utc)
    started = SimpleNamespace(completed_stages=())
    completed = SimpleNamespace(evidence_as_of=now, generation_id=None)
    failed: list[dict[str, object]] = []

    monkeypatch.setattr(worker, "begin_evidence_stage", lambda *args, **kwargs: started)
    monkeypatch.setitem(
        worker._STAGE_RUNNERS,
        "reference",
        lambda _values, _state: {
            "evidence_as_of": now,
            "reference_manifest_id": "manifest-a",
            "reference_manifest_path": "/tmp/reference-manifest.json",
        },
    )
    monkeypatch.setattr(
        worker,
        "complete_evidence_stage",
        lambda *args, **kwargs: completed,
    )
    monkeypatch.setattr(
        worker,
        "fail_evidence_stage",
        lambda *args, **kwargs: failed.append(kwargs),
    )

    def broken_completion_telemetry(*args, **kwargs):
        raise BrokenPipeError("stdout closed after durable completion")

    monkeypatch.setattr(worker, "print", broken_completion_telemetry, raising=False)

    assert worker.run_stage("reference", pipeline_id="pipeline-a", values={}) == 0
    assert failed == []


def test_worker_precompletion_error_still_fails_closed(monkeypatch):
    started = SimpleNamespace(completed_stages=())
    failed: list[dict[str, object]] = []

    monkeypatch.setattr(worker, "begin_evidence_stage", lambda *args, **kwargs: started)

    def fail_before_completion(_values, _state):
        raise RuntimeError("provider stage failed before checkpoint")

    monkeypatch.setitem(worker._STAGE_RUNNERS, "reference", fail_before_completion)
    monkeypatch.setattr(
        worker,
        "fail_evidence_stage",
        lambda *args, **kwargs: failed.append(kwargs),
    )

    assert worker.run_stage("reference", pipeline_id="pipeline-a", values={}) == 2
    assert failed
    assert failed[0]["stage"] == "reference"
    assert failed[0]["error_type"] == "RuntimeError"


def test_coordinator_reconciles_positive_exit_after_exact_durable_completion(
    monkeypatch,
    capsys,
):
    completed = _state(
        status="completed",
        completed_stages=coordinator._STAGES,
        generation_id="generation-a",
    )
    failures = _install_coordinator_child_result(
        monkeypatch,
        return_code=2,
        latest=completed,
    )

    assert coordinator.run_pipeline({}) == 0
    assert failures == []
    assert "stage_isolated_evidence_stage_exit_reconciled" in capsys.readouterr().out


def test_coordinator_does_not_reconcile_missing_stage_completion(monkeypatch):
    incomplete = _state(
        completed_stages=coordinator._STAGES[:-1],
        current_stage="finalize",
    )
    failures = _install_coordinator_child_result(
        monkeypatch,
        return_code=2,
        latest=incomplete,
    )

    assert coordinator.run_pipeline({}) == 2
    assert len(failures) == 1
    assert failures[0]["return_code"] == 2


def test_coordinator_does_not_reconcile_wrong_pipeline_identity(monkeypatch):
    completed_other_pipeline = _state(
        pipeline_id="pipeline-b",
        status="completed",
        completed_stages=coordinator._STAGES,
        generation_id="generation-b",
    )
    failures = _install_coordinator_child_result(
        monkeypatch,
        return_code=2,
        latest=completed_other_pipeline,
    )

    assert coordinator.run_pipeline({}) == 2
    assert len(failures) == 1


def test_coordinator_does_not_reconcile_signal_exit(monkeypatch):
    completed = _state(
        status="completed",
        completed_stages=coordinator._STAGES,
        generation_id="generation-a",
    )
    failures = _install_coordinator_child_result(
        monkeypatch,
        return_code=-9,
        latest=completed,
    )

    assert coordinator.run_pipeline({}) == -9
    assert len(failures) == 1
    assert failures[0]["return_code"] == -9


def test_coordinator_does_not_reconcile_failed_journal(monkeypatch):
    failed_state = _state(
        status="failed",
        completed_stages=coordinator._STAGES,
        generation_id="generation-a",
    )
    failures = _install_coordinator_child_result(
        monkeypatch,
        return_code=2,
        latest=failed_state,
    )

    assert coordinator.run_pipeline({}) == 2
    assert len(failures) == 1
