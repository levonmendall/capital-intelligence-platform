from __future__ import annotations

from run_render_service import managed_processes


def test_readiness_watchdog_does_not_restart_complete_render_service() -> None:
    processes = {
        process.name: process
        for process in managed_processes(port=10000, python_executable="python")
    }

    watchdog = processes["composite-readiness-watchdog"]
    assert watchdog.critical is False
    assert watchdog.restart_delay_seconds == 300

    # Processes whose loss means the operating service itself is unavailable
    # remain critical and continue to trigger a clean Render restart.
    assert processes["api"].critical is True
    assert processes["cio-paper-operator"].critical is True
    assert processes["streamlit"].critical is True
