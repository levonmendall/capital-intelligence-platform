from __future__ import annotations

import inspect
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import run_background_provider_validation as provider_worker
import run_bounded_manual_cio_diagnostic as diagnostic_watchdog
import run_render_service_nonblocking as render_bootstrap


def test_provider_validation_defers_while_manual_diagnostic_is_active(monkeypatch) -> None:
    states = iter(("pending", "in_progress", "completed"))
    monkeypatch.setattr(
        provider_worker,
        "latest_manual_cio_diagnostic",
        lambda: SimpleNamespace(state=next(states)),
    )
    stopping = Event()

    assert provider_worker._wait_for_diagnostic_memory_lane(
        stopping,
        poll_seconds=0.001,
    ) is True


def test_provider_validation_fails_memory_safe_when_coordination_is_unreadable(monkeypatch) -> None:
    def broken_state():
        raise ValueError("corrupt operational coordination state")

    monkeypatch.setattr(provider_worker, "latest_manual_cio_diagnostic", broken_state)
    assert provider_worker._diagnostic_active() is True


def test_provider_worker_does_not_eagerly_load_heavy_validation_stack() -> None:
    # The loop process must stay lightweight while the release diagnostic owns memory.
    assert "validate_live_providers" not in provider_worker.__dict__
    source = inspect.getsource(provider_worker.validate_once)
    assert "from operations.provider_validation import" in source


def test_diagnostic_container_high_water_stops_before_kernel_oom(monkeypatch) -> None:
    class Process:
        pid = 123

        def __init__(self) -> None:
            self.terminated = Event()
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15
            self.terminated.set()

        def kill(self) -> None:
            self.returncode = -9
            self.terminated.set()

        def wait(self, timeout=None):
            assert self.terminated.wait(timeout)
            return self.returncode

    monkeypatch.setattr(
        diagnostic_watchdog,
        "_process_memory_kib",
        lambda _pid: (700_000, 710_000),
    )
    monkeypatch.setattr(
        diagnostic_watchdog,
        "_cgroup_memory_kib",
        lambda: (1_800_000, 2_000_000),
    )
    monkeypatch.setattr(
        diagnostic_watchdog.os,
        "killpg",
        lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError()),
    )

    return_code, timed_out, memory_limited, process_peak, container_peak = (
        diagnostic_watchdog._wait_with_resource_bounds(
            Process(),
            timeout_seconds=30.0,
            memory_high_water_fraction=0.70,
            memory_reserve_kib=640 * 1024,
            poll_seconds=0.01,
        )
    )

    assert return_code == -15
    assert timed_out is False
    assert memory_limited is True
    assert process_peak == 710_000
    assert container_peak == 1_800_000


def test_render_fallback_keeps_memory_guard_active_without_cgroup_files(monkeypatch) -> None:
    monkeypatch.setattr(diagnostic_watchdog, "_cgroup_memory_kib", lambda: (None, None))
    monkeypatch.setattr(diagnostic_watchdog, "_proc_total_rss_kib", lambda: 900_000)

    current, limit, source = diagnostic_watchdog._container_memory_kib(
        {"RENDER": "true"}
    )

    assert current == 900_000
    assert limit == 2048 * 1024
    assert source == "proc_rss_fallback"


def test_memory_boundary_preserves_absolute_service_reserve() -> None:
    boundary = diagnostic_watchdog._effective_memory_boundary_kib(
        2_000_000,
        memory_high_water_fraction=0.85,
        memory_reserve_kib=640_000,
    )
    assert boundary == 1_360_000


def test_memory_high_water_defaults_leave_render_headroom() -> None:
    assert diagnostic_watchdog._memory_high_water_fraction({}) == 0.70
    assert diagnostic_watchdog._memory_reserve_kib({}) == 640 * 1024
    assert diagnostic_watchdog._memory_poll_seconds({}) == 0.10
    assert diagnostic_watchdog._memory_high_water_fraction(
        {"CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION": "0.80"}
    ) == 0.8


def test_diagnostic_uses_own_process_session_for_tree_termination() -> None:
    source = inspect.getsource(diagnostic_watchdog.run_bounded_diagnostic)
    assert 'start_new_session=(os.name == "posix")' in source


def test_memory_limited_release_diagnostic_is_not_force_retried() -> None:
    assert render_bootstrap._release_diagnostic_retryable(125) is False
    assert render_bootstrap._release_diagnostic_retryable(3) is True


def test_diagnostic_memory_guard_does_not_change_market_scope() -> None:
    source = Path("run_render_service_nonblocking.py").read_text(encoding="utf-8")
    assert '"CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true"' in source
    assert '"CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true"' in source
    assert "complete_all_market_coverage_required=True" in source
