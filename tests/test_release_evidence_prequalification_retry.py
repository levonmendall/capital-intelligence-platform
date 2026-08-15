from __future__ import annotations

import subprocess
from types import SimpleNamespace

from operations import continuous_evidence_plane
import run_render_service_memory_safe as runtime


def _install_safe_runtime(monkeypatch):
    writes: list[dict[str, object]] = []
    logs: list[tuple[str, dict[str, object]]] = []
    sleeps: list[float] = []

    def write(_values, **kwargs):
        writes.append(dict(kwargs))
        return {
            "prequalification_id": kwargs.get("prequalification_id") or "prequal-test",
        }

    monkeypatch.setattr(runtime, "write_release_evidence_prequalification", write)
    monkeypatch.setattr(
        runtime.render_bootstrap,
        "_publish_release_diagnostic_audit",
        lambda _values: None,
    )
    monkeypatch.setattr(
        runtime.render_bootstrap,
        "_log",
        lambda event, **kwargs: logs.append((event, dict(kwargs))),
    )
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: sleeps.append(seconds))
    return writes, logs, sleeps


def test_release_evidence_prequalification_recovers_from_transient_worker_failure(
    monkeypatch,
) -> None:
    writes, logs, sleeps = _install_safe_runtime(monkeypatch)
    calls: list[int] = []
    results = iter(
        (
            subprocess.CompletedProcess(args=("evidence",), returncode=125),
            subprocess.CompletedProcess(args=("evidence",), returncode=0),
        )
    )

    def run(*_args, **_kwargs):
        calls.append(1)
        return next(results)

    generation = SimpleNamespace(
        generation_id="generation:test",
        scheduled_lanes=("crypto", "fx"),
        historical_scope_count=7,
    )
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(
        continuous_evidence_plane,
        "load_latest_evidence_plane",
        lambda _values: generation,
    )

    values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_ATTEMPTS": "3",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_RETRY_SECONDS": "0",
    }

    assert runtime._prequalify_release_evidence(values) is True
    assert len(calls) == 2
    assert sleeps == []
    assert not any(item.get("state") == "failed" for item in writes)
    assert any(
        item.get("state") == "in_progress"
        and item.get("stage") == "evidence_refresh"
        and item.get("metrics", {}).get("qualifier_return_code") == 125
        for item in writes
    )
    completed = writes[-1]
    assert completed["state"] == "completed"
    assert completed["stage"] == "evidence_generation_ready"
    assert completed["generation_id"] == "generation:test"
    assert completed["metrics"]["attempt"] == 2
    assert completed["metrics"]["maximum_attempts"] == 3
    assert any(event == "release_evidence_prequalification_retrying" for event, _ in logs)
    assert any(event == "release_evidence_prequalification_finished" for event, _ in logs)


def test_release_evidence_prequalification_fails_only_after_retry_budget(
    monkeypatch,
) -> None:
    writes, logs, sleeps = _install_safe_runtime(monkeypatch)
    calls: list[int] = []

    def run(*_args, **_kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(args=("evidence",), returncode=2)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(
        continuous_evidence_plane,
        "load_latest_evidence_plane",
        lambda _values: (_ for _ in ()).throw(
            AssertionError("failed qualifier must not load a generation")
        ),
    )

    values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_ATTEMPTS": "3",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_RETRY_SECONDS": "0",
    }

    assert runtime._prequalify_release_evidence(values) is False
    assert len(calls) == 3
    assert sleeps == []
    failed = writes[-1]
    assert failed["state"] == "failed"
    assert failed["stage"] == "evidence_prequalification_failed"
    assert failed["metrics"] == {
        "attempt": 3,
        "maximum_attempts": 3,
        "qualifier_return_code": 2,
        "qualifier_return_code_negative": 0,
    }
    retries = [event for event, _ in logs if event == "release_evidence_prequalification_retrying"]
    assert len(retries) == 2
    assert logs[-1][0] == "release_evidence_prequalification_failed"


def test_release_evidence_prequalification_recovers_when_child_cannot_start_once(
    monkeypatch,
) -> None:
    writes, _logs, sleeps = _install_safe_runtime(monkeypatch)
    calls: list[int] = []

    def run(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("transient spawn failure")
        return subprocess.CompletedProcess(args=("evidence",), returncode=0)

    generation = SimpleNamespace(
        generation_id="generation:spawn-recovered",
        scheduled_lanes=(),
        historical_scope_count=0,
    )
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(
        continuous_evidence_plane,
        "load_latest_evidence_plane",
        lambda _values: generation,
    )

    values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_ATTEMPTS": "2",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_RETRY_SECONDS": "0",
    }

    assert runtime._prequalify_release_evidence(values) is True
    assert len(calls) == 2
    assert sleeps == []
    assert any(
        item.get("metrics", {}).get("qualifier_start_failed") == 1
        for item in writes
    )
    assert writes[-1]["generation_id"] == "generation:spawn-recovered"
