"""Regressions for parent-owned release evidence stall supervision."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations import release_prequalification_parent_watchdog as watchdog


def _progress_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def test_stale_public_progress_cannot_masquerade_as_current_attempt(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    stale = started - timedelta(minutes=20)
    monkeypatch.setattr(watchdog, "load_reference_prequalification_progress", lambda _values: None)
    monkeypatch.setattr(
        watchdog,
        "load_public_live_requirement_progress",
        lambda _values: {
            "updated_at": _progress_timestamp(stale),
            "state": "qualifying",
            "active_required_information": "ofac-sdn-live",
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_release_certification_dag_progress",
        lambda _values, started_at=None: None,
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "reference_binding"
    assert progress.component == "release-reference-manifest"
    assert progress.state == "starting"


def test_current_reference_component_wins_over_stale_public_progress(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    current = started + timedelta(seconds=2)
    monkeypatch.setattr(
        watchdog,
        "load_reference_prequalification_progress",
        lambda _values: {
            "updated_at": _progress_timestamp(current),
            "state": "qualifying",
            "active_component": "reference-futures-contracts",
            "required_count": 2,
            "qualified_count": 1,
            "pending_count": 1,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_public_live_requirement_progress",
        lambda _values: {
            "updated_at": _progress_timestamp(started - timedelta(minutes=5)),
            "state": "qualifying",
            "active_required_information": "ofac-sdn-live",
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_release_certification_dag_progress",
        lambda _values, started_at=None: None,
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "reference_acquisition"
    assert progress.component == "reference-futures-contracts"
    assert progress.metrics["qualified_count"] == 1
    assert progress.stall_limit_seconds >= 165


def test_newer_public_requirement_progress_advances_parent_phase(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    reference_at = started + timedelta(seconds=1)
    public_at = started + timedelta(seconds=3)
    monkeypatch.setattr(
        watchdog,
        "load_reference_prequalification_progress",
        lambda _values: {
            "updated_at": _progress_timestamp(reference_at),
            "state": "qualified",
            "active_component": None,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_public_live_requirement_progress",
        lambda _values: {
            "updated_at": _progress_timestamp(public_at),
            "state": "qualifying",
            "active_required_information": "sec-companyfacts-live",
            "required_count": 13,
            "qualified_count": 6,
            "pending_count": 7,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_release_certification_dag_progress",
        lambda _values, started_at=None: None,
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "public_live"
    assert progress.component == "sec-companyfacts-live"
    assert progress.metrics["qualified_count"] == 6
    assert progress.stall_limit_seconds == 120


def test_current_dag_journal_advances_without_requiring_new_decision_epoch(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    updated = started + timedelta(seconds=4)
    observed_started_at: list[object] = []
    monkeypatch.setattr(watchdog, "load_reference_prequalification_progress", lambda _values: None)
    monkeypatch.setattr(watchdog, "load_public_live_requirement_progress", lambda _values: None)

    def load_dag(_values, *, started_at=None):
        observed_started_at.append(started_at)
        return {
            "updated_at": _progress_timestamp(updated),
            "active_node": "deep-market-evidence:option",
            "focus_node": "deep-market-evidence:option",
            "counts": {
                "required_nodes": 5,
                "completed_nodes": 3,
                "running_nodes": 1,
                "pending_nodes": 1,
                "failed_nodes": 0,
            },
        }

    monkeypatch.setattr(watchdog, "load_release_certification_dag_progress", load_dag)

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert observed_started_at == [None]
    assert progress.phase == "comprehensive_discovery"
    assert progress.component == "deep-market-evidence:option"
    assert progress.metrics["completed_nodes"] == 3
    assert progress.stall_limit_seconds == 660


def test_parent_stall_returns_credential_safe_timeout(monkeypatch) -> None:
    signed_started = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(
        watchdog,
        "load_release_evidence_prequalification",
        lambda _values: {
            "state": "in_progress",
            "prequalification_id": "preq-test",
            "started_at": signed_started.isoformat(),
            "metrics": {"attempt": 1, "maximum_attempts": 1},
        },
    )
    frozen = watchdog.PrequalificationProgress(
        phase="reference_acquisition",
        component="reference-directories",
        updated_at=datetime.now(timezone.utc),
        state="running",
        stall_limit_seconds=0.1,
        metrics={},
    )
    monkeypatch.setattr(
        watchdog,
        "observe_current_prequalification_progress",
        lambda _values, started_at: frozen,
    )
    monkeypatch.setattr(watchdog, "_publish_parent_progress", lambda _values, progress: None)

    command = (
        sys.executable,
        "-c",
        "import time; time.sleep(10)",
        "run_bounded_continuous_evidence_plane.py",
    )
    result = watchdog._watched_run(
        command,
        original_run=subprocess.run,
        env={"CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PARENT_POLL_SECONDS": "0.01"},
        check=False,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 124
    assert result.stderr is not None
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    terminal = next(item for item in records if item.get("event") == "continuous_evidence_plane_failure_context")
    assert terminal["error_type"] == "ParentStallTimeout"
    assert "prequalification_phase=reference_acquisition" in terminal["error_detail"]
    assert "component=reference-directories" in terminal["error_detail"]
    assert terminal["credential_safe"] is True
    assert terminal["paper_only"] is True
    assert terminal["real_money_authorized"] is False


def test_installer_changes_only_memory_safe_subprocess_seam() -> None:
    module = SimpleNamespace(subprocess=subprocess)
    original_run = subprocess.run

    watchdog.install_release_prequalification_parent_watchdog(module)

    assert module.subprocess is not subprocess
    assert subprocess.run is original_run
    assert module.subprocess.PIPE is subprocess.PIPE
    completed = module.subprocess.run(
        (sys.executable, "-c", "print('delegated')"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "delegated"
