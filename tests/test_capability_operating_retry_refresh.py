from __future__ import annotations

from types import SimpleNamespace

from operations import capability_operating_retry_refresh as runtime
from operations import capability_scoped_render_bootstrap as capability_bootstrap


def test_fresh_evidence_does_not_run_bounded_owner(monkeypatch):
    calls = {"load": 0, "prequalify": 0}

    def load(_values):
        calls["load"] += 1
        return object()

    def prequalify(_values):
        calls["prequalify"] += 1
        return True

    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", load)
    values = {"RENDER": "true"}

    assert runtime._ensure_fresh_operating_evidence(values, prequalify=prequalify) is True
    assert calls == {"load": 1, "prequalify": 0}


def test_stale_evidence_runs_bounded_owner_once_then_revalidates(monkeypatch):
    calls = {"load": 0, "prequalify": 0}

    def load(_values):
        calls["load"] += 1
        if calls["load"] == 1:
            raise RuntimeError("stale")
        return object()

    def prequalify(_values):
        calls["prequalify"] += 1
        return True

    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", load)
    values = {"RENDER": "true"}

    assert runtime._ensure_fresh_operating_evidence(values, prequalify=prequalify) is True
    assert calls == {"load": 2, "prequalify": 1}


def test_failed_refresh_remains_fail_closed(monkeypatch):
    calls = {"load": 0, "prequalify": 0}

    def load(_values):
        calls["load"] += 1
        raise RuntimeError("stale")

    def prequalify(_values):
        calls["prequalify"] += 1
        return False

    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", load)
    values = {"RENDER": "true"}

    assert runtime._ensure_fresh_operating_evidence(values, prequalify=prequalify) is False
    assert calls == {"load": 1, "prequalify": 1}


def test_successful_refresh_must_still_pass_revalidation(monkeypatch):
    calls = {"load": 0, "prequalify": 0}

    def load(_values):
        calls["load"] += 1
        raise RuntimeError("still stale")

    def prequalify(_values):
        calls["prequalify"] += 1
        return True

    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", load)
    values = {"RENDER": "true"}

    assert runtime._ensure_fresh_operating_evidence(values, prequalify=prequalify) is False
    assert calls == {"load": 2, "prequalify": 1}


def test_installed_runner_refreshes_only_operating_evidence_before_cio_child(monkeypatch):
    events: list[str] = []
    logs: list[tuple[str, dict[str, object]]] = []

    def original_runner(*_args, **_kwargs):
        events.append("child")
        return 0

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=original_runner,
        _log=lambda event, **kwargs: logs.append((event, kwargs)),
    )
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)
    loads = {"count": 0}

    def load(_values):
        loads["count"] += 1
        if loads["count"] == 1:
            raise RuntimeError("stale")
        events.append("validated")
        return object()

    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", load)
    monkeypatch.setattr(
        capability_bootstrap,
        "prequalify_capability_operating_evidence",
        lambda _memory_safe, _values: events.append("refresh") or True,
    )
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values={"RENDER": "true", "CAPITAL_INTELLIGENCE_RELEASE": "abc123"},
    )

    assert result == 0
    assert events == ["refresh", "validated", "child"]
    assert logs == []


def test_installed_runner_does_not_start_child_when_operating_refresh_fails(monkeypatch):
    child_calls = {"count": 0}
    logs: list[tuple[str, dict[str, object]]] = []

    def original_runner(*_args, **_kwargs):
        child_calls["count"] += 1
        return 0

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=original_runner,
        _log=lambda event, **kwargs: logs.append((event, kwargs)),
    )
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)
    monkeypatch.setattr(
        runtime,
        "load_capability_operating_reference_manifest",
        lambda _values: (_ for _ in ()).throw(RuntimeError("stale")),
    )
    monkeypatch.setattr(
        capability_bootstrap,
        "prequalify_capability_operating_evidence",
        lambda _memory_safe, _values: False,
    )
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values={"RENDER": "true", "CAPITAL_INTELLIGENCE_RELEASE": "abc123"},
    )

    assert result == runtime._EVIDENCE_NOT_READY_RETURN_CODE
    assert child_calls["count"] == 0
    assert logs[-1][0] == "manual_cio_release_operating_evidence_not_ready"
    assert logs[-1][1]["diagnostic_child_started"] is False
    assert logs[-1][1]["comprehensive_all_market_gate_required"] is True
    assert logs[-1][1]["paper_only"] is True
    assert logs[-1][1]["real_money_authorized"] is False
