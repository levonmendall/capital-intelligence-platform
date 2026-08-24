from __future__ import annotations

import json
import subprocess

from operations import stage_isolated_evidence_pipeline as state_pipeline
import run_stage_isolated_evidence_pipeline as runtime


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-pre-reference-reclaim-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


class _FailingStageProcess:
    def __init__(self, command, *, events: list[tuple[str, str]], **_kwargs) -> None:
        events.append(("spawn", str(command[2])))

    def wait(self) -> int:
        return 9


def test_reclamation_runs_before_reference_stage_child(tmp_path, monkeypatch) -> None:
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

    state = state_pipeline.load_stage_isolated_evidence_state(values)
    assert state is not None
    assert state.current_stage == "reference"
    assert state.completed_stages == ()
    assert state.state == "running"


def test_reclamation_runs_only_at_reference_boundary(tmp_path, monkeypatch) -> None:
    values = _values(tmp_path)
    state = state_pipeline.ensure_stage_isolated_evidence_pipeline(values)
    state = state_pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    state_pipeline.complete_evidence_stage(
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


def test_reclamation_timeout_is_advisory_and_cannot_certify_reference(
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
    state = state_pipeline.load_stage_isolated_evidence_state(values)
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


def test_reclamation_does_not_change_memory_limits_or_reserves(monkeypatch, tmp_path) -> None:
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
