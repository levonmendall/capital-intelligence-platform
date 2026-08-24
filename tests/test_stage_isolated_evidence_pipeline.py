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

    def wait(self) -> int:
        return 9


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
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline(values) == 9
    assert events == [("spawn", "public_live")]


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
