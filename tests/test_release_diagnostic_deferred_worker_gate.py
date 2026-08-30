from __future__ import annotations

from pathlib import Path
from types import ModuleType

from operations.release_diagnostic_deferred_worker_gate import install


class _FakeThread:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


def _fake_memory_safe(thread):
    memory_safe = ModuleType("fake_memory_safe")
    supervisor = ModuleType("fake_render_supervisor")
    calls: dict[str, object] = {}

    def start(values):
        calls["start_values"] = values
        return thread

    def run_supervisor(*, environment=None, poll_seconds=1.0, deferred_start_ready=None):
        calls["environment"] = environment
        calls["poll_seconds"] = poll_seconds
        calls["deferred_start_ready"] = deferred_start_ready
        return 17

    memory_safe._start_release_diagnostic_after_prequalification = start
    supervisor.run_supervisor = run_supervisor
    memory_safe.render_supervisor = supervisor
    return memory_safe, calls


def test_release_certification_defers_non_web_workers_until_thread_finishes() -> None:
    thread = _FakeThread(alive=True)
    memory_safe, calls = _fake_memory_safe(thread)
    install(memory_safe)

    values = {"CAPITAL_INTELLIGENCE_RELEASE": "test-release"}
    assert memory_safe._start_release_diagnostic_after_prequalification(values) is thread
    assert memory_safe.render_supervisor.run_supervisor(
        environment=values,
        poll_seconds=0.25,
    ) == 17

    gate = calls["deferred_start_ready"]
    assert callable(gate)
    assert gate() is False
    thread.alive = False
    assert gate() is True
    assert calls["environment"] is values
    assert calls["poll_seconds"] == 0.25


def test_no_release_diagnostic_preserves_normal_supervisor_startup() -> None:
    memory_safe, calls = _fake_memory_safe(None)
    install(memory_safe)

    values = {"CAPITAL_INTELLIGENCE_RELEASE": "test-release"}
    assert memory_safe._start_release_diagnostic_after_prequalification(values) is None
    assert memory_safe.render_supervisor.run_supervisor(environment=values) == 17
    assert calls["deferred_start_ready"] is None


def test_existing_supervisor_gate_is_never_weakened() -> None:
    thread = _FakeThread(alive=True)
    memory_safe, calls = _fake_memory_safe(thread)
    install(memory_safe)
    memory_safe._start_release_diagnostic_after_prequalification({})

    existing_gate = lambda: False
    memory_safe.render_supervisor.run_supervisor(deferred_start_ready=existing_gate)
    assert calls["deferred_start_ready"] is existing_gate


def test_install_is_idempotent() -> None:
    thread = _FakeThread(alive=True)
    memory_safe, _calls = _fake_memory_safe(thread)
    install(memory_safe)
    first_start = memory_safe._start_release_diagnostic_after_prequalification
    first_supervisor = memory_safe.render_supervisor.run_supervisor

    install(memory_safe)

    assert memory_safe._start_release_diagnostic_after_prequalification is first_start
    assert memory_safe.render_supervisor.run_supervisor is first_supervisor


def test_render_workspace_installs_gate_before_service_start() -> None:
    source = Path("run_render_service_workspace.py").read_text(encoding="utf-8")
    install_call = "install_release_diagnostic_deferred_worker_gate(memory_safe)"
    assert install_call in source
    assert source.index(install_call) < source.index("return run_service()")
