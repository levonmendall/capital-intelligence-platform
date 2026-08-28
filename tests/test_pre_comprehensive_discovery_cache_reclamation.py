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


def _safe_report() -> dict[str, object]:
    return {
        "schema_version": runtime._PRECOMPREHENSIVE_CACHE_RECLAMATION_SCHEMA,
        "candidate_file_count": 12,
        "candidate_bytes": 2_400_000,
        "selected_file_count": 8,
        "selected_bytes": 2_100_000,
        "released_file_count": 8,
        "released_bytes": 2_100_000,
        "scan_truncated": False,
        "manifest_truncated": False,
        "raw_current_reclaimed_kib": 512_000,
        "inactive_file_reclaimed_kib": 500_000,
        "largest_candidates": [],
        "categories": [],
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


class _FailingStageProcess:
    def __init__(self, command, *, events: list[tuple[str, str]], **_kwargs) -> None:
        events.append(("spawn", str(command[2])))

    def wait(self, timeout=None) -> int:
        del timeout
        return 9

    def poll(self) -> int:
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
        runtime,
        "_run_completed_evidence_cache_reclamation",
        lambda _values, **kwargs: events.append(("reclaim", str(kwargs["stage"]))),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingStageProcess(command, events=events, **kwargs),
    )

    assert runtime.run_pipeline({}) == 9
    assert events == [("reclaim", "public_live"), ("spawn", "public_live")]


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


def test_comprehensive_reclamation_reports_exact_cache_ownership(monkeypatch, capsys) -> None:
    report = _safe_report()

    def _completed(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(report))

    monkeypatch.setattr(runtime.subprocess, "run", _completed)
    runtime._run_comprehensive_discovery_cache_reclamation({})

    event = json.loads(capsys.readouterr().out.strip())
    assert event["status"] == "completed"
    assert event["candidate_file_count"] == 12
    assert event["released_bytes"] == 2_100_000
    assert event["raw_current_reclaimed_kib"] == 512_000
    assert event["inactive_file_reclaimed_kib"] == 500_000
    assert event["cache_ownership"] == report
    assert event["advisory_only"] is True
    assert event["evidence_certified"] is False
    assert event["decision_authority"] is False
    assert event["execution_authority"] is False


def test_invalid_cache_ownership_report_remains_advisory(monkeypatch, capsys) -> None:
    unsafe = _safe_report()
    unsafe["decision_authority"] = True

    def _completed(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(unsafe))

    monkeypatch.setattr(runtime.subprocess, "run", _completed)
    runtime._run_comprehensive_discovery_cache_reclamation({})

    event = json.loads(capsys.readouterr().out.strip())
    assert event["status"] == "invalid_report"
    assert event["error_type"] == "CacheReclamationReportError"
    assert "cache_ownership" not in event
    assert event["advisory_only"] is True
    assert event["evidence_certified"] is False
    assert event["decision_authority"] is False
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
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(_safe_report()))

    monkeypatch.setattr(runtime.subprocess, "run", _completed)
    runtime._run_comprehensive_discovery_cache_reclamation(values)

    assert values == original
    assert len(calls) == 1
    assert calls[0]["timeout"] == runtime._REFERENCE_CACHE_RECLAMATION_TIMEOUT_SECONDS
    assert calls[0]["env"] == original
    assert calls[0]["start_new_session"] is False
    assert calls[0]["stdout"] == subprocess.PIPE
    assert calls[0]["text"] is True
    assert "operations.pre_comprehensive_cache_reclamation" in (
        runtime._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE
    )
    assert "release_pre_comprehensive_completed_stage_file_cache" in (
        runtime._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE
    )
    assert "operations.evidence_file_cache_release" in runtime._REFERENCE_CACHE_RECLAMATION_CODE
    assert "release_completed_operating_evidence_file_cache" in runtime._REFERENCE_CACHE_RECLAMATION_CODE


def test_reference_boundary_uses_broad_clean_page_reclaimer(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []
    report = _safe_report()
    report["failed_attempt_supersession_detected"] = False
    report["flush_attempted_file_count"] = 0
    report["flushed_file_count"] = 0

    def _completed(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(report))

    monkeypatch.setattr(runtime.subprocess, "run", _completed)
    runtime._run_reference_cache_reclamation({})

    assert len(calls) == 1
    assert calls[0]["command"][2] == runtime._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE
    assert calls[0]["stdout"] == subprocess.PIPE
    assert calls[0]["text"] is True
    assert calls[0]["start_new_session"] is False

    event = json.loads(capsys.readouterr().out.strip())
    assert event["stage"] == "reference"
    assert event["status"] == "completed"
    assert event["cache_ownership"]["failed_attempt_supersession_detected"] is False
    assert event["cache_ownership"]["flush_attempted_file_count"] == 0
    assert event["cache_ownership"]["flushed_file_count"] == 0
    assert event["advisory_only"] is True
    assert event["evidence_certified"] is False
    assert event["decision_authority"] is False
    assert event["real_money_authorized"] is False
