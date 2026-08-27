from __future__ import annotations

import json
import subprocess
import sys

import pytest

from operations import publication_lane_cache_reclamation as reclamation
from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator


def _safe_report() -> dict[str, object]:
    return {
        "schema_version": "pre-comprehensive-cache-reclamation.v1",
        "status": "completed",
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


def _completed(stdout: str, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        (sys.executable, "-c", reclamation._CODE),
        returncode,
        stdout=stdout,
        stderr="",
    )


def test_publication_lane_reclaimer_uses_disposable_child_without_dag_override(monkeypatch) -> None:
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_MEMORY_LIMIT_MB": "2048",
        "CAPITAL_INTELLIGENCE_MEMORY_RESERVE_MB": "640",
        "CAPITAL_INTELLIGENCE_CGROUP_HARD_CEILING_RATIO": "0.90",
    }
    original = dict(values)
    calls: list[tuple[object, dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return _completed(json.dumps(_safe_report(), sort_keys=True))

    monkeypatch.setattr(reclamation.subprocess, "run", run)

    payload = reclamation.run_publication_lane_cache_reclamation(
        values,
        asset_class="real_estate",
        index=8,
    )

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == (sys.executable, "-c", reclamation._CODE)
    assert kwargs["env"] == values
    assert kwargs["timeout"] == reclamation._TIMEOUT_SECONDS
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["start_new_session"] is False
    assert values == original
    assert "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS" not in values
    assert payload["status"] == "completed"
    assert payload["return_code"] == 0
    assert payload["disposable_child"] is True
    assert payload["released_bytes"] == 2_100_000
    assert payload["raw_current_reclaimed_kib"] == 512_000
    assert payload["cache_ownership"] == _safe_report()
    assert payload["advisory_only"] is True
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["candidate_authority"] is False
    assert payload["sizing_authority"] is False
    assert payload["construction_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_publication_lane_reclaimer_stays_disabled_outside_render(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("publication reclaimer must remain Render-scoped")

    monkeypatch.setattr(reclamation.subprocess, "run", forbidden)

    payload = reclamation.run_publication_lane_cache_reclamation(
        {},
        asset_class="real_estate",
        index=8,
    )

    assert payload["status"] == "skipped"
    assert payload["return_code"] is None
    assert payload["disposable_child"] is True
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["real_money_authorized"] is False


def test_publication_lane_reclaimer_rejects_authoritative_report(monkeypatch) -> None:
    unsafe = _safe_report()
    unsafe["decision_authority"] = True
    monkeypatch.setattr(
        reclamation.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(json.dumps(unsafe, sort_keys=True)),
    )

    payload = reclamation.run_publication_lane_cache_reclamation(
        {"RENDER": "true"},
        asset_class="fixed_income",
        index=7,
    )

    assert payload["status"] == "invalid_report"
    assert payload["return_code"] == 0
    assert payload["error_type"] == "CacheReclamationReportError"
    assert "cache_ownership" not in payload
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["real_money_authorized"] is False


def test_publication_lane_reclaimer_timeout_is_advisory(monkeypatch) -> None:
    def timeout(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, reclamation._TIMEOUT_SECONDS)

    monkeypatch.setattr(reclamation.subprocess, "run", timeout)

    payload = reclamation.run_publication_lane_cache_reclamation(
        {"RENDER": "true"},
        asset_class="real_estate",
        index=8,
    )

    assert payload["status"] == "timed_out"
    assert payload["return_code"] is None
    assert payload["error_type"] == "CacheReclamationTimeout"
    assert "cache_ownership" not in payload
    assert payload["advisory_only"] is True
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_publication_lane_reclaimer_nonzero_child_is_advisory(monkeypatch) -> None:
    monkeypatch.setattr(
        reclamation.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed("", returncode=9),
    )

    payload = reclamation.run_publication_lane_cache_reclamation(
        {"RENDER": "true"},
        asset_class="fixed_income",
        index=7,
    )

    assert payload["status"] == "failed"
    assert payload["return_code"] == 9
    assert payload["error_type"] == "CacheReclamationProcessError"
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["execution_authority"] is False


class _SuccessfulProcess:
    def __init__(self, _command, *, events, **_kwargs) -> None:
        self._events = events
        events.append("spawn")

    def wait(self) -> int:
        self._events.append("exit")
        return 0


class _FailedProcess:
    def __init__(self, _command, *, events, **_kwargs) -> None:
        self._events = events
        events.append("spawn")

    def wait(self) -> int:
        self._events.append("exit-failed")
        return 9


def test_publication_reclamation_runs_after_durable_state_validation_and_before_completion(
    monkeypatch,
    tmp_path,
) -> None:
    events: list[str] = []
    state = {
        "schema_version": coordinator._transaction._TRANSACTION_SCHEMA,
        "transactional_lane_compaction": True,
        "raw_catalog_persisted": False,
        "asset_class": "real_estate",
        "raw_record_count": 10,
        "record_count": 8,
        "peak_rss_bytes": 123,
    }

    monkeypatch.setattr(coordinator, "_record_transaction_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        coordinator.subprocess,
        "Popen",
        lambda command, **kwargs: _SuccessfulProcess(command, events=events, **kwargs),
    )

    def load_state(*_args, **_kwargs):
        events.append("durable-state-validated")
        return state

    monkeypatch.setattr(coordinator._bounded, "_load_stage_state", load_state)
    monkeypatch.setattr(
        coordinator,
        "run_lane_exit_exact_spool_cache_reclamation",
        lambda *args, **kwargs: events.append("exact-reclaim"),
    )
    monkeypatch.setattr(
        coordinator,
        "run_publication_lane_cache_reclamation",
        lambda *args, **kwargs: events.append("broad-reclaim"),
    )
    monkeypatch.setattr(
        coordinator,
        "_publish_transaction_completion",
        lambda **_kwargs: events.append("publication-complete"),
    )

    result = coordinator._run_lane_transaction(
        tmp_path / "request.json",
        {},
        asset_class="real_estate",
        index=8,
    )

    assert result is state
    assert events == [
        "spawn",
        "exit",
        "durable-state-validated",
        "exact-reclaim",
        "broad-reclaim",
        "publication-complete",
    ]


def test_failed_publication_lane_never_runs_reclamation(monkeypatch, tmp_path) -> None:
    events: list[str] = []
    monkeypatch.setattr(coordinator, "_record_transaction_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        coordinator.subprocess,
        "Popen",
        lambda command, **kwargs: _FailedProcess(command, events=events, **kwargs),
    )
    monkeypatch.setattr(
        coordinator._legacy,
        "load_failure",
        lambda _path: {
            "failure_stage": "publication",
            "error_type": "RuntimeError",
            "error_detail": "simulated",
        },
    )
    monkeypatch.setattr(
        coordinator,
        "run_lane_exit_exact_spool_cache_reclamation",
        lambda *args, **kwargs: events.append("unexpected-exact-reclaim"),
    )
    monkeypatch.setattr(
        coordinator,
        "run_publication_lane_cache_reclamation",
        lambda *args, **kwargs: events.append("unexpected-broad-reclaim"),
    )

    with pytest.raises(coordinator._legacy.ComprehensiveDiscoverySpoolError):
        coordinator._run_lane_transaction(
            tmp_path / "request.json",
            {},
            asset_class="real_estate",
            index=8,
        )

    assert events == ["spawn", "exit-failed"]
