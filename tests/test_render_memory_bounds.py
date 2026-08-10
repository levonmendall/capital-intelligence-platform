from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import run_background_provider_validation as provider_worker
import run_bounded_manual_cio_diagnostic as diagnostic_watchdog


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


def test_diagnostic_cgroup_high_water_stops_before_kernel_oom(monkeypatch) -> None:
    class Process:
        pid = 123

        @staticmethod
        def poll():
            return None

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

    return_code, timed_out, memory_limited, process_peak, cgroup_peak = (
        diagnostic_watchdog._wait_with_resource_bounds(
            Process(),
            timeout_seconds=30.0,
            memory_high_water_fraction=0.85,
        )
    )

    assert return_code is None
    assert timed_out is False
    assert memory_limited is True
    assert process_peak == 710_000
    assert cgroup_peak == 1_800_000


def test_diagnostic_memory_guard_does_not_change_market_scope() -> None:
    source = open("run_render_service_nonblocking.py", encoding="utf-8").read()
    assert '"CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true"' in source
    assert '"CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true"' in source
    assert "complete_all_market_coverage_required=True" in source


def test_memory_high_water_fraction_is_bounded() -> None:
    assert diagnostic_watchdog._memory_high_water_fraction({}) == 0.85
    assert diagnostic_watchdog._memory_high_water_fraction(
        {"CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION": "0.80"}
    ) == 0.8
