from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import run_stage_isolated_evidence_pipeline as runtime


def _state(*, next_stage: str):
    return SimpleNamespace(
        state="running",
        generation_id=None,
        next_stage=next_stage,
        pipeline_id="pipeline-test",
        evidence_as_of=datetime(2026, 8, 25, 17, 23, tzinfo=timezone.utc),
        completed_stages=("reference", "public_live", "us_equity_discovery"),
        current_stage="us_equity_discovery",
        error_type=None,
        error_detail=None,
    )


class _FailingStageProcess:
    def __init__(self, command, *, events: list[tuple[str, str]], **_kwargs) -> None:
        events.append(("spawn", str(command[2])))

    def wait(self) -> int:
        return 9


def test_reclamation_runs_after_us_equity_and_before_comprehensive_child(monkeypatch) -> None:
    state = _state(next_stage="comprehensive_discovery")
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(runtime, "_ensure_active_attempt", lambda _values: state)
    monkeypatch.setattr(runtime, "load_stage_isolated_evidence_state", lambda _values: state)
    monkeypatch.setattr(
        runtime,
        "_run_comprehensive_discovery_cache_reclamation",
        lambda _values: events.append(("reclaim", "comprehensive_discovery")),
    )
    monkeypatch.setattr(
        runtime,
        "_run_reference_cache_reclamation",
        lambda _values: events.append(("unexpected_reclaim", "reference")),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline({}) == 9
    assert state.completed_stages[-1] == "us_equity_discovery"
    assert events == [
        ("reclaim", "comprehensive_discovery"),
        ("spawn", "comprehensive_discovery"),
    ]


def test_comprehensive_reclamation_does_not_run_at_other_stage_boundaries(monkeypatch) -> None:
    state = _state(next_stage="public_live")
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(runtime, "_ensure_active_attempt", lambda _values: state)
    monkeypatch.setattr(runtime, "load_stage_isolated_evidence_state", lambda _values: state)
    monkeypatch.setattr(
        runtime,
        "_run_comprehensive_discovery_cache_reclamation",
        lambda _values: events.append(("reclaim", "comprehensive_discovery")),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline({}) == 9
    assert events == [("spawn", "public_live")]


def test_comprehensive_reclamation_timeout_is_advisory_and_cannot_certify(
    monkeypatch, capsys
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MEMORY_LIMIT_MB": "2048",
        "CAPITAL_INTELLIGENCE_MEMORY_RESERVE_MB": "640",
        "CAPITAL_INTELLIGENCE_CGROUP_HARD_CEILING_RATIO": "0.90",
    }

    def _timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(runtime.subprocess, "run", _timeout)
    runtime._run_comprehensive_discovery_cache_reclamation(values)

    reclamation_events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if runtime._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_EVENT in line
    ]
    assert len(reclamation_events) == 1
    event = reclamation_events[0]
    assert event["stage"] == "comprehensive_discovery"
    assert event["status"] == "timed_out"
    assert event["advisory_only"] is True
    assert event["evidence_certified"] is False
    assert event["decision_authority"] is False
    assert event["candidate_authority"] is False
    assert event["sizing_authority"] is False
    assert event["construction_authority"] is False
    assert event["execution_authority"] is False
    assert event["paper_only"] is True
    assert event["real_money_authorized"] is False


def test_comprehensive_reclamation_preserves_memory_controls(monkeypatch) -> None:
    values = {
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
    runtime._run_comprehensive_discovery_cache_reclamation(values)

    assert values == original
    assert len(calls) == 1
    assert calls[0]["timeout"] == runtime._REFERENCE_CACHE_RECLAMATION_TIMEOUT_SECONDS
    assert calls[0]["env"] == original
    assert calls[0]["start_new_session"] is False
    assert "operations.evidence_file_cache_release" in runtime._REFERENCE_CACHE_RECLAMATION_CODE
    assert "release_completed_operating_evidence_file_cache" in runtime._REFERENCE_CACHE_RECLAMATION_CODE
