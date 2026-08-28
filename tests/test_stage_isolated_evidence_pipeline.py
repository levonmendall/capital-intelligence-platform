from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from operations import stage_isolated_evidence_pipeline as pipeline
import run_stage_isolated_evidence_pipeline as runtime


def _values(tmp_path, *, max_age: str = "900") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-stage-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": max_age,
    }


def _advance_to_comprehensive(values: dict[str, str], tmp_path):
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )
    for stage in ("reference", "public_live", "us_equity_discovery"):
        state = pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
        )
        state = pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
            reference_manifest_id=("manifest-1" if stage == "reference" else None),
            reference_manifest_path=(
                str(tmp_path / "manifest.json") if stage == "reference" else None
            ),
        )
    assert state.next_stage == "comprehensive_discovery"
    return state


def test_stage_pipeline_persists_canonical_prefix_and_effective_cutoff(tmp_path) -> None:
    values = _values(tmp_path)
    requested = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested,
    )

    assert state.completed_stages == ()
    assert state.next_stage == "reference"

    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    effective = requested + timedelta(seconds=30)
    state = pipeline.complete_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        evidence_as_of=effective,
        reference_manifest_id="manifest-1",
        reference_manifest_path=str(tmp_path / "manifest.json"),
    )

    assert state.evidence_as_of == effective
    assert state.completed_stages == ("reference",)
    assert state.next_stage == "public_live"
    assert state.reference_manifest_id == "manifest-1"

    with pytest.raises(pipeline.StageIsolatedEvidencePipelineError):
        pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage="comprehensive_discovery",
        )


def test_failed_fresh_stage_resumes_same_pipeline(tmp_path) -> None:
    values = _values(tmp_path)
    requested = datetime.now(timezone.utc)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values, requested_at=requested)
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    failed = pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticFailure",
        error_detail="bounded failure",
    )

    resumed = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested + timedelta(seconds=30),
    )

    assert failed.state == "failed"
    assert resumed.pipeline_id == state.pipeline_id
    assert resumed.next_stage == "reference"
    assert resumed.error_type == "SyntheticFailure"


def test_stale_failed_stage_starts_new_pipeline(tmp_path) -> None:
    values = _values(tmp_path, max_age="1")
    requested = datetime.now(timezone.utc) - timedelta(seconds=10)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values, requested_at=requested)
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticFailure",
        error_detail="bounded failure",
    )

    replacement = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )

    assert replacement.pipeline_id != state.pipeline_id
    assert replacement.completed_stages == ()
    assert replacement.next_stage == "reference"


def test_final_stage_requires_generation_identity(tmp_path) -> None:
    values = _values(tmp_path)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values)
    for stage in pipeline._STAGES[:-1]:
        state = pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
        )
        state = pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
            reference_manifest_id=("manifest-1" if stage == "reference" else None),
            reference_manifest_path=(
                str(tmp_path / "manifest.json") if stage == "reference" else None
            ),
        )

    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="finalize",
    )
    with pytest.raises(pipeline.StageIsolatedEvidencePipelineError):
        pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage="finalize",
        )


class _FailingStageProcess:
    def __init__(self, command, *, events: list[tuple[str, str]], **_kwargs) -> None:
        events.append(("spawn", str(command[2])))

    def wait(self, timeout=None) -> int:
        del timeout
        return 9


class _FreshnessExpiredProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def wait(self, timeout=None) -> int:
        self.wait_timeouts.append(timeout)
        if self.returncode is not None:
            return self.returncode
        if self.killed:
            self.returncode = -9
            return self.returncode
        if self.terminated:
            self.returncode = -15
            return self.returncode
        raise subprocess.TimeoutExpired("stage-child", timeout)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class _TerminalRaceProcess:
    def __init__(self, on_timeout) -> None:
        self._on_timeout = on_timeout
        self._raised = False
        self.returncode: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def wait(self, timeout=None) -> int:
        if not self._raised:
            self._raised = True
            self._on_timeout()
            self.returncode = 17
            raise subprocess.TimeoutExpired("stage-child", timeout)
        assert self.returncode is not None
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True


def test_comprehensive_child_is_bounded_by_existing_evidence_freshness(
    tmp_path, monkeypatch, capsys
) -> None:
    values = _values(tmp_path)
    original = dict(values)
    _advance_to_comprehensive(values, tmp_path)
    child = _FreshnessExpiredProcess()

    monkeypatch.setattr(
        runtime,
        "_run_comprehensive_discovery_cache_reclamation",
        lambda _values: None,
    )
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: child)

    assert runtime.run_pipeline(values) == runtime._STAGE_FRESHNESS_EXPIRED_RETURN_CODE

    state = pipeline.load_stage_isolated_evidence_state(values)
    assert state is not None
    assert state.state == "failed"
    assert state.current_stage == "comprehensive_discovery"
    assert state.completed_stages == (
        "reference",
        "public_live",
        "us_equity_discovery",
    )
    assert state.error_type == "EvidenceFreshnessExpired"
    assert "max_age_seconds=900" in str(state.error_detail)
    assert child.terminated is True
    assert child.killed is False
    assert len(child.wait_timeouts) == 2
    assert child.wait_timeouts[0] is not None
    assert 0.0 < float(child.wait_timeouts[0]) <= 900.0
    assert child.wait_timeouts[1] == runtime._STAGE_TERMINATION_GRACE_SECONDS
    assert values == original

    failure_events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if "continuous_evidence_plane_failure_context" in line
    ]
    assert len(failure_events) == 1
    assert failure_events[0]["error_type"] == "EvidenceFreshnessExpired"
    assert failure_events[0]["failure_stage"] == (
        "stage_isolated_evidence:comprehensive_discovery"
    )
    assert failure_events[0]["decision_authority"] is False
    assert failure_events[0]["execution_authority"] is False
    assert failure_events[0]["real_money_authorized"] is False


def test_child_terminal_failure_wins_timeout_race(tmp_path, monkeypatch) -> None:
    values = _values(tmp_path)
    state = _advance_to_comprehensive(values, tmp_path)

    def _publish_child_terminal_failure() -> None:
        pipeline.fail_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage="comprehensive_discovery",
            error_type="ChildDiscoveryFailure",
            error_detail="child terminal truth",
        )

    child = _TerminalRaceProcess(_publish_child_terminal_failure)
    monkeypatch.setattr(
        runtime,
        "_run_comprehensive_discovery_cache_reclamation",
        lambda _values: None,
    )
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: child)

    assert runtime.run_pipeline(values) == 17

    latest = pipeline.load_stage_isolated_evidence_state(values)
    assert latest is not None
    assert latest.state == "failed"
    assert latest.current_stage == "comprehensive_discovery"
    assert latest.error_type == "ChildDiscoveryFailure"
    assert latest.error_detail == "child terminal truth"
    assert child.terminate_called is False
    assert child.kill_called is False


def test_pre_reference_cache_reclamation_runs_before_reference_child(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        runtime,
        "_run_reference_cache_reclamation",
        lambda _values: events.append(("reclaim", "reference")),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline(values) == 9
    assert events == [("reclaim", "reference"), ("spawn", "reference")]

    state = pipeline.load_stage_isolated_evidence_state(values)
    assert state is not None
    assert state.current_stage == "reference"
    assert state.completed_stages == ()
    assert state.state == "running"


def test_pre_reference_cache_reclamation_runs_only_at_reference_boundary(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values)
    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    pipeline.complete_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        reference_manifest_id="manifest-test",
        reference_manifest_path=str(tmp_path / "reference-manifest.json"),
    )

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runtime,
        "_run_reference_cache_reclamation",
        lambda _values: events.append(("reclaim", "reference")),
    )
    monkeypatch.setattr(
        runtime,
        "_run_completed_evidence_cache_reclamation",
        lambda _values, **kwargs: events.append(("reclaim", str(kwargs["stage"]))),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline(values) == 9
    assert events == [("reclaim", "public_live"), ("spawn", "public_live")]


def test_pre_reference_cache_reclamation_timeout_is_advisory_and_cannot_certify(
    tmp_path, monkeypatch, capsys
) -> None:
    values = _values(tmp_path)

    def _timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(runtime.subprocess, "run", _timeout)
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline(values) == 9
    state = pipeline.load_stage_isolated_evidence_state(values)
    assert state is not None
    assert state.current_stage == "reference"
    assert state.completed_stages == ()
    assert state.state == "running"
    assert events == [("spawn", "reference")]

    reclamation_events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "stage_isolated_reference_cache_reclamation" in line
    ]
    assert len(reclamation_events) == 1
    event = reclamation_events[0]
    assert event["status"] == "timed_out"
    assert event["advisory_only"] is True
    assert event["evidence_certified"] is False
    assert event["decision_authority"] is False
    assert event["execution_authority"] is False
    assert event["real_money_authorized"] is False


def test_pre_reference_cache_reclamation_preserves_memory_controls(
    monkeypatch, tmp_path
) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_MEMORY_LIMIT_MB": "2048",
        "CAPITAL_INTELLIGENCE_MEMORY_RESERVE_MB": "640",
        "CAPITAL_INTELLIGENCE_CGROUP_HARD_CEILING_RATIO": "0.90",
    }
    original = dict(values)
    calls: list[dict[str, object]] = []

    def _completed(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", _completed)
    runtime._run_reference_cache_reclamation(values)

    assert values == original
    assert len(calls) == 1
    assert calls[0]["timeout"] == runtime._REFERENCE_CACHE_RECLAMATION_TIMEOUT_SECONDS
    assert calls[0]["env"] == original
    assert calls[0]["start_new_session"] is False
    assert "operations.evidence_file_cache_release" in runtime._REFERENCE_CACHE_RECLAMATION_CODE
    assert "release_completed_operating_evidence_file_cache" in runtime._REFERENCE_CACHE_RECLAMATION_CODE